import logging

from google import genai

import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a cold email response classifier. Analyze the lead's reply and classify it as either "positive" or "negative".

POSITIVE means the lead shows interest:
- Asking about pricing, features, or details
- Requesting a call or meeting
- Asking for more information
- Forwarding internally or mentioning a colleague
- Expressing curiosity or openness
- Requesting a lead magnet, demo, or resource

NEGATIVE means the lead is not interested:
- Explicit rejection ("not interested", "no thanks")
- Unsubscribe or opt-out request
- Hostile or annoyed response
- Out of office with no interest signal
- Wrong person with no referral

Respond with ONLY the word "positive" or "negative". Nothing else."""


def analyze_sentiment(reply_text: str) -> str:
    """Classify a lead's email reply as positive or negative using Gemini.

    Args:
        reply_text: The full body of the lead's reply.

    Returns:
        "positive" or "negative"
    """
    client = genai.Client(api_key=config.GOOGLE_API_KEY)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\n---\n\nLead reply to classify:\n{reply_text}",
        )
        result = response.text.strip().lower()

        if result not in ("positive", "negative"):
            logger.warning(f"Unexpected sentiment result: {result}. Defaulting to negative.")
            return "negative"

        logger.info(f"Sentiment analysis: {result}")
        return result

    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        raise
