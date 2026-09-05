"""
Unit tests for HimalayasScraper.
Verifies camelCase parsing, single-bound and dual-bound salary formatting,
HTML unescaping, location mapping, date conversion, and resilient error isolation.
"""

import unittest
from unittest.mock import MagicMock, patch

from scraper.base_scraper import BaseScraper
from scraper.himalayas_scraper import HimalayasScraper


class TestHimalayasScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = HimalayasScraper()

    def test_inherits_base_scraper(self):
        self.assertIsInstance(self.scraper, BaseScraper)

    @patch("requests.Session.get")
    def test_himalayas_camelcase_and_field_parsing(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "title": "Senior Python Developer",
                    "companyName": "Acme Global",
                    "companySlug": "acme-global",
                    "minSalary": 120000,
                    "maxSalary": 150000,
                    "currency": "USD",
                    "locationRestrictions": ["United States", "Canada"],
                    "categories": ["Python", "Backend"],
                    "description": "<p>We are seeking a <b>Python</b> dev &amp; architect.</p>",
                    "pubDate": 1788086339,
                    "applicationLink": "https://himalayas.app/jobs/acme/python-dev",
                    "guid": "https://himalayas.app/jobs/acme/python-dev",
                }
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]

        self.assertEqual(job["platform"], "Himalayas")
        self.assertEqual(job["title"], "Senior Python Developer")
        self.assertEqual(job["company"], "Acme Global")
        self.assertEqual(job["salary_range"], "USD 120,000 - 150,000")
        self.assertEqual(job["salary"], "USD 120,000 - 150,000")
        self.assertEqual(job["location"], "United States, Canada")
        self.assertIn("Python dev & architect.", job["description"])
        self.assertNotIn("&amp;", job["description"])
        self.assertNotIn("<p>", job["description"])
        self.assertEqual(job["url"], "https://himalayas.app/jobs/acme/python-dev")
        self.assertEqual(job["job_id_on_platform"], "python-dev")
        self.assertEqual(job["skills_required"], "Python, Backend")
        self.assertEqual(job["skills"], "Python, Backend")
        self.assertIsNotNone(job["date_posted"])

    @patch("requests.Session.get")
    def test_himalayas_salary_variations(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "title": "Min Only Job",
                    "companyName": "Alpha",
                    "minSalary": 100000,
                    "maxSalary": None,
                    "currency": "EUR",
                    "guid": "alpha_1",
                },
                {
                    "title": "Max Only Job",
                    "companyName": "Beta",
                    "minSalary": None,
                    "maxSalary": 180000,
                    "currency": "GBP",
                    "guid": "beta_2",
                },
                {
                    "title": "No Salary Job",
                    "companyName": "Gamma",
                    "minSalary": None,
                    "maxSalary": None,
                    "guid": "gamma_3",
                },
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs([], limit=5)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0]["salary_range"], "EUR 100,000+")
        self.assertEqual(jobs[1]["salary_range"], "Up to GBP 180,000")
        self.assertEqual(jobs[2]["salary_range"], "Not specified")

    @patch("requests.Session.get")
    def test_himalayas_fallback_url_generation(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "title": "Staff Backend Engineer",
                    "companyName": "Startup Inc",
                    "companySlug": "startup-inc",
                    "applicationLink": None,
                    "guid": "hima_fallback",
                }
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs([], limit=5)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["url"], "https://himalayas.app/companies/startup-inc/jobs/staff-backend-engineer")

    @patch("requests.Session.get")
    def test_himalayas_html_cleaning_and_entity_unescaping(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "title": "Full Stack Dev",
                    "companyName": "Devs &amp; Co",
                    "description": "<p>Experience with &quot;React&quot; &#39;Node&#39; &amp; Python.</p>",
                    "guid": "hima_html",
                }
            ]
        }
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs([], limit=5)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["description"], "Experience with \"React\" 'Node' & Python.")

    @patch("requests.Session.get")
    def test_himalayas_network_error_isolation(self, mock_get):
        mock_get.side_effect = Exception("Connection refused / Timeout")
        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_himalayas_http_error_code_isolation(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_get.return_value = mock_response

        jobs = self.scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
