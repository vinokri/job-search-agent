# Job Search Agent

This repository contains a GitHub-ready local project for finding relevant jobs at NVIDIA, Databricks, Snowflake, and Google, ranking them against your profile, and stopping at a human approval gate before any application is submitted.

The current implementation is intentionally conservative:

- it builds a structured candidate profile from your LinkedIn URL and resume path
- it normalizes job records from official careers pages
- it scores and shortlists jobs against your profile
- it manages an approval queue so automation stops before submission

Automatic submission is intentionally out of scope in this first version because you asked the workflow to stop at approval.

## Profile seeded for this project

- Candidate: Vinodh Krishnamoorthy
- LinkedIn: `https://www.linkedin.com/in/vinodh-krishnamoorthy-4859a999/`
- Resume path: `/Users/vinodhkrishnamoorthy/Downloads/vinodh-krishnamoorthy-standard-resume (12) (1).pdf`
- Target companies: NVIDIA, Databricks, Snowflake, Google

Current limitation:

- The resume file path is wired into the project, but the PDF content was not auto-parsed because this environment does not currently have a PDF extraction library installed.
- The LinkedIn URL is stored in the profile, but this repository does not scrape LinkedIn directly.

## Project structure

```text
.
├── README.md
├── pyproject.toml
├── .gitignore
├── data/
│   ├── approved-jobs.json
│   ├── jobs.sample.json
│   ├── profile.json
│   ├── review-queue.json
│   ├── shortlist.json
│   └── shortlist.md
├── src/job_agent/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── models.py
│   ├── queue.py
│   └── shortlist.py
└── tests/
    └── test_smoke.py
```

## What has been done

1. Created a reusable skill for the broader job-hunt workflow under [`skills/job-hunt-apply`](/Users/vinodhkrishnamoorthy/Documents/New%20project/skills/job-hunt-apply).
2. Created this repository structure for a standalone GitHub project.
3. Seeded your profile data with your LinkedIn URL, resume path, and target companies.
4. Left `experience` empty in `data/profile.json` so it can be filled accurately from your resume or manual edits rather than inventing details.
5. Implemented deterministic job scoring based on title fit, location fit, skill overlap, remote preference, and seniority signals.
6. Implemented a review queue with `pending`, `approved`, `rejected`, and `hold` states.
7. Added CLI commands so the workflow is repeatable and easy to document.
8. Added sample data and generated sample shortlist outputs.
9. Added a smoke test to verify the main CLI flow.

## Workflow

### 1. Update your profile

Edit `data/profile.json` and add any missing experience, skills, location preferences, or sponsorship constraints.

### 2. Collect jobs from official career sites

Normalize jobs into `data/jobs.sample.json` or another JSON file using this shape:

```json
[
  {
    "id": "nvidia-123",
    "company": "NVIDIA",
    "title": "Senior Software Engineer",
    "url": "https://example.com/job",
    "location": "Santa Clara, CA, USA",
    "remote": "hybrid",
    "employment_type": "full-time",
    "posted_at": "2026-03-09",
    "description": "Role description here",
    "skills": ["python", "sql", "distributed systems"]
  }
]
```

### 3. Generate the shortlist

The `shortlist` command can now take runtime search parameters:

- up to 3 `--job-title` inputs
- up to 5 `--company` inputs

If provided, these override the profile defaults for shortlist generation and also filter jobs before scoring.

```bash
python3 -m job_agent shortlist \
  --profile data/profile.json \
  --jobs data/jobs.sample.json \
  --out data/shortlist.json \
  --markdown data/shortlist.md \
  --job-title "software engineer" \
  --job-title "data engineer" \
  --company "NVIDIA" \
  --company "Snowflake"
```

### 4. Run the end-to-end search in one command

If you want a single command that generates both the shortlist and the review queue, use `run-search`:

```bash
PYTHONPATH=src python3 -m job_agent run-search \
  --profile data/profile.json \
  --jobs data/jobs.sample.json \
  --shortlist-out data/shortlist.json \
  --queue-out data/review-queue.json \
  --markdown data/shortlist.md \
  --job-title "software engineer" \
  --job-title "data engineer" \
  --company "NVIDIA" \
  --company "Snowflake"
```

This command:

- filters the jobs by the provided titles and companies
- scores the filtered jobs
- writes the ranked shortlist
- seeds the review queue with `pending` items

### 5. Seed the approval queue manually

```bash
python3 -m job_agent seed-queue \
  --shortlist data/shortlist.json \
  --out data/review-queue.json
```

Use this only if you want to separate shortlist generation from queue creation.

### 6. Approve or reject jobs

```bash
python3 -m job_agent set-status \
  --queue data/review-queue.json \
  --job-id nvidia-123 \
  --status approved \
  --notes "Looks strong for platform and ML systems work"
```

### 7. Export only approved jobs

```bash
python3 -m job_agent export-approved \
  --queue data/review-queue.json \
  --out data/approved-jobs.json
```

At this point the automation stops. The approved list becomes the handoff point for later application preparation.

## Local development

Run the smoke test:

```bash
python3 -m unittest discover -s tests
```

## GitHub status

This repository is ready to push to GitHub, but this machine currently does not have `gh` installed and there is no remote configured. Once you provide a GitHub repo URL or install/authenticate `gh`, the local repo can be pushed directly.
