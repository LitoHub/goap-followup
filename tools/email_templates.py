"""Email templates for lead magnet delivery and follow-up sequence.

Each function returns a (subject, body) tuple. These are pure functions
with no side effects — easy to test and iterate on copy.
"""
from __future__ import annotations


def lead_magnet_email(lead_name: str, lead_magnet_url: str) -> tuple[str, str]:
    """Initial lead magnet delivery email."""
    first = lead_name.split()[0] if lead_name.strip() else "there"
    subject = f"Here's what I promised you"
    body = (
        f"Hey {first},\n\n"
        f"Thanks for your interest — here's the resource I mentioned:\n\n"
        f"{lead_magnet_url}\n\n"
        f"Take a look when you get a chance and let me know if you have any questions.\n\n"
        f"Talk soon"
    )
    return subject, body


def follow_up_1(lead_name: str) -> tuple[str, str]:
    """First follow-up — 3 days after lead magnet delivery."""
    first = lead_name.split()[0] if lead_name.strip() else "there"
    subject = f"Quick check-in"
    body = (
        f"Hey {first},\n\n"
        f"Just checking in — did you get a chance to look at what I sent over?\n\n"
        f"Happy to answer any questions or jump on a quick call if that's easier.\n\n"
        f"Let me know"
    )
    return subject, body


def follow_up_2(lead_name: str) -> tuple[str, str]:
    """Second follow-up — 6 days after lead magnet delivery."""
    first = lead_name.split()[0] if lead_name.strip() else "there"
    subject = f"Still on your radar?"
    body = (
        f"Hey {first},\n\n"
        f"I know things get busy — just wanted to bump this in case it slipped through.\n\n"
        f"If now's not the right time, no worries at all. But if you're still interested, "
        f"I'd love to chat for 15 minutes and see if it makes sense.\n\n"
        f"What do you think?"
    )
    return subject, body


def follow_up_3(lead_name: str) -> tuple[str, str]:
    """Third and final follow-up — 9 days after lead magnet delivery."""
    first = lead_name.split()[0] if lead_name.strip() else "there"
    subject = f"Last one from me"
    body = (
        f"Hey {first},\n\n"
        f"I'll keep this short — this is my last follow-up on this.\n\n"
        f"If you're interested in exploring this further, just reply and we can "
        f"pick things up. Otherwise, no hard feelings.\n\n"
        f"Wishing you the best"
    )
    return subject, body
