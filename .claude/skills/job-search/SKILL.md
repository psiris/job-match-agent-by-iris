---
name: job-search
description: Search medium-to-senior Strategy/Operations and AI/Tech Product roles in London, Dubai, Abu Dhabi, Zurich, and Amsterdam. Combines a structured job-board API (JSearch) with WebSearch on ATS boards and recruiter sites. Use when the user asks to find, search, or look for jobs.
---

# Job Search

Hybrid search across (1) JSearch API for the bulk of board listings and (2) `WebSearch` for ATS boards and recruiter sites the API misses. Outputs a normalised JSON long list at `output/_raw_<timestamp>.json` for the job-match skill to consume.

## Pre-flight

Before running:

1. Confirm both `cv_summary/stratops.md` and `cv_summary/techprod.md` exist — if not, follow the rule in CLAUDE.md (invoke `cv-reader` for both, OR ask the user which family to run if only one is present).
2. Confirm `.env` exists with `RAPIDAPI_KEY=...`. If missing, tell the user we'll need to set it up before this can run (see API setup section in CLAUDE.md / project plan).

## Efficiency rubric (Phase 2)

Every edit to Phase 2 is judged on two axes: **Efficient** = less token usage and fewer API requests; **Quality** = more distinct job postings found.

## Two-phase pipeline

### Phase 1 — API search (cheap, structured)

Run `search.py`:

```bash
python .claude/skills/job-search/search.py --family both
```

Optional flags:
- `--family stratops` or `--family techprod` — single family
- `--location London` — single city
- `--limit 5` — cap total results (testing only)
- `--test` — one-call connection test

The script handles seniority/salary/language/dedup filtering and freshness tagging at source. It writes `output/_raw_<timestamp>.json`.

### Phase 2 — Web augmentation (always run)

Always run Phase 2 after Phase 1, regardless of how many results Phase 1 returned.

#### 2a — Indeed (JobSpy, always run)

```
python .claude/skills/job-search/search.py --phase indeed \
  --input output/_raw_<ts>.json
```

Scrapes Indeed's mobile-app API via `python-jobspy` — no MCP, no Cloudflare, real pagination (`results_wanted=100` per query/city). Applies the same filters as Phase 1, dedups against prior phases, rewrites the raw JSON in place.

Install once: `/opt/homebrew/bin/python3.12 -m pip install python-jobspy pyyaml --break-system-packages` (requires Python 3.10+).

#### 2b — ATS boards + recruiter sites (WebSearch, always run)

Use `WebSearch` for market-wide title-scoped discovery. At runtime, read `queries.yaml` for the current `queries:<family>` list and pick 3–4 representative titles per family per ATS — do **not** hardcode a fixed list here. Substitute each target city from `queries.yaml` `locations:`.

**Query patterns (fill `<query>` and `<city>` from `queries.yaml` at runtime):**
```
site:boards.greenhouse.io "<query>" "<city>"
site:jobs.lever.co "<query>" "<city>"
site:jobs.ashbyhq.com "<query>" "<city>"
site:linkedin.com/jobs "<query>" "<city>"
site:per-people.com "<query>"
site:michaelpage.co.uk "<query>" "<city>"
site:michaelpage.ae "<query>" "<city>"
site:bayt.com "<query>" "<city>"
site:robertwalters.co.uk "<query>" "<city>"
```

Run ATS `site:` queries for both families. Run recruiter-site queries for both families. The `reject_seniority_keywords` filter handles juniors at post-filter — no need to encode seniority in the query string.

For each promising result:

1. Check the dedup set first (see Pre-fetch dedup rule below) — skip WebFetch if `(company, normalised_title, city)` is already seen.
2. Check the JD cache (`jd_cache.py`) — if the URL was fetched within 7 days, reuse the cached record and skip WebFetch.
3. Otherwise `WebFetch` the JD page and extract: title, company, location, posted date, salary (if present), apply URL, full JD text. **Cap description at 4000 chars when writing to the raw JSON.**
4. Apply the same filters as Phase 1.
5. Dedup against all prior results on `(company, normalised_title, location)`.
6. Append with `"source": "web"`.

#### 2c — ATS direct fetch (always run; gap-fill only)

Only for slugs whose company does NOT already appear from Phases 1/2a/2b.

Invocation:
```
python .claude/skills/job-search/search.py --phase ats --input output/_raw_<ts>.json
```

The script loads the raw JSON, builds `seen_companies` from it, and skips any slug whose company name is already present. It logs `· skip ats <source>/<slug> (already seen)` for skipped slugs and rewrites the raw JSON in place after appending gap-fill results.

The current `ats_targets` list in `queries.yaml` is deliberately tiny (`anthropic`, `scale-ai`) while the gap-fill plumbing is validated. Expand only for companies you expect WebSearch to miss.

Reporting: print `Phase 2c: skipped N slugs, fetched M, added K after dedup.`

**Token discipline — pre-fetch dedup (applies to 2b):**

Before any `WebFetch` call, perform these checks in order:

1. **Snippet dedup:** Extract `(company, normalised_title, city)` from the search-result snippet (the title/company/location are already in-context from `WebSearch` results — no extra fetch needed). Normalise title by lowercasing and collapsing whitespace/punctuation. If this tuple is already in the dedup set (which is seeded from Phases 1/2a results at the start of Phase 2b), **skip the fetch**. The dedup set is maintained in-context across the entire Phase 2 run.
2. **Cache check:** Run `python .claude/skills/job-search/jd_cache.py` equivalently — call `get(url)` from `jd_cache.py`. If a non-null record is returned, use it directly. **Do not call `WebFetch`.**
3. Only if both checks miss: perform the fetch, then call `put(url, job)` to cache the result for future runs.

WebSearch is still required to discover URLs — snippet dedup and caching only short-circuit the *body fetch*, not the discovery step.

## Auto-chain

After writing the raw long list, immediately invoke the **job-match** skill on the same file. Do not stop and ask — the user wants the CSV.

## Reporting

Print to chat (concise):
- Phase 1 (API): raw count (#) → after-filter count (#).
- Phase 2a (Indeed JobSpy): searches, raw (#) → after-filter count (#).
- Phase 2b (WebSearch ATS + recruiter): raw count (#) → after-filter count (#).
- Phase 2c (ATS gap-fill): skipped N slugs, fetched M, added K after dedup.
- Combined total after dedup.
- Fresh / stale / unknown breakdown.
- Path to `_raw_<timestamp>.json`.
- "Handing off to job-match…"

## Edits & extension

- New role keywords → edit `queries.yaml` under `queries:`.
- New ATS company → add to `queries.yaml` `ats_targets:`.
- New filter rule → edit `queries.yaml` `filters:` and the corresponding check in `search.py`.
- New location → edit `queries.yaml` `locations:` (also confirm it's in CLAUDE.md hard constraints).
