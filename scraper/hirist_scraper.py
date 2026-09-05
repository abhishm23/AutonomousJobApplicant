import logging
import os
import re
from typing import Any, Dict, List, Optional

from utils.browser_manager import BrowserManager, DEFAULT_USER_DATA_DIR
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class HiristScraper(BaseScraper):
    """
    Hirist job scraper using Playwright category-based search (/k/{keyword}-jobs).
    """
    BASE_URL = "https://www.hirist.tech"
    USER_DATA_DIR = DEFAULT_USER_DATA_DIR

    def __init__(self):
        self.platform_name = "Hirist"

    def _slugify_keyword(self, keyword: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", keyword).strip().lower()
        slug = re.sub(r"[\s-]+", "-", slug)
        return f"{slug}-jobs"

    def _extract_job_id(self, url: str) -> str:
        match = re.search(r"-([0-9]{5,})", url)
        if match:
            return match.group(1)
        return f"hirist_{abs(hash(url)) % 100000000}"

    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        if not keywords:
            return jobs

        primary_keyword = keywords[0] if keywords else "technology"
        category_slug = self._slugify_keyword(primary_keyword)
        target_url = f"{self.BASE_URL}/k/{category_slug}"

        logger.info(f"[Hirist] Scraping {target_url} (limit={limit})...")
        os.makedirs(self.USER_DATA_DIR, exist_ok=True)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("[Hirist] Playwright not installed. Returning empty list.")
            return jobs

        try:
            with sync_playwright() as p:
                context = BrowserManager.get_persistent_context(
                    p,
                    headless=True,
                    user_data_dir=self.USER_DATA_DIR,
                    viewport={"width": 1280, "height": 800},
                )
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(target_url, timeout=18000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    card_links = page.query_selector_all('a[href*="/j/"]')
                    logger.info(f"[Hirist] Found {len(card_links)} job cards.")

                    for card in card_links:
                        if len(jobs) >= limit:
                            break

                        href = card.get_attribute("href") or ""
                        if not href:
                            continue

                        full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                        job_id = self._extract_job_id(href)

                        # Extract title and company
                        title_el = card.query_selector('[data-testid="job_title"], p')
                        full_title_text = title_el.inner_text().strip() if title_el else ""

                        if " - " in full_title_text:
                            parts = full_title_text.split(" - ", 1)
                            company = parts[0].strip()
                            title = parts[1].strip()
                        elif " | " in full_title_text:
                            parts = full_title_text.split(" | ", 1)
                            company = parts[0].strip()
                            title = parts[1].strip()
                        else:
                            company = "Hirist Recruiter"
                            title = full_title_text or "Software Engineer"

                        # Extract location, experience, skills
                        p_elements = card.query_selector_all("p")
                        location = "India / Remote"
                        for p_tag in p_elements:
                            p_text = p_tag.inner_text().strip()
                            if p_text and p_text != full_title_text:
                                location = p_text
                                break

                        span_elements = card.query_selector_all("span")
                        spans_text = [s.inner_text().strip() for s in span_elements if s.inner_text().strip()]

                        experience = ""
                        date_posted: Optional[str] = None
                        salary = "Not specified"
                        skills_list: List[str] = []

                        for s_text in spans_text:
                            s_lower = s_text.lower()
                            if "yr" in s_lower or "exp" in s_lower:
                                experience = s_text
                            elif "posted" in s_lower or "day" in s_lower or "ago" in s_lower:
                                date_posted = s_text
                            elif "lpa" in s_lower or "inr" in s_lower or "$" in s_text:
                                salary = s_text
                            elif len(s_text) < 30 and not any(k in s_lower for k in ["save", "apply", "view"]):
                                if s_text not in skills_list:
                                    skills_list.append(s_text)

                        skills_str = ", ".join(skills_list) if skills_list else ", ".join(keywords)
                        remote_level = "Fully Remote" if "remote" in location.lower() else "On-site / Hybrid"

                        description = (
                            f"Position: {title} at {company}.\n"
                            f"Location: {location} ({remote_level}).\n"
                            f"Experience required: {experience or 'Not specified'}.\n"
                            f"Salary: {salary}.\n"
                            f"Key skills: {skills_str}."
                        )

                        jobs.append({
                            "platform": self.platform_name,
                            "job_id_on_platform": str(job_id),
                            "title": title,
                            "company": company,
                            "location": location,
                            "remote_level": remote_level,
                            "url": full_url,
                            "description": description[:3000],
                            "salary": salary,
                            "salary_range": salary,
                            "date_posted": date_posted,
                            "skills": skills_str,
                            "skills_required": skills_str,
                        })
                finally:
                    context.close()
        except Exception as e:
            logger.warning(f"[Hirist] Scraper error: {e}")

        logger.info(f"[Hirist] Completed scrape. Found {len(jobs)} jobs.")
        return jobs
