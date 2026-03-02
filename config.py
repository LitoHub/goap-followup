import os
from dotenv import load_dotenv

load_dotenv()

# Twenty CRM
TWENTY_API_KEY = os.getenv("TWENTY_API_KEY", "")
TWENTY_BASE_URL = os.getenv("TWENTY_BASE_URL", "https://api.twenty.com")
TWENTY_WEBHOOK_SECRET = os.getenv("TWENTY_WEBHOOK_SECRET", "")

# Bison (EmailBison)
BISON_API_KEY = os.getenv("BISON_API_KEY", "")
BISON_BASE_URL = os.getenv("BISON_BASE_URL", "https://dedi.emailbison.com")
BISON_OUTBOUND_CAMPAIGN_ID = os.getenv("BISON_OUTBOUND_CAMPAIGN_ID", "")  # Only process replies from this campaign
BISON_FOLLOWUP_CAMPAIGN_ID = os.getenv("BISON_FOLLOWUP_CAMPAIGN_ID", "")  # Pre-built follow-up campaign

# Google Gemini (sentiment analysis)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Database
# Railway provides postgres:// but SQLAlchemy requires postgresql://
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///.tmp/followup.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Scheduler
SCHEDULER_INTERVAL_HOURS = int(os.getenv("SCHEDULER_INTERVAL_HOURS", "1"))
FOLLOWUP_DELAY_DAYS = int(os.getenv("FOLLOWUP_DELAY_DAYS", "3"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
