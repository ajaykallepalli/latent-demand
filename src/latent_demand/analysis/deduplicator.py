"""Claude-powered deduplication against existing signals."""

from __future__ import annotations

import json

import anthropic
import structlog

from latent_demand.config import Settings
from latent_demand.storage import read_json

logger = structlog.get_logger()

DEDUP_SYSTEM = """\
You are deduplicating latent demand signals. You will be given a new signal \
and a list of existing signals. Determine if the new signal is a duplicate \
or close variant of any existing signal.

Two signals are duplicates if they describe the same underlying unmet need, \
even if the specific tools or wording differ. For example:
- "Users chaining Whisper + Claude for meeting notes" and \
  "People building speech-to-summary pipelines with AI" are duplicates.
- "Users uploading food photos for calorie estimates" and \
  "People using vision AI to track nutrition" are duplicates.
- "Users building custom CRM with spreadsheets + AI" and \
  "Users automating meeting notes with AI" are NOT duplicates.

Return JSON:
```json
{
  "is_duplicate": true/false,
  "duplicate_of": "signal_id or null",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}
```\
"""

DEDUP_USER_TEMPLATE = """\
New signal:
- Title: {new_title}
- Description: {new_description}
- Type: {new_type}

Existing signals:
{existing_list}

Is this new signal a duplicate of any existing signal? Return only JSON.\
"""


def check_duplicate(
    new_signal: dict,
    settings: Settings,
) -> dict:
    """Check if a signal is a duplicate of an existing one.

    Returns: {"is_duplicate": bool, "duplicate_of": str|None, "confidence": float}
    """
    existing_signals = read_json(settings.signals_path)

    if not existing_signals:
        return {"is_duplicate": False, "duplicate_of": None, "confidence": 1.0}

    # Only send a window of recent signals to keep context manageable
    recent = existing_signals[-settings.max_signals_for_dedup :]

    existing_list = ""
    for sig in recent:
        existing_list += f"- [{sig['id']}] {sig['title']}: {sig.get('description', '')[:150]}\n"

    user_prompt = DEDUP_USER_TEMPLATE.format(
        new_title=new_signal["title"],
        new_description=new_signal.get("description", ""),
        new_type=new_signal.get("signal_type", ""),
        existing_list=existing_list,
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.extraction_model,  # Use Sonnet for dedup (cheaper)
            max_tokens=512,
            system=[{"type": "text", "text": DEDUP_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:-1])

        result = json.loads(raw_text)

        logger.info(
            "dedup.check",
            signal=new_signal["title"][:50],
            is_duplicate=result.get("is_duplicate", False),
            duplicate_of=result.get("duplicate_of"),
            confidence=result.get("confidence", 0),
        )
        return result

    except (json.JSONDecodeError, anthropic.APIError) as e:
        logger.error("dedup.error", error=str(e))
        # On error, assume not a duplicate to avoid losing signals
        return {"is_duplicate": False, "duplicate_of": None, "confidence": 0.0}


def deduplicate_signals(
    new_signals: list[dict],
    settings: Settings,
) -> list[dict]:
    """Filter out duplicate signals from a list of newly extracted signals.

    Returns only the novel signals. For duplicates, merges evidence into
    the existing signal.
    """
    from latent_demand.storage import read_json, update_signal

    novel = []

    for signal in new_signals:
        result = check_duplicate(signal, settings)

        if result.get("is_duplicate") and result.get("confidence", 0) > 0.7:
            # Merge evidence into existing signal
            existing_id = result.get("duplicate_of")
            if existing_id:
                existing_signals = read_json(settings.signals_path)
                for existing in existing_signals:
                    if existing["id"] == existing_id:
                        existing_evidence = existing.get("evidence", [])
                        new_evidence = signal.get("evidence", [])
                        existing_evidence.extend(new_evidence)
                        update_signal(
                            settings.signals_path,
                            existing_id,
                            {"evidence": existing_evidence},
                        )
                        logger.info(
                            "dedup.merged",
                            new_signal=signal["title"][:50],
                            into=existing_id,
                        )
                        break
        else:
            novel.append(signal)

    logger.info(
        "dedup.complete",
        total=len(new_signals),
        novel=len(novel),
        duplicates=len(new_signals) - len(novel),
    )
    return novel
