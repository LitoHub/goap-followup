This is the comprehensive Product Requirements Document (PRD) designed to build an automated follow-up system. It bridges Twenty CRM, Bison, and a Python Backend.

PRD: Automated Cold Email Follow-up & CRM Integration System

## 1. Project Overview

The objective is to build a middleware system (Python) that orchestrates the lead lifecycle between Bison (Email Provider) and Twenty CRM. The system will automate lead creation based on sentiment, trigger lead magnet delivery via custom CRM fields, and manage a time-sensitive follow-up sequence (3-6-9 days) that automatically halts upon lead response.

## 2. Technical Stack

- Backend: Python (FastAPI or Flask recommended for webhook handling).
- CRM: Twenty CRM (Open Source).
- Email/Outreach: Bison.
- Database: SQLite or PostgreSQL (to track scheduled tasks and message states).
- Task Scheduling: Celery or a simple background worker with apscheduler.

## 3. CRM Data Model Requirements (Twenty CRM)

The coding agent should configure/ensure the following fields exist in the Opportunities or People object in Twenty CRM:

Field Name | Type | Description
lead_magnet_url | Text/URL | The URL to be sent to the lead.
bison_inbox_id | Text | The ID of the inbox used for the initial contact.
campaign_status | Select | [New, Ready to Send, Sent, Responded, Follow-up 1, Follow-up 2, Follow-up 3, Finished]
last_contact_date | DateTime | Timestamp of the last outgoing email.
follow_up_count | Number | Counter for sent follow-ups (0-3).

## 4. Workflow & Logic Stages

### Phase 1: Lead Qualification & Creation

1. Webhook Listener: Listen for new_reply events from Bison.
2. Sentiment Analysis: (Coding agent to implement via LLM like GPT-4o-mini).
 - If response is Positive:
    - Create a new Person and Opportunity in Twenty CRM.
    - Store the bison_inbox_id in the CRM record.
    - Set campaign_status to New.
 - If negative: Ignore/Archive.

### Phase 2: Lead Magnet Delivery

1. The Trigger: Monitor Twenty CRM via Webhooks.
- When the user updates lead_magnet_url AND moves the stage to Ready to Send.
2. Action:
    - The system fetches the lead_magnet_url and lead_email.
    - Sends a New Email via Bison using the stored bison_inbox_id.
    - Update CRM: Set campaign_status to Lead Magnet Sent and last_contact_date to Now.

### Phase 3: Response Detection (The "Kill Switch")

1. Continuous Listening: The system must listen for any subsequent replies from the lead.
2. Action: If a reply is received at any point:
    - Update CRM campaign_status to Responded.
    - Immediately cancel all future scheduled follow-ups for this lead.

### Phase 4: Automated Follow-up Sequence (3-6-9 Days)

The system runs a background worker every hour to check for leads requiring follow-up.

1. Follow-up 1:
    - Condition: campaign_status == 'Lead Magnet Sent' AND last_contact_date is > 3 days ago.
    - Action: Send Follow-up Email #1 via Bison. Update status to Follow-up 1, update last_contact_date.

2. Follow-up 2:
    - Condition: campaign_status == 'Follow-up 1' AND last_contact_date is > 3 days ago (Total 6).
    - Action: Send Follow-up Email #2. Update status to Follow-up 2, update last_contact_date.

3. Follow-up 3:
    - Condition: campaign_status == 'Follow-up 2' AND last_contact_date is > 3 days ago (Total 9).
    - Action: Send Follow-up Email #3. Update status to Finished.

## 5. API Integration Instructions for Coding Agent

### Twenty CRM Integration

- Docs: https://docs.twenty.com/developers/extend/capabilities/webhooks
- Requirement: Use the Twenty API to PATCH lead stages and GET custom field data.
- Requirement: Set up a Webhook in Twenty to notify the Python backend when lead_magnet_url is updated.

### Bison Integration

- Docs: https://send.leadgenjay.com/api/reference
- Requirement: Use the POST /send-email (or equivalent) endpoint.
- Critical: Ensure the inbox_id used for follow-ups matches the bison_inbox_id stored in the CRM to maintain sender reputation and consistency.

## 6. Functional Requirements

- Threading: While follow-ups are "New Messages," the system must ensure they are sent from the same email address that started the conversation.
- Concurrency: Ensure that if a lead responds minutes before a follow-up is scheduled, the follow-up is aborted.
- Error Handling: If Bison API returns a rate limit error, retry with exponential backoff.
- Logs: Maintain a log of every email sent and every webhook received for debugging.

## 7. Delivery Instructions

- Initialize a Python environment with FastAPI and SQLAlchemy.
- Create the Database Schema to track lead states.
- Build the /webhook/bison endpoint for sentiment and lead creation.
- Build the /webhook/twenty endpoint to trigger the initial Lead Magnet email.
- Create a scheduler.py script to handle the 3-6-9 day logic.
- Provide a .env template for API Keys (Twenty, Bison, OpenAI/LLM).

## 8. System Visibility & Observability Requirements

The user requires full, non-technical visibility into system executions, state changes, and errors. Implement the following two layers of observability:

### Layer 1: CRM Timeline Logging (Twenty CRM)

For every significant state change or action, the system must push a descriptive "Note" or "Activity" to the specific Contact/Opportunity record in Twenty CRM.

Events to Log:

- Positive sentiment detected -> Lead created.
- Lead Magnet URL detected -> Email fired (include timestamp).
- Follow-up scheduled -> Provide exact date/time.
- Reply detected -> Sequence killed.
- Errors -> (e.g., "Attempted to send Follow-up 1 but Bison returned an error.")

### Layer 2: Admin Dashboard (Streamlit)

Deploy a lightweight Streamlit web application alongside the backend to serve as a "Mission Control" for the user.

Required Views/Tabs:

1. Queue Management: A data table querying the backend database showing all pending tasks (Lead Email, Follow-up Number, Scheduled Execution Time).
2. System Logs: A human-readable history table of the last 100 actions taken by the background worker.
3. Error Monitor: A dedicated view for trapped exceptions (e.g., API rate limits, missing data) so the user knows if the system is failing silently.

