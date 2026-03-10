# Job Search Agent

This repository contains a GitHub-ready local project for finding relevant jobs at NVIDIA, Databricks, Snowflake, and Google, ranking them against your profile, and stopping at a human approval gate before any application is submitted.

The current implementation is an orchestrated multi-agent workflow:

- `SearchJobAgent` collects live jobs, normalizes them, and builds the shortlist
- `ResumeUpdateAgent` parses a source resume, rewrites a job-specific draft, and stages a tailored file for approval
- `ApplyJobAgent` records the apply-ready packet and uses the latest approved tailored resume file
- `JobSearchOrchestrator` coordinates agent transitions, shared state, and memory
- runtime state and agent memory are stored in JSON so the UI and CLI share the same workflow state

External ATS form submission is still intentionally out of scope. The `ApplyJobAgent` records the internal apply packet and sent workflow state, but it does not submit to third-party application forms yet.

## Profile seeded for this project

- Candidate: Vinodh Krishnamoorthy
- LinkedIn: `https://www.linkedin.com/in/vinodh-krishnamoorthy-4859a999/`
- Resume path: `/Users/vinodhkrishnamoorthy/Downloads/vinodh-krishnamoorthy-standard-resume (12) (1).pdf`
- Target companies: NVIDIA, Databricks, Snowflake, Google

Current limitation:

- The LinkedIn URL is stored in the profile, but this repository does not scrape LinkedIn directly.
- Resume parsing is best-effort. Text, Markdown, HTML, and many DOCX/RTF inputs are handled well; PDF parsing uses a lightweight text-extraction fallback.
- Tailored resume output is always generated as Markdown. DOCX generation is attempted when `textutil` is available on the host.

## Project structure

```text
.
├── README.md
├── run.sh
├── pyproject.toml
├── .gitignore
├── .dockerignore
├── Dockerfile
├── data/
│   ├── approved-jobs.json
│   ├── agent-memory.json
│   ├── agent-runtime.json
│   ├── application-packets/
│   ├── jobs.live.json
│   ├── jobs.sample.json
│   ├── profile.json
│   ├── resume-drafts/
│   ├── resume-structured.json
│   ├── review-queue.json
│   ├── source-resumes/
│   ├── shortlist.json
│   └── shortlist.md
├── src/job_agent/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── collectors.py
│   ├── models.py
│   ├── orchestration.py
│   ├── queue.py
│   ├── resume.py
│   ├── shortlist.py
│   └── web.py
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
10. Added a dependency-free web UI and container deployment files.
11. Added a live job collector and cache file for supported company career sources.
12. Added `run.sh` for one-command local startup.
13. Refactored the workflow into explicit search, resume, and apply agents with orchestration, runtime state, and memory.
14. Added resume source upload/selection, structured resume parsing, tailored draft generation, preview, and resume approval before apply.

## Agent workflow

### 1. SearchJobAgent

- collects live jobs from supported company sources
- writes `data/jobs.live.json`
- builds the shortlist
- seeds the current review queue
- updates `data/agent-runtime.json`
- appends search events to `data/agent-memory.json`

### 2. ResumeUpdateAgent

- parses the selected/uploaded source resume into `data/resume-structured.json`
- runs only after a job is approved
- creates a tailored resume draft in `data/resume-drafts/<job-id>.md`
- attempts a DOCX output in `data/resume-drafts/<job-id>.docx` when supported
- updates the job state to `resume_status = draft_ready`
- appends resume events to `data/agent-memory.json`

### 3. ApplyJobAgent

- runs only after approval and resume approval
- creates an application packet in `data/application-packets/<job-id>.json`
- records the exact tailored resume file path selected for the application
- updates the job state to `apply_status = sent`
- appends apply events to `data/agent-memory.json`

### 4. JobSearchOrchestrator

- owns the shared workflow transitions
- ensures agents run in the correct order
- keeps runtime state durable across UI and CLI usage

## Workflow

### 1. Update your profile

Edit `data/profile.json` and add any missing experience, skills, location preferences, or sponsorship constraints.

### 2. Parse your source resume

You can either point the system at an existing local resume path or upload a file in the UI.

CLI:

```bash
PYTHONPATH=src python3 -m job_agent parse-resume-source \
  --resume-path "/absolute/path/to/resume.pdf"
