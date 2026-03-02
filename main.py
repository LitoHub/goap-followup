from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, Request, HTTPException
from sqlalchemy.orm import Session

import config
from database import get_db, init_db
from models import Lead, ScheduledTask, SystemLog
from tools.twenty_client import TwentyCRMClient
from tools.bison_client import BisonClient
from tools.sentiment import analyze_sentiment
from tools.email_templates import lead_magnet_email
from scheduler import start_scheduler, shutdown_scheduler

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)

twenty = TwentyCRMClient()
bison = BisonClient()


def log_action(db: Session, action: str, details: str = "",
               lead_id: int | None = None, level: str = "info"):
    """Write an entry to the system_logs table."""
    entry = SystemLog(
        lead_id=lead_id,
        action=action,
        details=details,
        level=level,
    )
    db.add(entry)
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    init_db()
    logger.info("Database initialized")
    start_scheduler()
    logger.info("Scheduler started")
    yield
    shutdown_scheduler()
    logger.info("Scheduler stopped")


app = FastAPI(title="Follow-up System", lifespan=lifespan)


# --- Health Check ---

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    pending = db.query(ScheduledTask).filter(ScheduledTask.status == "pending").count()
    total_leads = db.query(Lead).count()
    return {
        "status": "ok",
        "pending_tasks": pending,
        "total_leads": total_leads,
    }


# --- Bison Webhook ---

