"""Daily/weekly digest generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import structlog

from latent_demand.config import Settings
from latent_demand.storage import read_json

logger = structlog.get_logger()


def generate_digest(settings: Settings, days: int = 1) -> str:
    """Generate a markdown digest of recent signals.

    Args:
        settings: App settings.
        days: How many days back to include (1 = daily, 7 = weekly).

    Returns:
        Markdown string of the digest.
    """
    signals = read_json(settings.signals_path)
    sources = read_json(settings.sources_path)

    # Filter to recent signals
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    recent = []
    for s in signals:
        try:
            created = datetime.fromisoformat(s["created_at"]).timestamp()
            if created >= cutoff:
                recent.append(s)
        except (KeyError, ValueError):
            continue

    # Sort by composite score (scored first, then unscored)
    scored = [s for s in recent if s.get("scores")]
    unscored = [s for s in recent if not s.get("scores")]
    scored.sort(key=lambda s: s["scores"].get("composite", 0), reverse=True)
    all_sorted = scored + unscored

    period = "Daily" if days <= 1 else f"{days}-Day"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"# Latent Demand {period} Digest — {today}",
        "",
        f"**{len(all_sorted)} signals** found in the last {days} day(s).",
        "",
    ]

    if not all_sorted:
        lines.append("No new signals found in this period.")
        return "\n".join(lines)

    # Top signals
    lines.append("## Top Signals")
    lines.append("")

    for i, signal in enumerate(all_sorted[:10], 1):
        scores = signal.get("scores") or {}
        composite = scores.get("composite", "unscored")
        if isinstance(composite, float):
            score_str = f"**{composite:.2f}**/1.00"
        else:
            score_str = "_unscored_"

        lines.append(f"### {i}. {signal['title']}")
        lines.append(f"**Score:** {score_str} | **Type:** {signal.get('signal_type', 'unknown')}")
        if signal.get("user_context"):
            lines.append(f" | **Who:** {signal['user_context']}")
        lines.append("")

        if signal.get("description"):
            lines.append(signal["description"])
            lines.append("")

        if signal.get("friction_indicator"):
            lines.append(f"**Friction:** {signal['friction_indicator']}")
            lines.append("")

        if signal.get("potential_product"):
            lines.append(f"**Product idea:** {signal['potential_product']}")
            lines.append("")

        if signal.get("market_size_hint"):
            lines.append(f"**Market size:** {signal['market_size_hint']}")
            lines.append("")

        # Show score breakdown if available
        if scores and isinstance(scores.get("composite"), float):
            dims = []
            for dim in ("friction", "frequency", "market_size", "feasibility", "timing", "competition"):
                val = scores.get(dim)
                if val is not None:
                    dims.append(f"{dim}: {val:.1f}")
            if dims:
                lines.append(f"**Breakdown:** {' | '.join(dims)}")
                lines.append("")

        # Show evidence
        evidence = signal.get("evidence", [])
        if evidence:
            lines.append("**Evidence:**")
            for ev in evidence[:3]:
                if isinstance(ev, dict):
                    quote = ev.get("quote", "")
                    source_url = ev.get("source_url", "")
                    author = ev.get("author", "")
                    if quote:
                        lines.append(f"> \"{quote[:300]}\"")
                        if author or source_url:
                            lines.append(f"> — {author} ([source]({source_url}))")
                        lines.append("")

        # Show opportunity summary and MVP if scored
        if signal.get("opportunity_summary"):
            lines.append(f"**Opportunity:** {signal['opportunity_summary']}")
            lines.append("")
        if signal.get("suggested_mvp"):
            lines.append(f"**Suggested MVP:** {signal['suggested_mvp']}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Source summary
    lines.append("## Source Summary")
    lines.append("")
    lines.append("| Source | Yield Score |")
    lines.append("|--------|------------|")
    for source in sorted(sources, key=lambda s: s.get("yield_score", 0), reverse=True):
        ys = source.get("yield_score", 0)
        lines.append(f"| {source['identifier']} | {ys:.2f} |")
    lines.append("")

    return "\n".join(lines)


def save_digest(settings: Settings, days: int = 1) -> Path:
    """Generate and save a digest to the reports directory. Never overwrites."""
    digest_md = generate_digest(settings, days)
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    period = "daily" if days <= 1 else "weekly"
    path = settings.reports_dir / f"digest_{period}_{timestamp}.md"
    path.write_text(digest_md)
    logger.info("digest.saved", path=str(path))
    return path
