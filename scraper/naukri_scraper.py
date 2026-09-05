import logging
import os
import re
from typing import Any, Dict, List, Optional

from utils.browser_manager import BrowserManager, DEFAULT_USER_DATA_DIR
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class NaukriScraper(BaseScraper):
    """
    Naukri job scraper using Playwright persistent context with anti-bot handling and graceful degradation.
    """
    BASE_URL = "https://www.naukri.com"
    USER_DATA_DIR = DEFAULT_USER_DATA_DIR

    def __init__(self):
        self.platform_name = "Naukri"

    def _slugify_keyword(self, keyword: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", keyword).strip().lower()
        slug = re.sub(r"[\s-]+", "-", slug)
        return f"{slug}-jobs"

    def _extract_job_id(self, url: str, el_job_id: str = "") -> str:
        if el_job_id:
            return str(el_job_id)
        match = re.search(r"-([0-9]{6,})(?:\?|$)", url)
        if match:
            return match.group(1)
        return f"naukri_{abs(hash(url)) % 100000000}"

    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        if not keywords:
            return jobs

        primary_keyword = keywords[0] if keywords else "software-developer"
        category_slug = self._slugify_keyword(primary_keyword)
        target_url = f"{self.BASE_URL}/{category_slug}"

        logger.info(f"[Naukri] Starting scrape for {target_url} (limit={limit})...")
        os.makedirs(self.USER_DATA_DIR, exist_ok=True)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("[Naukri] Playwright not installed. Returning empty list.")
            return jobs

        try:
            with sync_playwright() as p:
                context = BrowserManager.get_persistent_context(
                    p,
                    headless=True,
                    user_data_dir=self.USER_DATA_DIR,
                    viewport={"width": 1366, "height": 768},
                    locale="en-US",
                    timezone_id="Asia/Kolkata",
                )
                page = context.pages[0] if context.pages else context.new_page()

                try:
                    page.goto(target_url, timeout=18000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    page_title = page.title()
                    if "Access Denied" in page_title or "Security Check" in page_title:
                        logger.warning("[Naukri] Anti-bot block encountered (Access Denied). Gracefully returning empty list.")
                        logger.warning("[Naukri] Tip: Run 'python auth_login.py --portal naukri' to save session cookies.")
                        return jobs

                    tuples = page.query_selector_all("div.srp-jobtuple-wrapper, article.jobTuple, div.cust-job-tuple, div.tuple")
                    logger.info(f"[Naukri] Found {len(tuples)} job tuples.")

                    for item in tuples:
                        if len(jobs) >= limit:
                            break

                        title_el = item.query_selector("a.title")
                        comp_el = item.query_selector("a.comp-name, a.subTitle")
                        exp_el = item.query_selector("span.expwdth, span.exp-wrap")
                        sal_el = item.query_selector("span.sal-wrap, span.ni-job-tuple-icon-srp-rupee")
                        loc_el = item.query_selector("span.loc-wrap, span.locWdth")
                        desc_el = item.query_selector("div.job-desc, span.job-desc, div.row6")
                        tag_els = item.query_selector_all("ul.tags-gt li, ul.tag-li li, li.dot-gt")

                        title = title_el.inner_text().strip() if title_el else ""
                        url = title_el.get_attribute("href") if title_el else ""
                        company = comp_el.inner_text().strip() if comp_el else "Naukri Recruiter"
                        experience = exp_el.inner_text().strip() if exp_el else ""
                        salary = sal_el.inner_text().strip() if sal_el else "Not specified"
                        location = loc_el.inner_text().strip() if loc_el else "India"
                        snippet = desc_el.inner_text().strip() if desc_el else ""
                        skills = ", ".join([t.inner_text().strip() for t in tag_els if t.inner_text().strip()])

                        if not title or not url:
                            continue

                        data_id = item.get_attribute("data-job-id") or ""
                        job_id = self._extract_job_id(url, data_id)
                        remote_level = "Fully Remote" if "remote" in location.lower() else "On-site / Hybrid"

                        full_desc = f"{title} at {company}.\nLocation: {location}\nExperience: {experience}\nSalary: {salary}\nDescription: {snippet}\nSkills: {skills}"

                        jobs.append({
                            "platform": self.platform_name,
                            "job_id_on_platform": str(job_id),
                            "title": title,
                            "company": company,
                            "location": location,
                            "remote_level": remote_level,
                            "url": url,
                            "description": full_desc[:3000],
                            "salary": salary,
                            "salary_range": salary,
                            "date_posted": None,
                            "skills": skills or ", ".join(keywords),
                            "skills_required": skills or ", ".join(keywords),
                        })
                finally:
                    context.close()
        except Exception as e:
            logger.warning(f"[Naukri] Scraper error: {e}")

        logger.info(f"[Naukri] Completed scrape. Found {len(jobs)} jobs.")
        return jobs
