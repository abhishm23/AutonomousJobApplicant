from abc import ABC, abstractmethod
from typing import List, Dict

class BaseScraper(ABC):

    @abstractmethod
    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict]:
        """Scrape jobs based on keywords.
        Returns list of dicts with: title, company, description, url,
        salary_range, remote_level, job_id_on_platform, skills_required.
        """
        pass
