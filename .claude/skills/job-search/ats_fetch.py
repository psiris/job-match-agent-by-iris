#!/usr/bin/env python3
"""
ats_fetch.py — Direct ATS board ingestion via public unauthenticated JSON APIs.

Replaces WebSearch + WebFetch for known Greenhouse / Lever / Ashby slugs.
Returns a list of job dicts in the same normalised schema as normalise_jsearch() in search.py.

Usage (standalone test):
  python ats_fetch.py --slug anthropic --source greenhouse
  python ats_fetch.py --slug notion --source lever
  python ats_fetch.py --slug linear --source ashby
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# City names accepted by the job-search skill (lowercase for comparison).
ALLOWED_CITIES = {"london", "dubai", "abu dhabi", "zurich", "amsterdam"}

# Map of ATS source → endpoint template
_ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever":      "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
    "workable":   "https://apply.workable.com/api/v1/widget/accounts/{slug}",
}


def _fetch_json(url: str, timeout: int = 20) -> list | dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "job-match-agent/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  ! ATS fetch HTTP {e.code} for {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ! ATS fetch error for {url}: {e}", file=sys.stderr)
        return None


def _normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", title.lower())).strip()


def _location_str(raw: str | None) -> str:
    return (raw or "").strip()


def _in_allowed_city(location: str) -> bool:
    loc_lower = location.lower()
    return any(city in loc_lower for city in ALLOWED_CITIES)


def _parse_date(val) -> str | None:
    """Coerce epoch-ms int or ISO string to ISO datetime string."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        # Lever/Ashby use epoch milliseconds
        try:
            dt = datetime.fromtimestamp(val / 1000, tz=timezone.utc)
            return dt.isoformat()
        except Exception:
            return None
    if isinstance(val, str):
        try:
            datetime.fromisoformat(val.replace("Z", "+00:00"))
            return val
        except ValueError:
            return None
    return None


def _make_job(
    title: str,
    company: str,
    location: str,
    url: str,
    description: str,
    date_posted,
    source: str,
) -> dict:
    return {
        "family": None,          # caller fills this in
        "query": None,           # caller fills this in
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "salary_raw": "",
        "salary_gbp": None,
        "date_posted": _parse_date(date_posted),
        "description": (description or "")[:4000],
        "source": source,
        "freshness": None,       # caller fills this in via freshness_tag()
    }


# ---------- per-ATS fetchers ----------

def fetch_greenhouse(slug: str) -> list[dict]:
    url = _ENDPOINTS["greenhouse"].format(slug=slug)
    data = _fetch_json(url)
    if not data:
        return []
    jobs_raw = data.get("jobs") or []
    results = []
    for j in jobs_raw:
        location = _location_str(j.get("location", {}).get("name") if isinstance(j.get("location"), dict) else j.get("location"))
        if not _in_allowed_city(location):
            continue
        results.append(_make_job(
            title=j.get("title", ""),
            company=slug.replace("-", " ").title(),          # Greenhouse doesn't return company name; derive from slug
            location=location,
            url=j.get("absolute_url", ""),
            description=j.get("content", ""),
            date_posted=j.get("updated_at"),
            source="greenhouse",
        ))
    return results


def fetch_lever(slug: str) -> list[dict]:
    url = _ENDPOINTS["lever"].format(slug=slug)
    data = _fetch_json(url)
    if not data or not isinstance(data, list):
        return []
    results = []
    for j in data:
        categories = j.get("categories") or {}
        location = categories.get("location") or categories.get("city") or j.get("workplaceType") or ""
        if not _in_allowed_city(location):
            continue
        results.append(_make_job(
            title=j.get("text", ""),
            company=slug.replace("-", " ").title(),
            location=location,
            url=j.get("hostedUrl", ""),
            description=j.get("descriptionPlain") or j.get("description") or "",
            date_posted=j.get("createdAt"),
            source="lever",
        ))
    return results


def fetch_ashby(slug: str) -> list[dict]:
    url = _ENDPOINTS["ashby"].format(slug=slug)
    data = _fetch_json(url)
    if not data:
        return []
    jobs_raw = data.get("jobs") or []
    results = []
    for j in jobs_raw:
        location = j.get("locationName") or j.get("location") or ""
        if not _in_allowed_city(location):
            continue
        job_url = j.get("jobUrl") or j.get("externalLink") or ""
        results.append(_make_job(
            title=j.get("title", ""),
            company=data.get("organization", {}).get("name", slug.replace("-", " ").title()),
            location=location,
            url=job_url,
            description=j.get("descriptionHtml") or j.get("descriptionPlain") or "",
            date_posted=j.get("publishedAt") or j.get("updatedAt"),
            source="ashby",
        ))
    return results


def fetch_workable(slug: str) -> list[dict]:
    url = _ENDPOINTS["workable"].format(slug=slug)
    data = _fetch_json(url)
    if not data:
        return []
    jobs_raw = data.get("jobs") or []
    results = []
    for j in jobs_raw:
        city = j.get("city") or ""
        state = j.get("state") or ""
        country = j.get("country") or ""
        location = ", ".join(filter(None, [city, state, country]))
        if not _in_allowed_city(location):
            continue
        results.append(_make_job(
            title=j.get("title", ""),
            company=slug.replace("-", " ").title(),
            location=location,
            url=j.get("shortlink", ""),
            description="",
            date_posted=j.get("created_at"),
            source="workable",
        ))
    return results


# ---------- dispatch ----------

_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever":      fetch_lever,
    "ashby":      fetch_ashby,
    "workable":   fetch_workable,
}


def fetch_ats(source: str, slug: str) -> list[dict]:
    """Public entry point. source = 'greenhouse' | 'lever' | 'ashby' | 'workable'."""
    fetcher = _FETCHERS.get(source)
    if not fetcher:
        print(f"  ! Unknown ATS source: {source}", file=sys.stderr)
        return []
    return fetcher(slug)


# ---------- standalone test ----------

def main():
    ap = argparse.ArgumentParser(description="Test a single ATS board fetch")
    ap.add_argument("--slug", required=True, help="Board slug, e.g. 'anthropic'")
    ap.add_argument("--source", required=True, choices=list(_FETCHERS), help="ATS provider")
    args = ap.parse_args()

    jobs = fetch_ats(args.source, args.slug)
    print(f"{args.source}/{args.slug}: {len(jobs)} jobs in allowed cities")
    for j in jobs[:3]:
        print(f"  · {j['title']} @ {j['location']}  —  {j['url'][:80]}")


if __name__ == "__main__":
    main()
