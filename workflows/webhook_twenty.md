# Twenty CRM Webhook Handling

## Objective
Trigger lead magnet email delivery when a user sets the lead_magnet_url and moves status to "Ready to Send" in Twenty CRM.

## Endpoint
`POST /webhook/twenty`

## Expected Payload
```json
{
  "event": "opportunity.updated",
  "data": {
    "id": "opportunity-uuid",
    "customFields": {
      "lead_magnet_url": "https://example.com/resource",
      "campaign_status": "Ready to Send"
    }
  },
  "timestamp": "2026-02-28T15:30:50Z"
}
```

## Security
- HMAC SHA256 signature verification using `X-Twenty-Webhook-Signature` and `X-Twenty-Webhook-Timestamp` headers
- Signature = HMAC(secret, "{timestamp}:{payload_body}")
- Only validated if `TWENTY_WEBHOOK_SECRET` is set in .env

## Flow

1. Validate HMAC signature
2. Parse event type — only process `opportunity.updated`
3. Check if `lead_magnet_url` is set AND `campaign_status` is "Ready to Send"
4. Find lead in local DB by `twenty_opportunity_id`
5. Send lead magnet email via Bison (using stored `bison_inbox_id`)
6. Update local DB: status → "Lead Magnet Sent", set `last_contact_date`
7. Schedule Follow-up 1 (3 days from now)
8. Update Twenty CRM: status + last_contact_date
9. Create Note: "Lead magnet sent. Follow-up 1 scheduled for {date}."

## Events Ignored
- Any event other than `opportunity.updated`
- Updates that don't include both `lead_magnet_url` and `campaign_status = "Ready to Send"`
- Opportunities not found in local DB (logged as warning)

## Error Cases
- Invalid HMAC signature → 401
- Bison send fails → 500 (logged as error)
- Twenty CRM note creation fails → logged but doesn't block the flow
