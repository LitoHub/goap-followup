from __future__ import annotations

import logging
import time
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


class TwentyCRMClient:
    """REST API client for Twenty CRM."""

    def __init__(self):
        self.base_url = config.TWENTY_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {config.TWENTY_API_KEY}",
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
                    logger.warning(f"Rate limited by Twenty CRM. Retrying in {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                if response.status_code == 204:
                    return None
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error(f"Twenty CRM API error: {e.response.status_code} {e.response.text}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Twenty CRM request error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_BASE ** (attempt + 1))
                    continue
                raise

        raise Exception("Max retries exceeded for Twenty CRM API")

    # --- People ---

    def create_person(self, email: str, first_name: str = "", last_name: str = "",
                      custom_fields: dict | None = None) -> dict:
        """Create a new person record in Twenty CRM."""
        payload: dict[str, Any] = {
            "name": {"firstName": first_name, "lastName": last_name},
            "emails": {"primaryEmail": email},
        }
        if custom_fields:
            payload["customFields"] = custom_fields

        result = self._request("POST", "/rest/people", json=payload)
        logger.info(f"Created person in Twenty CRM: {email}")
        return result

    def get_person_by_email(self, email: str) -> dict | None:
        """Find a person by email address."""
        params = {
            "filter": f'{{"emails":{{"primaryEmail":{{"eq":"{email}"}}}}}}'
        }
        result = self._request("GET", "/rest/people", params=params)
        records = result.get("data", result) if isinstance(result, dict) else result
        if records and isinstance(records, list) and len(records) > 0:
            return records[0]
        return None

    # --- Opportunities ---

    def create_opportunity(self, name: str, stage: str = "New",
                           contact_id: str = "", custom_fields: dict | None = None) -> dict:
        """Create a new opportunity in Twenty CRM."""
        payload: dict[str, Any] = {
            "name": name,
            "stage": stage,
        }
        if contact_id:
            payload["pointOfContactId"] = contact_id
        if custom_fields:
            payload["customFields"] = custom_fields

        result = self._request("POST", "/rest/opportunities", json=payload)
        logger.info(f"Created opportunity in Twenty CRM: {name}")
        return result

    def update_opportunity(self, opportunity_id: str, **fields) -> dict:
        """Update an opportunity's fields."""
        result = self._request("PATCH", f"/rest/opportunities/{opportunity_id}", json=fields)
        logger.info(f"Updated opportunity {opportunity_id}")
        return result

    # --- Notes ---

    def create_note(self, body: str, contact_ids: list[str] | None = None,
                    opportunity_id: str = "") -> dict:
        """Create a note attached to a person and/or opportunity."""
        payload: dict[str, Any] = {"body": body}
        if contact_ids:
            payload["noteTargets"] = [
                {"personId": cid} for cid in contact_ids
            ]
        if opportunity_id:
            if "noteTargets" not in payload:
                payload["noteTargets"] = []
            payload["noteTargets"].append({"opportunityId": opportunity_id})

        result = self._request("POST", "/rest/notes", json=payload)
        logger.info(f"Created note in Twenty CRM")
        return result
