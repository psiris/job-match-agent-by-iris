---
name: job-match
description: Score candidate jobs against the user's CV summary. Extracts the top 8-10 required skills from each JD, scores each against the relevant cv_summary file, rolls up to an overall verdict, applies the freshness rule, and produces the final CSV. Use after job-search, or when the user says "match jobs" or "score jobs".
---

# Job Match

Turn the raw long list (`output/_raw_<timestamp>.json`) into a ranked CSV (`output/jobs_<timestamp>.csv`).

## Pipeline

### 1. Load inputs

- Most recent `output/_raw_<timestamp>.json` (or whichever the user names).
- `cv_summary/stratops.md` — for jobs where `family == "stratops"`.
- `cv_summary/techprod.md` — for jobs where `family == "techprod"`.

### 2. Per-job scoring (this is the LLM-heavy step)

For each job in the raw list:

**a. Extract the top 8–10 required skills from the JD.** Read `description`. Identify and rank from most → least critical:
- Must-have skills (explicitly stated requirements, qualifications)
- Nice-to-have / implied skills (read between the lines)
- Soft skills and traits (leadership, ownership, collaboration, ambiguity tolerance)
- Seniority and scope signals (IC vs lead, regional vs global, transformation vs strategy vs product)

**b. Score each skill against the relevant CV summary** as one of:
- **VS** (Very Strong) — direct, recent, deep evidence in CV
- **S** (Strong) — clear evidence, perhaps adjacent or slightly older
- **OK** — partial / inferred match, transferable
- **Poor** — no evidence

**c. Roll up to an overall verdict:**
- **Very Strong** — ≥80% of skills are VS or S, no critical Poor
- **Strong** — 60–79% VS/S, no more than one critical Poor
- **OK** — 40–59% VS/S
- **Poor** — <40% VS/S, OR a critical must-have is Poor

**d. Apply the freshness rule:**
- `fresh` (≤7 days) → keep if verdict is OK or better
- `stale` (>7 days) → keep only if verdict is Strong or Very Strong
- `unknown` → keep only if verdict is Strong or Very Strong

**e. Append to the job dict:**
```json
{
  "match_verdict": "Strong",
  "skills_total": 10,
  "skills_strong": 7,
  "match_notes": "1-line on the strongest fit and the biggest gap"  // optional but useful
}
```

### 3. Write scored intermediate file

Save the scored list (with the dropped jobs filtered out) to `output/_scored_<timestamp>.json`.

### 4. Hand off to score.py

Run:

```bash
python .claude/skills/job-match/score.py --scored output/_scored_<timestamp>.json --open
```

`score.py` will:
- Sort by match (Very Strong → Poor; ties broken by skill-strong count, then freshness)
- Write `output/jobs_<timestamp>.csv` with the 7 required columns
- Run a parallel HEAD check on every JD or Application URL; write any broken ones to `_url_issues_<timestamp>.txt`
- Print the fresh/stale/unknown breakdown and the top-10 preview
- Open the CSV

## Token discipline

This is the most expensive skill in the project. Mitigations:

- **Truncate JDs** to the first 3000 chars when scoring (description field is already capped at 4000 in search.py — that's the upper bound).
- **Score in batches.** Process 5–10 jobs per LLM turn, write the partial scored file, continue. Don't try to score 100 jobs in one giant turn.
- **Cache.** If a `_raw_<timestamp>.json` has already been scored (sibling `_scored_<timestamp>.json` exists), do NOT re-score — skip straight to step 4.
- **Skip obvious non-matches early.** If the title clearly doesn't fit (e.g. "Senior Backend Engineer"), score it Poor without deep JD analysis.

## Reporting

After `score.py` finishes, summarise to chat:

- Total searched (from `_raw`), total kept after match-filter (in CSV).
- Fresh / stale / unknown breakdown.
- Top 10 by match verdict.
- Any URL issues to flag.
- Path to the CSV (already opened).

## Step 5 — Query optimization: subset detection and new pattern discovery

After reporting, perform two scans of the `_scored_<timestamp>.json` and `_raw_<timestamp>.json` to optimize queries.yaml:

### 5a. Detect and suggest removal of subset queries (improves API efficiency)

For each seed query in `queries.yaml`, check if its results are substantially redundant with other queries:

Rules:
- **Data source:** For each query in `queries.yaml`, collect all jobs in `_raw_<timestamp>.json` where `job["query"]` matches that seed query (case-insensitive).
- **Normalise for comparison:** Apply to both query strings and job titles: lowercase, strip seniority prefixes ("Senior", "Interim", "Head of", "VP", etc.), trim whitespace.
- **Subset definition:** Query A is a **subset of query B** if ≥85% (or a threshold you specify: 85%, 90%, 95%) of A's normalised titles also appear in B's results.
- **Report only if meaningful:** Exclude trivial synonyms (e.g. "BizOps Manager" vs "bizops lead"). Only flag subsets that represent distinct searches made redundant.
- **Group by family** (`stratops` / `techprod`).
- **Cap at 5 suggestions per family.**

Output format (print to chat, do not auto-edit):
```
Subset queries (>85% coverage — candidates for removal):
  stratops: "Operations Strategy Manager" (86% of results already covered by "strategy and operations manager")
            "Asset Management operations strategy" (92% overlap with "Investment operations")
  techprod: "Tech operations" (88% coverage by "product manager" + "tech product manager" combined)
Remove any of these from queries.yaml? I'll update it on your say-so.
```

If no subsets detected (or coverage <85%), skip this section silently.

### 5b. New title pattern suggestions (scan all results for coverage optimization)

Scan ALL job titles in `_scored_<timestamp>.json` to find patterns that don't closely map to any existing seed query in `queries.yaml`. This helps identify valuable new searches that would improve result coverage.

Rules:
- Normalise titles (lowercase, strip seniority prefixes like "Senior", "Interim", "Head of") before comparing.
- Only flag a title if it represents a meaningfully different role type — not just a synonym (e.g. "BizOps Lead" ≈ "bizops manager", don't flag it).
- Group suggestions by family (`stratops` / `techprod`).
- Cap at 5 suggestions per family.

Output format (print to chat, do not auto-edit):
```
New title patterns worth adding to queries.yaml:
  stratops: "portfolio operations manager", "commercial excellence lead"
  techprod:  "AI solutions lead"
Add any of these? I'll update queries.yaml on your say-so.
```

If no new patterns found, skip this section silently.
