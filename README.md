# Job Match Agent (by Iris)

This repository is a sanitized public version of the Job Match Agent project.

## What This Project Attempts To Do
The project helps shortlist high-fit jobs by combining structured search with CV-aware scoring.

It is designed around two role families:
1. StratOps (strategy and operations roles such as Chief of Staff, Strategy & Operations, BizOps).
2. TechProd (product, AI product, AI transformation, and adjacent startup operations roles).

At a high level, it aims to:
1. Search relevant jobs across selected target locations.
2. Filter out poor-fit roles using hard constraints (location, language, seniority, and salary where stated).
3. Score each job against the candidate's CV summary.
4. Produce a ranked output that is practical to review and apply from.

## Workflow
### Input
1. CV source files: your PDFs in `latest_cv/`.
2. CV summaries: structured files in `cv_summary/stratops.md` and/or `cv_summary/techprod.md`.
3. Search configuration: role-family queries plus location filters.
4. Runtime secrets: API keys provided via local environment (for example `.env`) and never committed.

### Process
1. CV summary prep
Read each family CV and generate a normalized summary used for matching.

2. Search phase (full pipeline universe commitment) across multiple platforms with applied constraints
A full run searches both role families (`stratops` and `techprod`) across these source groups:
1. JSearch (RapidAPI), which aggregates roles from boards such as LinkedIn and similar job sites.
2. ATS and company-career pages discovered via web search.
3. Recruiter and specialist hiring pages where relevant.

The pipeline then applies hard filters:
1. Locations: London (GB), Dubai (AE), Abu Dhabi (AE), Zurich (CH), Amsterdam (NL).
2. Language: reject roles requiring German, French, or Italian.
3. Seniority: keep medium-to-senior roles; reject analyst/intern/associate-level and C-suite executive roles (except Chief of Staff).
4. Salary: reject roles with stated salary below 100k GBP-equivalent; keep roles where salary is not stated.

The search layer deduplicates postings across all sources before scoring.

3. Match phase
For each job description, extract the top required skills, score against the relevant CV summary, and produce an overall fit verdict.

4. Ranking and freshness
Apply freshness logic where available and rank jobs so the highest-fit and most actionable opportunities are surfaced first.

### Output
1. Primary output: timestamped CSV in `output/jobs_YYYY-MM-DD_HHMM.csv`.
2. Supporting artifacts: raw/scored JSON snapshots and URL issue logs for diagnostics.
3. Typical CSV fields include:
1. Job metadata (title, company, location, source URL).
2. Family classification (`stratops` or `techprod`).
3. Fit information (extracted requirements, per-skill scores, overall score/verdict).
4. Freshness/status indicators and notes used to prioritize review.

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
