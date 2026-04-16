from __future__ import annotations

import json
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Anthropic
    anthropic_api_key: str = ""

    # Models
    extraction_model: str = "claude-haiku-4-5-20251001"
    scoring_model: str = "claude-haiku-4-5-20251001"
    report_model: str = "claude-sonnet-4-6"

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "latent-demand-agent/0.1"

    # Paths
    data_dir: Path = Path("./data")
    seeds_dir: Path = Path("./seeds")

    # Pipeline
    extraction_batch_size: int = 15
    max_signals_for_dedup: int = 200

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def sources_path(self) -> Path:
        return self.data_dir / "sources.json"

    @property
    def signals_path(self) -> Path:
        return self.data_dir / "signals.json"

    @property
    def seen_path(self) -> Path:
        return self.data_dir / "seen.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(exist_ok=True)
        self.reports_dir.mkdir(exist_ok=True)

    def init_data_files(self) -> None:
        """Initialize data files from seeds if they don't exist."""
        self.ensure_dirs()

        if not self.sources_path.exists():
            seeds_file = self.seeds_dir / "initial_sources.json"
            if seeds_file.exists():
                sources = json.loads(seeds_file.read_text())
            else:
                sources = []
            self.sources_path.write_text(json.dumps(sources, indent=2))

        if not self.signals_path.exists():
            self.signals_path.write_text("[]")

        if not self.seen_path.exists():
            self.seen_path.write_text("{}")


def get_settings() -> Settings:
    return Settings()
