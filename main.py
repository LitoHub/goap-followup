from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, Request, HTTPException
from sqlalchemy.orm import Session

import config
from database import get_db, init_db
from models import Lead, SystemLog
from tools.twenty_client import TwentyCRMClient
from tools.bison_client import BisonClient
from tools.sentiment import analyze_sentiment
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


app = FastAPI(title="GOAP Follow-up System", lifespan=lifespan)


# --- Health Check ---

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    total_leads = db.query(Lead).count()
    active_leads = db.query(Lead).filter(
        Lead.campaign_status.in_(["Lead Magnet Sent", "Follow-up 1", "Follow-up 2"])
    ).count()
    return {
        "status": "ok",
        "total_leads": total_leads,
        "active_leads": active_leads,
    }


@app.get("/logs")
def get_logs(limit: int = 20, level: str | None = None,
             db: Session = Depends(get_db)):
    """Recent system logs for debugging."""
    query = db.query(SystemLog).order_by(SystemLog.timestamp.desc())
    if level:
        query = query.filter(SystemLog.level == level)
    logs = query.limit(limit).all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "details": log.details,
            "level": log.level,
            "lead_id": log.lead_id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


@app.get("/leads")
def get_leads(db: Session = Depends(get_db)):
    """List all leads for debugging."""
    leads = db.query(Lead).order_by(Lead.id.desc()).limit(50).all()
    return [
        {
            "id": l.id,
            "email": l.email,
            "first_name": l.first_name,
            "last_name": l.last_name,
            "bison_lead_id": l.bison_lead_id,
            "bison_reply_id": l.bison_reply_id,
            "bison_sender_email_id": l.bison_sender_email_id,
            "bison_inbox_id": l.bison_inbox_id,
            "twenty_contact_id": l.twenty_contact_id,
            "twenty_opportunity_id": l.twenty_opportunity_id,
            "campaign_status": l.campaign_status,
            "sentiment": l.sentiment,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in leads
    ]



# --- Bison Webhook ---

@app.post("/webhook/bison")
async def webhook_bison(request: Request, db: Session = Depends(get_db)):
    """Handle webhook events from Bison.

    Key events:
    - Contact Interested: New positive lead → sentiment check → create in CRM
    - Contact Replied: Lead replied to follow-up → kill switch
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Bison sends event as a dict: {"type": "LEAD_INTERESTED", "name": "...", ...}
    # or as a string for older formats
    raw_event = payload.get("event", "")
    if isinstance(raw_event, dict):
        event_type = raw_event.get("type", raw_event.get("name", "unknown"))
    else:
        event_type = raw_event or payload.get("type", "unknown")

    # Extract lead data from the 'data' key
    lead_data = payload.get("data", payload.get("lead", payload))

    # Log full payload structure for debugging
    log_action(db, "bison_webhook_received",
               f"Event: {event_type} | Data keys: {list(lead_data.keys()) if isinstance(lead_data, dict) else 'N/A'}")
    logger.info(f"Bison webhook received: event={event_type}")

    # Only process LEAD_INTERESTED and LEAD_REPLIED events
    valid_events = {"LEAD_INTERESTED", "LEAD_REPLIED",
                    "contact_interested", "contact_replied"}
    if event_type not in valid_events:
        return {"status": "ignored", "event": event_type}

    # Only process replies from our outbound campaign
    campaign_id = (
        lead_data.get("campaign_id")
        or lead_data.get("campaignId")
        or payload.get("campaign_id")
    )
    # Convert to string for comparison; also try nested campaign object
    if not campaign_id and isinstance(lead_data.get("campaign"), dict):
        campaign_id = lead_data["campaign"].get("id")
    campaign_id_str = str(campaign_id) if campaign_id else ""

    if config.BISON_OUTBOUND_CAMPAIGN_ID and campaign_id_str != config.BISON_OUTBOUND_CAMPAIGN_ID:
        # Log full data structure so we can find the campaign_id field
        data_summary = {}
        if isinstance(lead_data, dict):
            for k, v in lead_data.items():
                if isinstance(v, (dict, list)):
                    data_summary[k] = f"({type(v).__name__})"
                else:
                    data_summary[k] = v
        log_action(db, "bison_webhook_ignored",
                   f"Campaign mismatch. campaign_id={campaign_id}. "
                   f"Full data: {json.dumps(data_summary, default=str)[:800]}")
        return {"status": "ignored", "reason": "wrong_campaign"}

    lead_email = (
        lead_data.get("lead_email", "")
        or lead_data.get("email", "")
        or payload.get("email", "")
    )
    if isinstance(lead_email, str):
        lead_email = lead_email.strip().lower()
    else:
        lead_email = ""

    if not lead_email:
        log_action(db, "bison_webhook_ignored",
                   f"No email found in payload. Keys: {list(payload.keys())}",
                   level="warning")
        return {"status": "ignored", "reason": "no_email"}

    # Check if lead already exists in our DB
    existing_lead = db.query(Lead).filter(Lead.email == lead_email).first()

    if existing_lead:
        return _handle_existing_lead_reply(db, existing_lead, lead_data)
    else:
        return _handle_new_lead(db, lead_email, lead_data, payload)


def _handle_existing_lead_reply(db: Session, lead: Lead, lead_data: dict) -> dict:
    """Kill switch: cancel follow-ups when a lead in our system replies."""
    active_statuses = {"Lead Magnet Sent", "Follow-up 1", "Follow-up 2", "Follow-up 3"}

    if lead.campaign_status in active_statuses:
        lead.campaign_status = "Responded"
        db.commit()

        log_action(db, "sequence_killed",
                   f"Lead {lead.email} replied. Status changed to Responded.",
                   lead_id=lead.id)

        # Update Twenty CRM
        try:
            if lead.twenty_opportunity_id:
                twenty.update_pipeline_record(
                    lead.twenty_opportunity_id,
                    campaignStatus="RESPONDED",
                )
                twenty.create_note(
                    "Reply detected — follow-up sequence cancelled automatically.",
                    contact_ids=[lead.twenty_contact_id] if lead.twenty_contact_id else None,
                    pipeline_record_id=lead.twenty_opportunity_id,
                )
        except Exception as e:
            log_action(db, "crm_update_failed", str(e), lead_id=lead.id, level="error")

        return {"status": "responded", "email": lead.email}

    log_action(db, "duplicate_reply",
               f"Lead {lead.email} replied again (status: {lead.campaign_status})",
               lead_id=lead.id)
    return {"status": "already_responded"}


def _handle_new_lead(db: Session, email: str, lead_data: dict, payload: dict) -> dict:
    """Analyze sentiment and create lead in DB + CRM if positive."""
    reply_text = (
        lead_data.get("reply_text", "")
        or lead_data.get("body", "")
        or payload.get("reply_text", "")
        or payload.get("body", "")
    )

    sentiment = analyze_sentiment(reply_text)
    log_action(db, "sentiment_analyzed", f"Lead {email} classified as {sentiment}")

    if sentiment == "negative":
        return {"status": "negative_sentiment", "email": email}

    # Extract Bison IDs
    bison_lead_id = (
        lead_data.get("lead_id")
        or lead_data.get("id")
        or payload.get("lead_id")
    )
    # Reply ID — needed to reply in the same email thread
    bison_reply_id = (
        lead_data.get("reply_id")
        or payload.get("reply_id")
        or payload.get("id")  # Bison may use 'id' for the reply
    )
    # Sender email account ID (integer) — needed for sending replies
    bison_sender_email_id = (
        lead_data.get("sender_email_id")
        or payload.get("sender_email_id")
    )
    inbox_id = (
        lead_data.get("sender_email", "")
        or payload.get("sender_email", "")
        or payload.get("inbox_id", "")
    )
    first_name = lead_data.get("first_name", "")
    if not first_name and lead_data.get("lead_name"):
        first_name = lead_data["lead_name"].split()[0]
    last_name = lead_data.get("last_name", "")

    # Create lead in local DB
    lead = Lead(
        email=email,
        first_name=first_name,
        last_name=last_name,
        bison_lead_id=bison_lead_id,
        bison_reply_id=bison_reply_id,
        bison_sender_email_id=bison_sender_email_id,
        bison_inbox_id=str(inbox_id),
        campaign_status="New",
        original_reply_text=reply_text,
        sentiment=sentiment,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    log_action(db, "lead_created",
               f"Positive lead created: {email} (bison_lead_id={bison_lead_id})",
               lead_id=lead.id)

    # Create in Twenty CRM
    try:
        person = twenty.create_person(
            email=email,
            first_name=lead.first_name or "",
            last_name=lead.last_name or "",
        )
        person_id = person.get("id", "")
        lead.twenty_contact_id = person_id

        pipeline_record = twenty.create_pipeline_record(
            name=f"Follow-up: {email}",
            bison_inbox_id=lead.bison_inbox_id or "",
            person_id=person_id,
        )
        record_id = pipeline_record.get("id", "")
        lead.twenty_opportunity_id = record_id
        db.commit()

        twenty.create_note(
            "Positive sentiment detected — lead created from Bison reply.",
            contact_ids=[person_id] if person_id else None,
            pipeline_record_id=record_id,
        )

        log_action(db, "crm_records_created",
                   f"Twenty CRM person={person_id}, pipeline_record={record_id}",
                   lead_id=lead.id)

    except Exception as e:
        log_action(db, "crm_creation_failed", str(e), lead_id=lead.id, level="error")

    return {"status": "lead_created", "lead_id": lead.id, "email": email}


# --- Twenty CRM Webhook ---

@app.post("/webhook/twenty")
async def webhook_twenty(request: Request, db: Session = Depends(get_db)):
    """Handle goapNewPipeline update events from Twenty CRM.

    When user sets leadMagnetUrl and moves campaignStatus to READY_TO_SEND:
    1. Attach the lead to the follow-up campaign in Bison
    2. Update local DB status
    3. Bison handles the follow-up sequence automatically
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

    log_action(db, "twenty_webhook_received",
               f"Event: {event} | Keys: {list(payload.keys())} | Data keys: {list(data.keys())}")

    # Accept goapNewPipeline update events (exact event name may vary)
    valid_events = {"goapNewPipeline.updated", "goapNewPipelines.updated",
                    "goap_new_pipeline.updated"}
    if event not in valid_events:
        return {"status": "ignored", "event": event}

    # Fields are top-level on the custom object, not nested in customFields
    campaign_status = data.get("campaignStatus", "")
    lead_magnet_url_field = data.get("leadMagnetUrl", {})
    # leadMagnetUrl is LINKS type: {"primaryLinkUrl": "...", "primaryLinkLabel": "..."}
    if isinstance(lead_magnet_url_field, dict):
        magnet_url = lead_magnet_url_field.get("primaryLinkUrl", "")
    else:
        magnet_url = str(lead_magnet_url_field) if lead_magnet_url_field else ""

    if not magnet_url or campaign_status != "READY_TO_SEND":
        return {"status": "ignored", "reason": "not a READY_TO_SEND update"}

    record_id = data.get("id", "")
    lead = db.query(Lead).filter(Lead.twenty_opportunity_id == record_id).first()

    if not lead:
        log_action(db, "webhook_ignored",
                   f"Pipeline record {record_id} not found in local DB",
                   level="warning")
        return {"status": "not_found", "record_id": record_id}

    # Update lead magnet URL in local DB
    lead.lead_magnet_url = magnet_url

    # --- Step 1: Send the lead magnet email via Bison ---
    if not lead.bison_reply_id or not lead.bison_sender_email_id:
        log_action(db, "missing_bison_reply_info",
                   f"Lead {lead.email} missing bison_reply_id={lead.bison_reply_id} "
                   f"or sender_email_id={lead.bison_sender_email_id}",
                   lead_id=lead.id, level="error")
        raise HTTPException(
            status_code=400,
            detail="Lead is missing Bison reply_id or sender_email_id for sending email",
        )

    lead_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "there"
    email_body = (
        f"Hi {lead.first_name or 'there'},\n\n"
        f"Thanks for your interest! Here's the resource I mentioned:\n\n"
        f"{magnet_url}\n\n"
        f"Take a look and let me know if you have any questions — happy to help!\n\n"
        f"Best,\nLauren"
    )

    try:
        bison.reply_to_email(
            reply_id=lead.bison_reply_id,
            message=email_body,
            sender_email_id=lead.bison_sender_email_id,
            to_emails=[{"name": lead_name, "email_address": lead.email}],
        )
        log_action(db, "lead_magnet_sent",
                   f"Lead magnet email sent to {lead.email} via Bison reply_id={lead.bison_reply_id}",
                   lead_id=lead.id)
    except Exception as e:
        log_action(db, "lead_magnet_send_failed", str(e), lead_id=lead.id, level="error")
        raise HTTPException(status_code=500, detail="Failed to send lead magnet email via Bison")

    # --- Step 2: Attach lead to follow-up campaign in Bison ---
    campaign_id = config.BISON_FOLLOWUP_CAMPAIGN_ID
    if campaign_id and lead.bison_lead_id:
        try:
            bison.attach_leads_to_campaign(campaign_id, [lead.bison_lead_id])
            log_action(db, "followup_campaign_attached",
                       f"Lead {lead.email} attached to Bison campaign {campaign_id}",
                       lead_id=lead.id)
        except Exception as e:
            log_action(db, "bison_attach_failed", str(e), lead_id=lead.id, level="warning")
    elif not campaign_id:
        log_action(db, "config_warning",
                   "BISON_FOLLOWUP_CAMPAIGN_ID not set — skipping follow-up attachment",
                   lead_id=lead.id, level="warning")

    # --- Step 3: Update local DB and Twenty CRM ---
    now = datetime.now(timezone.utc)
    lead.campaign_status = "Lead Magnet Sent"
    lead.last_contact_date = now
    db.commit()

    try:
        twenty.update_pipeline_record(
            record_id,
            campaignStatus="LEAD_MAGNET_SENT",
            lastContactDate=now.isoformat(),
        )
        twenty.create_note(
            f"Lead magnet sent to {lead.email}. URL: {magnet_url}.",
            contact_ids=[lead.twenty_contact_id] if lead.twenty_contact_id else None,
            pipeline_record_id=record_id,
        )
    except Exception as e:
        log_action(db, "crm_update_failed", str(e), lead_id=lead.id, level="error")

    return {"status": "followup_activated", "lead_id": lead.id, "email": lead.email}


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
