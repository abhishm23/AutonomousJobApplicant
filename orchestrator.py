"""
End-to-End Pipeline Orchestrator for Autonomous Job Applicant.

Coordinates multi-portal scraping, DuckDB reverse-chronological ingestion,
composite-key deduplication, ATS match evaluation, tailored resume generation,
and initial application creation.
"""

import argparse
import json
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Union

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import config
from db.database import Database
from scraper.multi_scraper import scrape_all
from agents.evaluator_agent import evaluate_job
from agents.resume_tailor_agent import tailor_resume
from resume_engine.generator import ResumeGenerator
from utils.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

BASE_RESUME_PATH = os.path.join(PROJECT_ROOT, "base_resume.json")


def _load_base_resume() -> Dict[str, Any]:
    """Loads base resume dictionary from base_resume.json if present."""
    if os.path.exists(BASE_RESUME_PATH):
        try:
            with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse {BASE_RESUME_PATH}: {e}")
    return {}


def _generate_html_resume(resume_data: Union[Dict[str, Any], str]) -> str:
    """Generate HTML formatted resume from structured dictionary or JSON string."""
    try:
        generator = ResumeGenerator()
        return generator.generate(resume_data)
    except Exception as e:
        logger.warning(f"ResumeGenerator failed, using fallback HTML generator: {e}")

    # Fallback basic HTML generator
    if isinstance(resume_data, str):
        try:
            resume_data = json.loads(resume_data)
        except Exception:
            return f"<html><body><pre>{resume_data}</pre></body></html>"

    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'><style>body{font-family:sans-serif;margin:30px;line-height:1.5;}</style></head><body>"]
    name = resume_data.get("name", "")
    if name:
        parts.append(f"<h1>{name}</h1>")
    email = resume_data.get("email", "")
    phone = resume_data.get("phone", "")
    contact_parts = [p for p in [email, phone] if p]
    if contact_parts:
        parts.append(f"<p>{' · '.join(contact_parts)}</p>")

    summary = resume_data.get("summary", "")
    if summary:
        parts.append(f"<h2>Summary</h2><p>{summary}</p>")

    experience = resume_data.get("experience", [])
    if experience:
        parts.append("<h2>Experience</h2>")
        for exp in experience:
            if isinstance(exp, dict):
                company = exp.get("company", "")
                role = exp.get("role", "")
                dates = exp.get("dates", "")
                location = exp.get("location", "")
                header = f"{role}" + (f" at {company}" if company else "")
                meta = " · ".join(p for p in [dates, location] if p)
                parts.append(f"<h3>{header}</h3>")
                if meta:
                    parts.append(f"<p><em>{meta}</em></p>")
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
            parts.append("<p>" + ", ".join(str(s) for s in skills) + "</p>")
        else:
            parts.append(f"<p>{skills}</p>")

    education = resume_data.get("education", "")
    if education:
        parts.append(f"<h2>Education</h2><p>{education}</p>")

    parts.append("</body></html>")
    return "\n".join(parts)