```

This step:

- updates `candidate.resume_path` in `data/profile.json`
- extracts text from the source resume
- writes structured editable content to `data/resume-structured.json`

### 3. Collect jobs from official career sites

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

### 4. Generate the shortlist

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

### 5. Run the end-to-end search in one command

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

To collect live jobs first, use:

```bash
PYTHONPATH=src python3 -m job_agent run-search \
  --profile data/profile.json \
  --jobs data/jobs.live.json \
  --shortlist-out data/shortlist.json \
  --queue-out data/review-queue.json \
  --markdown data/shortlist.md \
  --collect-live \
  --live-jobs-out data/jobs.live.json \
  --job-title "software engineer" \
  --company "NVIDIA"
```

Or collect live jobs separately:

```bash
PYTHONPATH=src python3 -m job_agent collect-live-jobs \
  --out data/jobs.live.json \
  --job-title "software engineer" \
  --company "Google"
```

### 6. Seed the approval queue manually

```bash
python3 -m job_agent seed-queue \
  --shortlist data/shortlist.json \
  --out data/review-queue.json
```

Use this only if you want to separate shortlist generation from queue creation.

### 7. Approve jobs and generate tailored resumes

```bash
PYTHONPATH=src python3 -m job_agent approve-job --job-id snowflake-001
```

This transition:

1. marks the role approved
2. runs `ResumeUpdateAgent`
3. creates the tailored draft files
4. updates runtime state and memory

### 8. Preview and approve the tailored resume

CLI:

```bash
PYTHONPATH=src python3 -m job_agent approve-resume --job-id snowflake-001
```

In the UI, this is the `Approve Resume` button after the draft preview appears.

### 9. Apply using the latest approved tailored resume

CLI:

```bash
PYTHONPATH=src python3 -m job_agent apply-job --job-id snowflake-001
```

This uses the latest `selected_resume_path` recorded in runtime state.

### 10. Export only approved jobs

```bash
python3 -m job_agent export-approved \
  --queue data/review-queue.json \
  --out data/approved-jobs.json
```

At this point the internal workflow marks the application packet sent. External ATS form submission is still a separate future step.

## Local UI

Fastest local start:

```bash
cd "/Users/vinodhkrishnamoorthy/Documents/New project"
./run.sh
```

That starts the UI at [http://127.0.0.1:8000](http://127.0.0.1:8000).

Manual equivalent:

Run the browser UI:

```bash
cd "/Users/vinodhkrishnamoorthy/Documents/New project"
PYTHONPATH=src python3 -m job_agent serve-ui --host 127.0.0.1 --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The UI supports:

- selecting an existing resume path or uploading a source resume file
- parsing the resume into structured editable content
- running the search with up to 3 job titles and up to 5 company filters
- collecting live jobs into `data/jobs.live.json` before scoring
- viewing the ranked shortlist
- approving jobs, which triggers the resume update agent
- previewing the tailored resume draft in the queue
- approving the tailored resume before apply
- applying jobs, which triggers the apply agent
- viewing agent runtime and recent memory events
- exporting the approved jobs list

When you click `Run search` in the UI, it now tries to fetch live jobs first from the supported company sources. If no live jobs are collected for that query, it falls back to the local sample file.

When you click `Approve`, the orchestrator:

1. marks the job approved
2. runs the resume update agent
3. persists the new resume draft path and state

When you click `Approve Resume`, the orchestrator:

1. validates that a tailored draft exists
2. marks that tailored file as the approved resume for the job
3. persists `selected_resume_path` for the apply step

When you click `Apply`, the orchestrator:

1. validates that the job is approved
2. validates that the tailored resume is approved
3. runs the apply agent
4. persists the application packet path, selected resume path, and sent state

## CLI agent commands

```bash
PYTHONPATH=src python3 -m job_agent parse-resume-source --resume-path /absolute/path/to/resume.pdf
PYTHONPATH=src python3 -m job_agent approve-job --job-id snowflake-001
PYTHONPATH=src python3 -m job_agent approve-resume --job-id snowflake-001
PYTHONPATH=src python3 -m job_agent apply-job --job-id snowflake-001
```

## Deployment

This repo now includes a simple `Dockerfile`, so it can be containerized and deployed on any service that accepts a container image.

Build locally:

```bash
docker build -t job-search-agent .
```

Run locally with Docker:

```bash
docker run --rm -p 8000:8000 job-search-agent
```

The container starts the same UI at `http://127.0.0.1:8000`.

## Local development

Run the smoke test:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## GitHub status

The repository is published at [vinokri/job-search-agent](https://github.com/vinokri/job-search-agent). Local pushes from this terminal still depend on GitHub authentication being available; GitHub Desktop remains the reliable push path on this machine.
