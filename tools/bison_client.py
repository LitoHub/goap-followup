from __future__ import annotations

import logging
import time

import httpx

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


class BisonClient:
    """REST API client for Bison (EmailBison)."""

    def __init__(self):
        self.base_url = config.BISON_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {config.BISON_API_KEY}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        """Make an HTTP request with exponential backoff on rate limits."""
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

    def send_email(self, inbox_id: str, to_email: str, subject: str, body: str) -> dict:
        """Send an email via Bison using a specific inbox.

        Follow-ups are sent as new messages (not thread replies)
        but always from the same inbox_id to maintain sender consistency.
        """
        payload = {
            "inbox_id": inbox_id,
            "to": to_email,
            "subject": subject,
            "body": body,
        }
        result = self._request("POST", "/api/send-email", json=payload)
        logger.info(f"Sent email via Bison: to={to_email}, inbox={inbox_id}")
        return result

    def get_replies(self, sender_email: str, limit: int = 50) -> list:
        """Get replies for a specific sender email.

        Used as a pre-send check (kill switch) to verify the lead
        hasn't responded before sending a follow-up.
        """
        params = {
            "sender_email": sender_email,
            "limit": limit,
        }
        result = self._request("GET", "/api/replies", params=params)
        if isinstance(result, list):
            return result
        return result.get("data", []) if isinstance(result, dict) else []

    def get_campaign_leads(self, campaign_id: str, interested_only: bool = True) -> list:
        """Get leads from a specific campaign."""
        params = {
            "campaign_id": campaign_id,
            "interested_only": str(interested_only).lower(),
        }
        result = self._request("GET", "/api/leads", params=params)
        if isinstance(result, list):
            return result
        return result.get("data", []) if isinstance(result, dict) else []
