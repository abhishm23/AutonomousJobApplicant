import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from utils.browser_manager import BrowserManager, DEFAULT_USER_DATA_DIR
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class LinkedInScraper(BaseScraper):
    """
    LinkedIn job scraper using public Guest API with Playwright persistent context fallback.
    """
    GUEST_API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    USER_DATA_DIR = DEFAULT_USER_DATA_DIR

    def __init__(self):
        self.platform_name = "LinkedIn"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _clean_html(self, text: Optional[str]) -> str:
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", clean).strip()

    def _extract_job_id(self, url: str) -> str:
        if not url:
            return ""
        match = re.search(r"view/.*?([0-9]{7,})", url)
        if match:
            return match.group(1)
        match = re.search(r"-([0-9]{7,})(?:\?|$)", url)
        if match:
            return match.group(1)
        return f"li_{abs(hash(url)) % 100000000}"

    def _fetch_job_description(self, job_url: str) -> str:
        try:
            resp = requests.get(job_url, headers=self.headers, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                desc_el = (
                    soup.find("div", class_="show-more-less-html__markup")
                    or soup.find("div", class_="description__text")
                    or soup.find("section", class_="show-more-less-html")
                )
                if desc_el:
                    return self._clean_html(desc_el.get_text(separator=" "))[:3000]
        except Exception:
            pass
        return ""

    def _scrape_guest_api(self, keywords: List[str], limit: int) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        query = " ".join(keywords[:3]) if keywords else "software engineer"
        params = {
            "keywords": query,
            "location": "Remote",
            "start": 0,
        }

        try:
            resp = requests.get(self.GUEST_API_URL, params=params, headers=self.headers, timeout=12)
            if resp.status_code != 200:
                logger.warning(f"[LinkedIn] Guest API returned status {resp.status_code}")
                return jobs

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("li")
            if not cards:
                cards = soup.find_all("div", class_="base-card")

            for card in cards:
                if len(jobs) >= limit:
                    break

                title_el = card.find("h3", class_="base-search-card__title") or card.find(class_="base-card__title")
                comp_el = card.find("h4", class_="base-search-card__subtitle") or card.find(class_="base-card__subtitle")
                link_el = card.find("a", class_="base-card__full-link") or card.find("a", href=re.compile(r"/jobs/view/"))
                loc_el = card.find("span", class_="job-search-card__location")
                time_el = card.find("time")
                sal_el = card.find("span", class_="job-search-card__salary-info")

                title = title_el.get_text(strip=True) if title_el else ""
                company = comp_el.get_text(strip=True) if comp_el else ""
                url = link_el["href"].split("?")[0] if (link_el and "href" in link_el.attrs) else ""
                location = loc_el.get_text(strip=True) if loc_el else "Remote"
                date_posted = time_el.get("datetime") or time_el.get_text(strip=True) if time_el else None
                salary = sal_el.get_text(strip=True) if sal_el else "Not specified"

                if not title or not company or not url:
                    continue

                job_id = self._extract_job_id(url)
                description = self._fetch_job_description(url)
                if not description:
                    description = f"{title} at {company} in {location}. Remote opportunities available."

                skills_str = ", ".join(keywords) if keywords else ""

                jobs.append({
                    "platform": self.platform_name,
                    "job_id_on_platform": str(job_id),
                    "title": title,
                    "company": company,
                    "location": location,
                    "remote_level": "Fully Remote" if "remote" in location.lower() else location,
                    "url": url,
                    "description": description[:3000],
                    "salary": salary,
                    "salary_range": salary,
                    "date_posted": date_posted,
                    "skills": skills_str,
                    "skills_required": skills_str,
                })
        except Exception as e:
            logger.warning(f"[LinkedIn] Guest API error: {e}")

        return jobs

    def _scrape_playwright_fallback(self, keywords: List[str], limit: int) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("[LinkedIn] Playwright not installed. Skipping browser fallback.")
            return jobs

        query = "+".join(keywords[:3]) if keywords else "software+engineer"
        search_url = f"https://www.linkedin.com/jobs/search/?keywords={query}&f_WT=2"

        try:
            with sync_playwright() as p:
                context = BrowserManager.get_persistent_context(
                    p,
                    headless=True,
                    user_data_dir=self.USER_DATA_DIR,
                    user_agent=self.headers.get("User-Agent"),
                    viewport={"width": 1280, "height": 800},
                )
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(search_url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    card_elements = page.query_selector_all("li.jobs-search-results__list-item, div.job-card-container, div.base-card")
                    for el in card_elements:
                        if len(jobs) >= limit:
                            break
                        title_el = el.query_selector("a.job-card-list__title, h3.base-search-card__title, .job-card-container__link")
                        comp_el = el.query_selector(".job-card-container__primary-description, h4.base-search-card__subtitle")
                        link_el = el.query_selector("a.job-card-list__title, a.base-card__full-link")
                        loc_el = el.query_selector("li.job-card-container__metadata-item, span.job-search-card__location")

                        title = title_el.inner_text().strip() if title_el else ""
                        company = comp_el.inner_text().strip() if comp_el else ""
                        href = link_el.get_attribute("href") if link_el else ""
                        url = href.split("?")[0] if href else ""
                        location = loc_el.inner_text().strip() if loc_el else "Remote"

                        if not title or not company:
                            continue

                        job_id = self._extract_job_id(url) if url else f"li_{abs(hash(title + company))}"
                        desc = f"{title} at {company} ({location})."
                        skills_str = ", ".join(keywords) if keywords else ""

                        jobs.append({
                            "platform": self.platform_name,
                            "job_id_on_platform": str(job_id),
                            "title": title,
                            "company": company,
                            "location": location,
                            "remote_level": "Fully Remote" if "remote" in location.lower() else location,
                            "url": url,
                            "description": desc[:3000],
                            "salary": "Not specified",
                            "salary_range": "Not specified",
                            "date_posted": None,
                            "skills": skills_str,
                            "skills_required": skills_str,
                        })
                finally:
                    context.close()
        except Exception as e:
            logger.warning(f"[LinkedIn] Playwright fallback error: {e}")

        return jobs

    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        logger.info(f"[LinkedIn] Starting scrape for keywords: {keywords}")
        jobs = self._scrape_guest_api(keywords, limit)
        if not jobs:
            logger.info("[LinkedIn] Guest API returned 0 jobs; attempting Playwright fallback...")
            jobs = self._scrape_playwright_fallback(keywords, limit)
        logger.info(f"[LinkedIn] Completed scrape. Found {len(jobs)} jobs.")
        return jobs
