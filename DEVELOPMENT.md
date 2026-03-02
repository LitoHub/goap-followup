# Development History — Automated Follow-up System

**Project:** GOAP (Automated Cold Email Follow-up & CRM Integration)
**Started:** 2026-02-28
**Last Updated:** 2026-02-28

---

## What This System Does

A Python middleware that sits between Bison (cold email outreach) and Twenty CRM. It automates the full lifecycle of a lead that responds positively to a cold email campaign:

1. **Inbound reply arrives** via Bison webhook → sentiment classified by GPT-4o-mini
2. **Positive leads** get created in Twenty CRM (Person + Opportunity)
3. **User sets a lead magnet URL** in CRM and moves status to "Ready to Send"
4. **System sends the lead magnet email** via Bison from the original sender inbox
5. **3-6-9 day follow-up sequence** fires automatically if no reply
6. **Kill switch** — any reply from the lead cancels all future follow-ups instantly

---

## Architecture

Built on the **WAT framework** (Workflows, Agents, Tools):

```
Bison Webhooks ──→ main.py (FastAPI) ──→ tools/*.py (API clients)
                        │                       │
Twenty Webhooks ──→     │                       ▼
                        ├──→ scheduler.py ──→ Bison API (send emails)
                        │                   Twenty API (update CRM)
                        ▼
                   .tmp/followup.db (SQLite)
                        │
                        ▼ (read-only)
                   dashboard.py (Streamlit)
```

**Key design decisions made:**
- **SQLite over PostgreSQL** — single writer process, <1000 leads, zero config. Migration path: just change `DATABASE_URL`.
- **APScheduler embedded in FastAPI** — avoids Redis/RabbitMQ dependency. The hourly job runs in a background thread. Migration path: extract to Celery if needed.
- **httpx over requests** — async-capable for non-blocking webhook handlers.
- **Dual kill switch** — webhook-based (instant) + pre-send check in scheduler (safety net if webhook was missed).
- **`from __future__ import annotations`** — required in all files because the runtime is Python 3.9 which doesn't support `X | Y` union types natively.

---

## Development Timeline

### Session 1 (2026-02-28) — Full Project Initialization

**What was done:**

| Phase | Files Created | Status |
|-------|--------------|--------|
| 1. Foundation | `requirements.txt`, `config.py`, `database.py`, `models.py`, `.env` | Done |
| 2. API Clients | `tools/twenty_client.py`, `tools/bison_client.py`, `tools/sentiment.py` | Done |
| 3. Email Templates | `tools/email_templates.py` | Done |
| 4. FastAPI Webhooks | `main.py` | Done |
| 5. Scheduler | `scheduler.py` | Done |
| 6. CSV Seed Script | `tools/seed_leads.py` | Done |
| 7. Streamlit Dashboard | `dashboard.py` | Done |
| 8. Workflow Docs | `workflows/*.md` (5 SOPs) | Done |

**Verification performed:**
- All Python modules import successfully
- Database initializes with correct schema (3 tables: `leads`, `scheduled_tasks`, `system_logs`)
- FastAPI server starts, scheduler launches, `/health` returns 200
- Python venv created at `.venv/` with all deps installed

---

## Current Project Status

### What Works (Verified)
- All code imports and compiles without errors
- Database creates and schema is correct
- FastAPI server starts with embedded scheduler
- Health endpoint responds correctly
- Email templates generate proper subject/body pairs

### What's Pending (Not Yet Tested Against Live APIs)
- **Bison webhook ingestion** — endpoint built but needs real Bison payload format validation
- **Twenty CRM webhook ingestion** — endpoint built but needs real webhook payload testing
- **Sentiment analysis** — code written but needs OpenAI API key to test
- **Email sending via Bison** — client built but exact API endpoints need confirmation against Bison docs
- **Twenty CRM CRUD** — client built following Twenty REST API patterns, but field names (especially `customFields`) need validation against the actual workspace schema
- **Scheduler follow-up sending** — logic complete but needs end-to-end test with live APIs
- **Streamlit dashboard** — code complete but untested with real data
- **CSV seed script** — written but not yet run (leads table is empty)