def evaluate_pending_jobs(
    db: Optional[Database] = None,
    resume_data: Optional[Union[Dict[str, Any], str]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    limit: int = 100,
) -> int:
    """
    Evaluates all unevaluated jobs in DuckDB against the provided resume.
    Strictly skips jobs already marked as applied or existing in Applications.

    Returns:
        Count of successfully evaluated jobs.
    """
    owned_db = False
    if db is None:
        db = Database()
        owned_db = True

    try:
        if resume_data is None:
            resume_data = _load_base_resume()
        resume_str = json.dumps(resume_data) if isinstance(resume_data, dict) else str(resume_data)

        unevaluated = db.get_unevaluated_jobs(limit=limit)
        if progress_callback:
            progress_callback(f"Evaluating {len(unevaluated)} unevaluated jobs against resume...")

        evaluated_count = 0
        for job in unevaluated:
            job_id = job.get("id") if isinstance(job, dict) else job[0]
            title = job.get("title", "Position") if isinstance(job, dict) else job[1]
            description = job.get("description", "") if isinstance(job, dict) else (job[3] if len(job) > 3 else "")

            try:
                score, reasoning = evaluate_job(description, resume_str)
                db.update_job_score(job_id, score, reasoning)
                evaluated_count += 1
                if progress_callback:
                    progress_callback(f"  Evaluated '{title}': Score {score}%")
            except Exception as e:
                logger.error(f"Failed to evaluate job ID {job_id} ('{title}'): {e}")
                if progress_callback:
                    progress_callback(f"  Warning: Evaluation failed for '{title}': {e}")

        return evaluated_count
    finally:
        if owned_db:
            db.close()


def tailor_high_match_jobs(
    db: Optional[Database] = None,
    resume_data: Optional[Union[Dict[str, Any], str]] = None,
    min_score: int = 70,
    progress_callback: Optional[Callable[[str], None]] = None,
    limit: int = 50,
) -> int:
    """
    Tailors resumes for top-matching evaluated jobs and generates initial applications
    in 'Ready to Apply' status. Strictly skips jobs already in Applications.

    Returns:
        Count of applications created.
    """
    owned_db = False
    if db is None:
        db = Database()
        owned_db = True

    try:
        if resume_data is None:
            resume_data = _load_base_resume()
        resume_dict = resume_data if isinstance(resume_data, dict) else {"raw_text": str(resume_data)}
        resume_str = json.dumps(resume_dict)

        candidates = db.get_evaluated_jobs_for_application(min_score=min_score, limit=limit)
        if progress_callback:
            progress_callback(f"Found {len(candidates)} high-match roles (>= {min_score}%). Generating tailored resumes...")

        ready_count = 0
        for job in candidates:
            job_id = job.get("id") if isinstance(job, dict) else job[0]
            title = job.get("title", "Position") if isinstance(job, dict) else job[1]
            company = job.get("company", "Company") if isinstance(job, dict) else job[2]
            description = job.get("description", "") if isinstance(job, dict) else (job[3] if len(job) > 3 else "")

            try:
                tailored = tailor_resume(resume_dict, description, title, company)
                app_resume_json = json.dumps(tailored)
                resume_html = _generate_html_resume(tailored)
                db.insert_application(
                    job_id=job_id,
                    resume_json=app_resume_json,
                    resume_html=resume_html,
                    status="Ready to Apply",
                    notes="Auto-tailored by pipeline",
                )
                ready_count += 1
                if progress_callback:
                    progress_callback(f"  Tailored resume ready for '{title}' at {company}")
            except Exception as e:
                logger.error(f"Failed to tailor resume for job ID {job_id} ('{title}'): {e}")
                if progress_callback:
                    progress_callback(f"  Warning: Tailoring failed for '{title}': {e}")

        return ready_count
    finally:
        if owned_db:
            db.close()


def run_pipeline(
    resume_text: Optional[str] = None,
    resume_json: Optional[Union[Dict[str, Any], str]] = None,
    keywords: Optional[List[str]] = None,
    min_score: int = 70,
    limit_per_source: int = 10,
    enabled_sources: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    db: Optional[Database] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the full end-to-end autonomous job applicant workflow:
    1. Scrape: Concurrently scrape free direct job boards (Himalayas, Remotive, LinkedIn, Naukri, Wellfound, Hirist).
    2. Ingest: Reverse-chronological deduplication in DuckDB with composite keys.
    3. Evaluate: Score unevaluated listings against resume (Gemini with keyword fallback).
    4. Tailor: Customize resume for high-match roles and create 'Ready to Apply' applications.

    Args:
        resume_text: Raw resume text string.
        resume_json: Structured resume dictionary or JSON string.
        keywords: Target role keywords / search terms.
        min_score: Minimum match score threshold for tailoring (0-100).
        limit_per_source: Max jobs to scrape per portal.
        enabled_sources: Optional list of enabled portal names.
        progress_callback: Optional status update callable for UI/CLI.
        db: Optional existing Database instance.
        db_path: Optional database file path.

    Returns:
        Dictionary summarizing pipeline metrics.
    """
    owned_db = False
    if db is None:
        db = Database(db_path=db_path)
        owned_db = True

    errors: List[str] = []

    try:
        if progress_callback:
            progress_callback("Initializing pipeline and parsing resume...")

        # 1. Resolve resume data
        base_resume = _load_base_resume()
        if resume_json and isinstance(resume_json, dict):
            resume_data = resume_json
        elif resume_json and isinstance(resume_json, str):
            try:
                resume_data = json.loads(resume_json)
            except Exception:
                resume_data = {"raw_text": resume_json}
        elif resume_text and isinstance(resume_text, str):
            resume_data = {"raw_text": resume_text}
        elif base_resume:
            resume_data = base_resume
        else:
            resume_data = {"raw_text": "Software and Data Engineer with AI automation experience."}

        resume_str = json.dumps(resume_data)

        # 2. Resolve keywords
        if not keywords:
            target_str = getattr(config, "TARGET_ROLES", "Software Engineer, Data Engineer")
            keywords = [k.strip() for k in target_str.split(",") if k.strip()]

        # ── Phase 1: Scrape & Ingest ──
        if progress_callback:
            progress_callback(f"Scraping job boards for: {', '.join(keywords)}...")

        raw_jobs = scrape_all(
            keywords=keywords,
            limit_per_source=limit_per_source,
            enabled_sources=enabled_sources,
        )

        newly_stored = 0
        for job in raw_jobs:
            try:
                _, is_new = db.insert_job(job)
                if is_new:
                    newly_stored += 1
            except Exception as e:
                logger.error(f"Error inserting scraped job {job.get('title')}: {e}")
                errors.append(f"Insert error: {e}")

        if progress_callback:
            progress_callback(f"Scraped {len(raw_jobs)} listings ({newly_stored} new listings stored).")

        # ── Phase 2: Evaluate ──
        evaluated_count = evaluate_pending_jobs(
            db=db,
            resume_data=resume_data,
            progress_callback=progress_callback,
            limit=100,
        )

        # ── Phase 3: Tailor & Create Applications ──
        ready_count = tailor_high_match_jobs(
            db=db,
            resume_data=resume_data,
            min_score=min_score,
            progress_callback=progress_callback,
            limit=50,
        )

        if progress_callback:
            progress_callback("Autonomous pipeline run complete!")

        return {
            "total_scraped": len(raw_jobs),
            "newly_stored": newly_stored,
            "evaluated": evaluated_count,
            "ready": ready_count,
            "status": "success",
            "errors": errors,
        }

    finally:
        if owned_db:
            db.close()


def main() -> int:
    """CLI runner for orchestrator."""
    parser = argparse.ArgumentParser(description="Autonomous Job Applicant Orchestrator")
    parser.add_argument("--keywords", type=str, help="Comma-separated keywords (e.g. 'python, data engineer')")
    parser.add_argument("--min-score", type=int, default=70, help="Minimum score threshold (default: 70)")
    parser.add_argument("--limit-per-source", type=int, default=10, help="Max jobs per source (default: 10)")
    parser.add_argument("--resume-path", type=str, default=None, help="Path to resume JSON or text file")
    args = parser.parse_args()

    kw_list = [k.strip() for k in args.keywords.split(",")] if args.keywords else None
    resume_data = None
    if args.resume_path and os.path.exists(args.resume_path):
        with open(args.resume_path, "r", encoding="utf-8") as f:
            content = f.read()
            try:
                resume_data = json.loads(content)
            except Exception:
                resume_data = content

    print("\n" + "=" * 60)
    print("🚀 Starting Autonomous Job Applicant Pipeline")
    print("=" * 60)

    result = run_pipeline(
        resume_json=resume_data if isinstance(resume_data, dict) else None,
        resume_text=resume_data if isinstance(resume_data, str) else None,
        keywords=kw_list,
        min_score=args.min_score,
        limit_per_source=args.limit_per_source,
        progress_callback=print,
    )

    print("\n" + "=" * 60)
    print("📊 Pipeline Execution Summary")
    print("=" * 60)
    print(f"Total Scraped: {result['total_scraped']}")
    print(f"Newly Stored:  {result['newly_stored']}")
    print(f"Evaluated:     {result['evaluated']}")
    print(f"Ready to Apply:{result['ready']}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
