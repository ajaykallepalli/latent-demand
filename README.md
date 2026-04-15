# Latent Demand Discovery Agent

An AI-powered agent that scours social platforms (Reddit, Hacker News, Twitter, GitHub) for signals of technically-ahead users creatively hacking together solutions with AI and technology — indicating unmet product opportunities.

## What is Latent Demand?

When technically sophisticated early adopters go through significant friction to solve a problem using creative hacks, they're essentially writing the product spec for a mass-market product.

**Real examples:**
- People **copy-pasting code into ChatGPT** → Anthropic saw this → built **Claude Code**
- People **uploading food photos to GPT-4V** to estimate calories → companies built **Cal AI** (millions in revenue)
- People **emailing files to themselves** → **Dropbox**
- People **writing custom API glue scripts** → **Zapier**

The pattern: **creative workaround by early adopters → polished product for everyone**

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌────────────┐
│  Collectors  │────▶│  Extraction  │────▶│  Scoring &  │────▶│   Output   │
│  (per-plat)  │     │  (Claude)    │     │  Dedup      │     │  (Reports) │
└─────────────┘     └──────────────┘     └─────────────┘     └────────────┘
```

1. **Collect** — Platform-specific collectors fetch posts and comments from Reddit, Hacker News, etc.
2. **Extract** — Claude identifies latent demand signals: workarounds, tool-chaining, friction complaints, creative hacks
3. **Score** — Each signal is scored across 6 dimensions: friction, frequency, market size, feasibility, timing, competition
4. **Report** — Generates daily digests and opportunity briefs with evidence and scoring

## Signal Types

The agent detects these patterns:

| Signal Type | Example |
|-------------|---------|
| **Unexpected Use Case** | "I've been using ChatGPT to estimate calories from food photos" |
| **Workaround Hack** | "I built a janky script that pipes Whisper output into Claude for meeting notes" |
| **Tool Chaining** | "My workflow: screenshot → GPT-4V → spreadsheet → email. Takes 20 min but saves hours" |
| **Explicit Wish** | "I wish there was a tool that could just do X automatically" |
| **Friction Complaint** | "The worst part of my day is manually doing X because no tool exists" |
| **Custom Script** | "I wrote a Chrome extension that does X because nothing else does" |

## Scoring Dimensions

Each signal gets a composite score (0–1) based on:

| Dimension | Weight | Question |
|-----------|--------|----------|
| Frequency | 25% | How many independent people are doing this? |
| Friction | 20% | How painful is the current workaround? |
| Market Size | 15% | Niche dev tool or millions of users? |
| Feasibility | 15% | Could a small team build this in 3–6 months? |
| Competition | 15% | Has someone already built this well? |
| Timing | 10% | Is the enabling technology mature enough? |

## Tech Stack

- **Python 3.12+** with `uv` for package management
- **Anthropic SDK** — Claude Sonnet for bulk extraction, Claude Opus for deep scoring
- **PRAW** — Reddit API
- **Algolia HN API** — Hacker News (free, no auth)
- **JSON files** — All state stored as JSON on disk (no database needed for MVP)
- **Typer** — CLI interface

## Quick Start

```bash
# Clone
git clone https://github.com/ajaykallepalli/latent-demand.git
cd latent-demand

# Install
uv sync

# Configure
cp .env.example .env
# Add your ANTHROPIC_API_KEY and REDDIT credentials to .env

# Scan Hacker News for signals
uv run latent-demand scan --source hackernews

# Scan Reddit
uv run latent-demand scan --source reddit

# Score extracted signals
uv run latent-demand analyze

# Generate a report
uv run latent-demand report
```

## Project Structure

```
latent-demand/
├── seeds/initial_sources.json     # Curated starting sources
├── data/                          # Runtime state (gitignored)
│   ├── sources.json
│   ├── signals.json
│   ├── seen.json
│   ├── raw/
│   └── reports/
└── src/latent_demand/
    ├── config.py                  # Settings
    ├── storage.py                 # JSON file helpers
    ├── cli.py                     # CLI entry point
    ├── collectors/                # Platform-specific scrapers
    │   ├── base.py
    │   ├── hackernews.py
    │   └── reddit.py
    ├── analysis/                  # AI-powered analysis
    │   ├── extractor.py           # Signal extraction (the core)
    │   ├── scorer.py              # Multi-dimension scoring
    │   ├── deduplicator.py
    │   └── prompts/
    ├── output/                    # Report generation
    └── pipeline/                  # Orchestration
```

## Sources

The agent monitors a curated, evolving list of sources:

**Reddit:** r/ChatGPT, r/ClaudeAI, r/LocalLLaMA, r/MachineLearning, r/SideProject, r/selfhosted, r/productivity, and more

**Hacker News:** Show HN, Ask HN, keyword searches for "I built", "workaround", "hack", "workflow"

Sources are dynamically prioritized based on signal yield — high-quality sources get scanned more frequently, low-yield sources get deprioritized.

## License

MIT