@app.post("/webhook/bison")
async def webhook_bison(request: Request, db: Session = Depends(get_db)):
    """Handle new_reply events from Bison.

    Two paths:
    1. Existing lead replied → kill switch (cancel follow-ups, mark Responded)
    2. New lead replied → sentiment analysis → create in CRM if positive
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    lead_email = payload.get("email", "").strip().lower()
    reply_text = payload.get("reply_text", "") or payload.get("body", "")
    inbox_id = payload.get("inbox_id", "") or payload.get("sender_email", "")

    if not lead_email:
        raise HTTPException(status_code=400, detail="Missing email in payload")

    log_action(db, "webhook_received", f"Bison reply from {lead_email}")

    # Check if lead already exists
    existing_lead = db.query(Lead).filter(Lead.email == lead_email).first()

    if existing_lead:
        return _handle_existing_lead_reply(db, existing_lead, reply_text)
    else:
        return _handle_new_lead(db, lead_email, reply_text, inbox_id, payload)


def _handle_existing_lead_reply(db: Session, lead: Lead, reply_text: str) -> dict:
    """Kill switch: cancel follow-ups when a lead replies."""
    active_statuses = {"Lead Magnet Sent", "Follow-up 1", "Follow-up 2", "Follow-up 3"}

    if lead.campaign_status in active_statuses:
        # Cancel all pending tasks for this lead
        pending_tasks = db.query(ScheduledTask).filter(
            ScheduledTask.lead_id == lead.id,
            ScheduledTask.status == "pending",
        ).all()
        for task in pending_tasks:
            task.status = "cancelled"

        lead.campaign_status = "Responded"
        db.commit()

        log_action(db, "sequence_killed",
                   f"Lead {lead.email} replied. Cancelled {len(pending_tasks)} pending tasks.",
                   lead_id=lead.id)

        # Update Twenty CRM
        try:
            if lead.twenty_opportunity_id:
                twenty.update_opportunity(
                    lead.twenty_opportunity_id,
                    customFields={"campaign_status": "Responded"},
                )
                twenty.create_note(
                    f"Reply detected — follow-up sequence cancelled. "
                    f"{len(pending_tasks)} pending tasks removed.",
                    contact_ids=[lead.twenty_contact_id] if lead.twenty_contact_id else None,
                    opportunity_id=lead.twenty_opportunity_id,
                )
        except Exception as e:
            log_action(db, "crm_update_failed", str(e), lead_id=lead.id, level="error")

        return {"status": "responded", "cancelled_tasks": len(pending_tasks)}

    # Lead already responded or finished — just log
    log_action(db, "duplicate_reply",
               f"Lead {lead.email} replied again (status: {lead.campaign_status})",
               lead_id=lead.id)
    return {"status": "already_responded"}


def _handle_new_lead(db: Session, email: str, reply_text: str,
                     inbox_id: str, payload: dict) -> dict:
    """Analyze sentiment and create lead in DB + CRM if positive."""
    sentiment = analyze_sentiment(reply_text)

    log_action(db, "sentiment_analyzed",
               f"Lead {email} classified as {sentiment}")

    if sentiment == "negative":
        return {"status": "negative_sentiment", "email": email}

    # Create lead in local DB
    lead = Lead(
        email=email,
        first_name=payload.get("first_name", ""),
        last_name=payload.get("last_name", ""),
        bison_lead_id=payload.get("lead_id"),
        bison_inbox_id=inbox_id,
        campaign_status="New",
        original_reply_text=reply_text,
        sentiment=sentiment,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    log_action(db, "lead_created",
               f"Positive lead created: {email}",
               lead_id=lead.id)

    # Create in Twenty CRM
    try:
        person = twenty.create_person(
            email=email,
            first_name=lead.first_name or "",
            last_name=lead.last_name or "",
            custom_fields={"bison_inbox_id": inbox_id},
        )
        person_id = person.get("id", "")
        lead.twenty_contact_id = person_id

        opportunity = twenty.create_opportunity(
            name=f"Follow-up: {email}",
            stage="New",
            contact_id=person_id,
            custom_fields={
                "campaign_status": "New",
                "bison_inbox_id": inbox_id,
            },
        )
        opp_id = opportunity.get("id", "")
        lead.twenty_opportunity_id = opp_id
        db.commit()

        twenty.create_note(
            f"Positive sentiment detected — lead created from Bison reply.",
            contact_ids=[person_id] if person_id else None,
            opportunity_id=opp_id,
        )

        log_action(db, "crm_records_created",
                   f"Twenty CRM person={person_id}, opportunity={opp_id}",
                   lead_id=lead.id)

    except Exception as e:
        log_action(db, "crm_creation_failed", str(e), lead_id=lead.id, level="error")

    return {"status": "lead_created", "lead_id": lead.id, "email": email}


# --- Twenty CRM Webhook ---

@app.post("/webhook/twenty")
async def webhook_twenty(request: Request, db: Session = Depends(get_db)):
    """Handle opportunity.updated events from Twenty CRM.

    Triggers lead magnet delivery when:
    - lead_magnet_url is set
    - campaign_status is moved to 'Ready to Send'
    """
    body_bytes = await request.body()

    # Validate HMAC signature if webhook secret is configured
    if config.TWENTY_WEBHOOK_SECRET:
        signature = request.headers.get("X-Twenty-Webhook-Signature", "")
        timestamp = request.headers.get("X-Twenty-Webhook-Timestamp", "")
        if not _verify_twenty_signature(body_bytes, timestamp, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event", "")
    data = payload.get("data", {})

    log_action(db, "webhook_received", f"Twenty CRM event: {event}")

    if event != "opportunity.updated":
        return {"status": "ignored", "event": event}

    # Check if this update sets lead_magnet_url AND moves to Ready to Send
    custom_fields = data.get("customFields", {})
    magnet_url = custom_fields.get("lead_magnet_url", "")
    status = custom_fields.get("campaign_status", "")

    if not magnet_url or status != "Ready to Send":
        return {"status": "ignored", "reason": "not a ready_to_send update"}

    opportunity_id = data.get("id", "")
    lead = db.query(Lead).filter(Lead.twenty_opportunity_id == opportunity_id).first()

    if not lead:
        log_action(db, "webhook_ignored",
                   f"Opportunity {opportunity_id} not found in local DB",
                   level="warning")
        return {"status": "not_found", "opportunity_id": opportunity_id}

    # Update lead magnet URL in local DB
    lead.lead_magnet_url = magnet_url

    # Send the lead magnet email via Bison
    name = f"{lead.first_name or ''} {lead.last_name or ''}".strip()
    subject, body = lead_magnet_email(name, magnet_url)

    try:
        bison.send_email(lead.bison_inbox_id, lead.email, subject, body)
    except Exception as e:
        log_action(db, "email_send_failed", str(e), lead_id=lead.id, level="error")
        raise HTTPException(status_code=500, detail="Failed to send lead magnet email")

    now = datetime.now(timezone.utc)
    lead.campaign_status = "Lead Magnet Sent"
    lead.last_contact_date = now
    db.commit()

    log_action(db, "lead_magnet_sent",
               f"Lead magnet sent to {lead.email}: {magnet_url}",
               lead_id=lead.id)

    # Schedule follow-up 1 (3 days from now)
    task = ScheduledTask(
        lead_id=lead.id,
        task_type="follow_up_1",
        scheduled_time=now + timedelta(days=config.FOLLOWUP_DELAY_DAYS),
    )
    db.add(task)
    db.commit()

    log_action(db, "followup_scheduled",
               f"Follow-up 1 scheduled for {task.scheduled_time.isoformat()}",
               lead_id=lead.id)

    # Update Twenty CRM
    try:
        twenty.update_opportunity(
            opportunity_id,
            customFields={
                "campaign_status": "Lead Magnet Sent",
                "last_contact_date": now.isoformat(),
            },
        )
        twenty.create_note(
            f"Lead magnet email sent at {now.strftime('%Y-%m-%d %H:%M UTC')}. "
            f"URL: {magnet_url}. Follow-up 1 scheduled for "
            f"{task.scheduled_time.strftime('%Y-%m-%d %H:%M UTC')}.",
            contact_ids=[lead.twenty_contact_id] if lead.twenty_contact_id else None,
            opportunity_id=opportunity_id,
        )
    except Exception as e:
        log_action(db, "crm_update_failed", str(e), lead_id=lead.id, level="error")

    return {"status": "lead_magnet_sent", "lead_id": lead.id, "email": lead.email}


def _verify_twenty_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify HMAC SHA256 signature from Twenty CRM webhook."""
    if not signature or not timestamp:
        return False
    message = f"{timestamp}:{body.decode('utf-8')}"
    expected = hmac.new(
        config.TWENTY_WEBHOOK_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
