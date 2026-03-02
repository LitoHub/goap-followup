from __future__ import annotations

import logging
import time
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


class BisonClient:
    """REST API client for Bison (EmailBison).

    Bison is a campaign sequencer — it does NOT have a general-purpose
    "send email" endpoint. Emails are sent through campaign sequences.

    API Reference: https://dedi.emailbison.com/api/reference
    Auth: Bearer token via Authorization header.
    Pagination: 15 items/page, use ?page=N.
    """

    def __init__(self):
        self.base_url = config.BISON_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {config.BISON_API_KEY}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        """Make an HTTP request with exponential backoff on 429s."""
        url = f"{self.base_url}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(timeout=30) as client:
                    response = client.request(method, url, headers=self.headers, **kwargs)

                if response.status_code == 429:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning(f"Rate limited by Bison. Retrying in {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                if response.status_code == 204:
                    return None
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error(f"Bison API error: {e.response.status_code} {e.response.text}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Bison request error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_BASE ** (attempt + 1))
                    continue
                raise

        raise Exception("Max retries exceeded for Bison API")

    # --- Leads ---

    def get_lead_replies(self, lead_id: int | str, status: str | None = None,
                         campaign_id: int | None = None) -> list[dict]:
        """Get replies for a specific lead.

        Args:
            lead_id: Bison lead ID (integer) or lead email address.
            status: Filter by status: 'interested', 'automated_reply', 'not_automated_reply'.
            campaign_id: Filter replies to a specific campaign.
        """
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if campaign_id:
            params["campaign_id"] = campaign_id

        result = self._request("GET", f"/api/leads/{lead_id}/replies", params=params)
        if isinstance(result, dict):
            return result.get("data", [])
        return result if isinstance(result, list) else []

    # --- Campaigns ---

    def attach_leads_to_campaign(self, campaign_id: int | str, lead_ids: list[int]) -> dict | None:
        """Attach leads to a campaign. Leads start receiving the sequence.

        Note: Takes up to 5 minutes for leads to sync after attachment.
        """
        payload = {"lead_ids": lead_ids}
        result = self._request(
            "POST", f"/api/campaigns/{campaign_id}/leads/attach-leads", json=payload
        )
        logger.info(f"Attached {len(lead_ids)} leads to Bison campaign {campaign_id}")
        return result

    def resume_campaign(self, campaign_id: int | str) -> dict | None:
        """Launch or resume a paused campaign."""
        result = self._request("PATCH", f"/api/campaigns/{campaign_id}/resume")
        logger.info(f"Resumed Bison campaign {campaign_id}")
        return result

    # --- Replies ---

    def get_replies(self, status: str | None = None, campaign_id: int | None = None,
                    sender_email_id: int | None = None, folder: str = "inbox",
                    page: int = 1) -> dict:
        """Get replies from the global inbox.

        Args:
            status: 'interested', 'automated_reply', 'not_automated_reply'.
            campaign_id: Filter by campaign.
            sender_email_id: Filter by sender email.
            folder: 'inbox', 'sent', 'spam', 'bounced', 'all'.
            page: Page number (15 items per page).
        """
        params: dict[str, Any] = {"folder": folder, "page": page}
        if status:
            params["status"] = status
        if campaign_id:
            params["campaign_id"] = campaign_id
        if sender_email_id:
            params["sender_email_id"] = sender_email_id

        result = self._request("GET", "/api/replies", params=params)
        return result if isinstance(result, dict) else {"data": result or []}

    def reply_to_email(self, reply_id: int, message: str, sender_email_id: int,
                       to_emails: list[dict]) -> dict | None:
        """Send a reply to an existing email thread.

        Args:
            reply_id: The Bison reply ID to respond to.
            message: Email body content.
            sender_email_id: Integer ID of the sender email account.
            to_emails: List of dicts: [{"name": "...", "email_address": "..."}].
        """
        payload = {
            "message": message,
            "sender_email_id": sender_email_id,
            "to_emails": to_emails,
        }
        result = self._request("POST", f"/api/replies/{reply_id}/reply", json=payload)
        logger.info(f"Sent reply via Bison reply_id={reply_id}")
        return result

    # --- Sender Emails ---

    def get_sender_emails(self) -> list[dict]:
        """List all sender email accounts."""
        result = self._request("GET", "/api/sender-emails")
        if isinstance(result, dict):
            return result.get("data", [])
        return result if isinstance(result, list) else []
