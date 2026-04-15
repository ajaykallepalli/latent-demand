"""End-to-end pipeline orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from latent_demand.analysis.deduplicator import deduplicate_signals
from latent_demand.analysis.extractor import extract_signals
from latent_demand.analysis.scorer import score_unscored_signals
from latent_demand.collectors.hackernews import HackerNewsCollector
from latent_demand.config import Settings
from latent_demand.output.digest import save_digest
from latent_demand.storage import (
    add_signals,
    append_raw_content,
    get_seen_set,
    get_sources,
    mark_seen,
    update_source,
)

logger = structlog.get_logger()


def _should_scan(source: dict) -> bool:
    """Check if a source is due for scanning based on its interval."""
    last = source.get("last_scanned_at")
    if not last:
        return True
    interval_hours = source.get("scan_interval_hours", 6)
    try:
        last_dt = datetime.fromisoformat(last)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        return elapsed >= interval_hours
    except ValueError:
        return True


def _get_collector(source: dict, settings: Settings):
    """Get the appropriate collector for a source."""
    platform = source["platform"]

    if platform == "hackernews":
        return HackerNewsCollector()
    elif platform == "reddit":
        from latent_demand.collectors.reddit import RedditCollector

        return RedditCollector()
    else:
        logger.warning("collector.unknown_platform", platform=platform)
        return None


def run_collect(settings: Settings, platform: str | None = None) -> list[dict]:
    """Run the collection stage. Returns all newly collected items."""
    settings.init_data_files()
    sources = get_sources(settings.sources_path)
    seen = get_seen_set(settings.seen_path)
    all_new_items = []

    for source in sources:
        if platform and source["platform"] != platform:
            continue

        if not _should_scan(source):
            logger.info("collect.skip", source=source["identifier"], reason="not due")
            continue

        collector = _get_collector(source, settings)
        if not collector:
            continue

        logger.info("collect.start", source=source["identifier"])

        try:
            items = collector.collect(source)
        except Exception as e:
            logger.error("collect.error", source=source["identifier"], error=str(e))
            continue

        # Filter out already-seen content
        new_items = [item for item in items if item["id"] not in seen]

        if new_items:
            append_raw_content(settings.raw_dir, source["platform"], new_items)
            mark_seen(settings.seen_path, [item["id"] for item in new_items])
            all_new_items.extend(new_items)

        # Update source metadata
        yield_score = len(new_items) / max(len(items), 1) if items else 0
        old_yield = source.get("yield_score", 0)
        new_yield = 0.7 * old_yield + 0.3 * yield_score

        update_source(settings.sources_path, source["id"], {
            "last_scanned_at": datetime.now(timezone.utc).isoformat(),
            "yield_score": round(new_yield, 4),
        })

        logger.info(
            "collect.done",
            source=source["identifier"],
            total=len(items),
            new=len(new_items),
            yield_score=round(new_yield, 4),
        )

    return all_new_items


def run_extract(settings: Settings, items: list[dict]) -> list[dict]:
    """Run the extraction stage. Returns new signals."""
    if not items:
        logger.info("extract.skip", reason="no items to analyze")
        return []

    logger.info("extract.start", items=len(items))
    raw_signals = extract_signals(items, settings)

    if not raw_signals:
        logger.info("extract.no_signals")
        return []

    # Deduplicate against existing signals
    novel_signals = deduplicate_signals(raw_signals, settings)

    if novel_signals:
        add_signals(settings.signals_path, novel_signals)

    logger.info(
        "extract.done",
        raw_signals=len(raw_signals),
        novel=len(novel_signals),
        duplicates=len(raw_signals) - len(novel_signals),
    )
    return novel_signals


def run_score(settings: Settings) -> int:
    """Score all unscored signals. Returns count scored."""
    logger.info("score.start")
    count = score_unscored_signals(settings)
    logger.info("score.done", scored=count)
    return count


def run_full_pipeline(
    settings: Settings,
    platform: str | None = None,
    skip_scoring: bool = False,
    generate_report: bool = True,
) -> dict:
    """Run the full pipeline: collect → extract → score → report.

    Returns a summary dict.
    """
    logger.info("pipeline.start", platform=platform or "all")

    # 1. Collect
    new_items = run_collect(settings, platform=platform)

    # 2. Extract signals
    new_signals = run_extract(settings, new_items)

    # 3. Score
    scored = 0
    if not skip_scoring and new_signals:
        scored = run_score(settings)

    # 4. Report
    report_path = None
    if generate_report:
        report_path = save_digest(settings)

    summary = {
        "items_collected": len(new_items),
        "signals_extracted": len(new_signals),
        "signals_scored": scored,
        "report": str(report_path) if report_path else None,
    }

    logger.info("pipeline.done", **summary)
    return summary
