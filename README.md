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
1. CV summary prep
Generate or refresh structured CV summaries per family (for example `stratops` and `techprod`).

2. Search phase
Run query sets against job sources, deduplicate results, and keep only medium-to-senior roles in target geographies.

3. Match phase
Extract key requirements from each job description and score them against the relevant CV summary.

4. Output phase
Write scored results to timestamped files (CSV/JSON), then review top-ranked roles first.

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
