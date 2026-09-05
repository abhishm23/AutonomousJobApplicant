import logging
import os
import re
from typing import Any, Dict, List, Optional

from utils.browser_manager import BrowserManager, DEFAULT_USER_DATA_DIR
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class WellfoundScraper(BaseScraper):
    """
    Wellfound (formerly AngelList Talent) scraper using Playwright persistent context.
    """
    BASE_URL = "https://wellfound.com"
    USER_DATA_DIR = DEFAULT_USER_DATA_DIR

    def __init__(self):
        self.platform_name = "Wellfound"

    def _slugify_role(self, keyword: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", keyword).strip().lower()
        slug = re.sub(r"[\s-]+", "-", slug)
        return slug

    def _extract_job_id(self, url: str) -> str:
        match = re.search(r"/jobs/([0-9]{5,})", url)
        if match:
            return match.group(1)
        return f"wellfound_{abs(hash(url)) % 100000000}"

    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        if not keywords:
            return jobs

        primary_role = keywords[0] if keywords else "software-engineer"
        role_slug = self._slugify_role(primary_role)
        target_url = f"{self.BASE_URL}/role/{role_slug}"

        logger.info(f"[Wellfound] Starting scrape for {target_url} (limit={limit})...")
        os.makedirs(self.USER_DATA_DIR, exist_ok=True)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("[Wellfound] Playwright not installed. Returning empty list.")
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
                    response = page.goto(target_url, timeout=18000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    # If role page 404s, fallback to /jobs
                    if response and response.status == 404:
                        logger.info("[Wellfound] Role page 404, falling back to https://wellfound.com/jobs...")
                        page.goto(f"{self.BASE_URL}/jobs", timeout=15000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)

                    # Find job links and cards
                    job_anchors = page.query_selector_all("a[href*='/jobs/']")
                    logger.info(f"[Wellfound] Found {len(job_anchors)} job links.")

                    seen_urls = set()
                    for a in job_anchors:
                        if len(jobs) >= limit:
                            break

                        href = a.get_attribute("href") or ""
                        if not href or "/signup" in href or "/login" in href:
                            continue

                        full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        title = a.inner_text().strip()
                        if not title or len(title) > 100:
                            continue

                        job_id = self._extract_job_id(full_url)

                        # Try to locate parent card text for company and salary
                        card_parent = a.evaluate_handle("el => el.closest('div[class*=\"styles_result\"], [data-test=\"StartupResult\"]')")
                        card_text = card_parent.as_element().inner_text() if card_parent and card_parent.as_element() else ""

                        company = "Startup Employer"
                        salary = "Not specified"
                        location = "Remote"

                        if card_text:
                            lines = [line.strip() for line in card_text.split("\n") if line.strip()]
                            if lines:
                                company = lines[0]
                            # Look for salary patterns like $120k - $150k
                            sal_match = re.search(r"(\$[0-9]+k?\s*[-–—]\s*\$[0-9]+k?)", card_text)
                            if sal_match:
                                salary = sal_match.group(1)
                            if "remote" in card_text.lower():
                                location = "Remote"

                        desc = f"{title} at {company}. Startup job opportunity on Wellfound. Location: {location}. Compensation: {salary}."
                        skills_str = ", ".join(keywords) if keywords else ""

                        jobs.append({
                            "platform": self.platform_name,
                            "job_id_on_platform": str(job_id),
                            "title": title,
                            "company": company,
                            "location": location,
                            "remote_level": "Fully Remote" if "remote" in location.lower() else "Hybrid / On-site",
                            "url": full_url,
                            "description": desc[:3000],
                            "salary": salary,
                            "salary_range": salary,
                            "date_posted": None,
                            "skills": skills_str,
                            "skills_required": skills_str,
                        })
                finally:
                    context.close()
        except Exception as e:
            logger.warning(f"[Wellfound] Scraper error: {e}")

        logger.info(f"[Wellfound] Completed scrape. Found {len(jobs)} jobs.")
        return jobs
