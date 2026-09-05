import html
import logging
import re
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class RemotiveScraper(BaseScraper):
    API_URL = "https://remotive.com/api/remote-jobs"

    def __init__(self):
        self.platform_name = "Remotive"
        self.session = self._create_resilient_session()

    def _create_resilient_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _clean_html(self, text: Optional[str]) -> str:
        if not text:
            return ""
        clean = html.unescape(text)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _extract_salary(self, listing: Dict[str, Any]) -> str:
        raw_salary = listing.get("salary")
        if raw_salary and str(raw_salary).strip():
            return str(raw_salary).strip()

        salary_min = listing.get("salary_min")
        salary_max = listing.get("salary_max")
        if salary_min and salary_max:
            return f"${int(salary_min):,} - ${int(salary_max):,}"
        elif salary_min:
            return f"${int(salary_min):,}+"
        elif salary_max:
            return f"Up to ${int(salary_max):,}"

        return "Not specified"

    def _extract_date_posted(self, pub_date: Any) -> Optional[str]:
        if not pub_date:
            return None
        try:
            date_str = str(pub_date).strip()
            if "T" in date_str:
                return date_str.split("T")[0]
            return date_str[:10]
        except Exception:
            return None

    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        keywords_lower = [k.lower().strip() for k in keywords if k.strip()]
        search_query = " ".join(keywords[:3]) if keywords else ""

        params: Dict[str, Any] = {"limit": min(limit * 3, 100)}
        if search_query:
            params["search"] = search_query

        try:
            resp = self.session.get(self.API_URL, params=params, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"[Remotive] HTTP {resp.status_code} received from API.")
                return jobs
            data = resp.json()
        except Exception as e:
            logger.warning(f"[Remotive] Failed to fetch jobs: {e}")
            return jobs

        listings = data.get("jobs", []) if isinstance(data, dict) else []

        for listing in listings:
            if len(jobs) >= limit:
                break
            if not isinstance(listing, dict):
                continue

            title = listing.get("title", "") or ""
            company = listing.get("company_name", "") or ""
            tags = listing.get("tags", [])
            tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags or "")
            category = listing.get("category", "") or ""
            description = self._clean_html(listing.get("description", ""))

            searchable = f"{title} {company} {tags_str} {category} {description}".lower()
            if keywords_lower and not any(kw in searchable for kw in keywords_lower):
                continue

            salary_range = self._extract_salary(listing)
            location = listing.get("candidate_required_location") or "Remote / Worldwide"
            date_posted = self._extract_date_posted(listing.get("publication_date"))
            url = listing.get("url", "") or ""
            job_id = str(listing.get("id") or f"rem_{len(jobs)}_{abs(hash(title + company))}")

            jobs.append({
                "platform": self.platform_name,
                "job_id_on_platform": job_id,
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "description": description[:3000],
                "url": url.strip(),
                "salary_range": salary_range,
                "salary": salary_range,
                "remote_level": "Fully Remote",
                "skills_required": tags_str,
                "skills": tags_str,
                "date_posted": date_posted,
            })

        return jobs
