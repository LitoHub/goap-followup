from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import SessionLocal
from models import Lead, ScheduledTask, SystemLog
from tools.twenty_client import TwentyCRMClient
from tools.bison_client import BisonClient
from tools import email_templates

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# Status transition map: current_status -> (template_func, next_status, is_final)
FOLLOW_UP_MAP = {
    "Lead Magnet Sent": (email_templates.follow_up_1, "Follow-up 1", False),
    "Follow-up 1": (email_templates.follow_up_2, "Follow-up 2", False),
    "Follow-up 2": (email_templates.follow_up_3, "Finished", True),
}


def _log(db, action: str, details: str = "", lead_id: int | None = None, level: str = "info"):
    entry = SystemLog(lead_id=lead_id, action=action, details=details, level=level)
    db.add(entry)
    db.commit()


def check_follow_ups():
    """Hourly job: find leads needing follow-up and send emails.

    For each eligible lead:
    1. Check Bison for recent replies (kill switch safety net)
    2. Send the appropriate follow-up email
    3. Update local DB + Twenty CRM
    """
    db = SessionLocal()
    twenty = TwentyCRMClient()
    bison = BisonClient()
    now = datetime.now(timezone.utc)
    delay = timedelta(days=config.FOLLOWUP_DELAY_DAYS)

    try:
        # Find leads that are due for a follow-up
        eligible_statuses = list(FOLLOW_UP_MAP.keys())
        leads = db.query(Lead).filter(
            Lead.campaign_status.in_(eligible_statuses),
            Lead.last_contact_date <= now - delay,
        ).all()

        if not leads:
            logger.debug("No leads due for follow-up")
            return

        logger.info(f"Found {len(leads)} leads due for follow-up")

        for lead in leads:
            _process_lead_follow_up(db, lead, twenty, bison, now)

    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        _log(db, "scheduler_error", str(e), level="error")
    finally:
        db.close()


def _process_lead_follow_up(db, lead: Lead, twenty: TwentyCRMClient,
                             bison: BisonClient, now: datetime):
    """Process a single lead's follow-up. Includes pre-send kill switch check."""
    # PRE-SEND KILL SWITCH: Check Bison for replies before sending
    try:
        replies = bison.get_replies(sender_email=lead.bison_inbox_id, limit=50)
        lead_replied = any(
            r.get("email", "").lower() == lead.email.lower()
            for r in replies
        )
        if lead_replied:
            lead.campaign_status = "Responded"
            # Cancel all pending tasks
            pending = db.query(ScheduledTask).filter(
                ScheduledTask.lead_id == lead.id,
                ScheduledTask.status == "pending",
            ).all()
            for task in pending:
                task.status = "cancelled"
            db.commit()

            _log(db, "response_detected_presend",
                 f"Reply from {lead.email} detected before follow-up. Sequence killed.",
                 lead_id=lead.id)

            # Update CRM
            try:
                if lead.twenty_opportunity_id:
                    twenty.update_opportunity(
                        lead.twenty_opportunity_id,
                        customFields={"campaign_status": "Responded"},
                    )
                    twenty.create_note(
                        f"Reply detected during pre-send check. Sequence cancelled.",
                        contact_ids=[lead.twenty_contact_id] if lead.twenty_contact_id else None,
                        opportunity_id=lead.twenty_opportunity_id,
                    )
            except Exception as e:
                _log(db, "crm_update_failed", str(e), lead_id=lead.id, level="error")
            return

    except Exception as e:
        # If we can't check replies, log warning but proceed with caution
        _log(db, "reply_check_failed",
             f"Could not check Bison for replies from {lead.email}: {e}",
             lead_id=lead.id, level="warning")

    # Determine which follow-up to send
    template_func, next_status, is_final = FOLLOW_UP_MAP[lead.campaign_status]
    name = f"{lead.first_name or ''} {lead.last_name or ''}".strip()
    subject, body = template_func(name)

    # Send via Bison
    try:
        bison.send_email(lead.bison_inbox_id, lead.email, subject, body)
    except Exception as e:
        _log(db, "email_send_failed",
             f"Failed to send {next_status} to {lead.email}: {e}",
             lead_id=lead.id, level="error")
        return

    # Update lead state
    lead.campaign_status = next_status
    lead.last_contact_date = now
    lead.follow_up_count += 1

    # Mark the scheduled task as completed (if one exists)
    task_type_map = {
        "Follow-up 1": "follow_up_1",
        "Follow-up 2": "follow_up_2",
        "Finished": "follow_up_3",
    }
    task_type = task_type_map.get(next_status, "")
    if task_type:
        task = db.query(ScheduledTask).filter(
            ScheduledTask.lead_id == lead.id,
            ScheduledTask.task_type == task_type,
            ScheduledTask.status == "pending",
        ).first()
        if task:
            task.status = "completed"
            task.completed_at = now

    # Schedule the next follow-up (unless this was the final one)
    if not is_final:
        next_task_type_map = {
            "Follow-up 1": "follow_up_2",
            "Follow-up 2": "follow_up_3",
        }
        next_task_type = next_task_type_map.get(next_status, "")
        if next_task_type:
            new_task = ScheduledTask(
                lead_id=lead.id,
                task_type=next_task_type,
                scheduled_time=now + timedelta(days=config.FOLLOWUP_DELAY_DAYS),
            )
            db.add(new_task)

    db.commit()

    _log(db, f"{next_status.lower().replace(' ', '_').replace('-', '_')}_sent",
         f"Sent to {lead.email} via inbox {lead.bison_inbox_id}",
         lead_id=lead.id)

    # Update Twenty CRM
    try:
        if lead.twenty_opportunity_id:
            twenty.update_opportunity(
                lead.twenty_opportunity_id,
                customFields={
                    "campaign_status": next_status,
                    "last_contact_date": now.isoformat(),
                    "follow_up_count": lead.follow_up_count,
                },
            )
            note_text = f"{next_status} sent at {now.strftime('%Y-%m-%d %H:%M UTC')}."
            if not is_final:
                next_time = now + timedelta(days=config.FOLLOWUP_DELAY_DAYS)
                note_text += f" Next follow-up scheduled for {next_time.strftime('%Y-%m-%d %H:%M UTC')}."
            else:
                note_text += " This was the final follow-up. Sequence complete."
            twenty.create_note(
                note_text,
                contact_ids=[lead.twenty_contact_id] if lead.twenty_contact_id else None,
                opportunity_id=lead.twenty_opportunity_id,
            )
    except Exception as e:
        _log(db, "crm_update_failed", str(e), lead_id=lead.id, level="error")

    logger.info(f"{next_status} sent to {lead.email}")


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        check_follow_ups,
        "interval",
        hours=config.SCHEDULER_INTERVAL_HOURS,
        id="follow_up_checker",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Scheduler started: checking every {config.SCHEDULER_INTERVAL_HOURS} hour(s)")


def shutdown_scheduler():
    """Gracefully stop the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
