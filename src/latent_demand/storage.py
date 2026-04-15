"""JSON file storage helpers with atomic writes."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Read and parse a JSON file. Returns empty list/dict if file doesn't exist."""
    if not path.exists():
        return [] if path.name != "seen.json" else {}
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    """Atomically write data to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2, default=str)
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def append_raw_content(raw_dir: Path, platform: str, items: list[dict]) -> None:
    """Append collected items to the daily raw content file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = raw_dir / f"{platform}_{today}.json"

    existing = read_json(path) if path.exists() else []
    existing.extend(items)
    write_json(path, existing)


def mark_seen(seen_path: Path, content_ids: list[str]) -> None:
    """Mark content IDs as seen."""
    seen = read_json(seen_path)
    now = datetime.now(timezone.utc).isoformat()
    for cid in content_ids:
        seen[cid] = now
    write_json(seen_path, seen)


def is_seen(seen_path: Path, content_id: str) -> bool:
    """Check if a content ID has already been processed."""
    seen = read_json(seen_path)
    return content_id in seen


def get_seen_set(seen_path: Path) -> set[str]:
    """Get all seen content IDs as a set for batch checking."""
    seen = read_json(seen_path)
    return set(seen.keys())


def add_signals(signals_path: Path, new_signals: list[dict]) -> None:
    """Append new signals to the signals file."""
    existing = read_json(signals_path)
    existing.extend(new_signals)
    write_json(signals_path, existing)


def update_signal(signals_path: Path, signal_id: str, updates: dict) -> None:
    """Update a signal by ID."""
    signals = read_json(signals_path)
    for signal in signals:
        if signal["id"] == signal_id:
            signal.update(updates)
            break
    write_json(signals_path, signals)


def get_sources(sources_path: Path) -> list[dict]:
    """Get all enabled sources."""
    sources = read_json(sources_path)
    return [s for s in sources if s.get("enabled", True)]


def update_source(sources_path: Path, source_id: str, updates: dict) -> None:
    """Update a source by ID."""
    sources = read_json(sources_path)
    for source in sources:
        if source["id"] == source_id:
            source.update(updates)
            break
    write_json(sources_path, sources)


def next_signal_id(signals_path: Path) -> str:
    """Generate the next signal ID."""
    signals = read_json(signals_path)
    if not signals:
        return "sig_001"
    last_num = max(int(s["id"].split("_")[1]) for s in signals)
    return f"sig_{last_num + 1:03d}"
