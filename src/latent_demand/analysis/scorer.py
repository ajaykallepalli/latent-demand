"""Deep scoring of extracted signals using Claude."""

from __future__ import annotations

import json
import time

import anthropic
import structlog

from latent_demand.analysis.prompts.scoring import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from latent_demand.config import Settings

logger = structlog.get_logger()


def score_signal(signal: dict, settings: Settings) -> dict | None:
    """Score a single signal across 6 dimensions.

    Returns the scores dict to be merged into the signal, or None on failure.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Format evidence for the prompt
    evidence_text = ""
    for ev in signal.get("evidence", []):
        if isinstance(ev, dict):
            evidence_text += f"- \"{ev.get('quote', '')}\"\n"
            evidence_text += f"  Source: {ev.get('source_url', 'N/A')} by {ev.get('author', 'N/A')}\n"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=signal["title"],
        description=signal.get("description", ""),
        signal_type=signal.get("signal_type", ""),
        evidence=evidence_text or "No direct quotes available",
        friction_indicator=signal.get("friction_indicator", "Not specified"),
        potential_product=signal.get("potential_product", "Not specified"),
    )

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=settings.scoring_model,
                max_tokens=2048,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw_text = response.content[0].text.strip()

            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(lines[1:-1])

            result = json.loads(raw_text)

            scores = {}
            for dim in ("friction", "frequency", "market_size", "feasibility", "timing", "competition"):
                dim_data = result.get("scores", {}).get(dim, {})
                scores[dim] = dim_data.get("score", 0.0)

            scores["composite"] = result.get("composite_score", _compute_composite(scores))

            logger.info(
                "scoring.complete",
                signal=signal["title"][:60],
                composite=scores["composite"],
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            # Rate limit: stay under 30k tokens/min
            time.sleep(10)

            return {
                "scores": scores,
                "opportunity_summary": result.get("opportunity_summary", ""),
                "risks": result.get("risks", []),
                "suggested_mvp": result.get("suggested_mvp", ""),
            }

        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            logger.warning("scoring.rate_limited", wait_seconds=wait, attempt=attempt + 1)
            time.sleep(wait)
        except json.JSONDecodeError as e:
            logger.error("scoring.json_parse_error", signal=signal["id"], error=str(e))
            break
        except anthropic.APIError as e:
            logger.error("scoring.api_error", signal=signal["id"], error=str(e))
            break

    return None


def score_unscored_signals(settings: Settings) -> int:
    """Score all signals that don't have scores yet. Returns count scored."""
    from latent_demand.storage import read_json, update_signal

    signals = read_json(settings.signals_path)
    scored_count = 0

    for signal in signals:
        if signal.get("scores") is not None:
            continue

        result = score_signal(signal, settings)
        if result:
            update_signal(settings.signals_path, signal["id"], result)
            scored_count += 1

    return scored_count


def _compute_composite(scores: dict) -> float:
    weights = {
        "friction": 0.20,
        "frequency": 0.25,
        "market_size": 0.15,
        "feasibility": 0.15,
        "timing": 0.10,
        "competition": 0.15,
    }
    return round(sum(scores.get(k, 0) * w for k, w in weights.items()), 3)
