"""
core/news.py
Fetches financial headlines from NewsAPI with a 1-hour in-memory cache
to protect the 100 req/day free tier quota.
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

# Simple in-memory cache: {cache_key: {"data": [...], "timestamp": float}}
_cache: dict = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_market_news(query: str = "stock market", num_articles: int = 5) -> list[dict]:
    """
    Returns a list of recent news articles:
    [{"title": "...", "description": "...", "url": "..."}, ...]

    Results are cached per query for 1 hour to preserve NewsAPI free-tier quota.
    Returns an empty list (with a note) if the API key is missing or the call fails.
    """
    if not NEWS_API_KEY:
        print("WARNING: NEWS_API_KEY not set — skipping news fetch.")
        return [{"title": "News unavailable", "description": "NEWS_API_KEY not configured.", "url": ""}]

    cache_key = f"{query}:{num_articles}"
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"]) < CACHE_TTL_SECONDS:
        return cached["data"]

    try:
        response = requests.get(
            NEWS_API_URL,
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": num_articles,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        )
        response.raise_for_status()
        articles = response.json().get("articles", [])

        result = [
            {
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "url": a.get("url", ""),
                "published_at": a.get("publishedAt", ""),
            }
            for a in articles
            if a.get("title")
        ]

        _cache[cache_key] = {"data": result, "timestamp": time.time()}
        return result

    except requests.exceptions.RequestException as e:
        print(f"WARNING: NewsAPI request failed: {e}")
        return [{"title": "News unavailable", "description": str(e), "url": ""}]


if __name__ == "__main__":
    import json
    print("Fetching market news...")
    news = get_market_news("stock market", num_articles=5)
    print(json.dumps(news, indent=2))
