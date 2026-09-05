"""
Multi-source job scraper coordinator.
Executes active scrapers concurrently with ThreadPoolExecutor, 25-second timeouts,
universal job contract normalization, complete error isolation, and deduplication.
"""

import concurrent.futures
import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .base_scraper import BaseScraper
from .himalayas_scraper import HimalayasScraper
from .hirist_scraper import HiristScraper
from .linkedin_scraper import LinkedInScraper
from .naukri_scraper import NaukriScraper
from .remotive_scraper import RemotiveScraper
from .wellfound_scraper import WellfoundScraper

logger = logging.getLogger(__name__)

# Active Scraper Registry (Free Direct Portals)
SCRAPERS = {
    "LinkedIn": LinkedInScraper,
    "Naukri": NaukriScraper,
    "Wellfound": WellfoundScraper,
    "Hirist": HiristScraper,
    "Himalayas": HimalayasScraper,
    "Remotive": RemotiveScraper,
}

DEFAULT_SCRAPER_TIMEOUT = 25.0


def _normalize_job(raw_job: Dict[str, Any], default_platform: str = "Unknown") -> Dict[str, Any]:
    """
    Normalizes and sanitizes a raw job dictionary into the standard interface contract.
    Ensures strict typing, field fallback, SHA-256 fallback job ID, and cross-field compatibility.
    """
    if not isinstance(raw_job, dict):
        return {}

    # Extract platform
    platform = str(raw_job.get("platform") or default_platform).strip()
    if not platform:
        platform = "Unknown"

    # Extract title and company
    title = str(raw_job.get("title") or "Untitled Position").strip()
    if not title:
        title = "Untitled Position"

    company = str(raw_job.get("company") or "Unknown Company").strip()
    if not company:
        company = "Unknown Company"

    # Extract url
    url = str(raw_job.get("url") or "").strip()

    # Extract or generate job_id_on_platform
    raw_job_id = raw_job.get("job_id_on_platform")
    job_id = str(raw_job_id).strip() if raw_job_id is not None else ""

    if not job_id:
        # Generate deterministic SHA-256 fallback hash based on platform, title, company, url
        seed = f"{platform.lower()}:{title.lower()}:{company.lower()}:{url.lower()}"
        job_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    # Extract and clean description (max 3000 chars)
    raw_desc = raw_job.get("description")
    description = str(raw_desc).strip() if raw_desc is not None else ""
    if len(description) > 3000:
        description = description[:3000]

    # Extract location / remote_level
    location = raw_job.get("location") or raw_job.get("remote_level") or "Remote"
    location_str = str(location).strip()

    # Extract salary / salary_range
    salary = raw_job.get("salary") or raw_job.get("salary_range")
    salary_str = str(salary).strip() if salary is not None else "Not specified"
    if not salary_str:
        salary_str = "Not specified"

    # Extract date_posted
    date_posted = raw_job.get("date_posted")
    date_posted_str = str(date_posted).strip() if date_posted is not None else None

    # Extract skills / skills_required
    skills = raw_job.get("skills") or raw_job.get("skills_required")
    if isinstance(skills, list):
        skills_str = ", ".join(str(s).strip() for s in skills if s)
    elif skills is not None:
        skills_str = str(skills).strip()
    else:
        skills_str = ""

    return {
        "job_id_on_platform": job_id,
        "platform": platform,
        "title": title,
        "company": company,
        "location": location_str,
        "url": url,
        "description": description,
        "salary": salary_str if salary_str != "Not specified" else None,
        "date_posted": date_posted_str,
        "skills": skills_str if skills_str else None,
        # Backward compatibility aliases for existing db/database.py & orchestrator.py
        "salary_range": salary_str,
        "remote_level": location_str,
        "skills_required": skills_str,
    }


