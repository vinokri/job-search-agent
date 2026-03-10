from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from .models import dump_json


USER_AGENT = "job-search-agent/0.1 (+https://github.com/vinokri/job-search-agent)"
WORKDAY_NVIDIA_JOBS = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
GOOGLE_RESULTS = "https://www.google.com/about/careers/applications/jobs/results"
SNOWFLAKE_RESULTS = "https://careers.snowflake.com/us/en/search-results"
SNOWFLAKE_SITEMAP = "https://careers.snowflake.com/sitemap.xml"
DATABRICKS_SITEMAP = "https://www.databricks.com/sitemap.xml"


def fetch_url(url: str, method: str = "GET", data: bytes | None = None, content_type: str | None = None) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    if content_type:
        headers["Content-Type"] = content_type
    if "wd5.myworkdayjobs.com" in url:
        headers["Origin"] = "https://nvidia.wd5.myworkdayjobs.com"
        headers["Referer"] = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "job"


def unique_jobs(jobs: Iterable[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for job in jobs:
        key = job.get("url") or job.get("id")
        if key:
            deduped[key] = job
    return list(deduped.values())


def extract_json_ld_objects(html: str) -> list[dict]:
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    objects: list[dict] = []
    for match in matches:
        raw = match.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            objects.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            objects.append(payload)
    return objects


def extract_jobposting_from_html(html: str, url: str, company: str) -> dict | None:
    for item in extract_json_ld_objects(html):
        item_type = item.get("@type")
        if item_type == "JobPosting":
            title = normalize_whitespace(str(item.get("title", "")))
            description = normalize_whitespace(str(item.get("description", "")))
            location = ""
            job_location = item.get("jobLocation")
            if isinstance(job_location, dict):
                address = job_location.get("address", {})
                if isinstance(address, dict):
                    parts = [
                        address.get("addressLocality", ""),
                        address.get("addressRegion", ""),
                        address.get("addressCountry", ""),
                    ]
                    location = normalize_whitespace(", ".join(part for part in parts if part))
            return {
                "id": f"{slugify(company)}-{slugify(title)}",
                "company": company,
                "title": title,
                "url": url,
                "location": location,
                "remote": "unknown",
                "employment_type": "full-time",
                "posted_at": str(item.get("datePosted", "")),
                "description": description,
                "skills": extract_skills_from_text(" ".join([title, description])),
            }
    return None


def extract_meta_content(html: str, attr: str, value: str) -> str:
    pattern = rf'<meta[^>]+{attr}=["\']{re.escape(value)}["\'][^>]+content=["\'](.*?)["\']'
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    return normalize_whitespace(match.group(1)) if match else ""


def extract_skills_from_text(text: str) -> list[str]:
    keywords = [
        "python",
        "sql",
        "spark",
        "distributed systems",
        "machine learning",
        "data pipelines",
        "aws",
        "gcp",
        "kubernetes",
        "cloud",
        "java",
        "go",
        "backend",
        "platform",
        "analytics",
    ]
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword in lowered]


def title_matches(job_title: str, requested_titles: list[str] | None) -> bool:
    if not requested_titles:
        return True
    lowered = job_title.lower()
    return any(title.lower() in lowered for title in requested_titles)


def collect_nvidia_jobs(job_titles: list[str] | None, limit: int = 20) -> list[dict]:
    collected: list[dict] = []
    search_texts = job_titles or [""]
    for search_text in search_texts:
        payload = json.dumps(
            {
                "appliedFacets": {},
                "limit": limit,
                "offset": 0,
                "searchText": search_text,
            }
        ).encode("utf-8")
        try:
            response = fetch_url(
                WORKDAY_NVIDIA_JOBS,
                method="POST",
                data=payload,
                content_type="application/json",
            )
        except (HTTPError, URLError):
            continue
        parsed = json.loads(response)
        for posting in parsed.get("jobPostings", []):
            title = normalize_whitespace(str(posting.get("title", "")))
            if not title_matches(title, job_titles):
                continue
            external_path = posting.get("externalPath", "")
            locations = posting.get("locationsText") or ", ".join(
                location.get("displayName", "")
                for location in posting.get("locations", [])
                if isinstance(location, dict)
            )
            description = normalize_whitespace(str(posting.get("bulletFields", [])))
            job_url = (
                f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/{external_path}"
                if external_path
                else "https://www.nvidia.com/en-us/about-nvidia/careers/"
            )
            collected.append(
                {
                    "id": posting.get("bulletFields", [title])[0].lower().replace(" ", "-")
                    if posting.get("bulletFields")
                    else f"nvidia-{slugify(title)}",
                    "company": "NVIDIA",
                    "title": title,
                    "url": job_url,
                    "location": normalize_whitespace(locations),
                    "remote": "unknown",
                    "employment_type": "full-time",
                    "posted_at": str(posting.get("postedOn", "")),
                    "description": description,
                    "skills": extract_skills_from_text(" ".join([title, description])),
                }
            )
    return unique_jobs(collected)[:limit]


def extract_google_results(html: str) -> list[dict]:
    jobs: list[dict] = []
    pattern = re.compile(
        r'href="(/about/careers/applications/jobs/results/[^"]+)"[^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for href, label in pattern.findall(html):
        title = normalize_whitespace(re.sub(r"<[^>]+>", " ", label))
        if not title:
            continue
        jobs.append(
            {
                "id": f"google-{slugify(title)}",
                "company": "Google",
                "title": title,
                "url": urljoin("https://www.google.com", href),
                "location": "",
                "remote": "unknown",
                "employment_type": "full-time",
                "posted_at": "",
                "description": title,
                "skills": extract_skills_from_text(title),
            }
        )
    if jobs:
        return unique_jobs(jobs)

    plain_text = normalize_whitespace(re.sub(r"<[^>]+>", "\n", html))
    fallback_pattern = re.compile(
        r"(Software Engineer[^\n]*|Data Engineer[^\n]*|Machine Learning Engineer[^\n]*|Product Solutions Engineer[^\n]*|Customer Solutions Engineer[^\n]*)\s+Google \| ([^\n]+)",
        flags=re.IGNORECASE,
    )
    for title, location in fallback_pattern.findall(plain_text):
        clean_title = normalize_whitespace(title)
        jobs.append(
            {
                "id": f"google-{slugify(clean_title)}",
                "company": "Google",
                "title": clean_title,
                "url": GOOGLE_RESULTS,
                "location": normalize_whitespace(location),
                "remote": "unknown",
                "employment_type": "full-time",
                "posted_at": "",
                "description": clean_title,
                "skills": extract_skills_from_text(clean_title),
            }
        )
    return unique_jobs(jobs)


def collect_google_jobs(job_titles: list[str] | None, limit: int = 20) -> list[dict]:
    collected: list[dict] = []
    queries = job_titles or [""]
    for query in queries:
        url = GOOGLE_RESULTS
        if query:
            url = f"{GOOGLE_RESULTS}/?q={quote_plus(query)}"
        try:
            html = fetch_url(url)
        except (HTTPError, URLError):
            continue
        for item in extract_google_results(html):
            collected.append(item)
    filtered = [item for item in unique_jobs(collected) if title_matches(item["title"], job_titles)]
    if filtered:
        return filtered[:limit]
    return unique_jobs(collected)[:limit]


def extract_sitemap_urls(xml_text: str, contains: str | None = None) -> list[str]:
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml_text)
    urls = [
        element.text.strip()
        for element in root.findall(".//sm:loc", namespace)
        if element.text and (contains is None or contains in element.text)
    ]
    return urls


def collect_databricks_jobs(job_titles: list[str] | None, limit: int = 20) -> list[dict]:
    try:
        sitemap = fetch_url(DATABRICKS_SITEMAP)
    except (HTTPError, URLError):
        return []
    urls = extract_sitemap_urls(sitemap, "/company/careers/")
    collected: list[dict] = []
    for url in urls:
        slug = urlparse(url).path.rsplit("/", 1)[-1].replace("-", " ")
        if job_titles and not any(title.lower() in slug.lower() for title in job_titles):
            continue
        try:
            html = fetch_url(url)
        except (HTTPError, URLError):
            continue
        posting = extract_jobposting_from_html(html, url, "Databricks")
        if posting:
            posting["id"] = f"databricks-{slugify(posting['title'])}"
            collected.append(posting)
        else:
            title = extract_meta_content(html, "property", "og:title") or normalize_whitespace(slug.title())
            description = extract_meta_content(html, "name", "description")
            collected.append(
                {
                    "id": f"databricks-{slugify(title)}",
                    "company": "Databricks",
                    "title": title,
                    "url": url,
                    "location": "",
                    "remote": "unknown",
                    "employment_type": "full-time",
                    "posted_at": "",
                    "description": description,
                    "skills": extract_skills_from_text(" ".join([title, description])),
                }
            )
        if len(collected) >= limit:
            break
    return unique_jobs(collected)[:limit]


def extract_snowflake_links(html: str) -> list[str]:
    patterns = [
        r'href="(/us/en/job/[^"]+)"',
        r'href="(https://careers\.snowflake\.com/us/en/job/[^"]+)"',
    ]
    links: list[str] = []
    for pattern in patterns:
        links.extend(re.findall(pattern, html, flags=re.IGNORECASE))
    return [urljoin("https://careers.snowflake.com", link) for link in links]


def collect_snowflake_jobs(job_titles: list[str] | None, limit: int = 20) -> list[dict]:
    collected: list[dict] = []
    try:
        search_html = fetch_url(SNOWFLAKE_RESULTS)
        links = extract_snowflake_links(search_html)
    except (HTTPError, URLError):
        links = []

    if not links:
        try:
            sitemap = fetch_url(SNOWFLAKE_SITEMAP)
            category_urls = extract_sitemap_urls(sitemap, "/us/en/c/")
        except (HTTPError, URLError):
            category_urls = []
        for url in category_urls[:10]:
            try:
                links.extend(extract_snowflake_links(fetch_url(url)))
            except (HTTPError, URLError):
                continue

    for url in unique_jobs({"url": link, "id": link} for link in links):
        link = url["url"]
        if len(collected) >= limit:
            break
        if job_titles and not any(title.lower().replace(" ", "-") in link.lower() for title in job_titles):
            continue
        try:
            html = fetch_url(link)
        except (HTTPError, URLError):
            continue
        posting = extract_jobposting_from_html(html, link, "Snowflake")
        if posting:
            posting["id"] = f"snowflake-{slugify(posting['title'])}"
            collected.append(posting)
        else:
            title = extract_meta_content(html, "property", "og:title") or normalize_whitespace(link.rsplit("/", 1)[-1].replace("-", " "))
            description = extract_meta_content(html, "name", "description")
            if title_matches(title, job_titles):
                collected.append(
                    {
                        "id": f"snowflake-{slugify(title)}",
                        "company": "Snowflake",
                        "title": title,
                        "url": link,
                        "location": "",
                        "remote": "unknown",
                        "employment_type": "full-time",
                        "posted_at": "",
                        "description": description,
                        "skills": extract_skills_from_text(" ".join([title, description])),
                    }
                )
    return unique_jobs(collected)[:limit]


def collect_live_jobs(
    out_path: str | None = None,
    job_titles: list[str] | None = None,
    companies: list[str] | None = None,
    limit_per_company: int = 20,
) -> list[dict]:
    jobs, _ = collect_live_jobs_with_diagnostics(out_path, job_titles, companies, limit_per_company)
    return jobs


def collect_live_jobs_with_diagnostics(
    out_path: str | None = None,
    job_titles: list[str] | None = None,
    companies: list[str] | None = None,
    limit_per_company: int = 20,
) -> tuple[list[dict], dict[str, dict]]:
    normalized = {company.strip().lower(): company.strip() for company in companies or [] if company.strip()}
    requested = set(normalized) or {"nvidia", "google", "databricks", "snowflake"}

    jobs: list[dict] = []
    diagnostics: dict[str, dict] = {}

    def run_collector(label: str, fn) -> None:
        try:
            collected = fn(job_titles, limit_per_company)
            jobs.extend(collected)
            diagnostics[label] = {
                "status": "ok",
                "jobs_collected": len(collected),
                "requested_titles": job_titles or [],
            }
        except Exception as exc:  # noqa: BLE001
            diagnostics[label] = {
                "status": "error",
                "jobs_collected": 0,
                "requested_titles": job_titles or [],
                "error": str(exc),
            }

    if "nvidia" in requested:
        run_collector("NVIDIA", collect_nvidia_jobs)
    if "google" in requested:
        run_collector("Google", collect_google_jobs)
    if "databricks" in requested:
        run_collector("Databricks", collect_databricks_jobs)
    if "snowflake" in requested:
        run_collector("Snowflake", collect_snowflake_jobs)

    filtered = unique_jobs(jobs)
    if out_path:
        dump_json(out_path, filtered)
    return filtered, diagnostics
