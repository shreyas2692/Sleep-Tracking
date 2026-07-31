"""Claude-generated weekly sleep summary.

Optional feature: activates only when ANTHROPIC_API_KEY is set (or another
credential source the anthropic SDK resolves). Without it the endpoint
reports {"available": false} and clients hide the card.

Copy rules mirror the InsightEngine: trends over single nights, neutral
phrasing, no scores, no alarmism (see PRODUCT.md on orthosomnia).
"""

import os

try:
    import anthropic
except ImportError:  # pragma: no cover - dependency is in requirements.txt
    anthropic = None

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are the weekly-summary writer inside a privacy-first sleep tracker.
You receive the user's aggregated sleep statistics as JSON and write a short,
plain-language summary of how their sleep has been trending.

Rules:
- 2 short paragraphs maximum, under 120 words total. No headings, no lists,
  no markdown. Address the user as "you".
- Focus on multi-week trends and patterns (weekday differences, consistency,
  direction of change) — never judge a single night.
- Neutral, warm, matter-of-fact tone. Never alarmist, never clinical advice,
  no medical claims, no numeric "scores".
- At most one gentle, practical observation the user could act on, phrased
  as an option, not an instruction.
- If the data is thin or unremarkable, say so plainly and keep it short."""


def summary_available():
    """True when the SDK is importable and a credential is configured."""
    return anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))


def generate_summary(digest_json):
    """Return summary text for the given insights digest, or raise."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": digest_json}],
    )
    if response.stop_reason == "refusal":
        return None
    return next(
        (block.text for block in response.content if block.type == "text"), None
    )
