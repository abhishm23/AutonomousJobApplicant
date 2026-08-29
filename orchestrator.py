"""Main pipeline: scrape → evaluate → tailor."""

import json
import os

from scraper.multi_scraper import scrape_all
from db.database import Database
from agents.evaluator_agent import evaluate_job
from agents.resume_tailor_agent import tailor_resume
from resume_engine.resume_parser import extract_resume_from_upload


BASE_RESUME_PATH = os.path.join(os.path.dirname(__file__), "base_resume.json")


def _load_base_resume():
    if os.path.exists(BASE_RESUME_PATH):
        with open(BASE_RESUME_PATH, "r") as f:
            return json.load(f)
    return {}


def run_pipeline(resume_text=None, resume_json=None, keywords=None, min_score=70, progress_callback=None):
    """Scrape jobs, evaluate against resume, tailor for top matches."""
    db = Database()
    if progress_callback:
        progress_callback("Starting pipeline...")

    base_resume = _load_base_resume()
    resume_data = base_resume
    if resume_json and isinstance(resume_json, dict):
        resume_data = resume_json
    elif resume_text and isinstance(resume_text, str):
        resume_data = {"raw_text": resume_text}

    resume_str = json.dumps(resume_data)

    if not keywords:
        from config import config
        keywords = [k.strip() for k in config.TARGET_ROLES.split(",") if k.strip()]

    # Phase 1: Scrape
    if progress_callback:
        progress_callback("Scraping job boards...")
    raw_jobs = scrape_all(keywords)

    stored = 0
    for job in raw_jobs:
        result = db.insert_job(
            job["platform"],
            job.get("job_id_on_platform", ""),
            job["title"],
            job["company"],
            job.get("description", ""),
            job.get("url", ""),
            job.get("salary_range", ""),
            job.get("remote_level", ""),
            job.get("skills_required", ""),
        )
        if result:
            stored += 1

    if progress_callback:
        progress_callback(f"Scraped {len(raw_jobs)} jobs, {stored} new.")

    # Phase 2: Evaluate
    unevaluated = db.get_unevaluated_jobs()
    if progress_callback:
        progress_callback(f"Evaluating {len(unevaluated)} jobs...")

    for job_id, title, company, description in unevaluated:
        try:
            score, reasoning = evaluate_job(description, resume_str)
            db.update_job_match(job_id, score, reasoning)
        except Exception as e:
            if progress_callback:
                progress_callback(f"  Failed to evaluate {title}: {e}")

    # Phase 3: Tailor
    if progress_callback:
        progress_callback("Tailoring resumes for top matches...")

    high_match = db.get_evaluated_jobs_for_application(min_score=min_score)
    for job_id, title, company, description, url in high_match:
        try:
            tailored = tailor_resume(resume_str, description, title, company)
            app_resume_json = json.dumps(tailored)
            resume_html = _generate_html_resume(tailored)
            db.insert_application(job_id, app_resume_json, resume_html)
        except Exception as e:
            if progress_callback:
                progress_callback(f"  Failed to tailor for {title}: {e}")

    if progress_callback:
        progress_callback("Pipeline complete!")

    return {
        "total_scraped": len(raw_jobs),
        "newly_stored": stored,
        "evaluated": len(unevaluated),
        "ready": len(high_match),
    }


def _generate_html_resume(resume_data):
    """Generate a simple HTML resume from structured data."""
    parts = ["<html><body>"]
    name = resume_data.get("name", "")
    if name:
        parts.append(f"<h1>{name}</h1>")
    email = resume_data.get("email", "")
    if email:
        parts.append(f"<p>Email: {email}</p>")
    summary = resume_data.get("summary", "")
    if summary:
        parts.append(f"<h2>Summary</h2><p>{summary}</p>")

    experience = resume_data.get("experience", [])
    if experience:
        parts.append("<h2>Experience</h2>")
        for exp in experience:
            company = exp.get("company", "")
            role = exp.get("role", "")
            dates = exp.get("dates", "")
            header = f"{role}" + (f" at {company}" if company else "")
            if dates:
                header += f" ({dates})"
            parts.append(f"<h3>{header}</h3>")
            bullets = exp.get("bullets", [])
            if bullets:
                parts.append("<ul>")
                for b in bullets:
                    parts.append(f"<li>{b}</li>")
                parts.append("</ul>")

    skills = resume_data.get("skills", [])
    if skills:
        parts.append("<h2>Skills</h2>")
        if isinstance(skills, list):
            parts.append("<p>" + ", ".join(skills) + "</p>")
        else:
            parts.append(f"<p>{skills}</p>")

    parts.append("</body></html>")
    return "\n".join(parts)
