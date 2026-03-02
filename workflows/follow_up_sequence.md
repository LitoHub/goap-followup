# Follow-up Sequence (3-6-9 Days)

## Objective
Automatically send follow-up emails at 3-day intervals after lead magnet delivery, stopping immediately if the lead replies.

## Scheduler
- Runs every hour via APScheduler (embedded in FastAPI process)
- Function: `scheduler.check_follow_ups()`
- Configurable interval via `SCHEDULER_INTERVAL_HOURS` in .env

## State Machine

```
New → Ready to Send → Lead Magnet Sent → Follow-up 1 → Follow-up 2 → Follow-up 3 → Finished
                           |                  |              |              |
                           +---------- Responded (at any point) ----------+
```

## Follow-up Schedule

| Follow-up | Triggered When | Status After Send |
|-----------|---------------|-------------------|
| Lead Magnet | User sets URL + "Ready to Send" in CRM | Lead Magnet Sent |
| Follow-up 1 | Status = "Lead Magnet Sent" AND last_contact > 3 days | Follow-up 1 |
| Follow-up 2 | Status = "Follow-up 1" AND last_contact > 3 days | Follow-up 2 |
| Follow-up 3 | Status = "Follow-up 2" AND last_contact > 3 days | Finished |

## Pre-Send Kill Switch

Before every follow-up send, the scheduler:
1. Queries Bison for recent replies from the sender email
2. Checks if any reply came from this lead's email
3. If reply found → mark as "Responded", cancel all tasks, update CRM
4. If check fails (API error) → logs warning, proceeds with send

This is a safety net in case the Bison webhook was delayed or missed.

## Email Templates
Defined in `tools/email_templates.py`:
- `follow_up_1()` — casual check-in
- `follow_up_2()` — gentle bump
- `follow_up_3()` — final message (friendly close)

All follow-ups are sent as **new messages** (not thread replies) from the **same inbox** (bison_inbox_id) that initiated the original conversation.

## CRM Updates Per Follow-up
- Update opportunity `campaign_status` and `last_contact_date`
- Create a Note with timestamp and next follow-up date
- On final follow-up: Note says "Sequence complete"

## Configurable
- `FOLLOWUP_DELAY_DAYS` (default: 3) — days between each follow-up
- `SCHEDULER_INTERVAL_HOURS` (default: 1) — how often the scheduler checks
