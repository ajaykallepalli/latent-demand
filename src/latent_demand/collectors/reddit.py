"""Reddit collector using the public JSON API (no credentials needed)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import structlog

from latent_demand.collectors.base import BaseCollector

logger = structlog.get_logger()

REDDIT_BASE = "https://www.reddit.com"


class RedditCollector(BaseCollector):
    platform = "reddit"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=30,
            headers={"User-Agent": "latent-demand-agent/0.1"},
            follow_redirects=True,
        )
        self._last_request = 0.0

    def _rate_limit(self) -> None:
        """Reddit public JSON API wants ~1 req/sec."""
        elapsed = time.time() - self._last_request
        if elapsed < 1.5:
            time.sleep(1.5 - elapsed)
        self._last_request = time.time()

    def _get_json(self, url: str, params: dict | None = None) -> dict:
        self._rate_limit()
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def collect(self, source: dict) -> list[dict]:
        config = source.get("config", {})
        subreddit = config.get("subreddit", "")
        sort = config.get("sort", "hot")
        limit = config.get("limit", 50)

        if not subreddit:
            logger.warning("reddit.no_subreddit", source=source["id"])
            return []

        # Fetch posts
        url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json"
        data = self._get_json(url, params={"limit": limit, "raw_json": 1})

        posts = data.get("data", {}).get("children", [])
        results = []

        for post_wrapper in posts:
            post = post_wrapper.get("data", {})
            parsed = self._parse_post(post, source["identifier"])
            if parsed:
                results.append(parsed)

            # Fetch comments for posts with decent engagement
            num_comments = post.get("num_comments", 0)
            if num_comments >= 5:
                comments = self._fetch_comments(
                    subreddit, post.get("id", ""), source["identifier"]
                )
                results.extend(comments)

        logger.info(
            "reddit.collected",
            source=source["identifier"],
            posts=len([r for r in results if r.get("content_type") == "post"]),
            comments=len([r for r in results if r.get("content_type") == "comment"]),
        )
        return results

    def _fetch_comments(
        self, subreddit: str, post_id: str, source_name: str, limit: int = 10
    ) -> list[dict]:
        """Fetch top comments for a post via the public JSON API."""
        url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
        try:
            data = self._get_json(url, params={"limit": limit, "sort": "best", "raw_json": 1})
        except httpx.HTTPError:
            logger.warning("reddit.comments_failed", post_id=post_id)
            return []

        # Reddit returns [post_listing, comments_listing]
        if not isinstance(data, list) or len(data) < 2:
            return []

        comment_children = data[1].get("data", {}).get("children", [])
        results = []
        for wrapper in comment_children[:limit]:
            if wrapper.get("kind") != "t1":
                continue
            comment = wrapper.get("data", {})
            parsed = self._parse_comment(comment, source_name, post_id)
            if parsed:
                results.append(parsed)
        return results

    def _parse_post(self, post: dict, source_name: str) -> dict | None:
        title = post.get("title", "")
        body = post.get("selftext", "")

        if not body and not title:
            return None

        post_id = post.get("id", "")
        permalink = post.get("permalink", "")

        return {
            "id": self.content_id(post_id),
            "platform": self.platform,
            "source": source_name,
            "content_type": "post",
            "author": post.get("author", "[deleted]"),
            "title": title,
            "body": body,
            "url": f"https://reddit.com{permalink}",
            "engagement": {
                "upvotes": post.get("score", 0),
                "comments": post.get("num_comments", 0),
                "upvote_ratio": post.get("upvote_ratio", 0),
            },
            "published_at": datetime.fromtimestamp(
                post.get("created_utc", 0), tz=timezone.utc
            ).isoformat(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    def _parse_comment(
        self, comment: dict, source_name: str, post_id: str
    ) -> dict | None:
        body = comment.get("body", "")
        if not body or len(body) < 50:
            return None

        author = comment.get("author", "[deleted]")
        if author in ("[deleted]", "AutoModerator"):
            return None

        comment_id = comment.get("id", "")
        permalink = comment.get("permalink", "")

        return {
            "id": self.content_id(f"c_{comment_id}"),
            "platform": self.platform,
            "source": source_name,
            "content_type": "comment",
            "author": author,
            "title": f"Comment on post {post_id}",
            "body": body,
            "url": f"https://reddit.com{permalink}",
            "engagement": {
                "upvotes": comment.get("score", 0),
                "comments": 0,
            },
            "published_at": datetime.fromtimestamp(
                comment.get("created_utc", 0), tz=timezone.utc
            ).isoformat(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
