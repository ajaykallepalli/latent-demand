"""Reddit collector using PRAW."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from latent_demand.collectors.base import BaseCollector

logger = structlog.get_logger()


class RedditCollector(BaseCollector):
    platform = "reddit"

    def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
        import praw

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )

    def collect(self, source: dict) -> list[dict]:
        config = source.get("config", {})
        subreddit_name = config.get("subreddit", "")
        sort = config.get("sort", "hot")
        limit = config.get("limit", 50)

        if not subreddit_name:
            logger.warning("reddit.no_subreddit", source=source["id"])
            return []

        subreddit = self._reddit.subreddit(subreddit_name)

        if sort == "hot":
            posts = subreddit.hot(limit=limit)
        elif sort == "new":
            posts = subreddit.new(limit=limit)
        elif sort == "top":
            posts = subreddit.top(limit=limit, time_filter="day")
        else:
            posts = subreddit.hot(limit=limit)

        results = []
        for post in posts:
            parsed = self._parse_post(post, source["identifier"])
            if parsed:
                results.append(parsed)

            # Fetch top-level comments for posts with decent engagement
            if post.num_comments >= 5:
                post.comment_sort = "best"
                post.comments.replace_more(limit=0)
                for comment in post.comments[:10]:
                    parsed_comment = self._parse_comment(
                        comment, source["identifier"], post.id
                    )
                    if parsed_comment:
                        results.append(parsed_comment)

        logger.info(
            "reddit.collected",
            source=source["identifier"],
            posts=len([r for r in results if r.get("content_type") == "post"]),
            comments=len([r for r in results if r.get("content_type") == "comment"]),
        )
        return results

    def _parse_post(self, post: object, source_name: str) -> dict | None:
        title = getattr(post, "title", "")
        body = getattr(post, "selftext", "")

        # Skip link-only posts with no discussion body
        if not body and not title:
            return None

        return {
            "id": self.content_id(post.id),
            "platform": self.platform,
            "source": source_name,
            "content_type": "post",
            "author": str(getattr(post, "author", "[deleted]")),
            "title": title,
            "body": body,
            "url": f"https://reddit.com{post.permalink}",
            "engagement": {
                "upvotes": post.score,
                "comments": post.num_comments,
                "upvote_ratio": getattr(post, "upvote_ratio", 0),
            },
            "published_at": datetime.fromtimestamp(
                post.created_utc, tz=timezone.utc
            ).isoformat(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    def _parse_comment(
        self, comment: object, source_name: str, post_id: str
    ) -> dict | None:
        body = getattr(comment, "body", "")
        if not body or len(body) < 50:
            return None

        # Skip bot/deleted comments
        author = str(getattr(comment, "author", "[deleted]"))
        if author in ("[deleted]", "AutoModerator"):
            return None

        return {
            "id": self.content_id(f"c_{comment.id}"),
            "platform": self.platform,
            "source": source_name,
            "content_type": "comment",
            "author": author,
            "title": f"Comment on post {post_id}",
            "body": body,
            "url": f"https://reddit.com{comment.permalink}",
            "engagement": {
                "upvotes": comment.score,
                "comments": 0,
            },
            "published_at": datetime.fromtimestamp(
                comment.created_utc, tz=timezone.utc
            ).isoformat(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
