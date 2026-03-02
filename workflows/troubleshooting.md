# Troubleshooting

## Common Issues

### Bison API Rate Limited (429)
**Symptom:** Errors in logs like "Bison API error: 429"
**Fix:** The client has exponential backoff built in (retries 3 times). If persistent:
- Check Bison account limits
- Increase `SCHEDULER_INTERVAL_HOURS` to spread sends over more time
- Check Error Monitor tab in dashboard for frequency

### Twenty CRM API Errors
**Symptom:** "crm_update_failed" or "crm_creation_failed" in logs
**Fix:**
- Verify `TWENTY_API_KEY` is valid (Settings → APIs & Webhooks)
- Check `TWENTY_BASE_URL` matches your instance
- Twenty API has a 100 calls/minute limit — check if you're hitting it
- Lead creation still works locally even if CRM sync fails

### Webhook Not Receiving Events
**Symptom:** No new entries in system_logs after expected events
**Fix:**
- Verify webhook URL is publicly accessible (not localhost in production)
- Check Bison/Twenty webhook configuration points to correct URL
- Test with: `curl -X POST http://localhost:8000/webhook/bison -H "Content-Type: application/json" -d '{"email":"test@test.com","reply_text":"I am interested","inbox_id":"test"}'`

### Database Locked Errors
**Symptom:** "database is locked" errors
**Fix:** SQLite only supports one writer at a time. This shouldn't happen in normal operation (single FastAPI process + read-only Streamlit). If it does:
- Ensure only one `uvicorn` instance is running
- Restart the FastAPI server
- If persistent, consider migrating to PostgreSQL (change `DATABASE_URL` in .env)

### Sentiment Misclassification
**Symptom:** Negative leads being created as positive (or vice versa)
**Fix:**
- Check the system prompt in `tools/sentiment.py`
- Review edge cases in logs and adjust the prompt
- Consider adding a "neutral" category for ambiguous responses

### Follow-ups Not Sending
**Symptom:** Leads stuck in "Lead Magnet Sent" or "Follow-up N" past expected time
**Fix:**
- Check scheduler is running: `GET /health` should show the server is up
- Verify `FOLLOWUP_DELAY_DAYS` and `SCHEDULER_INTERVAL_HOURS` in .env
- Check `last_contact_date` on the lead — it must be older than FOLLOWUP_DELAY_DAYS
- Look for errors in the Error Monitor dashboard tab
- Run manually: `python -c "from scheduler import check_follow_ups; check_follow_ups()"`

## Checking System Health

1. **API Health:** `curl http://localhost:8000/health`
2. **Dashboard:** `http://localhost:8501` — check Error Monitor tab
3. **Database:** `sqlite3 .tmp/followup.db "SELECT count(*) FROM leads; SELECT count(*) FROM scheduled_tasks WHERE status='pending';"`
4. **Logs:** Check System Logs tab in dashboard, filter by level "error"
