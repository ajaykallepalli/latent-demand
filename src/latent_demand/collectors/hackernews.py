"""Hacker News collector using the Algolia Search API."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import structlog

from latent_demand.collectors.base import BaseCollector

logger = structlog.get_logger()

ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
HN_ITEM_URL = "https://news.ycombinator.com/item?id="


class HackerNewsCollector(BaseCollector):
    platform = "hackernews"

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30)

    def collect(self, source: dict) -> list[dict]:
        config = source.get("config", {})
        tags = config.get("tags")
        query = config.get("query", "")
        search_type = config.get("search_type", "search_by_date")

        items = self._search(query=query, tags=tags, search_type=search_type)

        results = []
        for hit in items:
            story = self._parse_hit(hit, source["identifier"])
            if story:
                results.append(story)

            # For stories with significant comments, fetch top comments
            if hit.get("num_comments", 0) >= 5:
                comments = self._fetch_comments(hit["objectID"], source["identifier"])
                results.extend(comments)

        logger.info(
            "hackernews.collected",
            source=source["identifier"],
            stories=len([r for r in results if r.get("content_type") == "story"]),
            comments=len([r for r in results if r.get("content_type") == "comment"]),
        )
        return results

    def _search(
        self,
        query: str = "",
        tags: str | None = None,
        search_type: str = "search_by_date",
        hits_per_page: int = 30,
    ) -> list[dict]:
        params: dict = {
            "hitsPerPage": hits_per_page,
            # Look back 24 hours
            "numericFilters": f"created_at_i>{int(time.time()) - 86400}",
        }
        if query:
            params["query"] = query
        if tags:
            params["tags"] = tags

        url = f"{ALGOLIA_BASE}/{search_type}"
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("hits", [])

    def _fetch_comments(
        self, story_id: str, source_name: str, limit: int = 10
    ) -> list[dict]:
        """Fetch top comments for a story."""
        params = {
            "tags": f"comment,story_{story_id}",
            "hitsPerPage": limit,
        }
        try:
            resp = self._client.get(f"{ALGOLIA_BASE}/search", params=params)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except httpx.HTTPError:
            logger.warning("hackernews.comments_failed", story_id=story_id)
            return []

        results = []
        for hit in hits:
            comment = self._parse_comment(hit, source_name, story_id)
            if comment:
                results.append(comment)
        return results

    def _parse_hit(self, hit: dict, source_name: str) -> dict | None:
        object_id = hit.get("objectID")
        if not object_id:
            return None

        title = hit.get("title", "")
        # story_text is the body for Show HN / Ask HN posts
        body = hit.get("story_text") or hit.get("comment_text") or ""

        return {
            "id": self.content_id(object_id),
            "platform": self.platform,
            "source": source_name,
            "content_type": "story",
            "author": hit.get("author", ""),
            "title": title,
            "body": body,
            "url": hit.get("url") or f"{HN_ITEM_URL}{object_id}",
            "engagement": {
                "points": hit.get("points", 0),
                "comments": hit.get("num_comments", 0),
            },
            "published_at": hit.get("created_at", ""),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    def _parse_comment(
        self, hit: dict, source_name: str, story_id: str
    ) -> dict | None:
        object_id = hit.get("objectID")
        if not object_id:
            return None

        body = hit.get("comment_text", "")
        if not body or len(body) < 50:
            return None

        return {
            "id": self.content_id(f"c_{object_id}"),
            "platform": self.platform,
            "source": source_name,
            "content_type": "comment",
            "author": hit.get("author", ""),
            "title": f"Comment on story {story_id}",
            "body": body,
            "url": f"{HN_ITEM_URL}{object_id}",
            "engagement": {
                "points": hit.get("points", 0),
                "comments": 0,
            },
            "published_at": hit.get("created_at", ""),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