### Configuration Needed
The `.env` file has placeholders for:
- `TWENTY_API_KEY` — needed
- `TWENTY_BASE_URL` — defaults to `https://api.twenty.com`
- `TWENTY_WEBHOOK_SECRET` — needed for HMAC verification
- `BISON_API_KEY` — needed
- `BISON_BASE_URL` — defaults to `https://dedi.emailbison.com`
- `OPENAI_API_KEY` — needed

---

## File Inventory

```
GOAP/
├── .env                          # API keys (template, needs credentials)
├── .gitignore                    # Ignores .env, .tmp/, .venv/, __pycache__/
├── .mcp.json                     # BridgeKit MCP connection (active)
├── CLAUDE.md                     # WAT framework instructions
├── DEVELOPMENT.md                # This file
├── follow_up_prd.md              # Original PRD (source of truth for requirements)
├── requirements.txt              # Python deps (fastapi, sqlalchemy, httpx, etc.)
├── config.py                     # Centralized env var loading
├── database.py                   # SQLAlchemy engine, session, init_db()
├── models.py                     # Lead, ScheduledTask, SystemLog ORM models
├── main.py                       # FastAPI app: /health, /webhook/bison, /webhook/twenty
├── scheduler.py                  # APScheduler: hourly check_follow_ups()
├── dashboard.py                  # Streamlit: queue, logs, error monitor
├── tools/
│   ├── __init__.py
│   ├── twenty_client.py          # TwentyCRMClient (create/update people, opps, notes)
│   ├── bison_client.py           # BisonClient (send_email, get_replies)
│   ├── sentiment.py              # GPT-4o-mini positive/negative classifier
│   ├── email_templates.py        # 4 templates: lead_magnet + 3 follow-ups
│   └── seed_leads.py             # One-time CSV → DB import
├── workflows/
│   ├── system_setup.md           # Deployment & config SOP
│   ├── webhook_bison.md          # Bison webhook handling SOP
│   ├── webhook_twenty.md         # Twenty webhook handling SOP
│   ├── follow_up_sequence.md     # 3-6-9 day follow-up SOP
│   └── troubleshooting.md        # Error recovery SOP
└── .tmp/
    ├── followup.db               # SQLite database (0 rows, schema ready)
    └── Jonathan_Garces_Interested_Leads.csv  # ~150 sample leads
```

---

## Database Schema

### leads
| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Internal ID |
| email | VARCHAR(255) UNIQUE | Lead's email |
| first_name, last_name | VARCHAR(100) | Contact name |
| bison_lead_id | INTEGER | Bison's internal lead ID |
| bison_inbox_id | VARCHAR(100) | Sender inbox for follow-ups |
| twenty_contact_id | VARCHAR(100) | Twenty CRM Person ID |
| twenty_opportunity_id | VARCHAR(100) | Twenty CRM Opportunity ID |
| campaign_status | VARCHAR(50) | State machine position |
| lead_magnet_url | TEXT | URL to send to lead |
| last_contact_date | DATETIME | Last outgoing email timestamp |
| follow_up_count | INTEGER | 0-3 counter |
| original_reply_text | TEXT | Lead's initial reply |
| sentiment | VARCHAR(20) | "positive" or "negative" |
| created_at, updated_at | DATETIME | Timestamps |

**State machine:**
```
New → Ready to Send → Lead Magnet Sent → Follow-up 1 → Follow-up 2 → Follow-up 3 → Finished
                           |                  |              |              |
                           +------------- Responded (at any point) -------+
```

### scheduled_tasks
Tracks pending/completed/cancelled follow-up sends. Indexed on `(status, scheduled_time)`.

### system_logs
Audit trail of every action. Indexed on `timestamp` and `level`. Powers the dashboard.

---

## Immediate Next Steps

### Priority 1: Wire Up Live APIs
1. Fill in `.env` with real API credentials
2. Test Twenty CRM client: create a test person, verify field names match workspace schema
3. Test Bison client: confirm exact endpoint paths (`/api/send-email`, `/api/replies`) against Bison API docs at `https://send.leadgenjay.com/api/reference`
4. Test sentiment analysis with a few sample replies from the CSV
5. Adjust API client code based on real response formats

