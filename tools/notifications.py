from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)


def send_reply_notification(lead_email: str, lead_name: str,
                            reply_preview: str = "") -> bool:
    """Notify the user when a manual-workflow lead replies.

    Currently logs the notification. The CRM note with [ACTION REQUIRED]
    prefix is created by the caller (main.py) and Twenty CRM's built-in
    notifications will alert the user.

    Future: extend with SMTP, Slack webhook, or BridgeKit integration.
    """
    if not config.NOTIFICATION_EMAIL:
        logger.warning("NOTIFICATION_EMAIL not configured — notification logged only")

    preview = reply_preview[:200] if reply_preview else "(no preview)"
    logger.info(
        f"[NOTIFICATION] Lead replied — {lead_name} ({lead_email}). "
        f"Preview: {preview}. "
        f"Target: {config.NOTIFICATION_EMAIL or 'not configured'}"
    )
    return True
