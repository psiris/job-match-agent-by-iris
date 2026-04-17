# Job Match Agent (by Iris)

This repository is a sanitized public version of the Job Match Agent project.

## What This Project Attempts To Do
The project helps shortlist high-fit jobs by combining structured search with CV-aware scoring.

At a high level, it aims to:
1. Search relevant jobs across selected target locations.
2. Filter out poor-fit roles using hard constraints (location, language, seniority, and salary where stated).
3. Score each job against the candidate's CV summary.
4. Produce a ranked output that is practical to review and apply from.

## Workflow
### Input
1. CV source files: your PDFs in `latest_cv/`.
2. Search configuration: role-family queries plus filters.

### Process
1. CV summary prep <br>
Read each family CV and generate a normalized summary used for matching.

2. Search across various platforms <br>
  A. JSearch (RapidAPI; aggregating LinkedIn and similar boards) <br>
  B. ATS/company career pages via web search <br>
  C. Targeted recruiter/specialist hiring pages from the user-defined "watchlist"

  The search layer deduplicates postings across sources before the next step.

3. Match phase <br>
For each job description, extract the top required skills, score against the relevant CV summary, and produce an overall fit verdict.

4. Assessment phase <br>
Apply freshness logic (e.g., jobs less than 7 days old) where available, and rank jobs so the highest-fit and most actionable opportunities are surfaced first.

### Output
1. Primary output: timestamped CSV in `output/jobs_YYYY-MM-DD_HHMM.csv`
2. Key fields: job metadata (title, company, location, source URL), fit verdict (very strong, strong, ok, poor), freshness indicator 
3. Supporting artifacts: raw/scored JSON snapshots and URL issue logs for diagnostics.

## Setup
1. Supply your own CV in a format compatible with the scripts.
2. Provide your own API keys in a local `.env` file (never commit it).
3. Install dependencies using `pip install -r requirements.txt` (if available).

## Typical Usage
1. Create CV summaries for the role family you want to run.
2. Execute job search.
3. Execute job match/scoring.
4. Open the generated CSV in `output/` and prioritize top matches.

## Note
Personal data, keys, local machine details, chat transcripts, prior run outputs, and private config have been removed from this version.
