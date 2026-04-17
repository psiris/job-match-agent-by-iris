#!/usr/bin/env python3
"""
score.py — CSV writer, URL health checker, and summary printer.

Reads one input:
  A scored list passed via --scored <path>: a JSON array where each item is the
  raw job dict plus three extra keys:
     - "match_verdict": "Very Strong" | "Strong" | "OK" | "Poor"
     - "skills_total": int (e.g. 10)
     - "skills_strong": int (e.g. 9)  # count of VS or S among the top skills
  The job-match skill (Claude) produces this scored file before calling score.py.

Usage:
  python score.py --scored output/_scored_2026-04-16_1430.json
  python score.py --scored ... --no-url-check         # skip URL HEAD checks
  python score.py --scored ... --open                 # `open` the resulting CSV (mac)

Output:
  - output/jobs_<timestamp>.csv  (the deliverable, sorted by match)
  - output/_url_issues_<timestamp>.txt  (only if any URLs are broken)
  - Stdout: total / fresh / stale / unknown breakdown + top-10 preview.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "output"

VERDICT_RANK = {"Very Strong": 0, "Strong": 1, "OK": 2, "Poor": 3}
URL_TIMEOUT = 8
URL_WORKERS = 8


def url_is_alive(url: str) -> bool:
    if not url:
        return False
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=URL_TIMEOUT) as resp:
            return 200 <= resp.status < 400
    except Exception:
        # Some servers reject HEAD — try GET with a tiny range.
        try:
            req2 = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-512"}
            )
            with urllib.request.urlopen(req2, timeout=URL_TIMEOUT) as resp:
                return 200 <= resp.status < 400
        except Exception:
            return False


def check_urls(jobs: list[dict]) -> list[dict]:
    """Return list of {idx, label, url} for broken URLs."""
    tasks = []
    for i, j in enumerate(jobs):
        for label in ("url",):
            url = j.get(label)
            if url:
                tasks.append((i, label, url))
    broken = []
    with ThreadPoolExecutor(max_workers=URL_WORKERS) as pool:
        future_to_task = {pool.submit(url_is_alive, t[2]): t for t in tasks}
        for fut in as_completed(future_to_task):
            i, label, url = future_to_task[fut]
            try:
                if not fut.result():
                    broken.append({"idx": i, "label": label, "url": url})
            except Exception:
                broken.append({"idx": i, "label": label, "url": url})
    return broken


def sort_key(job: dict):
    rank = VERDICT_RANK.get(job.get("match_verdict", "Poor"), 99)
    strong = -int(job.get("skills_strong", 0))
    fresh_priority = {"fresh": 0, "stale": 1, "unknown": 2}.get(job.get("freshness", "unknown"), 9)
    return (rank, strong, fresh_priority)


def write_csv(jobs: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "Company", "Location", "Role Title", "Post Date",
            "JD URL", "Match Result",
        ])
        for j in jobs:
            verdict = j.get("match_verdict", "Poor")
            ss = j.get("skills_strong", 0)
            st = j.get("skills_total", 0)
            match_result = f"{verdict} ({ss}/{st} VS·S)" if st else verdict
            w.writerow([
                j.get("company", ""),
                j.get("location", ""),
                j.get("title", ""),
                (j.get("date_posted") or "")[:10],
                j.get("url", ""),
                match_result,
            ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", required=True, help="Path to the scored JSON file")
    ap.add_argument("--no-url-check", action="store_true")
    ap.add_argument("--open", action="store_true", help="open the CSV after writing (macOS)")
    args = ap.parse_args()

    scored_path = Path(args.scored)
    if not scored_path.exists():
        print(f"ERROR: scored file not found: {scored_path}", file=sys.stderr)
        sys.exit(1)

    jobs = json.loads(scored_path.read_text())
    if not isinstance(jobs, list):
        print("ERROR: scored file must be a JSON array.", file=sys.stderr)
        sys.exit(1)

    jobs.sort(key=sort_key)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_path = OUTPUT_DIR / f"jobs_{timestamp}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(jobs, csv_path)

    # URL health
    if not args.no_url_check:
        n_urls = sum(1 for j in jobs if j.get("url"))
        print(f"Checking {n_urls} URLs...")
        broken = check_urls(jobs)
        if broken:
            issues_path = OUTPUT_DIR / f"_url_issues_{timestamp}.txt"
            with issues_path.open("w") as f:
                for b in broken:
                    j = jobs[b["idx"]]
                    f.write(f"{j.get('company')} | {j.get('title')} | {b['label']}: {b['url']}\n")
            print(f"  ! {len(broken)} broken URL(s) — see {issues_path}")
        else:
            print("  ✓ All URLs alive.")

    # Summary — single pass for freshness counts
    fresh = stale = unknown = 0
    for j in jobs:
        f = j.get("freshness")
        if f == "fresh":
            fresh += 1
        elif f == "stale":
            stale += 1
        else:
            unknown += 1
    total = len(jobs)
    pct = lambda n: f"{(100*n/total):.0f}%" if total else "0%"
    print(f"\nTotal: {total} jobs  |  fresh: {fresh} ({pct(fresh)})  stale: {stale} ({pct(stale)})  unknown: {unknown} ({pct(unknown)})")

    print("\nTop 10 by match:")
    for j in jobs[:10]:
        v = j.get("match_verdict", "?")
        ss = j.get("skills_strong", 0); st = j.get("skills_total", 0)
        print(f"  [{v:11s} {ss}/{st}]  {j.get('company','?'):25s}  {j.get('title','?')[:55]}  ({j.get('location','')[:25]})")

    print(f"\nCSV: {csv_path}")

    if args.open:
        import subprocess
        subprocess.run(["open", str(csv_path)], check=False)


if __name__ == "__main__":
    main()
