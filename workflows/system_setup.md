# System Setup & Deployment

## Objective
Get the follow-up system running locally with all services connected.

## Prerequisites
- Python 3.9+
- Twenty CRM account with API key
- Bison account with API key
- OpenAI API key

## Setup Steps

### 1. Install Dependencies
```bash
cd /Users/pablogaviria/Projects/Parallelo/GOAP
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
Edit `.env` with your actual credentials:
- `TWENTY_API_KEY` — from Twenty Settings → APIs & Webhooks → Create Key
- `TWENTY_BASE_URL` — `https://api.twenty.com` for cloud, or your self-hosted URL
- `TWENTY_WEBHOOK_SECRET` — from Twenty webhook configuration
- `BISON_API_KEY` — from Bison account settings
- `BISON_BASE_URL` — `https://dedi.emailbison.com` or your Bison instance
- `OPENAI_API_KEY` — from OpenAI platform

### 3. Initialize Database
```bash
python -c "from database import init_db; init_db()"
```
This creates `.tmp/followup.db` with the leads, scheduled_tasks, and system_logs tables.

### 4. (Optional) Seed Existing Leads
```bash
python -m tools.seed_leads
```

### 5. Configure Webhooks

**Bison:** Set your webhook URL to `https://{your-domain}/webhook/bison` for `new_reply` events.

**Twenty CRM:** Go to Settings → APIs & Webhooks → Webhooks → Create Webhook. Set URL to `https://{your-domain}/webhook/twenty`. All events will be sent (Twenty doesn't support filtering yet).

### 6. Start the Backend
```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```
The scheduler starts automatically with the server.

### 7. Start the Dashboard
```bash
streamlit run dashboard.py --server.port 8501
```

## Verification
- `GET http://localhost:8000/health` should return `{"status": "ok", ...}`
- Dashboard at `http://localhost:8501` should load with three tabs

## Notes
- For production, use a reverse proxy (nginx) with HTTPS for webhook security
- The scheduler runs inside the FastAPI process — no separate worker needed
- SQLite is stored in `.tmp/followup.db` which is gitignored
