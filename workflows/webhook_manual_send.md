# Manual Email Send Workflow

## Objective
When a manual email is sent from any Bison campaign, automatically move the lead to a follow-up campaign and track them in the GOAP EXISTING pipeline in Twenty CRM.

## Trigger
- **Bison webhook event:** `MANUAL_EMAIL_SENT`
- **Endpoint:** `POST /webhook/bison`
- Fires when user manually sends an email from any campaign in Bison

## Payload
Key fields extracted from the Bison webhook payload:
- `data.lead.id` — Bison lead ID (used to attach to follow-up campaign)
- `data.lead.email` — Lead's email address
- `data.lead.first_name`, `data.lead.last_name` — Lead name
- `data.campaign.id` — Source campaign ID
- `data.sender_email.id` — Sender email account ID
- `data.sender_email.email` — Sender email address (inbox ID)
- `data.reply.email_subject` — Subject of the sent email

## Flow

```
MANUAL_EMAIL_SENT webhook received
        |
        v
Extract lead email + Bison IDs
        |
        v
Already in manual workflow? --> YES --> Return (duplicate)
        |
        NO
        v
1. Attach lead to BISON_MANUAL_FOLLOWUP_CAMPAIGN_ID
   (Bison will send follow-up sequence automatically)
        |
        v
2. Create/update Lead in local DB (workflow_type = "manual_send")
        |
        v
3. Create Person in Twenty CRM (find or create)
        |
        v
4. Create GOAP EXISTING pipeline record (status = INITIAL_SEND)
        |
        v
Done — waiting for follow-ups or reply
```

## Reply Detection (Kill Switch)

When a lead replies (via `LEAD_REPLIED` or `LEAD_INTERESTED` event):
1. Sentiment analysis on the reply text
2. **Positive reply:** Status → `RESPONDED`, CRM note with `[ACTION REQUIRED]` prefix, notification sent
3. **Negative reply:** Status → `UNSUBSCRIBED`, CRM note with `[UNSUBSCRIBED]` prefix

## Pipeline Stages (Twenty CRM)

| Stage | Value | Meaning |
|-------|-------|---------|
| Initial Send | `INITIAL_SEND` | Manual email sent, lead moved to follow-up campaign |
| Follow-up 1 | `FOLLOW_UP_1` | First follow-up sent by Bison |
| Follow-up 2 | `FOLLOW_UP_2` | Second follow-up sent |
| Follow-up 3 | `FOLLOW_UP_3` | Third follow-up sent |
| Responded | `RESPONDED` | Lead replied positively |
| Unsubscribed | `UNSUBSCRIBED` | Lead replied negatively |

## Required Configuration

| Env Var | Purpose |
|---------|---------|
| `BISON_MANUAL_FOLLOWUP_CAMPAIGN_ID` | Bison campaign with pre-built follow-up sequence |
| `NOTIFICATION_EMAIL` | Email address to notify when leads reply |

## Key Files

- `main.py` — `_handle_manual_email_sent()` handler + modified kill switch
- `tools/twenty_client.py` — `create_manual_pipeline_record()`, `update_manual_pipeline_record()`
- `tools/notifications.py` — Reply notification (currently logs + CRM note)
- `models.py` — `Lead.workflow_type`, `Lead.twenty_manual_pipeline_id`
- `config.py` — New env vars

## Edge Cases

- **Lead exists from inbound workflow:** The same Lead record gets `workflow_type` updated to `manual_send` and gets a `twenty_manual_pipeline_id`. Both CRM pipeline records coexist.
- **Bison attach fails:** CRM record creation still proceeds. Error is logged.
- **Missing BISON_MANUAL_FOLLOWUP_CAMPAIGN_ID:** Warning logged, lead still tracked in CRM.
