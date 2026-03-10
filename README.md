# Job Search Agent

This project is a multi-agent job workflow for:

- collecting live jobs from NVIDIA, Databricks, Snowflake, and Google
- ranking them against a structured candidate profile
- approving a target role
- generating a tailored resume for that role
- preparing a browser-based ATS apply run
- stopping before final submit until the user confirms it manually

The system is intentionally human-in-the-loop. It automates search, ranking, resume preparation, and browser apply setup, but the final ATS submission remains a separate explicit confirmation step.

## Architecture

The current architecture is built around explicit orchestration and durable state:

- `SearchJobAgent`
  - collects live jobs
  - normalizes them into a common schema
  - builds the shortlist
- `ResumeSourceManager`
  - owns source resume ingestion
  - copies uploaded/selected source files into `data/source-resumes/`
  - builds canonical resume artifacts where possible
- `ResumeUpdateAgent`
  - runs after a job is approved
  - prepares a job-specific tailored draft
- `ResumeRenderAgent`
  - renders tailored Markdown
  - attempts tailored DOCX and PDF outputs
- `ApplyJobAgent`
  - prepares an external apply packet
  - creates a browser apply run
  - selects the ATS adapter
- `ATSAdapter`
  - provider interface for company-specific apply flows
  - first provider implemented: Google
- `ApplicationRunStore`
  - stores apply-run metadata, screenshots, launcher scripts, and errors
- `JobSearchOrchestrator`
  - coordinates the state machine across all agents

The project does not use an external orchestration framework. The orchestration layer is custom Python in [orchestration.py](/Users/vinodhkrishnamoorthy/Documents/New%20project/src/job_agent/orchestration.py).

## Current state model

Each job in runtime tracks:

- `review_status`
- `resume_status`
- `apply_status`
- `resume_preview_path`
- `resume_draft_path`
- `rendered_resume_docx_path`
- `rendered_resume_pdf_path`
- `selected_resume_path`
- `application_packet_path`
- `application_run_id`
- `application_run_path`
- `apply_provider`
- `apply_launch_command`

Shared runtime lives in [agent-runtime.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/agent-runtime.json). Append-only memory lives in [agent-memory.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/agent-memory.json).

## Resume pipeline

The improved resume flow is:

1. Select or upload a source resume.
2. `ResumeSourceManager` parses it into [resume-structured.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/resume-structured.json).
3. The source is copied into [source-resumes](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/source-resumes).
4. Canonical artifacts are created when possible:
   - `*.canonical.md`
   - `*.canonical.docx`
   - `*.canonical.pdf`
5. When a job is approved, `ResumeUpdateAgent` and `ResumeRenderAgent` generate:
   - `data/resume-drafts/<job-id>.md`
   - `data/resume-drafts/<job-id>.docx` when supported
   - `data/resume-drafts/<job-id>.pdf` when supported
6. After `Approve Resume`, the preferred artifact is stored in `selected_resume_path`.

Design choice:

- PDF is treated as an output artifact, not the primary editable format.
- The editable system representation is the structured resume JSON plus generated Markdown/DOCX.

## External ATS flow

The external apply flow is now browser-oriented.

1. `Apply In Browser` prepares the application packet.
2. The system selects an ATS adapter for the company.
3. It creates an application run under [application-runs](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/application-runs).
4. For Google, it writes a Playwright-compatible launcher script and a local launch command.
5. The browser run is intended to stop before final submit.
6. After you manually complete the external ATS submit, you click `Mark Submitted`.

This means:

- internal workflow automation is complete
- external browser assistance is prepared
- final submission is still a human decision

## Project structure

```text
.
├── README.md
├── run.sh
├── pyproject.toml
├── Dockerfile
├── data/
│   ├── approved-jobs.json
│   ├── agent-memory.json
│   ├── agent-runtime.json
│   ├── application-packets/
│   ├── application-runs/
│   ├── jobs.live.json
│   ├── jobs.sample.json
│   ├── profile.json
│   ├── resume-drafts/
│   ├── resume-structured.json
│   ├── review-queue.json
│   ├── shortlist.json
│   ├── shortlist.md
│   └── source-resumes/
├── src/job_agent/
│   ├── ats.py
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

## End-to-end flow

### 1. Parse the source resume

CLI:

```bash
PYTHONPATH=src python3 -m job_agent parse-resume-source \
  --resume-path "/absolute/path/to/resume.pdf"
