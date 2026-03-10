#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")
LEVEL_TERMS = {
    "intern": -12,
    "student": -12,
    "junior": -6,
    "entry": -6,
    "senior": 5,
    "staff": 6,
    "principal": 6,
    "lead": 4,
    "manager": 2,
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def tokenize(text):
    return set(TOKEN_RE.findall((text or "").lower()))


def normalize_list(values):
    return [str(value).strip() for value in values or [] if str(value).strip()]


def phrase_in_text(phrase, text):
    return phrase.lower() in (text or "").lower()


def score_job(profile, job):
    candidate = profile.get("candidate", {})
    preferences = profile.get("preferences", {})
    skills = profile.get("skills", {})

    title = job.get("title", "")
    description = job.get("description", "")
    location = job.get("location", "")
    remote = str(job.get("remote", "unknown")).lower()
    company = job.get("company", "")
    combined_text = " ".join(
        [
            title,
            description,
            " ".join(normalize_list(job.get("skills", []))),
        ]
    )
    tokens = tokenize(combined_text)

    score = 0
    reasons = []

    for phrase in normalize_list(preferences.get("titles_include", [])):
        if phrase_in_text(phrase, title):
            score += 12
            reasons.append(f"title matches preferred phrase '{phrase}'")

    for phrase in normalize_list(preferences.get("titles_exclude", [])):
        if phrase_in_text(phrase, title):
            score -= 30
            reasons.append(f"title contains excluded phrase '{phrase}'")

    preferred_companies = {value.lower() for value in normalize_list(preferences.get("companies", []))}
    if company.lower() in preferred_companies:
        score += 8
        reasons.append("company is in preferred list")

    preferred_locations = normalize_list(preferences.get("locations_preferred", []))
    if preferred_locations:
        lowered_location = location.lower()
        if any(item.lower() in lowered_location for item in preferred_locations if item.lower() != "remote"):
            score += 8
            reasons.append("location matches preferred geography")

    remote_preference = str(preferences.get("remote_preference", "any")).lower()
    if remote_preference != "any" and remote_preference == remote:
        score += 5
        reasons.append(f"remote mode matches '{remote_preference}' preference")

    if remote_preference == "remote" and remote == "onsite":
        score -= 6
        reasons.append("on-site role conflicts with remote preference")

    employment_types = {value.lower() for value in normalize_list(preferences.get("employment_types", []))}
    employment_type = str(job.get("employment_type", "")).lower()
    if employment_types and employment_type in employment_types:
        score += 4
        reasons.append("employment type matches preference")

    matched_skills = []
    missing_must_have = []

    for skill in normalize_list(skills.get("must_have", [])):
        if phrase_in_text(skill, combined_text) or skill.lower() in tokens:
            score += 10
            matched_skills.append(skill)
        else:
            score -= 8
            missing_must_have.append(skill)

    for skill in normalize_list(skills.get("strong", [])):
        if phrase_in_text(skill, combined_text) or skill.lower() in tokens:
            score += 5
            matched_skills.append(skill)

    for skill in normalize_list(skills.get("nice_to_have", [])):
        if phrase_in_text(skill, combined_text) or skill.lower() in tokens:
            score += 2
            matched_skills.append(skill)

    seniority = str(candidate.get("seniority", "")).lower()
    if seniority:
        for term, weight in LEVEL_TERMS.items():
            in_title = phrase_in_text(term, title)
            if seniority == "senior" and in_title and term in {"senior", "staff", "principal", "lead"}:
                score += weight
                reasons.append(f"seniority aligns with '{term}'")
            elif seniority in {"mid", "intermediate"} and in_title and term in {"intern", "student"}:
                score += weight
            elif seniority == "entry" and in_title and term in {"intern", "student", "junior", "entry"}:
                score += abs(weight)

    if candidate.get("requires_sponsorship") is False and "sponsorship" in tokens:
        score += 1

    summary_tokens = tokenize(candidate.get("headline", "") + " " + candidate.get("summary", ""))
    overlap = sorted(token for token in tokens & summary_tokens if len(token) > 3)
    if overlap:
        score += min(len(overlap), 8)
        reasons.append("description overlaps with profile summary")

    reasons.extend([f"matched skill '{skill}'" for skill in matched_skills[:8]])
    if missing_must_have:
        reasons.extend([f"missing must-have '{skill}'" for skill in missing_must_have])

    return {
        "id": job.get("id", ""),
        "company": company,
        "title": title,
        "url": job.get("url", ""),
        "score": score,
        "reasons": reasons,
        "matched_skills": sorted(set(matched_skills)),
        "missing_must_have": missing_must_have,
    }


def render_markdown(shortlist):
    lines = [
        "# Job Shortlist",
        "",
        "| Score | Company | Title | URL |",
        "| ---: | --- | --- | --- |",
    ]
    for item in shortlist:
        url = item["url"] or ""
        lines.append(
            f"| {item['score']} | {item['company']} | {item['title']} | {url} |"
        )
    lines.append("")
    for item in shortlist:
        lines.append(f"## {item['company']} - {item['title']}")
        lines.append("")
        lines.append(f"- Score: {item['score']}")
        lines.append(f"- URL: {item['url']}")
        if item["matched_skills"]:
            lines.append(f"- Matched skills: {', '.join(item['matched_skills'])}")
        if item["missing_must_have"]:
            lines.append(f"- Missing must-have: {', '.join(item['missing_must_have'])}")
        if item["reasons"]:
            lines.append(f"- Reasons: {'; '.join(item['reasons'][:8])}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Rank jobs against a structured candidate profile.")
    parser.add_argument("--profile", required=True, help="Path to profile JSON.")
    parser.add_argument("--jobs", required=True, help="Path to jobs JSON.")
    parser.add_argument("--out", required=True, help="Path to shortlist JSON output.")
    parser.add_argument("--markdown", help="Optional Markdown report output path.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum results to keep.")
    args = parser.parse_args()

    profile = load_json(args.profile)
    jobs = load_json(args.jobs)
    scored = [score_job(profile, job) for job in jobs]
    shortlist = sorted(scored, key=lambda item: item["score"], reverse=True)[: args.limit]

    dump_json(args.out, shortlist)
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(shortlist), encoding="utf-8")


if __name__ == "__main__":
    main()
