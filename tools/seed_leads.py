"""One-time script to import existing leads from CSV into the database.

Usage:
    python -m tools.seed_leads

Reads from .tmp/Jonathan_Garces_Interested_Leads.csv and populates the leads table.
Skips leads that already exist (by email).
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, init_db
from models import Lead

CSV_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "Jonathan_Garces_Interested_Leads.csv"


def seed_leads():
    init_db()
    db = SessionLocal()

    if not CSV_PATH.exists():
        print(f"CSV not found: {CSV_PATH}")
        return

    created = 0
    skipped = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("Email", "").strip().lower()
            if not email:
                continue

            # Skip if already exists
            existing = db.query(Lead).filter(Lead.email == email).first()
            if existing:
                skipped += 1
                continue

            # Parse dates
            reply_date = None
            raw_date = row.get("Date of Initial Reply", "").strip()
            if raw_date:
                try:
                    reply_date = datetime.strptime(raw_date, "%Y-%m-%d")
                except ValueError:
                    pass

            lead = Lead(
                email=email,
                bison_lead_id=int(row.get("Lead ID", 0)) if row.get("Lead ID", "").strip() else None,
                bison_inbox_id="",  # Unknown from CSV — needs to be set manually or via Bison API
                campaign_status="New",
                original_reply_text=row.get("Lead Full Body Reply", ""),
                sentiment="positive",  # These are from an "interested leads" export
                created_at=reply_date or datetime.utcnow(),
            )
            db.add(lead)
            created += 1

    db.commit()
    db.close()
    print(f"Seed complete: {created} leads created, {skipped} skipped (already exist)")


if __name__ == "__main__":
    seed_leads()
