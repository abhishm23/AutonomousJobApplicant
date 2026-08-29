import requests
import re
from .base_scraper import BaseScraper

class HimalayasScraper(BaseScraper):
    API_URL = "https://himalayas.app/jobs/api"

    def __init__(self):
        self.platform_name = "Himalayas"

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
        search_query = " ".join(keywords[:3])

        try:
            resp = requests.get(
                self.API_URL,
                params={"search": search_query, "limit": min(limit * 3, 60)},
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [Himalayas] Failed to fetch: {e}")
            return jobs

        listings = data.get("jobs", [])
        print(f"  [Himalayas] Fetched {len(listings)} listings. Filtering...")

        for listing in listings:
            if len(jobs) >= limit:
                break
            title = listing.get("title", "")
            company = listing.get("companyName", "")
            description = self._clean_html(listing.get("description", ""))
            url = listing.get("applicationLink", "")
            if not url:
                slug = listing.get("companySlug", "")
                job_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                url = f"https://himalayas.app/companies/{slug}/jobs/{job_slug}" if slug else ""

            salary_min = listing.get("minSalary")
            salary_max = listing.get("maxSalary")
            currency = listing.get("currency") or "USD"
            if salary_min and salary_max:
                salary_range = f"{currency} {int(salary_min):,} - {int(salary_max):,}"
            else:
                salary_range = "Not specified"

            categories = listing.get("categories", [])
            tags_str = ", ".join(c.replace("-", " ") for c in categories) if isinstance(categories, list) else ""

            searchable = f"{title} {company} {description} {tags_str}".lower()
            if not any(kw in searchable for kw in keywords_lower):
                continue

            job_id = listing.get("guid", listing.get("companySlug", f"him_{len(jobs)}"))
            jobs.append({
                "platform": self.platform_name,
                "job_id_on_platform": str(job_id),
                "title": title,
                "company": company,
                "description": description[:3000],
                "url": url,
                "salary_range": salary_range,
                "remote_level": "Fully Remote",
                "skills_required": tags_str,
            })

        print(f"  [Himalayas] Found {len(jobs)} matching jobs.")
        return jobs
