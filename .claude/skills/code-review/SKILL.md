# Code Review Skill

## Triggers

Invoke this skill when the user says any of:
- "review and improve code"
- "review code"
- "code review"
- "audit the code"
- "check for bugs"

---

## What this skill does

Performs a structured review of the entire Job Match Agent codebase and reports findings grouped by severity. On user approval, applies fixes.

---

## Files to review

Read all of the following before producing any output:

**Python source**
- `.claude/skills/job-search/search.py`
- `.claude/skills/job-search/ats_fetch.py`
- `.claude/skills/job-search/jd_cache.py`
- `.claude/skills/job-match/score.py`

**Config & data**
- `.claude/skills/job-search/queries.yaml`

**Skill definitions**
- `.claude/skills/job-search/SKILL.md`
- `.claude/skills/job-match/SKILL.md`
- `.claude/skills/cv-reader/SKILL.md`
- `.claude/skills/code-review/SKILL.md`

**Project instructions**
- `CLAUDE.md`

---

## Review checklist

For each file, check the following categories:

### Bugs
- Filter logic errors (seniority, location, salary, language filters applied to wrong fields)
- Dedup key correctness (are keys unique enough to catch real duplicates?)
- Dead code paths (unreachable branches, silently ignored config entries)
- Off-by-one or type errors in data transformations
- Docstring / comment accuracy (does stated behaviour match actual code?)

### Config consistency
- Are all ATS targets in `queries.yaml` actually supported in `ats_fetch.py`?
- Do reject keywords in `queries.yaml` contradict queries in the same file?
- Are CLAUDE.md hard constraints faithfully implemented in code?

### Improvement opportunities
- Hardcoded values that should be config (e.g. FX rates, thresholds)
- Unnecessary duplicate work (e.g. checking the same URL twice)
- Fragile parsing that works today but could break on minor YAML changes

### Nits
- Misleading variable names
- Stale comments

---

## Output format

Produce a report with three sections:

```
## Bugs  (must fix)
[n] <File>:<line> — <short title>
    Problem: <what is wrong>
    Fix: <specific change to make>

## Improvements  (should fix)
[n] <File>:<line> — <short title>
    Problem: <what is wrong>
    Fix: <specific change to make>

## Nits  (optional)
[n] <File>:<line> — <short title>
    Problem: <what is wrong>
    Fix: <specific change to make>
```

After the report, ask: **"Apply fixes? Reply 'all', 'bugs only', a list of numbers, or 'no'."**

---

## Applying fixes

- For each approved fix, use the Edit tool to make the minimal targeted change.
- Do not refactor surrounding code or add comments beyond what the fix requires.
- After all edits, summarise what was changed (file + line range only — no prose).