```

This:

- updates `candidate.resume_path` in [profile.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/profile.json)
- stores the source under [source-resumes](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/source-resumes)
- builds [resume-structured.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/resume-structured.json)
- creates canonical Markdown and best-effort DOCX/PDF artifacts

### 2. Run search

CLI:

```bash
PYTHONPATH=src python3 -m job_agent run-search \
  --profile data/profile.json \
  --jobs data/jobs.live.json \
  --shortlist-out data/shortlist.json \
  --queue-out data/review-queue.json \
  --markdown data/shortlist.md \
  --collect-live \
  --live-jobs-out data/jobs.live.json \
  --job-title "senior solutions architect" \
  --company "Google"
```

This:

- collects live jobs
- stores them in [jobs.live.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/jobs.live.json)
- writes [shortlist.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/shortlist.json)
- writes [review-queue.json](/Users/vinodhkrishnamoorthy/Documents/New%20project/data/review-queue.json)
- persists diagnostics in runtime

### 3. Approve the job

CLI:

```bash
PYTHONPATH=src python3 -m job_agent approve-job --job-id google-001
```

This:

- marks the role approved
- triggers `ResumeUpdateAgent`
- generates tailored resume outputs

### 4. Approve the tailored resume

CLI:

```bash
PYTHONPATH=src python3 -m job_agent approve-resume --job-id google-001
```

This:

- validates the tailored draft exists
- locks in the preferred resume artifact through `selected_resume_path`

### 5. Prepare the browser apply run

CLI:

```bash
PYTHONPATH=src python3 -m job_agent apply-job --job-id google-001
```

This:

- creates the application packet
- creates the browser apply run
- selects the adapter
- writes the launch command into runtime
- does not mark the application submitted yet

### 6. Confirm final external submission

CLI:

```bash
PYTHONPATH=src python3 -m job_agent mark-submitted --job-id google-001
```

Use this only after you complete the final ATS submit in the browser.

## UI flow

Fastest local start:

```bash
cd "/Users/vinodhkrishnamoorthy/Documents/New project"
./run.sh
```

Manual equivalent:

```bash
cd "/Users/vinodhkrishnamoorthy/Documents/New project"
PYTHONPATH=src python3 -m job_agent serve-ui --host 127.0.0.1 --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The UI supports:

- selecting or uploading a resume source
- parsing the resume into structured content
- running a live search with up to 3 job titles and 5 companies
- reviewing search diagnostics
- approving jobs
- previewing and approving tailored resumes
- preparing browser apply runs
- marking external submissions as completed
- exporting approved jobs

## Commands

```bash
PYTHONPATH=src python3 -m job_agent parse-resume-source --resume-path /absolute/path/to/resume.pdf
PYTHONPATH=src python3 -m job_agent approve-job --job-id google-001
PYTHONPATH=src python3 -m job_agent approve-resume --job-id google-001
PYTHONPATH=src python3 -m job_agent apply-job --job-id google-001
PYTHONPATH=src python3 -m job_agent mark-submitted --job-id google-001
PYTHONPATH=src python3 -m job_agent serve-ui --host 127.0.0.1 --port 8000
```

## Deployment

This repo includes a [Dockerfile](/Users/vinodhkrishnamoorthy/Documents/New%20project/Dockerfile), so it can be deployed to a container host such as Render.

Build locally:

```bash
docker build -t job-search-agent .
```

Run locally with Docker:

```bash
docker run --rm -p 8000:8000 job-search-agent
```

Important note:

- hosted environments like Render can prepare apply runs
- browser automation should be launched on your local machine, not on the hosted container

## Local development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Current limitations

- Live collector parsing remains best-effort because career sites change frequently.
- Google is the first ATS adapter wired into the browser apply architecture.
- DOCX and PDF generation depend on tools available in the host runtime.
- PDF source parsing is still fallback-grade compared with native DOCX parsing.
- Hosted containers use ephemeral storage unless you add persistence.

## GitHub

The repository is published at [vinokri/job-search-agent](https://github.com/vinokri/job-search-agent).
