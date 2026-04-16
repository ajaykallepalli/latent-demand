"""Dynamic subreddit discovery — finds new sources each run for variety."""

from __future__ import annotations

import random
import time

import httpx
import structlog

logger = structlog.get_logger()

_BASE = "https://old.reddit.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) LatentDemandResearch/0.1",
}

# Verticals to search for subreddits — rotated each run
_SEARCH_QUERIES = [
    "ai automation workflow",
    "ai tools productivity",
    "side hustle business",
    "home automation smart home",
    "healthcare technology",
    "education technology",
    "personal finance budgeting",
    "creative freelance design",
    "real estate investing",
    "food meal planning",
    "fitness wearable tracking",
    "parenting technology",
    "legal technology",
    "music production tools",
    "video editing ai",
    "customer service support",
    "project management",
    "data analysis spreadsheet",
    "remote work tools",
    "ecommerce shopify",
    "construction trades",
    "veterinary pet care",
    "mental health therapy",
    "travel planning",
    "wedding planning",
    "automotive repair",
    "farming agriculture tech",
    "restaurant management",
    "nonprofit volunteer",
    "insurance claims",
]

# Large rotation pool — subreddits worth checking occasionally.
# Each run picks a random subset so we don't always scan the same places.
_ROTATION_POOL = [
    "Bookkeeping", "PropertyManagement", "InsurancePros", "veterinary",
    "dentistry", "optometry", "physicaltherapy", "OccupationalTherapy",
    "socialwork", "Plumbing", "electricians", "HVAC",
    "TaxPros", "Bookkeeping", "FinancialPlanning", "CPA",
    "realtors", "CommercialRealEstate", "PropertyManagement",
    "restaurateur", "KitchenConfidential", "barista",
    "AutoDetailing", "MechanicAdvice", "Justrolledintotheshop",
    "landscaping", "lawncare",
    "weddingplanning", "EventPlanning",
    "therapists", "psychotherapy", "SLP",
    "VetTech", "AskVet",
    "ChildCare", "Nanny", "ECEProfessionals",
    "nonprofit", "fundraising",
    "TruckDrivers", "Truckers",
    "RealEstateTechnology", "proptech",
    "dataengineering", "analytics", "BusinessIntelligence",
    "CustomerSuccess", "CustomerService",
    "UXDesign", "userexperience",
    "contentcreation", "YouTubers", "podcasting",
    "Twitch", "streaming",
    "dropshipping", "AmazonSeller", "Etsy",
    "Flipping", "thrifting",
    "digitalnomad", "overemployed",
    "Bookkeeping", "QuickBooks",
    "sysadmin", "MSP",
    "solar", "electricvehicles",
    "HomeLab", "smarthome",
    "3Dprinting", "lasercutting", "CNC",
    "ArtificialInteligence", "singularity",
    "ClaudeAI", "ChatGPT", "LocalLLaMA",
]


def _get(url: str, timeout: int = 10) -> dict | None:
    """GET with rate limiting and error handling."""
    time.sleep(2)
    try:
        resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        logger.debug("discovery.http_error", url=url, status=resp.status_code)
    except (httpx.HTTPError, Exception) as e:
        logger.debug("discovery.error", url=url, error=str(e))
    return None


def discover_popular(limit: int = 10) -> list[str]:
    """Get currently popular subreddits from Reddit."""
    data = _get(f"{_BASE}/subreddits/popular.json?limit={limit}")
    if not data:
        return []
    subs = []
    for child in data.get("data", {}).get("children", []):
        name = child.get("data", {}).get("display_name", "")
        if name:
            subs.append(name)
    logger.info("discovery.popular", found=len(subs))
    return subs


def discover_by_search(num_queries: int = 3, results_per: int = 5) -> list[str]:
    """Search for subreddits using random vertical queries."""
    queries = random.sample(_SEARCH_QUERIES, min(num_queries, len(_SEARCH_QUERIES)))
    subs = []
    for query in queries:
        data = _get(f"{_BASE}/subreddits/search.json?q={query}&limit={results_per}&sort=relevance")
        if not data:
            continue
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            name = d.get("display_name", "")
            subscriber_count = d.get("subscribers", 0)
            # Skip tiny subs — not enough content to be useful
            if name and subscriber_count >= 5000:
                subs.append(name)
        logger.info("discovery.search", query=query, found=len(subs))
    return list(set(subs))


def discover_random(count: int = 5) -> list[str]:
    """Pick random subreddits from the rotation pool."""
    picked = random.sample(_ROTATION_POOL, min(count, len(_ROTATION_POOL)))
    logger.info("discovery.random_pool", picked=picked)
    return picked


def discover_trending_random(count: int = 3) -> list[str]:
    """Hit Reddit's /r/random endpoint for true randomness."""
    subs = []
    for _ in range(count):
        try:
            time.sleep(2)
            resp = httpx.get(
                f"{_BASE}/r/random/.json?limit=1",
                headers=_HEADERS,
                follow_redirects=True,
                timeout=10,
            )
            if resp.status_code == 200:
                # Extract subreddit name from the redirect URL
                url_parts = str(resp.url).split("/")
                if len(url_parts) >= 5:
                    sub = url_parts[4]
                    if sub and sub != "random":
                        subs.append(sub)
        except (httpx.HTTPError, Exception):
            continue
    logger.info("discovery.random_reddit", found=subs)
    return subs


def discover_sources(
    num_popular: int = 8,
    num_search_queries: int = 3,
    num_random_pool: int = 5,
    num_random_reddit: int = 3,
    existing_ids: set[str] | None = None,
) -> list[dict]:
    """Run all discovery strategies and return temporary source dicts.

    These sources are for a single run — they don't get persisted to
    sources.json unless they yield signals.

    Args:
        num_popular: How many popular subs to fetch.
        num_search_queries: How many vertical search queries to run.
        num_random_pool: How many subs to pick from the rotation pool.
        num_random_reddit: How many hits to /r/random.
        existing_ids: Set of subreddit names already in sources.json (to skip).

    Returns:
        List of source dicts in the same format as sources.json entries.
    """
    existing = {s.lower() for s in (existing_ids or set())}

    all_subs: set[str] = set()

    # Run discovery strategies
    for sub in discover_popular(num_popular):
        all_subs.add(sub)
    for sub in discover_by_search(num_search_queries):
        all_subs.add(sub)
    for sub in discover_random(num_random_pool):
        all_subs.add(sub)
    for sub in discover_trending_random(num_random_reddit):
        all_subs.add(sub)

    # Filter out subs we already have
    novel = [s for s in all_subs if s.lower() not in existing]

    logger.info(
        "discovery.complete",
        total_discovered=len(all_subs),
        novel=len(novel),
        already_tracked=len(all_subs) - len(novel),
    )

    # Build source dicts
    sources = []
    for sub in novel:
        sources.append({
            "id": f"discovered-{sub.lower()}",
            "platform": "reddit",
            "identifier": f"r/{sub}",
            "config": {"subreddit": sub, "sort": "hot", "limit": 30},
            "priority": 5,
            "yield_score": 0.0,
            "scan_interval_hours": 24,
            "last_scanned_at": None,
            "enabled": True,
            "_discovered": True,  # Flag so pipeline knows these are temporary
        })

    return sources
