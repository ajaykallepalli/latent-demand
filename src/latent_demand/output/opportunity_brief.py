"""Generate deep-dive opportunity briefs for top signals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import structlog

from latent_demand.config import Settings
from latent_demand.storage import read_json

logger = structlog.get_logger()

BRIEF_SYSTEM = """\
You are a product strategist writing an opportunity brief for a latent demand \
signal. This brief should be actionable — someone should be able to read it \
and decide whether to build a product around this opportunity.

Write in markdown format with the following sections:
1. **Executive Summary** — 2-3 sentences on the opportunity
2. **The Problem** — What friction are users experiencing? Why does this matter?
3. **Evidence** — What are users actually doing today? Include quotes and sources.
4. **Market Opportunity** — Who would use this? How big is the market?
5. **Competitive Landscape** — What exists today? What are the gaps?
6. **Product Vision** — What would a great product look like?
7. **MVP Specification** — What's the smallest thing you could build to validate?
8. **Risks & Open Questions** — What could go wrong? What needs to be validated?
9. **Verdict** — Build it, watch it, or skip it? And why.

Be specific and grounded in the evidence. Avoid hype.\
"""

BRIEF_USER_TEMPLATE = """\
Write an opportunity brief for this latent demand signal:

**Signal:** {title}
**Description:** {description}
**Signal Type:** {signal_type}

**Evidence:**
{evidence}

**Friction:** {friction}
**Potential Product:** {potential_product}

**Scores:**
{scores}

{extra_context}\
"""


def generate_brief(signal: dict, settings: Settings) -> str:
    """Generate an opportunity brief for a single signal."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    evidence_text = ""
    for ev in signal.get("evidence", []):
        if isinstance(ev, dict):
            evidence_text += f"- \"{ev.get('quote', '')}\"\n"
            evidence_text += f"  By {ev.get('author', 'unknown')} on {ev.get('platform', 'unknown')}\n"
            evidence_text += f"  {ev.get('source_url', '')}\n\n"

    scores = signal.get("scores", {})
    scores_text = ""
    if scores:
        for dim, val in scores.items():
            if dim != "composite":
                scores_text += f"- {dim}: {val}\n"
        scores_text += f"- **Composite: {scores.get('composite', 'N/A')}**\n"

    extra = ""
    if signal.get("opportunity_summary"):
        extra += f"**Prior Analysis:** {signal['opportunity_summary']}\n"
    if signal.get("risks"):
        extra += f"**Known Risks:** {', '.join(signal['risks'])}\n"
    if signal.get("suggested_mvp"):
        extra += f"**Prior MVP Suggestion:** {signal['suggested_mvp']}\n"

    user_prompt = BRIEF_USER_TEMPLATE.format(
        title=signal["title"],
        description=signal.get("description", ""),
        signal_type=signal.get("signal_type", ""),
        evidence=evidence_text or "No direct evidence available",
        friction=signal.get("friction_indicator", "Not specified"),
        potential_product=signal.get("potential_product", "Not specified"),
        scores=scores_text or "Not yet scored",
        extra_context=extra,
    )

    response = client.messages.create(
        model=settings.scoring_model,
        max_tokens=4096,
        system=[{"type": "text", "text": BRIEF_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    brief = response.content[0].text

    logger.info(
        "brief.generated",
        signal=signal["title"][:50],
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return brief


def generate_and_save_brief(signal: dict, settings: Settings) -> Path:
    """Generate and save an opportunity brief."""
    brief_md = generate_brief(signal, settings)

    slug = signal["title"][:50].lower()
    slug = "".join(c if c.isalnum() or c == " " else "" for c in slug)
    slug = slug.strip().replace(" ", "-")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    path = settings.reports_dir / f"brief_{today}_{slug}.md"

    header = (
        f"# Opportunity Brief: {signal['title']}\n\n"
        f"_Generated {today} | Signal ID: {signal['id']}_\n\n"
        f"---\n\n"
    )
    path.write_text(header + brief_md)
    logger.info("brief.saved", path=str(path))
    return path
