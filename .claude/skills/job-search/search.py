#!/usr/bin/env python3
"""
search.py — Hybrid job search via JSearch (RapidAPI) + filters + dedup.

Usage:
  python search.py --test                          # one-shot connection test
  python search.py --family stratops               # full search for one family
  python search.py --family techprod --location London --limit 5
  python search.py --family both                   # default (api then ats)
  python search.py --phase api --family both       # Phase 1 only (JSearch API)
  python search.py --phase indeed --input output/_raw_<ts>.json  # Phase 2a only (JobSpy Indeed)
  python search.py --phase ats --input output/_raw_<ts>.json  # Phase 2c only (ATS gap-fill)

Output: JSON file at output/_raw_<timestamp>.json containing the normalised long list.
The job-match skill consumes that file next.

API key is read from .env at the project root (RAPIDAPI_KEY=...).
If the key is missing, the script exits with a clear instruction.

Efficiency rubric: every edit here is judged on two axes — fewer API calls (efficient)
and more distinct postings found (quality). Both matter; neither dominates.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))
ENV_PATH = PROJECT_ROOT / ".env"
QUERIES_PATH = Path(__file__).parent / "queries.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output"

JSEARCH_HOST = "jsearch.p.rapidapi.com"
JSEARCH_URL = f"https://{JSEARCH_HOST}/search"

# FX rates loaded from queries.yaml at runtime; this is the fallback if config is missing.
FX_TO_GBP: dict[str, float] = {"GBP": 1.0, "USD": 0.79, "EUR": 0.85, "CHF": 0.91, "AED": 0.21}

# JobSpy country vocabulary for Indeed
_INDEED_COUNTRY_MAP = {
    "GB": "UK",
    "AE": "united arab emirates",
    "CH": "Switzerland",
    "NL": "Netherlands",
}

JOBSPY_PYTHON = "/opt/homebrew/bin/python3.12"


# ---------- helpers ----------

def load_env() -> dict:
    """Tiny .env parser — avoids python-dotenv dependency."""
    if not ENV_PATH.exists():
        return {}
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_queries() -> dict:
    """Load queries.yaml. Tries PyYAML; falls back to a minimal parser.
    Also updates the global FX_TO_GBP table from fx_rates_to_gbp if present."""
    global FX_TO_GBP
    text = QUERIES_PATH.read_text()
    try:
        import yaml  # type: ignore
        cfg = yaml.safe_load(text)
    except ImportError:
        cfg = _minimal_yaml_parse(text)
    if "fx_rates_to_gbp" in cfg:
        FX_TO_GBP = {k.upper(): float(v) for k, v in cfg["fx_rates_to_gbp"].items()}
    return cfg


def _minimal_yaml_parse(text: str) -> dict:
    """Bare-bones YAML parser supporting only the subset used in queries.yaml."""
    root: dict = {}
    stack = [(0, root)]
    pending_list_key = None
    lines = text.splitlines()
    for raw_idx, raw in enumerate(lines):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = _yaml_scalar(line[2:].strip())
            if isinstance(parent, list):
                parent.append(item)
            else:
                parent[pending_list_key].append(item)
        elif ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if not val:
                # Peek at next non-empty, non-comment line to decide list vs dict
                next_lines = [l.strip() for l in lines[raw_idx + 1:] if l.strip() and not l.lstrip().startswith("#")]
                if next_lines and ":" in next_lines[0] and not next_lines[0].startswith("- "):
                    new: list | dict = {}
                else:
                    new = []
                parent[key] = new
                pending_list_key = key
                stack.append((indent + 2, new))
            elif val.startswith("["):
                parent[key] = _yaml_inline_list(val)
            elif val.startswith("{"):
                parent[key] = _yaml_inline_dict(val)
            else:
                parent[key] = _yaml_scalar(val)
    return root


def _yaml_scalar(s: str):
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() in {"true", "false"}:
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _yaml_inline_list(s: str) -> list:
    inner = s.strip().lstrip("[").rstrip("]")
    if not inner.strip():
        return []
    return [_yaml_scalar(x) for x in _split_top_level(inner, ",")]


def _yaml_inline_dict(s: str) -> dict:
    inner = s.strip().lstrip("{").rstrip("}")
    out = {}
    for pair in _split_top_level(inner, ","):
        k, _, v = pair.partition(":")
        out[k.strip()] = _yaml_scalar(v.strip())
    return out


def _split_top_level(s: str, sep: str) -> list[str]:
    parts, depth, buf = [], 0, []
    for ch in s:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", title.lower())).strip()


def normalise_location(loc: str) -> str:
    s = (loc or "").lower().strip()
    for city in ("london", "dubai", "abu dhabi", "zurich", "amsterdam"):
        if city in s:
            return city
    return s


def parse_salary_to_gbp(min_sal, max_sal, currency: str | None) -> float | None:
    if not min_sal and not max_sal:
        return None
    rate = FX_TO_GBP.get((currency or "").upper())
    if rate is None:
        return None
    val = max_sal or min_sal
    try:
        return float(val) * rate
    except (TypeError, ValueError):
        return None


_SALARY_PAT = re.compile(
    r"(£|\$|€|GBP|USD|EUR|CHF|AED)\s*([\d,]+(?:\.\d+)?)\s*(k)?"
    r"(?:\s*[-–]\s*(?:£|\$|€|GBP|USD|EUR|CHF|AED)?\s*([\d,]+(?:\.\d+)?)\s*(k)?)?",
    re.IGNORECASE,
)
_SALARY_KEYWORD_PAT = re.compile(
    r"salary|compensation|pay|package|per\s+annum|p\.a\.|annual|base\s+salary",
    re.IGNORECASE,
)
_SYM_TO_CODE = {"£": "GBP", "$": "USD", "€": "EUR"}


def extract_salary_from_text(text: str) -> float | None:
    """Extract the best salary estimate (GBP) from free text; returns None if not found."""
    if not text:
        return None
    keyword_positions = [m.start() for m in _SALARY_KEYWORD_PAT.finditer(text)]
    best: float | None = None
    for m in _SALARY_PAT.finditer(text):
        pos = m.start()
        near_keyword = any(abs(pos - kp) < 200 for kp in keyword_positions)
        code = _SYM_TO_CODE.get(m.group(1).upper(), m.group(1).upper())
        if code not in FX_TO_GBP:
            continue

        def _parse(num_str, k_flag):
            if not num_str:
                return None
            n = float(num_str.replace(",", ""))
            return n * 1000 if k_flag else n

        lo = _parse(m.group(2), m.group(3))
        hi = _parse(m.group(4), m.group(5))
        val = hi if hi else lo
        if val is None:
            continue
        # Monthly → annual
        after = text[m.end():m.end() + 20].lower()
        if re.search(r"/\s*(?:month|mo)\b", after):
            val *= 12
        gbp_val = val * FX_TO_GBP[code]
        if gbp_val < 20_000 or gbp_val > 2_000_000:
            continue
        if near_keyword or gbp_val >= 50_000:
            if best is None or gbp_val > best:
                best = gbp_val
    return best


def freshness_tag(date_posted_iso: str | None, fresh_days: int) -> str:
    if not date_posted_iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(date_posted_iso.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    return "fresh" if age <= timedelta(days=fresh_days) else "stale"


# ---------- filters ----------

def passes_seniority(title: str, description: str, reject_keywords: list[str]) -> bool:
    # Check title only — description often mentions keywords legitimately (e.g. "manages analysts")
    blob = title.lower()
    return not any(kw.lower() in blob for kw in reject_keywords)


def passes_language(description: str, reject_keywords: list[str]) -> bool:
    blob = description.lower()
    return not any(kw.lower() in blob for kw in reject_keywords)


def passes_salary(salary_gbp: float | None, threshold: float) -> bool:
    return True if salary_gbp is None else salary_gbp >= threshold


# ---------- API ----------

# Escalating per-attempt timeouts: fail fast on first try, give slow paths room on retries.
JSEARCH_TIMEOUTS = [15, 30, 45]


def jsearch_call(query: str, location: str, country_code: str, api_key: str, page: int = 1, retries: int = 2) -> list[dict]:
    q = f"{query} in {location}"
    params = urllib.parse.urlencode({
        "query": q,
        "page": str(page),
        "num_pages": "1",
        "country": country_code.lower(),
        "date_posted": "month",
    })
    req = urllib.request.Request(
        f"{JSEARCH_URL}?{params}",
        headers={
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": JSEARCH_HOST,
        },
    )
    for attempt in range(retries + 1):
        timeout = JSEARCH_TIMEOUTS[min(attempt, len(JSEARCH_TIMEOUTS) - 1)]
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return data.get("data", []) or []
        except urllib.error.HTTPError as e:
            # Don't retry 4xx (except 429): the request itself is bad.
            if 400 <= e.code < 500 and e.code != 429:
                print(f"  ! JSearch {e.code} for '{q}': {e.reason}", file=sys.stderr)
                return []
            if attempt < retries:
                if e.code == 429:
                    # Honor Retry-After if present; cap at 30s to avoid pathological waits.
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    try:
                        sleep_s = min(float(retry_after), 30.0) if retry_after else 5.0
                    except ValueError:
                        sleep_s = 5.0
                else:
                    sleep_s = (2 ** attempt) + random.random()  # jittered backoff
                time.sleep(sleep_s)
            else:
                print(f"  ! JSearch {e.code} for '{q}' (giving up): {e.reason}", file=sys.stderr)
                return []
        except Exception as e:
            if attempt < retries:
                time.sleep((2 ** attempt) + random.random())  # jittered backoff
            else:
                print(f"  ! JSearch error for '{q}': {e}", file=sys.stderr)
                return []
    return []


def normalise_jsearch(raw: dict, query: str, family: str) -> dict:
    salary_gbp = parse_salary_to_gbp(
        raw.get("job_min_salary"),
        raw.get("job_max_salary"),
        raw.get("job_salary_currency"),
    )
    description = raw.get("job_description", "")[:4000]
    if salary_gbp is None:
        salary_gbp = extract_salary_from_text(description)
    return {
        "family": family,
        "query": query,
        "title": raw.get("job_title", ""),
        "company": raw.get("employer_name", ""),
        "location": ", ".join(filter(None, [raw.get("job_city"), raw.get("job_country")])),
        "url": raw.get("job_apply_link") or raw.get("job_google_link") or "",
        "salary_raw": f"{raw.get('job_salary_currency') or ''} {raw.get('job_min_salary') or ''}-{raw.get('job_max_salary') or ''}".strip(),
        "salary_gbp": salary_gbp,
        "date_posted": raw.get("job_posted_at_datetime_utc"),
        "description": description,
        "source": "jsearch",
    }


# ---------- Indeed / JobSpy ----------

def _indeed_country(country_code: str) -> str:
    return _INDEED_COUNTRY_MAP.get(country_code.upper(), country_code)


def normalise_jobspy(row, family: str, query: str, city: str) -> dict:
    """Convert a JobSpy DataFrame row to our standard job schema."""
    import math

    def _safe(val):
        """Return None for NaN/NaT/None, otherwise the value."""
        try:
            if val is None:
                return None
            if isinstance(val, float) and math.isnan(val):
                return None
            return val
        except Exception:
            return None

    title = _safe(row.get("title")) or ""
    company = _safe(row.get("company")) or ""
    location = _safe(row.get("location")) or ""
    job_url = _safe(row.get("job_url")) or ""
    description = _safe(row.get("description")) or ""
    min_amount = _safe(row.get("min_amount"))
    max_amount = _safe(row.get("max_amount"))
    currency = _safe(row.get("currency"))
    date_posted = _safe(row.get("date_posted"))

    salary_gbp = parse_salary_to_gbp(min_amount, max_amount, str(currency) if currency else None)
    if salary_gbp is None:
        salary_gbp = extract_salary_from_text(description)

    if date_posted is not None:
        try:
            date_posted_iso = date_posted.isoformat()
        except AttributeError:
            date_posted_iso = str(date_posted) if date_posted else None
    else:
        date_posted_iso = None

    return {
        "family": family,
        "query": query,
        "title": title,
        "company": company,
        "location": location,
        "url": job_url,
        "salary_raw": f"{currency or ''} {min_amount or ''}-{max_amount or ''}".strip(),
        "salary_gbp": salary_gbp,
        "date_posted": date_posted_iso,
        "description": description[:4000],
        "source": "indeed",
    }


def run_indeed_jobspy(cfg: dict, existing_keys: set[tuple] | None = None) -> tuple[list[dict], int, int]:
    """Phase 2a: scrape Indeed via JobSpy across all (family × query × city) combos.

    Returns (results, n_raw, n_kept).
    """
    try:
        import subprocess
        import importlib.util
        # Try to import jobspy; if not available in current interpreter, use JOBSPY_PYTHON
        spec = importlib.util.find_spec("jobspy")
        if spec is None:
            raise ImportError("jobspy not in current interpreter")
        from jobspy import scrape_jobs  # type: ignore
        _use_subprocess = False
    except ImportError:
        _use_subprocess = True

    filt = cfg["filters"]
    fresh_days = cfg["freshness"]["fresh_days"]
    threshold = float(filt["min_salary_gbp"])
    seen_keys: set[tuple] = set(existing_keys) if existing_keys else set()
    results: list[dict] = []
    n_raw = 0

    families = ["stratops", "techprod"]
    for family in families:
        for query in cfg["queries"][family]:
            for loc in cfg["locations"]:
                city = loc["city"]
                country_code = loc["country_code"]
                country_indeed = _indeed_country(country_code)
                print(f"  · indeed | {query} @ {city}")

                if _use_subprocess:
                    # Run scrape_jobs in the JobSpy-capable interpreter and get JSON back
                    script = (
                        "import json, sys, math\n"
                        "from jobspy import scrape_jobs\n"
                        "df = scrape_jobs(\n"
                        f"    site_name='indeed', search_term={query!r}, location={city!r},\n"
                        f"    results_wanted=100, hours_old=168, country_indeed={country_indeed!r},\n"
                        "    job_type='fulltime', description_format='markdown'\n"
                        ")\n"
                        "rows = []\n"
                        "for _, r in df.iterrows():\n"
                        "    row = {}\n"
                        "    for k, v in r.items():\n"
                        "        if hasattr(v, 'isoformat'):\n"
                        "            row[k] = v.isoformat()\n"
                        "        elif isinstance(v, float) and math.isnan(v):\n"
                        "            row[k] = None\n"
                        "        else:\n"
                        "            row[k] = v\n"
                        "    rows.append(row)\n"
                        "print(json.dumps(rows))\n"
                    )
                    try:
                        proc = subprocess.run(
                            [JOBSPY_PYTHON, "-c", script],
                            capture_output=True, text=True, timeout=120
                        )
                        if proc.returncode != 0:
                            print(f"  ! jobspy subprocess error: {proc.stderr[:200]}", file=sys.stderr)
                            continue
                        rows = json.loads(proc.stdout)
                    except Exception as e:
                        print(f"  ! jobspy subprocess failed for '{query}' @ {city}: {e}", file=sys.stderr)
                        continue
                else:
                    try:
                        df = scrape_jobs(  # type: ignore  # noqa: F821
                            site_name="indeed",
                            search_term=query,
                            location=city,
                            results_wanted=100,
                            hours_old=168,
                            country_indeed=country_indeed,
                            job_type="fulltime",
                            description_format="markdown",
                        )
                        rows = df.to_dict("records")
                    except Exception as e:
                        print(f"  ! jobspy error for '{query}' @ {city}: {e}", file=sys.stderr)
                        continue

                n_raw += len(rows)
                for row in rows:
                    job = normalise_jobspy(row, family, query, city)
                    if not job["description"]:
                        continue
                    # City-match filter: reject nearby towns
                    if city.lower() not in (job["location"] or "").lower():
                        continue
                    key = (job["company"].lower(), normalise_title(job["title"]), normalise_location(job["location"]))
                    if key in seen_keys:
                        continue
                    if not passes_seniority(job["title"], job["description"], filt["reject_seniority_keywords"]):
                        continue
                    if not passes_language(job["description"], filt["reject_language_requirements"]):
                        continue
                    if not passes_salary(job["salary_gbp"], threshold):
                        continue
                    job["freshness"] = freshness_tag(job["date_posted"], fresh_days)
                    seen_keys.add(key)
                    results.append(job)

    return results, n_raw, len(results)


# ---------- pipeline ----------

def run_search(family: str, location_filter: str | None, limit: int | None, api_key: str, cfg: dict, seen: set[tuple] | None = None) -> list[dict]:
    queries = cfg["queries"][family]
    locations = cfg["locations"]
    if location_filter:
        locations = [l for l in locations if l["city"].lower() == location_filter.lower()]
        if not locations:
            print(f"! Unknown location: {location_filter}", file=sys.stderr)
            return []

    filt = cfg["filters"]
    fresh_days = cfg["freshness"]["fresh_days"]
    threshold = float(filt["min_salary_gbp"])

    if seen is None:
        seen = set()
    results: list[dict] = []
    called: set[tuple[str, str]] = set()  # (query_lower, city_lower) — avoids duplicate API calls across families

    for query in queries:
        if limit and len(results) >= limit:
            break
        for loc in locations:
            if limit and len(results) >= limit:
                break
            call_key = (query.lower(), loc["city"].lower())
            if call_key in called:
                continue
            called.add(call_key)
            print(f"  · {family} | {query} @ {loc['city']}")
            raw_jobs = jsearch_call(query, loc["city"], loc["country_code"], api_key)
            time.sleep(1.0)  # be polite to the API
            for raw in raw_jobs:
                job = normalise_jsearch(raw, query, family)
                if not job["location"]:
                    job["location"] = f"{loc['city']}, {loc['country_code']}"
                if not job["description"]:
                    continue
                key = (job["company"].lower(), normalise_title(job["title"]), normalise_location(job["location"]))
                if key in seen:
                    continue
                if not passes_seniority(job["title"], job["description"], filt["reject_seniority_keywords"]):
                    continue
                if not passes_language(job["description"], filt["reject_language_requirements"]):
                    continue
                if not passes_salary(job["salary_gbp"], threshold):
                    continue
                job["freshness"] = freshness_tag(job["date_posted"], fresh_days)
                seen.add(key)
                results.append(job)
                if limit and len(results) >= limit:
                    return results

    return results


def run_ats_gapfill(cfg: dict, seen_companies: set[str], fresh_days: int, existing_keys: set[tuple] | None = None) -> tuple[list[dict], int, int, int]:
    """Phase 2c: ATS direct fetch, gap-fill only.

    Skips slugs whose company already appears in seen_companies (built from
    Phases 1/2a/2b). existing_keys seeds the per-job dedup set so jobs already
    present in earlier phases are not re-added. Returns (new_jobs, n_skipped, n_fetched, n_added).
    """
    try:
        from ats_fetch import fetch_ats
    except ImportError:
        print("  ! ats_fetch not available — skipping Phase 2c", file=sys.stderr)
        return [], 0, 0, 0

    try:
        from jd_cache import get as cache_get, put as cache_put
    except ImportError:
        cache_get = cache_put = None  # type: ignore

    filt = cfg["filters"]
    ats_targets = cfg.get("ats_targets", {})
    results: list[dict] = []
    seen_keys: set[tuple] = set(existing_keys) if existing_keys else set()
    n_skipped = n_fetched = n_added = 0

    for ats_source, slugs in ats_targets.items():
        for slug in slugs:
            slug_name = slug.replace("-", " ").lower().strip()
            # Skip if any existing company name contains or is contained by slug_name
            if any(slug_name in c or c in slug_name for c in seen_companies):
                print(f"  · skip ats {ats_source}/{slug} (already seen)", file=sys.stderr)
                n_skipped += 1
                continue
            print(f"  · ats {ats_source}/{slug}")
            n_fetched += 1
            ats_jobs = fetch_ats(ats_source, slug)
            for job in ats_jobs:
                url = job.get("url", "")
                # Cache check: merge cached fields (preserves family/query/freshness assigned below)
                if cache_get and url:
                    cached = cache_get(url)
                    if cached:
                        job.update(cached)
                # Assign family by title keywords
                title_lower = job["title"].lower()
                if any(kw in title_lower for kw in ["product", "ai ", "tech", "program", "digital", "gtm", "revenue ops"]):
                    job["family"] = "techprod"
                else:
                    job["family"] = "stratops"
                job["query"] = f"ats:{ats_source}"
                key = (job["company"].lower(), normalise_title(job["title"]), normalise_location(job["location"]))
                if key in seen_keys:
                    continue
                if not job["description"]:
                    continue
                if not passes_seniority(job["title"], job["description"], filt["reject_seniority_keywords"]):
                    continue
                if not passes_language(job["description"], filt["reject_language_requirements"]):
                    continue
                job["freshness"] = freshness_tag(job["date_posted"], fresh_days)
                seen_keys.add(key)
                results.append(job)
                n_added += 1
                # Cache the fetched job for future runs
                if cache_put and url:
                    cache_put(url, job)

    return results, n_skipped, n_fetched, n_added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=["stratops", "techprod", "both"], default="both")
    ap.add_argument("--location", help="Restrict to a single city (must match queries.yaml)")
    ap.add_argument("--limit", type=int, help="Cap total results (for testing)")
    ap.add_argument("--test", action="store_true", help="One-call connection test")
    ap.add_argument(
        "--phase",
        choices=["all", "api", "indeed", "ats"],
        default="all",
        help="all=api+indeed+ats (default); api=JSearch only; indeed=Phase 2a JobSpy only (requires --input); ats=Phase 2c gap-fill only (requires --input)",
    )
    ap.add_argument(
        "--input",
        metavar="PATH",
        help="Path to existing raw JSON (required for --phase ats)",
    )
    args = ap.parse_args()

    cfg = load_queries()
    fresh_days = cfg["freshness"]["fresh_days"]

    # --phase indeed: JobSpy Indeed only, no API key needed
    if args.phase == "indeed":
        if not args.input:
            print("ERROR: --phase indeed requires --input <path>", file=sys.stderr)
            sys.exit(1)
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        raw_jobs = json.loads(in_path.read_text())
        existing_keys = {(j["company"].lower(), normalise_title(j["title"]), normalise_location(j.get("location") or "")) for j in raw_jobs}
        new_jobs, n_raw, n_kept = run_indeed_jobspy(cfg, existing_keys)
        if new_jobs:
            raw_jobs.extend(new_jobs)
            in_path.write_text(json.dumps(raw_jobs, indent=2, ensure_ascii=False))
        print(f"Phase 2a (Indeed JobSpy): {len(cfg['queries']['stratops']) + len(cfg['queries']['techprod'])} queries × {len(cfg['locations'])} cities, {n_raw} raw → {n_kept} kept.")
        print(f"Raw long list updated: {in_path}")
        return

    # --phase ats: gap-fill only, no API key needed
    if args.phase == "ats":
        if not args.input:
            print("ERROR: --phase ats requires --input <path>", file=sys.stderr)
            sys.exit(1)
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        raw_jobs: list[dict] = json.loads(in_path.read_text())
        seen_companies = {j["company"].lower().strip() for j in raw_jobs}
        existing_keys = {(j["company"].lower(), normalise_title(j["title"]), normalise_location(j.get("location") or "")) for j in raw_jobs}
        new_jobs, n_skipped, n_fetched, n_added = run_ats_gapfill(cfg, seen_companies, fresh_days, existing_keys)
        if new_jobs:
            raw_jobs.extend(new_jobs)
            in_path.write_text(json.dumps(raw_jobs, indent=2, ensure_ascii=False))
        print(f"Phase 2c: skipped {n_skipped} slugs, fetched {n_fetched}, added {n_added} after dedup.")
        print(f"Raw long list updated: {in_path}")
        return

    # --phase api: JSearch only, skip Phase 2c ATS gap-fill
    # (handled below by skipping the args.phase == "all" block)

    env = load_env()
    api_key = env.get("RAPIDAPI_KEY") or os.environ.get("RAPIDAPI_KEY")
    if not api_key:
        print("ERROR: RAPIDAPI_KEY not found.\n  Add it to .env at the project root: RAPIDAPI_KEY=your_key", file=sys.stderr)
        sys.exit(1)

    if args.test:
        print("Connection test: querying 'chief of staff' in London...")
        raw = jsearch_call("chief of staff", "London", "GB", api_key)
        if raw:
            print(f"OK — got {len(raw)} jobs. First: {raw[0].get('job_title')} at {raw[0].get('employer_name')}")
        else:
            print("No jobs returned. Either the API key is invalid, the free tier is exhausted, or no results matched.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    families = ["stratops", "techprod"] if args.family == "both" else [args.family]
    all_results: list[dict] = []
    shared_seen: set[tuple] = set()
    for fam in families:
        print(f"\n=== {fam.upper()} ===")
        all_results.extend(run_search(fam, args.location, args.limit, api_key, cfg, seen=shared_seen))

    # Phase 2a Indeed JobSpy (only when running full pipeline; skip for --phase api)
    if args.phase == "all":
        existing_keys_indeed = {(j["company"].lower(), normalise_title(j["title"]), normalise_location(j.get("location") or "")) for j in all_results}
        indeed_jobs, n_indeed_raw, n_indeed_kept = run_indeed_jobspy(cfg, existing_keys_indeed)
        all_results.extend(indeed_jobs)
        print(f"Phase 2a (Indeed JobSpy): {len(cfg['queries']['stratops']) + len(cfg['queries']['techprod'])} queries × {len(cfg['locations'])} cities, {n_indeed_raw} raw → {n_indeed_kept} kept.")

    # Phase 2c ATS gap-fill (only when running full pipeline; skip for --phase api)
    if args.phase == "all":
        seen_companies = {j["company"].lower().strip() for j in all_results}
        existing_keys = {(j["company"].lower(), normalise_title(j["title"]), normalise_location(j.get("location") or "")) for j in all_results}
        new_jobs, n_skipped, n_fetched, n_added = run_ats_gapfill(cfg, seen_companies, fresh_days, existing_keys)
        all_results.extend(new_jobs)
        print(f"Phase 2c: skipped {n_skipped} slugs, fetched {n_fetched}, added {n_added} after dedup.")

    for job in all_results:
        if "freshness" not in job:
            job["freshness"] = freshness_tag(job.get("date_posted"), fresh_days)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_path = OUTPUT_DIR / f"_raw_{timestamp}.json"
    out_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))

    fresh = sum(1 for j in all_results if j["freshness"] == "fresh")
    stale = sum(1 for j in all_results if j["freshness"] == "stale")
    unknown = sum(1 for j in all_results if j["freshness"] == "unknown")
    print(f"\nTotal: {len(all_results)} jobs  |  fresh: {fresh}  stale: {stale}  unknown: {unknown}")
    print(f"Raw long list: {out_path}")


if __name__ == "__main__":
    main()
