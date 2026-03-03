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
    """REST API client for Twenty CRM.

    Uses two objects:
    - /rest/people — standard People object for contacts
    - /rest/goapNewPipelines — custom object "GOAP NEW PIPELINE" for tracking
      the follow-up state machine
    """

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
                body = e.response.text[:500]
                logger.error(f"Twenty CRM API error: {e.response.status_code} {body}")
                raise Exception(f"Twenty CRM {e.response.status_code}: {body}") from e
            except httpx.RequestError as e:
                logger.error(f"Twenty CRM request error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_BASE ** (attempt + 1))
                    continue
                raise

        raise Exception("Max retries exceeded for Twenty CRM API")

    def _extract_data(self, result: dict | list | None) -> dict:
        """Extract the actual record from Twenty's response wrapper."""
        if isinstance(result, dict):
            data = result.get("data", result)
            if isinstance(data, dict):
                # Response is {"data": {"createGoapNewPipeline": {...}}} or similar
                for key, val in data.items():
                    if isinstance(val, dict) and "id" in val:
                        return val
                return data
        return result or {}

    # --- People ---

    def find_person_by_email(self, email: str) -> dict | None:
        """Search for an existing person by email. Returns the person dict or None."""
        from urllib.parse import quote
        safe_email = quote(email, safe="")
        result = self._request(
            "GET",
            f"/rest/people?filter=emails.primaryEmail[eq]:{safe_email}&limit=5",
        )
        records = result if isinstance(result, list) else (result or {}).get("data", {}).get("people", [])
        if records and isinstance(records, list):
            for person in records:
                person_email = person.get("emails", {}).get("primaryEmail", "")
                if person_email.lower() == email.lower():
                    logger.info(f"Found existing person for {email}: {person.get('id', '')}")
                    return person
        return None

    def create_person(self, email: str, first_name: str = "",
                      last_name: str = "") -> dict:
        """Create a new person record in Twenty CRM."""
        payload: dict[str, Any] = {
            "name": {"firstName": first_name, "lastName": last_name},
            "emails": {"primaryEmail": email},
        }
        result = self._request("POST", "/rest/people", json=payload)
        record = self._extract_data(result)
        logger.info(f"Created person in Twenty CRM: {email} (id={record.get('id', '')})")
        return record

    def find_or_create_person(self, email: str, first_name: str = "",
                              last_name: str = "") -> dict:
        """Find existing person by email, or create a new one."""
        existing = self.find_person_by_email(email)
        if existing:
            return existing
        return self.create_person(email, first_name, last_name)

    # --- GOAP Pipeline (custom object) ---

    def create_pipeline_record(self, name: str, bison_inbox_id: str = "",
                               person_id: str = "",
                               lead_reply: str = "",
                               lead_email: str = "") -> dict:
        """Create a new record in the GOAP NEW PIPELINE custom object."""
        payload: dict[str, Any] = {
            "name": name,
            "campaignStatus": "NEW",
            "bisonInboxId": bison_inbox_id,
        }
        if lead_reply:
            payload["leadReply"] = lead_reply
        if lead_email:
            payload["leadEmail"] = {"primaryEmail": lead_email}
        result = self._request("POST", "/rest/goapNewPipelines", json=payload)
        record = self._extract_data(result)
        logger.info(f"Created GOAP pipeline record: {name} (id={record.get('id', '')})")
        return record

    def update_pipeline_record(self, record_id: str, **fields) -> dict:
        """Update a GOAP pipeline record.

        Common updates:
            campaignStatus="LEAD_MAGNET_SENT"
            lastContactDate="2026-01-01T00:00:00Z"
            followUpCount=1
        """
        result = self._request("PATCH", f"/rest/goapNewPipelines/{record_id}", json=fields)
        record = self._extract_data(result)
        logger.info(f"Updated GOAP pipeline record {record_id}")
        return record

    # --- Notes ---

    def create_note(self, text: str, contact_ids: list[str] | None = None,
                    pipeline_record_id: str = "") -> dict:
        """Create a note and link it to person/pipeline record via noteTargets."""
        payload: dict[str, Any] = {
            "title": text[:255] if len(text) > 255 else text,
            "bodyV2": {"blocknote": None, "markdown": text},
        }

        result = self._request("POST", "/rest/notes", json=payload)
        record = self._extract_data(result)
        note_id = record.get("id", "")
        logger.info(f"Created note in Twenty CRM: {note_id}")

        # Link note to person(s) and/or pipeline record via noteTargets
        if note_id:
            targets = []
            if contact_ids:
                for pid in contact_ids:
                    if pid:
                        targets.append(("person", pid))
            if pipeline_record_id:
                targets.append(("goapNewPipeline", pipeline_record_id))

            for target_type, target_id in targets:
                try:
                    self._request("POST", "/rest/noteTargets", json={
                        "noteId": note_id,
                        "targetObjectNameSingular": target_type,
                        "targetObjectRecordId": target_id,
                    })
                    logger.info(f"Linked note {note_id} to {target_type} {target_id}")
                except Exception as e:
                    logger.warning(f"Failed to link note to {target_type} {target_id}: {e}")

        return record
