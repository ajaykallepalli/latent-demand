"""Signal extraction — sends content batches to Claude for latent demand analysis."""

from __future__ import annotations

import json
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

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    batch_size = settings.extraction_batch_size
    all_signals = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        platform = batch[0].get("platform", "unknown")

        content_text = format_content_batch(batch)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            count=len(batch),
            platform=platform,
            content=content_text,
        )

        logger.info(
            "extraction.batch",
            batch_num=i // batch_size + 1,
            items=len(batch),
            platform=platform,
        )

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
                continue

            # Convert extracted signals to storage format
            for raw_signal in raw_signals:
                signal = _format_signal(raw_signal, settings)
                if signal:
                    all_signals.append(signal)

            logger.info(
                "extraction.batch_complete",
                signals_found=len(raw_signals),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read=getattr(response.usage, "cache_read_input_tokens", 0),
            )

        except json.JSONDecodeError as e:
            logger.error("extraction.json_parse_error", error=str(e))
        except anthropic.APIError as e:
            logger.error("extraction.api_error", error=str(e))

    return all_signals


def _format_signal(raw_signal: dict, settings: Settings) -> dict | None:
    """Convert a raw extracted signal to the storage format."""
    title = raw_signal.get("title")
    if not title:
        return None

    signal_id = next_signal_id(settings.signals_path)
    evidence = raw_signal.get("evidence", {})
    if isinstance(evidence, dict):
        evidence = [evidence]

    return {
        "id": signal_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "description": raw_signal.get("description", ""),
        "signal_type": raw_signal.get("signal_type", "unknown"),
        "evidence": evidence,
        "friction_indicator": raw_signal.get("friction_indicator", ""),
        "potential_product": raw_signal.get("potential_product", ""),
        "scores": None,
        "status": "new",
        "related_signal_ids": [],
    }
