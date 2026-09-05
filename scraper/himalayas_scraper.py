import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class HimalayasScraper(BaseScraper):
    API_URL = "https://himalayas.app/jobs/api"

    def __init__(self):
        self.platform_name = "Himalayas"
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

    def _format_salary(self, min_sal: Optional[float], max_sal: Optional[float], currency: Optional[str]) -> str:
        curr = currency or "USD"
        if min_sal and max_sal:
            return f"{curr} {int(min_sal):,} - {int(max_sal):,}"
        elif min_sal:
            return f"{curr} {int(min_sal):,}+"
        elif max_sal:
            return f"Up to {curr} {int(max_sal):,}"
        return "Not specified"

    def _extract_date_posted(self, pub_date: Any) -> Optional[str]:
        if not pub_date:
            return None
        try:
            if isinstance(pub_date, (int, float)):
                return datetime.fromtimestamp(pub_date, tz=timezone.utc).strftime("%Y-%m-%d")
            return str(pub_date)[:10]
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
            resp = self.session.get(
                self.API_URL,
                params=params,
                headers=headers,
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning(f"[Himalayas] HTTP {resp.status_code} received from API.")
                return jobs
            data = resp.json()
        except Exception as e:
            logger.warning(f"[Himalayas] Failed to fetch jobs: {e}")
            return jobs

        listings = data.get("jobs", []) if isinstance(data, dict) else []

        for listing in listings:
            if len(jobs) >= limit:
                break
            if not isinstance(listing, dict):
                continue

            title = listing.get("title", "") or ""
            company = listing.get("companyName", "") or ""
            description = self._clean_html(listing.get("description", ""))

            url = listing.get("applicationLink", "") or ""
            if not url:
                slug = listing.get("companySlug", "")
                job_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                url = f"https://himalayas.app/companies/{slug}/jobs/{job_slug}" if slug else ""

            salary_min = listing.get("minSalary")
            salary_max = listing.get("maxSalary")
            currency = listing.get("currency")
            salary_range = self._format_salary(salary_min, salary_max, currency)

            categories = listing.get("categories", [])
            tags_str = ", ".join(c.replace("-", " ") for c in categories) if isinstance(categories, list) else ""

            loc_restrictions = listing.get("locationRestrictions", [])
            location = ", ".join(loc_restrictions) if isinstance(loc_restrictions, list) and loc_restrictions else "Remote / Worldwide"

            date_posted = self._extract_date_posted(listing.get("pubDate"))

            searchable = f"{title} {company} {description} {tags_str}".lower()
            if keywords_lower and not any(kw in searchable for kw in keywords_lower):
                continue

            guid = str(listing.get("guid") or "").strip()
            job_id = guid.rstrip("/").split("/")[-1] if guid else f"him_{len(jobs)}_{abs(hash(title + company))}"

            jobs.append({
                "platform": self.platform_name,
                "job_id_on_platform": job_id,
                "title": title.strip(),
                "company": company.strip(),
                "location": location,
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
