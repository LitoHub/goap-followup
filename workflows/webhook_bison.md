# Bison Webhook Handling

## Objective
Process incoming reply events from Bison, classify sentiment, and create leads in CRM.

## Endpoint
`POST /webhook/bison`

## Expected Payload
```json
{
  "email": "lead@example.com",
  "reply_text": "The full body of the lead's reply...",
  "inbox_id": "sender-inbox-id",
  "lead_id": 123456,
  "first_name": "John",
  "last_name": "Doe"
}
```

## Flow

### Path A: New Lead
1. Payload received → logged to system_logs
2. No existing lead found by email
3. Sentiment analysis via GPT-4o-mini
4. If **positive**:
   - Create Lead record in local DB
   - Create Person in Twenty CRM
   - Create Opportunity in Twenty CRM (status: "New")
   - Create Note in Twenty CRM: "Positive sentiment detected"
5. If **negative**: log and return (no records created)

### Path B: Existing Lead Reply (Kill Switch)
1. Payload received → logged
2. Existing lead found with active status (Lead Magnet Sent, Follow-up 1/2/3)
3. Set campaign_status → "Responded"
4. Cancel all pending scheduled_tasks for this lead
5. Update Twenty CRM opportunity status
6. Create Note: "Reply detected — sequence cancelled"

### Path C: Duplicate Reply
1. Lead exists but already "Responded" or "Finished"
2. Log and return — no state change

## Error Cases
- Missing `email` field → 400 error
- OpenAI sentiment call fails → 500 error (logged)
- Twenty CRM API fails → Lead still created locally, CRM sync logged as error

## Key Constraint
The `inbox_id` from the payload is stored on the lead and used for all future follow-ups to maintain sender consistency.
