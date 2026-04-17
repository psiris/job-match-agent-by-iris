"""
jd_cache.py — URL-keyed disk cache for job descriptions.

Cache location: output/_cache/jd/<sha256(url)[:16]>.json
TTL: 7 days (matches the freshness threshold so stale→fresh transitions are not missed).

Only caches the per-URL fetch step (Indeed get_job_details, WebFetch).
Search-discovery calls (search_jobs, WebSearch) always run in full.

API
---
  from jd_cache import get, put

  cached = get(url)           # returns dict | None
  if cached:
      job = cached
  else:
      job = fetch_jd(url)     # your fetch logic
      put(url, job)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Cache lives under the project output/ directory.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CACHE_DIR = _PROJECT_ROOT / "output" / "_cache" / "jd"
_TTL_DAYS = 7


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{key}.json"


def get(url: str) -> dict | None:
    """Return the cached job dict if it exists and is within TTL, else None."""
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = datetime.fromisoformat(data["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - cached_at > timedelta(days=_TTL_DAYS):
            return None  # expired — caller will re-fetch
        return data["job"]
    except Exception:
        return None  # corrupt cache file — treat as miss


def put(url: str, job: dict) -> None:
    """Write job dict to cache keyed by URL. Silently ignores write failures."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(url)
        payload = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "job": job,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass  # cache is best-effort; don't abort the search run on write failure
