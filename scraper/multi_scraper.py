"""Multi-source job scraper: coordinates all scrapers, deduplicates results."""

from .remoteok_scraper import RemoteOKScraper
from .weworkremotely_scraper import WeWorkRemotelyScraper
from .remotive_scraper import RemotiveScraper
from .himalayas_scraper import HimalayasScraper

SCRAPERS = {
    "RemoteOK": RemoteOKScraper,
    "WeWorkRemotely": WeWorkRemotelyScraper,
    "Remotive": RemotiveScraper,
    "Himalayas": HimalayasScraper,
}


def scrape_all(keywords, limit_per_source=10):
    """Run all scrapers and return deduplicated job list."""
    all_jobs = []
    for name in SCRAPERS:
        try:
            scraper = SCRAPERS[name]()
            all_jobs.extend(scraper.scrape_jobs(keywords, limit=limit_per_source))
        except Exception as e:
            print(f"  [{name}] failed: {e}")

    seen = set()
    unique = []
    for job in all_jobs:
        key = (job["title"].lower().strip(), job["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)

    print(f"\n  Total unique jobs: {len(unique)}")
    return unique
