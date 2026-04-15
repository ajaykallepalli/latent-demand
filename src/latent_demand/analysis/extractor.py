"""Signal extraction — sends content batches to Claude for latent demand analysis."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import anthropic
import structlog

from latent_demand.analysis.prompts.extraction import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_content_batch,
)
from latent_demand.config import Settings
from latent_demand.storage import next_signal_id, read_json

logger = structlog.get_logger()

# Keywords that suggest content MIGHT contain a latent demand signal.
# Items without any of these are skipped before sending to Claude.
_SIGNAL_KEYWORDS = re.compile(
    r"chatgpt|gpt-?[45]|claude|openai|gemini|copilot|midjourney|dall-?e|"
    r"stable.diffusion|whisper|llm|language.model|"
    r"artificial.intelligence|machine.learning|"
    r"automat(?:e|ed|ion|ing)|script|spreadsheet.hack|workaround|"
    r"i(?:'ve)?\s+(?:built|made|use|created|wrote)\s|started\s+using|"
    r"workflow|every\s+(?:week|day|morning)\s+i|hours?\s+doing|manually|"
    r"i\s+wish|why\s+doesn'?t|why\s+isn'?t\s+there|"
    r"chrome\s+extension|google\s+sheets|zapier|make\.com|n8n|airtable",
    re.IGNORECASE,
)


def pre_filter(items: list[dict]) -> list[dict]:
    """Filter items to only those likely to contain latent demand signals.

    Domain-specific subreddit posts about cooking recipes or workout routines
    won't contain AI usage signals. This saves ~80% of API calls.
    """
    filtered = []
    for item in items:
        text = (item.get("title", "") + " " + item.get("body", "")).lower()
        if _SIGNAL_KEYWORDS.search(text):
            filtered.append(item)

    skipped = len(items) - len(filtered)
    if skipped:
        logger.info("extraction.pre_filter", total=len(items), kept=len(filtered), skipped=skipped)
    return filtered


def extract_signals(
    items: list[dict],
    settings: Settings,
) -> list[dict]:
    """Extract latent demand signals from a batch of raw content items.

    Sends content to Claude in batches and returns structured signal dicts
    ready to be stored in signals.json.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for extraction. Set it in .env")

    # Pre-filter to skip items unlikely to contain signals
    items = pre_filter(items)
    if not items:
        logger.info("extraction.skip", reason="no items passed pre-filter")
        return []

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    batch_size = settings.extraction_batch_size
    all_signals = []

    # Pre-compute starting signal ID to avoid collisions within a run
    existing = read_json(settings.signals_path)
    if existing:
        last_num = max(int(s["id"].split("_")[1]) for s in existing)
    else:
        last_num = 0
    _counter = {"n": last_num}

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        platform = batch[0].get("platform", "unknown")

        # Collect source names for context
        sources_in_batch = set(item.get("source", "") for item in batch)
        source_context = ", ".join(s for s in sources_in_batch if s) or "mixed"

        content_text = format_content_batch(batch)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            count=len(batch),
            platform=platform,
            source_context=source_context,
            content=content_text,
        )

        logger.info(
            "extraction.batch",
            batch_num=i // batch_size + 1,
            items=len(batch),
            platform=platform,
        )

        for attempt in range(3):
            try:
                response = client.messages.create(
                    model=settings.extraction_model,
                    max_tokens=4096,
                    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user_prompt}],
                )

                raw_text = response.content[0].text.strip()

                # Handle markdown code blocks
                if raw_text.startswith("```"):
                    lines = raw_text.split("\n")
                    raw_text = "\n".join(lines[1:-1])

                raw_signals = json.loads(raw_text)

                if not isinstance(raw_signals, list):
                    logger.warning("extraction.invalid_response", response=raw_text[:200])
                    break

                # Convert extracted signals to storage format
                for raw_signal in raw_signals:
                    _counter["n"] += 1
                    signal = _format_signal(raw_signal, _counter["n"])
                    if signal:
                        all_signals.append(signal)

                logger.info(
                    "extraction.batch_complete",
                    signals_found=len(raw_signals),
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_read=getattr(response.usage, "cache_read_input_tokens", 0),
                )

                # Rate limit: ~6 batches/min to stay under 30k tokens/min
                time.sleep(10)
                break

            except anthropic.RateLimitError:
                wait = 30 * (attempt + 1)
                logger.warning("extraction.rate_limited", wait_seconds=wait, attempt=attempt + 1)
                time.sleep(wait)
            except json.JSONDecodeError as e:
                logger.error("extraction.json_parse_error", error=str(e))
                break
            except anthropic.APIError as e:
                logger.error("extraction.api_error", error=str(e))
                break

    return all_signals


def _format_signal(raw_signal: dict, seq_num: int) -> dict | None:
    """Convert a raw extracted signal to the storage format."""
    title = raw_signal.get("title")
    if not title:
        return None

    signal_id = f"sig_{seq_num:03d}"
    evidence = raw_signal.get("evidence", {})
    if isinstance(evidence, dict):
        evidence = [evidence]

    return {
        "id": signal_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "description": raw_signal.get("description", ""),
        "signal_type": raw_signal.get("signal_type", "unknown"),
        "user_context": raw_signal.get("user_context", ""),
        "evidence": evidence,
        "friction_indicator": raw_signal.get("friction_indicator", ""),
        "potential_product": raw_signal.get("potential_product", ""),
        "market_size_hint": raw_signal.get("market_size_hint", ""),
        "scores": None,
        "status": "new",
        "related_signal_ids": [],
    }
