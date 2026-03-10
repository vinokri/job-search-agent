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


def libreoffice_available() -> str:
    return shutil.which("libreoffice") or shutil.which("soffice") or ""


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def wkhtmltopdf_available() -> bool:
    return shutil.which("wkhtmltopdf") is not None


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
        "source": {},
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


def write_pdf_if_possible(markdown_text: str, pdf_path: str | Path, docx_source_path: str | Path | None = None) -> str:
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    office = libreoffice_available()
    if office:
        if docx_source_path and Path(docx_source_path).exists():
            try:
                subprocess.check_call(
                    [office, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_path.parent), str(docx_source_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                converted = pdf_path.parent / f"{Path(docx_source_path).stem}.pdf"
                if converted.exists():
                    if converted != pdf_path:
                        if pdf_path.exists():
                            pdf_path.unlink()
                        converted.rename(pdf_path)
                    return str(pdf_path)
            except subprocess.CalledProcessError:
                pass

    html_path = pdf_path.with_suffix(".html")
    html_path.write_text(markdown_to_html(markdown_text), encoding="utf-8")
    if wkhtmltopdf_available():
        try:
            subprocess.check_call(
                ["wkhtmltopdf", str(html_path), str(pdf_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if pdf_path.exists():
                return str(pdf_path)
        except subprocess.CalledProcessError:
            pass

    if pandoc_available():
        try:
            subprocess.check_call(
                ["pandoc", str(html_path), "-o", str(pdf_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if pdf_path.exists():
                return str(pdf_path)
        except subprocess.CalledProcessError:
            pass

    return ""


def store_uploaded_resume_bytes(destination: str | Path, payload: bytes) -> str:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return str(destination)


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name.strip()) or "resume-upload.txt"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", base)


class ResumeSourceManager:
    def ingest_source(
        self,
        resume_path: str | Path,
        source_dir: str | Path,
        structured_path: str | Path,
    ) -> dict:
        source_dir = Path(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)
        original_path = Path(resume_path)
        stored_source = source_dir / sanitize_filename(original_path.name)
        if original_path.resolve() != stored_source.resolve():
            shutil.copy2(original_path, stored_source)

        extracted_text = extract_resume_text(stored_source)
        structured = parse_resume_structure(extracted_text)
        canonical_markdown = source_dir / f"{stored_source.stem}.canonical.md"
        canonical_markdown.write_text(self._build_canonical_markdown(structured), encoding="utf-8")

        canonical_docx = source_dir / f"{stored_source.stem}.canonical.docx"
        canonical_docx_path = ""
        if stored_source.suffix.lower() == ".docx":
            if stored_source != canonical_docx:
                shutil.copy2(stored_source, canonical_docx)
            canonical_docx_path = str(canonical_docx)
        else:
            canonical_docx_path = write_docx_if_possible(canonical_markdown.read_text(encoding="utf-8"), canonical_docx)

        canonical_pdf = source_dir / f"{stored_source.stem}.canonical.pdf"
        canonical_pdf_path = ""
        if stored_source.suffix.lower() == ".pdf":
            if stored_source != canonical_pdf:
                shutil.copy2(stored_source, canonical_pdf)
            canonical_pdf_path = str(canonical_pdf)
        elif canonical_docx_path:
            canonical_pdf_path = write_pdf_if_possible(
                canonical_markdown.read_text(encoding="utf-8"),
                canonical_pdf,
                canonical_docx_path,
            )

        structured["source"] = {
            "original_resume_path": str(original_path),
            "stored_resume_path": str(stored_source),
            "canonical_markdown_path": str(canonical_markdown),
            "canonical_docx_path": canonical_docx_path,
            "canonical_pdf_path": canonical_pdf_path,
        }
        save_structured_resume(structured_path, structured)
        return structured

    def _build_canonical_markdown(self, structured_resume: dict) -> str:
        lines = [f"# {structured_resume.get('name') or 'Candidate'}", ""]
        for section_name, section_lines in structured_resume.get("sections", {}).items():
            lines.append(f"## {section_name.title()}")
            if section_name == "skills":
                for line in section_lines:
                    lines.append(f"- {line}")
            else:
                lines.extend(section_lines or [""])
            lines.append("")
        return "\n".join(lines).strip() + "\n"


class ResumeRenderAgent:
    def render_tailored_resume(
        self,
        profile: dict,
        structured_resume: dict,
        job: dict,
        drafts_dir: str | Path,
    ) -> dict:
        drafts_dir = Path(drafts_dir)
        drafts_dir.mkdir(parents=True, exist_ok=True)

        markdown_text = build_tailored_resume_markdown(profile, structured_resume, job)
        markdown_path = drafts_dir / f"{job['job_id']}.md"
        markdown_path.write_text(markdown_text, encoding="utf-8")

        docx_path = drafts_dir / f"{job['job_id']}.docx"
        generated_docx = write_docx_if_possible(markdown_text, docx_path)
        pdf_path = drafts_dir / f"{job['job_id']}.pdf"
        generated_pdf = write_pdf_if_possible(markdown_text, pdf_path, generated_docx or None)

        preferred_path = generated_pdf or generated_docx or str(markdown_path)
        return {
            "resume_preview_path": str(markdown_path),
            "resume_draft_path": str(markdown_path),
            "rendered_resume_markdown_path": str(markdown_path),
            "rendered_resume_docx_path": generated_docx,
            "rendered_resume_pdf_path": generated_pdf,
            "selected_resume_path": preferred_path,
        }