def _run_single_scraper(
    name: str,
    scraper_cls: Any,
    keywords: List[str],
    limit: int
) -> List[Dict[str, Any]]:
    """
    Safely instantiates and executes a single scraper with try/except isolation.
    Returns normalized job dicts; never raises exceptions to caller.
    """
    logger.info(f"[{name}] Starting scraper execution for keywords: {keywords}")
    try:
        scraper = scraper_cls()
        raw_jobs = scraper.scrape_jobs(keywords, limit=limit)

        if not isinstance(raw_jobs, list):
            logger.warning(f"[{name}] Scraper returned non-list type: {type(raw_jobs)}. Returning empty list.")
            return []

        normalized_jobs = []
        for raw in raw_jobs:
            if isinstance(raw, dict):
                norm = _normalize_job(raw, default_platform=name)
                if norm:
                    normalized_jobs.append(norm)

        logger.info(f"[{name}] Successfully scraped {len(normalized_jobs)} jobs.")
        return normalized_jobs

    except Exception as e:
        logger.error(f"[{name}] Scraper failed with unhandled exception: {e}", exc_info=True)
        return []


def scrape_all(
    keywords: List[str],
    limit_per_source: int = 10,
    enabled_sources: Optional[List[str]] = None,
    timeout: float = DEFAULT_SCRAPER_TIMEOUT,
) -> List[Dict[str, Any]]:
    """
    Concurrently coordinates all active scrapers with timeout protection,
    per-scraper error isolation, and composite key deduplication.

    Args:
        keywords: List of search terms/titles.
        limit_per_source: Maximum jobs to fetch per individual scraper.
        enabled_sources: Optional list of platform names to run. If None, runs all in SCRAPERS.
        timeout: Maximum seconds to wait for each scraper before timing out (default 25s).

    Returns:
        Deduplicated list of normalized job dictionaries.
    """
    # Select active scrapers
    if enabled_sources:
        active_scrapers = {k: v for k, v in SCRAPERS.items() if k in enabled_sources}
    else:
        active_scrapers = dict(SCRAPERS)

    if not active_scrapers:
        logger.warning("No active scrapers selected for scraping.")
        return []

    logger.info(f"Initiating concurrent scrape across {len(active_scrapers)} sources: {list(active_scrapers.keys())}")

    raw_results: List[Dict[str, Any]] = []
    max_workers = min(len(active_scrapers), 8)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_to_source = {
            executor.submit(_run_single_scraper, name, cls, keywords, limit_per_source): name
            for name, cls in active_scrapers.items()
        }

        # Wait for all futures with the specified timeout
        done, not_done = concurrent.futures.wait(
            future_to_source.keys(),
            timeout=timeout,
            return_when=concurrent.futures.ALL_COMPLETED,
        )

        # Process completed tasks
        for future in done:
            source_name = future_to_source[future]
            try:
                jobs = future.result()
                if jobs:
                    raw_results.extend(jobs)
            except Exception as e:
                logger.error(f"[{source_name}] Error retrieving future result: {e}", exc_info=True)

        # Log timed-out scrapers
        for future in not_done:
            source_name = future_to_source[future]
            logger.warning(f"[{source_name}] Scraper timed out after {timeout}s. Skipping.")
            future.cancel()
    finally:
        # Avoid blocking caller on long-running/timed-out threads
        executor.shutdown(wait=False, cancel_futures=True)

    # Deduplicate by (platform, job_id_on_platform)
    seen_keys: Set[Tuple[str, str]] = set()
    unique_jobs: List[Dict[str, Any]] = []

    for job in raw_results:
        platform = job.get("platform", "").lower().strip()
        job_id = job.get("job_id_on_platform", "").strip()
        composite_key = (platform, job_id)

        if composite_key not in seen_keys:
            seen_keys.add(composite_key)
            unique_jobs.append(job)

    logger.info(f"Scrape complete: {len(raw_results)} total fetched, {len(unique_jobs)} unique jobs after deduplication.")
    return unique_jobs


# Public convenience aliases
normalize_job = _normalize_job
run_single_scraper = _run_single_scraper