### Priority 2: End-to-End Webhook Test
1. Start server locally with `uvicorn main:app --port 8000`
2. Use ngrok or similar to expose locally for webhook delivery
3. Send a test Bison webhook payload → verify lead creation in DB + CRM
4. Manually update a Twenty CRM opportunity → verify lead magnet email sends
5. Verify scheduler picks up due follow-ups

### Priority 3: Seed Existing Data
1. Run `python -m tools.seed_leads` to import the 150 existing leads
2. Note: `bison_inbox_id` is blank in the CSV — need to set this manually or via Bison API lookup

### Priority 4: Dashboard Validation
1. Run `streamlit run dashboard.py --server.port 8501`
2. Verify all three tabs render correctly with real data

---

## Future Vision: From Script to App

### Short-term Hardening
- **Webhook signature validation** — Bison webhook auth (if they support it)
- **Idempotency** — deduplicate webhook deliveries (Bison may send duplicates)
- **Structured logging** — replace print-style logging with JSON structured logs for better observability
- **Health checks** — add API connectivity checks to `/health` (can the server reach Twenty? Bison? OpenAI?)
- **Email template customization** — move templates to a config file or DB so users can edit without code changes

### Medium-term: Multi-tenant Architecture
- **Per-client configuration** — support multiple Bison accounts/inboxes per campaign
- **User authentication** — add auth to the dashboard and API endpoints
- **PostgreSQL migration** — swap SQLite for PostgreSQL when multiple workers are needed
- **Celery + Redis** — move scheduler to a proper task queue for reliability and horizontal scaling
- **Rate limit management** — centralized rate limiter across all API clients

### Long-term: Full SaaS Product
- **Multi-user dashboard** — role-based access (admin, sales rep, viewer)
- **Campaign builder UI** — let users create follow-up sequences via the dashboard instead of code
- **A/B testing** — multiple email template variants per follow-up step, track open/reply rates
- **Analytics** — conversion funnel (sent → opened → replied → meeting booked), per-campaign and per-inbox
- **CRM agnostic** — abstract the CRM layer to support HubSpot, Salesforce, Pipedrive alongside Twenty
- **Email provider agnostic** — abstract Bison into a provider interface, support Instantly, Smartlead, etc.
- **Webhook relay service** — instead of requiring a public URL, provide a managed webhook endpoint that queues events
- **AI-powered reply handling** — beyond positive/negative classification, auto-draft contextual responses for human review
- **Compliance layer** — CAN-SPAM / GDPR tracking, automatic unsubscribe handling, suppression list management
- **Docker + cloud deployment** — Dockerfile, docker-compose, one-click deploy to Railway/Render/Fly.io

### Technical Debt to Address Before Scaling
1. **Python 3.9** — upgrade to 3.11+ to drop `from __future__ import annotations` workaround and get performance gains
2. **No tests** — add pytest suite covering webhook handlers, scheduler logic, and template generation
3. **No migrations** — add Alembic for schema migrations (currently using `create_all()` which doesn't handle changes)
4. **Hardcoded Bison endpoints** — need to validate against actual API docs and potentially restructure
5. **No retry queue** — failed sends are logged but not retried beyond the immediate exponential backoff
6. **No monitoring** — add Sentry or similar for production error tracking

---

## Installed Dependencies (exact versions)

```
fastapi==0.115.6
uvicorn==0.34.0
sqlalchemy==2.0.36
httpx==0.28.1
apscheduler==3.10.4
openai==1.59.6
streamlit==1.41.1
python-dotenv==1.0.1
pydantic==2.10.4
```

Python runtime: **3.9.6** (macOS Darwin 23.6.0)

---

## Key Reference Links
- **Twenty CRM API:** `https://docs.twenty.com/developers/extend/capabilities/apis.md`
- **Twenty Webhooks:** `https://docs.twenty.com/developers/extend/capabilities/webhooks.md`
- **Bison API:** `https://send.leadgenjay.com/api/reference`
- **PRD:** `follow_up_prd.md` (in project root)
