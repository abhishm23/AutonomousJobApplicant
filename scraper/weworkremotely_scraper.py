import requests
import re
import xml.etree.ElementTree as ET
from .base_scraper import BaseScraper

class WeWorkRemotelyScraper(BaseScraper):
    BASE_URL = "https://weworkremotely.com"
    RSS_FEEDS = [
        "/categories/remote-programming-jobs.rss",
        "/categories/remote-data-jobs.rss",
        "/categories/remote-devops-sysadmin-jobs.rss",
    ]

    def __init__(self):
        self.platform_name = "WeWorkRemotely"

    def _clean_html(self, text):
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def scrape_jobs(self, keywords, limit=10):
        jobs = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        keywords_lower = [k.lower() for k in keywords]

        for rss_url in self.RSS_FEEDS:
            if len(jobs) >= limit:
                break
            try:
                resp = requests.get(f"{self.BASE_URL}{rss_url}", headers=headers, timeout=20)
                resp.raise_for_status()
            except Exception as e:
                print(f"  [WeWorkRemotely] Failed to fetch {rss_url}: {e}")
                continue

            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as e:
                print(f"  [WeWorkRemotely] XML parse error: {e}")
                continue

            ns = {"dc": "http://purl.org/dc/elements/1.1/"}
            for item in root.findall(".//item"):
                if len(jobs) >= limit:
                    break
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                description_raw = item.findtext("description", "")
                description = self._clean_html(description_raw)
                category = item.findtext("category", "")
                company_tag = item.find("company") or item.find("dc:creator", ns)
                company = company_tag.text.strip() if company_tag is not None and company_tag.text else ""

                if not company and ":" in title:
                    parts = title.split(":", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()

                searchable = f"{title} {company} {category} {description}".lower()
                if not any(kw in searchable for kw in keywords_lower):
                    continue

                job_id = link.split("/")[-1] if link else f"wwr_{len(jobs)}"
                jobs.append({
                    "platform": self.platform_name,
                    "job_id_on_platform": str(job_id),
                    "title": title,
                    "company": company,
                    "description": description[:3000],
                    "url": link,
                    "salary_range": "Not specified",
                    "remote_level": "Fully Remote",
                    "skills_required": category,
                })

        print(f"  [WeWorkRemotely] Found {len(jobs)} matching jobs.")
        return jobs
