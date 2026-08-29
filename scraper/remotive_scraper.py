import requests
import re
from .base_scraper import BaseScraper

class RemotiveScraper(BaseScraper):
    API_URL = "https://remotive.com/api/remote-jobs"

    def __init__(self):
        self.platform_name = "Remotive"

    def _clean_html(self, text):
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def scrape_jobs(self, keywords, limit=10):
        jobs = []
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AutonomousJobApplicant/1.0)"}
        keywords_lower = [k.lower() for k in keywords]

        try:
            resp = requests.get(self.API_URL, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [Remotive] Failed to fetch: {e}")
            return jobs

        listings = data.get("jobs", [])
        print(f"  [Remotive] Fetched {len(listings)} listings. Filtering...")

        for listing in listings:
            if len(jobs) >= limit:
                break
            title = listing.get("title", "")
            company = listing.get("company_name", "")
            tags = listing.get("tags", [])
            category = listing.get("category", "")
            description = self._clean_html(listing.get("description", ""))
            searchable = f"{title} {company} {' '.join(tags)} {category} {description}".lower()
            if not any(kw in searchable for kw in keywords_lower):
                continue

            salary_min = listing.get("salary_min")
            salary_max = listing.get("salary_max")
            if salary_min and salary_max:
                salary_range = f"${int(salary_min):,} - ${int(salary_max):,}"
            else:
                salary_range = "Not specified"

            url = listing.get("url", "")
            job_id = listing.get("id", "")
            jobs.append({
                "platform": self.platform_name,
                "job_id_on_platform": str(job_id),
                "title": title,
                "company": company,
                "description": description[:3000],
                "url": url,
                "salary_range": salary_range,
                "remote_level": "Fully Remote",
                "skills_required": ", ".join(tags),
            })

        print(f"  [Remotive] Found {len(jobs)} matching jobs.")
        return jobs
