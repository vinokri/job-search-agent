# Data Contracts

## `profile.json`

```json
{
  "candidate": {
    "name": "",
    "linkedin_url": "",
    "resume_path": "",
    "headline": "",
    "summary": "",
    "locations": [],
    "work_authorization": [],
    "requires_sponsorship": false,
    "seniority": ""
  },
  "preferences": {
    "companies": [],
    "titles_include": [],
    "titles_exclude": [],
    "locations_preferred": [],
    "employment_types": [],
    "remote_preference": "any"
  },
  "skills": {
    "must_have": [],
    "strong": [],
    "nice_to_have": []
  },
  "experience": [
    {
      "title": "",
      "company": "",
      "duration": "",
      "summary": "",
      "skills": []
    }
  ],
  "application_notes": {
    "default_cover_note": "",
    "portfolio_url": "",
    "github_url": ""
  }
}
```

## `jobs.json`

```json
[
  {
    "id": "",
    "company": "",
    "title": "",
    "url": "",
    "location": "",
    "remote": "unknown",
    "employment_type": "full-time",
    "posted_at": "",
    "description": "",
    "skills": []
  }
]
```

## `shortlist.json`

```json
[
  {
    "id": "",
    "company": "",
    "title": "",
    "url": "",
    "score": 0,
    "reasons": [],
    "matched_skills": [],
    "missing_must_have": []
  }
]
```

## `review-queue.json`

```json
[
  {
    "id": "",
    "company": "",
    "title": "",
    "url": "",
    "score": 0,
    "status": "pending",
    "notes": "",
    "reasons": []
  }
]
```

## Status values

- `pending`
- `approved`
- `rejected`
- `hold`
