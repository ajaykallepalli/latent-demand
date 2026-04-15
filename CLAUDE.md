# Latent Demand Discovery Agent

## Quick Reference

```bash
uv run latent-demand init                    # Initialize data directory
uv run latent-demand scan --source hackernews # Scan HN only
uv run latent-demand scan --source reddit     # Scan Reddit only
uv run latent-demand scan                     # Scan all platforms
uv run latent-demand analyze                  # Score unscored signals
uv run latent-demand report --days 7          # Weekly digest
uv run latent-demand brief sig_001            # Deep-dive on a signal
uv run latent-demand run                      # Full pipeline
uv run latent-demand signals                  # List signals
uv run latent-demand sources                  # List sources
```

## Architecture

Four-stage pipeline: Collect → Extract (Sonnet) → Score (Opus) → Report

All state is JSON files in `data/` (gitignored). No database.

## Key Files

- `src/latent_demand/analysis/prompts/extraction.py` — The extraction prompt is the core IP
- `src/latent_demand/analysis/extractor.py` — Orchestrates Claude calls for signal extraction
- `src/latent_demand/pipeline/orchestrator.py` — End-to-end pipeline coordinator
- `src/latent_demand/collectors/` — Platform-specific scrapers (HN, Reddit)
- `seeds/initial_sources.json` — Curated source list (committed to git)

## Environment Variables

Required in `.env`:
- `ANTHROPIC_API_KEY` — for signal extraction and scoring
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` — for Reddit collector

## Adding a New Source

Add an entry to `seeds/initial_sources.json` and re-run `latent-demand init`.

## Adding a New Collector

1. Create `src/latent_demand/collectors/{platform}.py`
2. Extend `BaseCollector` from `collectors/base.py`
3. Register it in `pipeline/orchestrator.py` `_get_collector()`
