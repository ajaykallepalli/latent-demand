"""CLI entry point for the latent demand discovery agent."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
import typer

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)

app = typer.Typer(
    name="latent-demand",
    help="Discover latent demand by finding creative hacks on social platforms.",
)


def _get_settings():
    from latent_demand.config import get_settings

    return get_settings()


@app.command()
def scan(
    source: Optional[str] = typer.Option(
        None, "--source", "-s", help="Platform to scan (hackernews, reddit). Scans all if omitted."
    ),
):
    """Collect content from sources and extract latent demand signals."""
    settings = _get_settings()
    from latent_demand.pipeline.orchestrator import run_collect, run_extract

    typer.echo(f"Scanning {source or 'all platforms'}...")

    items = run_collect(settings, platform=source)
    typer.echo(f"Collected {len(items)} new items.")

    if items:
        signals = run_extract(settings, items)
        typer.echo(f"Extracted {len(signals)} new signals.")
    else:
        typer.echo("No new content to analyze.")


@app.command()
def extract(
    platform: Optional[str] = typer.Option(
        None, "--platform", "-p", help="Filter raw files by platform."
    ),
    date: Optional[str] = typer.Option(
        None, "--date", "-d", help="Date to process (YYYY-MM-DD). Defaults to today."
    ),
):
    """Extract signals from already-collected raw data."""
    settings = _get_settings()
    settings.init_data_files()
    from datetime import datetime as dt
    from datetime import timezone

    from latent_demand.pipeline.orchestrator import run_extract
    from latent_demand.storage import read_json

    if not date:
        date = dt.now(timezone.utc).strftime("%Y-%m-%d")

    # Find matching raw files
    import glob as g
    pattern = str(settings.raw_dir / f"{'*' if not platform else platform}_{date}.json")
    files = g.glob(pattern)

    if not files:
        typer.echo(f"No raw files found for pattern: {pattern}")
        raise typer.Exit(1)

    all_items = []
    for f in files:
        items = read_json(Path(f))
        all_items.extend(items)

    typer.echo(f"Found {len(all_items)} items in {len(files)} raw file(s).")
    signals = run_extract(settings, all_items)
    typer.echo(f"Extracted {len(signals)} new signals.")


@app.command()
def analyze():
    """Score all unscored signals."""
    settings = _get_settings()
    from latent_demand.analysis.scorer import score_unscored_signals

    typer.echo("Scoring unscored signals...")
    count = score_unscored_signals(settings)
    typer.echo(f"Scored {count} signals.")


@app.command()
def report(
    days: int = typer.Option(1, "--days", "-d", help="Number of days to include (1=daily, 7=weekly)."),
    print_report: bool = typer.Option(True, "--print/--no-print", help="Print to stdout."),
):
    """Generate a digest report of recent signals."""
    settings = _get_settings()
    settings.init_data_files()
    from latent_demand.output.digest import generate_digest, save_digest

    path = save_digest(settings, days=days)
    typer.echo(f"Report saved to {path}")

    if print_report:
        typer.echo("")
        typer.echo(generate_digest(settings, days=days))


@app.command()
def brief(
    signal_id: str = typer.Argument(help="Signal ID to generate a brief for (e.g., sig_001)."),
):
    """Generate a deep-dive opportunity brief for a specific signal."""
    settings = _get_settings()
    from latent_demand.output.opportunity_brief import generate_and_save_brief
    from latent_demand.storage import read_json

    signals = read_json(settings.signals_path)
    target = None
    for s in signals:
        if s["id"] == signal_id:
            target = s
            break

    if not target:
        typer.echo(f"Signal {signal_id} not found.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Generating opportunity brief for: {target['title']}")
    path = generate_and_save_brief(target, settings)
    typer.echo(f"Brief saved to {path}")

    brief_text = path.read_text()
    typer.echo("")
    typer.echo(brief_text)


@app.command()
def run(
    platform: Optional[str] = typer.Option(
        None, "--platform", "-p", help="Limit to a specific platform."
    ),
    skip_scoring: bool = typer.Option(False, "--skip-scoring", help="Skip the scoring step."),
    no_report: bool = typer.Option(False, "--no-report", help="Skip report generation."),
):
    """Run the full pipeline: collect → extract → score → report."""
    settings = _get_settings()
    from latent_demand.pipeline.orchestrator import run_full_pipeline

    typer.echo("Running full pipeline...")
    summary = run_full_pipeline(
        settings,
        platform=platform,
        skip_scoring=skip_scoring,
        generate_report=not no_report,
    )

    typer.echo("")
    typer.echo("Pipeline complete:")
    typer.echo(f"  Items collected:    {summary['items_collected']}")
    typer.echo(f"  Signals extracted:  {summary['signals_extracted']}")
    typer.echo(f"  Signals scored:     {summary['signals_scored']}")
    if summary.get("report"):
        typer.echo(f"  Report:             {summary['report']}")


@app.command()
def signals(
    top: int = typer.Option(10, "--top", "-n", help="Number of signals to show."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
):
    """List stored signals, sorted by composite score."""
    settings = _get_settings()
    settings.init_data_files()
    from latent_demand.storage import read_json

    all_signals = read_json(settings.signals_path)

    if status:
        all_signals = [s for s in all_signals if s.get("status") == status]

    # Sort: scored signals first by composite, then unscored
    scored = [s for s in all_signals if s.get("scores")]
    unscored = [s for s in all_signals if not s.get("scores")]
    scored.sort(key=lambda s: s["scores"].get("composite", 0), reverse=True)
    sorted_signals = scored + unscored

    if not sorted_signals:
        typer.echo("No signals found.")
        return

    typer.echo(f"{'ID':<10} {'Score':<8} {'Type':<22} Title")
    typer.echo("-" * 80)

    for s in sorted_signals[:top]:
        sid = s["id"]
        scores = s.get("scores") or {}
        composite = scores.get("composite")
        score_str = f"{composite:.2f}" if composite is not None else "  -  "
        stype = s.get("signal_type", "unknown")[:20]
        title = s["title"][:45]
        typer.echo(f"{sid:<10} {score_str:<8} {stype:<22} {title}")


@app.command()
def sources():
    """List all configured sources and their yield scores."""
    settings = _get_settings()
    settings.init_data_files()
    from latent_demand.storage import read_json

    all_sources = read_json(settings.sources_path)
    all_sources.sort(key=lambda s: s.get("yield_score", 0), reverse=True)

    typer.echo(f"{'ID':<25} {'Platform':<12} {'Priority':<10} {'Yield':<8} Last Scanned")
    typer.echo("-" * 80)

    for src in all_sources:
        sid = src["id"][:23]
        platform = src["platform"][:10]
        priority = str(src.get("priority", "-"))
        ys = src.get("yield_score", 0)
        yield_str = f"{ys:.3f}" if ys else "  -  "
        last = src.get("last_scanned_at", "never")
        if last and last != "never":
            last = last[:19]
        typer.echo(f"{sid:<25} {platform:<12} {priority:<10} {yield_str:<8} {last}")


@app.command()
def init():
    """Initialize data directory and seed sources."""
    settings = _get_settings()
    settings.init_data_files()
    typer.echo(f"Initialized data directory at {settings.data_dir}")
    typer.echo("Sources loaded from seeds/initial_sources.json")


if __name__ == "__main__":
    app()
