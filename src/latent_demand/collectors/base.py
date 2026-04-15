"""Base collector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    """Abstract base for platform-specific content collectors."""

    platform: str

    @abstractmethod
    def collect(self, source: dict) -> list[dict]:
        """Fetch new content from this source.

        Args:
            source: Source config dict from sources.json.

        Returns:
            List of raw content dicts with keys:
                id, platform, source, author, title, body, url,
                engagement, published_at, collected_at
        """
        ...

    def content_id(self, external_id: str) -> str:
        """Create a globally unique content ID."""
        return f"{self.platform}:{external_id}"
