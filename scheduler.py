from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import SessionLocal
from models import Lead, SystemLog
from tools.twenty_client import TwentyCRMClient

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _log(db, action: str, details: str = "", lead_id: int | None = None, level: str = "info"):
    entry = SystemLog(lead_id=lead_id, action=action, details=details, level=level)
    db.add(entry)
    db.commit()


def sync_statuses():
    """Hourly job: sync lead statuses and detect stale leads.

    Bison handles the actual follow-up email sending via campaigns.
    This job monitors the system and keeps Twenty CRM in sync.
    """
    db = SessionLocal()
    twenty = TwentyCRMClient()
    now = datetime.now(timezone.utc)

    try:
        # Find active leads (in follow-up sequence)
        active_statuses = ["Lead Magnet Sent", "Follow-up 1", "Follow-up 2"]
        active_leads = db.query(Lead).filter(
            Lead.campaign_status.in_(active_statuses)
        ).all()

        if not active_leads:
            logger.debug("No active leads in follow-up sequence")
            return

        logger.info(f"Monitoring {len(active_leads)} active leads")

        for lead in active_leads:
            _check_lead_status(db, lead, twenty, now)

    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        _log(db, "scheduler_error", str(e), level="error")
    finally:
        db.close()


def _check_lead_status(db, lead: Lead, twenty: TwentyCRMClient, now: datetime):
    """Check a single lead's status and log any issues."""
    # Calculate days since last contact
    if lead.last_contact_date:
        days_elapsed = (now - lead.last_contact_date).days
    else:
        days_elapsed = None

    # Log warning for leads stuck too long (e.g., >15 days without status change)
    if days_elapsed and days_elapsed > 15:
        _log(db, "stale_lead_detected",
             f"Lead {lead.email} has been in '{lead.campaign_status}' for {days_elapsed} days",
             lead_id=lead.id, level="warning")


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        sync_statuses,
        "interval",
        hours=config.SCHEDULER_INTERVAL_HOURS,
        id="status_sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Scheduler started: syncing every {config.SCHEDULER_INTERVAL_HOURS} hour(s)")


def shutdown_scheduler():
    """Gracefully stop the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
