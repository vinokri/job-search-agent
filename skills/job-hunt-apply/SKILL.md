---
name: job-hunt-apply
description: Shortlist, review, and prepare job applications for target companies based on a candidate profile. Use when Codex needs to compare a LinkedIn/resume-derived profile against openings at NVIDIA, Databricks, Snowflake, Google, or similar employers; scan official career sites; rank roles by fit; present a human approval queue; and only submit applications after explicit user approval.
---

# Job Hunt Apply

## Overview

Use this skill to run a controlled job-search workflow: build a structured candidate profile, collect live openings from official career sites, score the openings against the profile, and manage an approval gate before any application is submitted.

Keep the process auditable. Do not auto-apply to any role until the user has explicitly approved that exact job in the review queue.

## Workflow

### 1. Build the candidate profile

Start from the user's LinkedIn profile, resume, and any explicit preferences.

Populate [`assets/profile.template.json`](./assets/profile.template.json). Focus on:

- target job titles and excluded titles
- preferred locations and remote preference
- must-have and strong skills
- level/seniority signals
- work authorization and sponsorship constraints
- resume path, LinkedIn URL, and reusable application notes

If the LinkedIn profile is only available as free text, summarize it into the JSON contract instead of trying to scrape LinkedIn directly.

### 2. Collect openings from official career sites

Use the employer's official careers site, not third-party aggregators, unless the user explicitly asks otherwise.

For this user, start with:

- NVIDIA: [references/company-targets.md](./references/company-targets.md)
- Databricks: [references/company-targets.md](./references/company-targets.md)
- Snowflake: [references/company-targets.md](./references/company-targets.md)
- Google: [references/company-targets.md](./references/company-targets.md)

Normalize the results into [`assets/jobs.template.json`](./assets/jobs.template.json). Capture:

- stable job ID
- company
- title
- job URL
- location
- remote/hybrid/on-site signal
- employment type
- posted date if visible
- short description text
- extracted skills/keywords

If a site is dynamic and requires browser automation, browse it live and then store normalized records locally before scoring.

### 3. Score and shortlist

Run:

```bash
python3 scripts/shortlist_jobs.py \
  --profile assets/profile.template.json \
  --jobs assets/jobs.template.json \
  --out shortlist.json \
  --markdown shortlist.md
```

The scorer uses deterministic heuristics for title fit, location fit, skill overlap, seniority alignment, sponsorship mismatch, and company preference.

Use the JSON output for machine-readable follow-up steps and the Markdown output for human review.

### 4. Create and manage the review queue

Seed the queue from the shortlist:

```bash
python3 scripts/review_queue.py seed \
  --shortlist shortlist.json \
  --out review-queue.json
```

Mark each role as `approved`, `rejected`, or `hold`:

```bash
python3 scripts/review_queue.py set-status \
  --queue review-queue.json \
  --job-id google-123 \
  --status approved \
  --notes "Good fit for data platform background"
```

Export only approved roles:

```bash
python3 scripts/review_queue.py export-approved \
  --queue review-queue.json \
  --out approved-jobs.json
```

### 5. Prepare applications

For each approved role:

- tailor the resume bullets to the job description
- draft a concise role-specific note or cover letter only if the employer asks for one
- confirm application answers that need human judgment
- keep a record of every field filled and every uploaded file

Do not invent years of experience, visa status, education details, compensation history, or security-clearance answers.

### 6. Submit only after explicit user approval

Before submission, verify all of the following:

- the job is marked `approved` in the review queue
- resume path and required documents are present
- form answers match the user's real background
- the user has explicitly said to submit that application

If any of those checks fail, stop and ask for clarification rather than guessing.

## Data contracts

Read [`references/data-contracts.md`](./references/data-contracts.md) before editing the profile, jobs, or queue files. Keep field names stable so the scripts continue to work.

## Operational rules

- Prefer official career pages over job boards.
- Re-check live job pages immediately before submission in case a role has closed or changed.
- Preserve exact job URLs and job IDs for auditability.
- Track one queue entry per job ID.
- Keep human approval as a hard gate. Shortlisting can be automated; submission cannot be assumed.
- If a company form blocks automation, stop after preparing the application package and hand control back to the user.

## Resources

- `scripts/shortlist_jobs.py`: score and rank openings against the candidate profile
- `scripts/review_queue.py`: maintain approval state and export approved jobs
- `references/data-contracts.md`: schema for profile, job, and queue files
- `references/company-targets.md`: target companies and official career entry points
- `assets/profile.template.json`: starter profile contract
- `assets/jobs.template.json`: normalized job-list input contract
- `assets/review-queue.template.json`: starter approval queue contract
