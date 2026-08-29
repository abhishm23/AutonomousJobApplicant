import requests
import re
from .base_scraper import BaseScraper

class RemoteOKScraper(BaseScraper):
    API_URL = "https://remoteok.com/api"

    def __init__(self):
        self.platform_name = "RemoteOK"

    def _clean_html(self, text):
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def scrape_jobs(self, keywords, limit=10):
        jobs = []
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AutonomousJobApplicant/1.0)"}
        print(f"Fetching jobs from RemoteOK API...")
        try:
            response = requests.get(self.API_URL, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Failed to fetch from RemoteOK API: {e}")
            return jobs

        job_listings = data[1:] if len(data) > 1 else []
        print(f"Fetched {len(job_listings)} total listings. Filtering for: {keywords}")
        keywords_lower = [k.lower() for k in keywords]

        for listing in job_listings:
            title = listing.get("position", "")
            company = listing.get("company", "")
            tags = listing.get("tags", [])
            description = self._clean_html(listing.get("description", ""))
            searchable = f"{title} {company} {' '.join(tags)} {description}".lower()
            if not any(kw in searchable for kw in keywords_lower):
                continue

            salary_min = listing.get("salary_min")
            salary_max = listing.get("salary_max")
            if salary_min and salary_max:
                salary_range = f"${salary_min:,} - ${salary_max:,}"
            elif salary_min:
                salary_range = f"${salary_min:,}+"
            else:
                salary_range = "Not specified"

            job_id = listing.get("id", listing.get("slug", ""))
            url = listing.get("url", f"https://remoteok.com/remote-jobs/{job_id}")
            if url and not url.startswith("http"):
                url = f"https://remoteok.com{url}"

            jobs.append({
                "platform": self.platform_name,
                "job_id_on_platform": str(job_id),
                "title": title,
                "company": company,
                "description": description[:3000],
                "url": url,
                "salary_range": salary_range,
                "remote_level": "Fully Remote",
                "skills_required": ", ".join(tags) if tags else ""
            })
            print(f"  Matched: {title} at {company}")
            if len(jobs) >= limit:
                break

        print(f"Found {len(jobs)} matching jobs.")
        return jobs
