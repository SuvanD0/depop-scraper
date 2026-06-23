"""Depop unofficial web API client. See research.md for endpoint notes (verified 2026-06-09)."""
from __future__ import annotations

import json
import random
import time
import urllib.parse
import urllib.request
import uuid

SEARCH_URL = "https://www.depop.com/presentation/api/v1/search/products/"

# Fresh UUIDs are accepted; without these headers the API returns 400.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "depop-device-id": str(uuid.uuid4()),
    "depop-session-id": str(uuid.uuid4()),
    "x-cached-sizes": "true",
}


class RateLimited(Exception):
    pass


def _get(url: str, delay: float, retries: int = 2) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        time.sleep(delay + random.uniform(0, 1) + attempt * 5)
        headers = {**_HEADERS, "depop-search-id": str(uuid.uuid4())}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise RateLimited(f"HTTP {e.code} from {url}")
            last_err = e
        except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as e:
            # Transient network errors — back off and retry
            last_err = e
            print(f"[depop] transient {type(e).__name__} on attempt {attempt + 1}, retrying")
    raise RateLimited(f"giving up after {retries + 1} attempts: {last_err}")


def search(query: str, max_price: float, pages: int, per_page: int, delay: float) -> list[dict]:
    """Return raw product rows across up to `pages` pages."""
    rows: list[dict] = []
    cursor = None
    for _ in range(pages):
        params = {
            "what": query,
            "limit": per_page,
            "country": "us",
            "currency": "USD",
            "price_max": max_price,
            "from": "in_country_search",
            "include_like_count": "true",
        }
        if cursor:
            params["after"] = cursor
        data = _get(SEARCH_URL + "?" + urllib.parse.urlencode(params), delay)
        rows.extend(data.get("objects", []))
        page_info = data.get("page_info", {})
        cursor = page_info.get("last")
        if not page_info.get("has_more") or not cursor:
            break
    return rows


def normalize(row: dict) -> dict:
    """Normalize a search row into the pipeline schema."""
    slug = row.get("slug", "")
    pricing = row.get("pricing", {}) or {}
    final_key = pricing.get("final_price_key", "original_price")
    price = float((pricing.get(final_key) or {}).get("total_price") or 0)

    images = []
    for pic in row.get("pictures") or []:
        formats = pic.get("formats") or {}
        for fmt in formats.values():
            if isinstance(fmt, dict) and fmt.get("url"):
                images.append(fmt["url"])
                break
    if not images:
        preview = (row.get("preview") or {}).get("formats") or {}
        for fmt in preview.values():
            if isinstance(fmt, dict) and fmt.get("url"):
                images.append(fmt["url"])
                break

    attrs = row.get("attributes") or {}
    return {
        "id": str(row.get("id", slug)),
        "slug": slug,
        "title": slug.rsplit("-", 1)[0].replace("-", " ") if slug else "",
        "price": price,
        "currency": pricing.get("currency_name", "USD"),
        "brand": row.get("brand_name", "") if row.get("brand_name") != "Other" else "",
        "description": row.get("description", "") or "",
        "condition": attrs.get("condition", ""),
        "images": images[:4],
        "url": f"https://www.depop.com/products/{slug}/",
        "seller": slug.split("-", 1)[0] if slug else "",
        "discount_pct": pricing.get("discount_percentage", 0),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
