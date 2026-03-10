from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import dump_json, load_json


KNOWN_SECTION_NAMES = {
    "summary": "summary",
    "professional summary": "summary",
    "experience": "experience",
    "professional experience": "experience",
    "work experience": "experience",
    "skills": "skills",
    "technical skills": "skills",
    "education": "education",
    "projects": "projects",
    "certifications": "certifications",
}


def textutil_available() -> bool:
    return shutil.which("textutil") is not None


def strings_available() -> bool:
    return shutil.which("strings") is not None


def extract_resume_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", raw)
    if suffix in {".doc", ".docx", ".rtf"} and textutil_available():
        output = subprocess.check_output(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            text=True,
        )
        return output
    if suffix == ".pdf" and strings_available():
        output = subprocess.check_output(
            ["strings", "-n", "8", str(path)],
            text=True,
        )
        return output
    return path.read_text(encoding="utf-8", errors="replace")


def parse_resume_structure(text: str) -> dict:
    normalized = text.replace("\r\n", "\n")
    lines = [line.strip() for line in normalized.splitlines()]
    lines = [line for line in lines if line]
    candidate_name = lines[0] if lines else ""
    sections: dict[str, list[str]] = {}
    current = "summary"
    sections[current] = []
    for line in lines[1:]:
        canonical = KNOWN_SECTION_NAMES.get(line.lower())
        if canonical:
            current = canonical
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    skills_text = " ".join(sections.get("skills", []))
    skill_candidates = []
    for token in re.split(r"[,|/•·]", skills_text):
        cleaned = token.strip()
        if cleaned and len(cleaned) < 40:
            skill_candidates.append(cleaned.lower())

    return {
        "name": candidate_name,
        "raw_text": normalized,
        "sections": sections,
        "skills": sorted(set(skill_candidates)),
    }


def save_structured_resume(structured_path: str | Path, payload: dict) -> None:
    dump_json(structured_path, payload)


def load_structured_resume(structured_path: str | Path) -> dict:
    return load_json(structured_path)


def build_tailored_resume_markdown(profile: dict, structured_resume: dict, job: dict) -> str:
    summary_lines = structured_resume.get("sections", {}).get("summary", [])
    summary = " ".join(summary_lines[:3]).strip()
    if not summary:
        summary = profile.get("candidate", {}).get("summary", "")

    relevant_reasons = job.get("reasons", [])[:6]
    skills = ", ".join(job.get("reasons", [])[:4])
    experience_lines = structured_resume.get("sections", {}).get("experience", [])
    top_experience = experience_lines[:10]
    source_skills = structured_resume.get("skills", [])[:20]

    lines = [
        f"# {structured_resume.get('name') or profile.get('candidate', {}).get('name', 'Candidate')}",
        "",
        f"Target Role: {job['title']} at {job['company']}",
        "",
        "## Tailored Summary",
        summary or "Add a tailored summary here.",
        f"Focus this version on {job['title']} responsibilities, emphasizing alignment with the approved role.",
        "",
        "## Why This Role Matches",
        *(f"- {reason}" for reason in relevant_reasons),
        "",
        "## Skills To Highlight",
        f"- Job-aligned themes: {skills or 'Highlight distributed systems, data, and ML platform work.'}",
        f"- Resume skills: {', '.join(source_skills) or 'Add relevant technical skills here.'}",
        "",
        "## Experience Bullets To Prioritize",
        *(f"- {line}" for line in top_experience),
        "",
        "## Source Resume Sections",
    ]

    for section_name, section_lines in structured_resume.get("sections", {}).items():
        if not section_lines:
            continue
        lines.append(f"### {section_name.title()}")
        lines.extend(section_lines[:12])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def markdown_to_html(markdown_text: str) -> str:
    html_lines = ["<html><body>"]
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            html_lines.append(f"<p>&bull; {line[2:]}</p>")
        elif line.strip():
            html_lines.append(f"<p>{line}</p>")
        else:
            html_lines.append("<br>")
    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def write_docx_if_possible(markdown_text: str, docx_path: str | Path) -> str:
    docx_path = Path(docx_path)
    if not textutil_available():
        return ""
    html_path = docx_path.with_suffix(".html")
    html_path.write_text(markdown_to_html(markdown_text), encoding="utf-8")
    try:
        subprocess.check_call(
            ["textutil", "-convert", "docx", str(html_path), "-output", str(docx_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return ""
    return str(docx_path) if docx_path.exists() else ""


def store_uploaded_resume_bytes(destination: str | Path, payload: bytes) -> str:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return str(destination)


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name.strip()) or "resume-upload.txt"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", base)
