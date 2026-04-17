---
name: cv-reader
description: Read a CV PDF from latest_cv/ and produce a structured summary in cv_summary/. Use when the user asks to summarise, read, or refresh their CV, or when a required cv_summary/{family}.md file is missing before a job search.
---

# CV Reader

Convert PDFs in `latest_cv/` into reusable structured summaries that feed the matching workflow.

## When to run

- User asks to "summarise my CV", "read CV", "refresh my profile", or similar.
- Orchestrator (CLAUDE.md) detects a missing `cv_summary/{family}.md` before a job search.
- **Skip if the target summary already exists** — re-running burns tokens for no gain. Only re-run if the user explicitly asks to refresh.

## Inputs

- PDFs in `latest_cv/`. Match by case-insensitive substring:
  - `stratops` → StratOps family
  - `techprod` → TechProd family
- File names contain dates and other text (e.g. `202604 Iris Jiang StratOps.pdf`) — use substring matching, not exact names.

## Process

For each family that needs a summary:

1. **Find the PDF.** Use `Glob` with `latest_cv/*.pdf`, then filter by substring. If none found, stop and tell the user which family's PDF is missing.
2. **Read the PDF.** Use the `Read` tool on the PDF path. Read the full document.
3. **Write the summary** to `cv_summary/{family}.md` using the template below.
4. **Self-check.** Re-read the PDF (or scan your own working memory of it) and produce a delta list:
   - Roles, companies, dates, skills, achievements present in the PDF but missing from your summary.
   - Anything in your summary that is NOT supported by the PDF (hallucination check).
   If the delta is non-empty, edit the summary file and re-check. Loop until clean (max 3 iterations to avoid waste).
5. **Report.** Tell the user: file path written, word count, and "self-check: clean" or list any issues that survived 3 iterations.

## Summary template

```markdown
# {Family} CV Summary
_Source: {pdf filename} · Generated: {YYYY-MM-DD}_

## Headline
One sentence: current role, years experience, primary domain.

## Experience
For each role (most recent first):
- **{Title} — {Company}** ({start}–{end}, {location})
  - Scope: team size, budget, geography
  - 3–5 bullet achievements (quantified where possible)

## Skills
- **Technical:** tools, languages, platforms (e.g. SQL, Python, Tableau, Salesforce, Looker)
- **Functional:** strategy, ops, finance modelling, GTM, transformation, project mgmt, stakeholder mgmt
- **Domain expertise:** specific frameworks, methodologies

## Vertical & domain exposure
List industries / sectors with depth indicator: deep / moderate / light.

## Strengths
3–5 differentiators that would make this candidate stand out for {Family} roles.

## Seniority signals
- Years of experience: {N}
- Largest team led: {N}
- Largest budget owned: {currency + amount}
- Geographic scope: {local / regional / global}
- Reporting level: {individual contributor / lead / manager-of-managers}
```

## Output expectations

- One file per family in `cv_summary/`. Lowercase, no spaces: `stratops.md`, `techprod.md`.
- Aim for 400–800 words per summary — comprehensive enough for matching, lean enough to stay cheap to load.
- No marketing fluff. Concrete bullets only.
