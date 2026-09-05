"""
Unit tests for RemotiveScraper.
Verifies salary string preservation, HTML unescaping, tag filtering,
location mapping, date parsing, and error isolation.
"""

import unittest
from unittest.mock import MagicMock, patch

from scraper.base_scraper import BaseScraper
from scraper.remotive_scraper import RemotiveScraper


class TestRemotiveScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = RemotiveScraper()

    def test_inherits_base_scraper(self):
        self.assertIsInstance(self.scraper, BaseScraper)

    @patch("requests.Session.get")
    def test_remotive_salary_string_and_tag_parsing(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "id": 101,
                    "url": "https://remotive.com/job/101",
                    "title": "Lead Python Engineer",
                    "company_name": "CloudScale",
                    "category": "Software Development",
                    "tags": ["python", "django", "aws"],
                    "publication_date": "2026-08-28T12:00:00",
                    "candidate_required_location": "Worldwide",
                    "salary": "$140k - $180k",
                    "description": "<p>Great role &amp; culture for &quot;engineers&quot;.</p>",
                }
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]

        self.assertEqual(job["platform"], "Remotive")
        self.assertEqual(job["title"], "Lead Python Engineer")
        self.assertEqual(job["company"], "CloudScale")
        self.assertEqual(job["salary_range"], "$140k - $180k")
        self.assertEqual(job["salary"], "$140k - $180k")
        self.assertEqual(job["location"], "Worldwide")
        self.assertEqual(job["date_posted"], "2026-08-28")
        self.assertEqual(job["job_id_on_platform"], "101")
        self.assertIn("Great role & culture for \"engineers\".", job["description"])
        self.assertNotIn("&amp;", job["description"])
        self.assertEqual(job["skills_required"], "python, django, aws")

    @patch("requests.Session.get")
    def test_remotive_salary_min_max_fallback(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "id": 201,
                    "title": "Backend Architect",
                    "company_name": "Acme",
                    "salary_min": 120000,
                    "salary_max": 160000,
                    "tags": ["python"],
                },
                {
                    "id": 202,
                    "title": "Frontend Lead",
                    "company_name": "Beta",
                    "salary_min": 90000,
                    "salary_max": None,
                    "tags": ["react"],
                },
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs([], limit=5)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["salary_range"], "$120,000 - $160,000")
        self.assertEqual(jobs[1]["salary_range"], "$90,000+")

    @patch("requests.Session.get")
    def test_remotive_keyword_filtering(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "id": 301,
                    "title": "Senior Python Developer",
                    "company_name": "Alpha",
                    "tags": ["python"],
                    "description": "Python job",
                },
                {
                    "id": 302,
                    "title": "Ruby Rails Specialist",
                    "company_name": "Beta",
                    "tags": ["ruby", "rails"],
                    "description": "Ruby job only",
                },
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id_on_platform"], "301")

    @patch("requests.Session.get")
    def test_remotive_network_error_isolation(self, mock_get):
        mock_get.side_effect = Exception("HTTP 500 Internal Server Error")
        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_remotive_http_status_failure(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
