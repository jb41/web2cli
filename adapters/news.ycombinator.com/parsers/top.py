"""
Custom parser for HN stories endpoints (top, new, best, etc.)

These endpoints return arrays of item IDs. This parser fetches
each item concurrently and returns structured data.
"""

import asyncio
import json
from typing import Any

import httpx

HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
HN_STORY_URL = "https://news.ycombinator.com/item?id={}"


async def _fetch_item(client: httpx.AsyncClient, item_id: int) -> dict | None:
    try:
        resp = await client.get(HN_ITEM_URL.format(item_id))
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def _resolve_items(item_ids: list[int]) -> list[dict]:
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_item(client, iid) for iid in item_ids]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """
    Parse stories endpoint response.

    The endpoint returns a JSON array of item IDs.
    We fetch each item concurrently and return structured records.
    """
    item_ids = json.loads(body)
    limit = args.get("limit", 20)
    item_ids = item_ids[:limit]

    items = asyncio.run(_resolve_items(item_ids))

    return [
        {
            "rank": i + 1,
            "title": item.get("title", ""),
            "score": item.get("score", 0),
            "author": item.get("by", ""),
            "comments": item.get("descendants", 0),
            "url": item.get("url") or HN_STORY_URL.format(item.get("id")),
            "id": item.get("id"),
        }
        for i, item in enumerate(items)
    ]
