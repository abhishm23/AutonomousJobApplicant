"""
Comprehensive Unit & Integration Test Suite for Scraper Subsystem.
Tests:
- Scraper registry and paywall deprecation
- Job normalization and interface contract compliance
- Concurrency, 25-second timeout, error isolation, and deduplication
- Unit testing for all direct portal scrapers (LinkedIn, Naukri, Wellfound, Hirist, Himalayas, Remotive)
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from scraper.base_scraper import BaseScraper
from scraper.himalayas_scraper import HimalayasScraper
from scraper.hirist_scraper import HiristScraper
from scraper.linkedin_scraper import LinkedInScraper
from scraper.multi_scraper import (
    DEFAULT_SCRAPER_TIMEOUT,
    SCRAPERS,
    _normalize_job,
    _run_single_scraper,
    scrape_all,
)
from scraper.naukri_scraper import NaukriScraper
from scraper.remotive_scraper import RemotiveScraper
from scraper.wellfound_scraper import WellfoundScraper


class TestScraperRegistryAndDeprecation(unittest.TestCase):
    """Verifies that paywalled sources are removed and only active direct sources are registered."""

    def test_deprecated_scrapers_excluded(self):
        self.assertNotIn("RemoteOK", SCRAPERS)
        self.assertNotIn("WeWorkRemotely", SCRAPERS)
        self.assertNotIn("Adzuna", SCRAPERS)

    def test_active_scrapers_registered(self):
        expected_portals = {"LinkedIn", "Naukri", "Wellfound", "Hirist", "Himalayas", "Remotive"}
        self.assertEqual(set(SCRAPERS.keys()), expected_portals)

    def test_scrapers_inherit_base_scraper(self):
        for name, scraper_cls in SCRAPERS.items():
            self.assertTrue(
                issubclass(scraper_cls, BaseScraper),
                f"Scraper class {name} does not inherit from BaseScraper",
            )


class TestJobNormalization(unittest.TestCase):
    """Tests the _normalize_job contract validator and sanitizer."""

    def test_normalize_job_full_valid(self):
        raw = {
            "platform": "LinkedIn",
            "job_id_on_platform": "123456",
            "title": "Senior Python Engineer",
            "company": "Tech Corp",
            "location": "Remote, US",
            "url": "https://linkedin.com/jobs/view/123456",
            "description": "Building scalable backend services.",
            "salary": "$150,000 - $180,000",
            "date_posted": "2026-08-28",
            "skills": "Python, FastAPI, Docker",
        }
        norm = _normalize_job(raw, default_platform="LinkedIn")

        self.assertEqual(norm["platform"], "LinkedIn")
        self.assertEqual(norm["job_id_on_platform"], "123456")
        self.assertEqual(norm["title"], "Senior Python Engineer")
        self.assertEqual(norm["company"], "Tech Corp")
        self.assertEqual(norm["location"], "Remote, US")
        self.assertEqual(norm["url"], "https://linkedin.com/jobs/view/123456")
        self.assertEqual(norm["description"], "Building scalable backend services.")
        self.assertEqual(norm["salary"], "$150,000 - $180,000")
        self.assertEqual(norm["date_posted"], "2026-08-28")
        self.assertEqual(norm["skills"], "Python, FastAPI, Docker")
        # Compatibility aliases
        self.assertEqual(norm["salary_range"], "$150,000 - $180,000")
        self.assertEqual(norm["remote_level"], "Remote, US")
        self.assertEqual(norm["skills_required"], "Python, FastAPI, Docker")

    def test_normalize_job_missing_fields_defaulting(self):
        raw = {}
        norm = _normalize_job(raw, default_platform="Himalayas")

        self.assertEqual(norm["platform"], "Himalayas")
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["company"], "Unknown Company")
        self.assertEqual(norm["location"], "Remote")
        self.assertEqual(norm["url"], "")
        self.assertEqual(norm["description"], "")
        self.assertIsNone(norm["salary"])
        self.assertIsNone(norm["date_posted"])
        self.assertIsNone(norm["skills"])
        # Should have a 16-character SHA-256 fallback ID
        self.assertTrue(len(norm["job_id_on_platform"]) == 16)

    def test_normalize_job_deterministic_sha256_id(self):
        job_a = {"title": "Data Scientist", "company": "AI Labs", "url": "https://example.com/job1"}
        job_b = {"title": "Data Scientist", "company": "AI Labs", "url": "https://example.com/job1"}
        job_c = {"title": "Data Scientist", "company": "AI Labs", "url": "https://example.com/job2"}

        norm_a = _normalize_job(job_a, default_platform="Remotive")
        norm_b = _normalize_job(job_b, default_platform="Remotive")
        norm_c = _normalize_job(job_c, default_platform="Remotive")

        self.assertEqual(norm_a["job_id_on_platform"], norm_b["job_id_on_platform"])
        self.assertNotEqual(norm_a["job_id_on_platform"], norm_c["job_id_on_platform"])

    def test_normalize_job_description_truncation(self):
        long_desc = "x" * 5000
        raw = {"title": "Developer", "description": long_desc}
        norm = _normalize_job(raw, default_platform="Hirist")

        self.assertEqual(len(norm["description"]), 3000)

    def test_normalize_job_none_safety(self):
        raw = {
            "platform": None,
            "job_id_on_platform": None,
            "title": None,
            "company": None,
            "url": None,
            "description": None,
            "salary": None,
            "location": None,
            "skills": None,
        }
        norm = _normalize_job(raw, default_platform="Naukri")
        self.assertEqual(norm["platform"], "Naukri")
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["company"], "Unknown Company")
        self.assertTrue(len(norm["job_id_on_platform"]) > 0)


class TestRunSingleScraperIsolation(unittest.TestCase):
    """Tests the safe wrapper function _run_single_scraper."""

    def test_run_single_scraper_success(self):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.scrape_jobs.return_value = [
            {"job_id_on_platform": "1", "title": "Dev", "company": "Co", "url": "http://a.com"}
        ]
        mock_cls.return_value = mock_instance

        results = _run_single_scraper("TestScraper", mock_cls, ["python"], limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Dev")
        self.assertEqual(results[0]["platform"], "TestScraper")

    def test_run_single_scraper_non_list_handling(self):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.scrape_jobs.return_value = None  # Returns None instead of list
        mock_cls.return_value = mock_instance

        results = _run_single_scraper("BadScraper", mock_cls, ["python"], limit=5)
        self.assertEqual(results, [])

    def test_run_single_scraper_exception_barrier(self):
        mock_cls = MagicMock()
        mock_cls.side_effect = RuntimeError("Fatal browser crash")

        # Must not raise RuntimeError
        results = _run_single_scraper("CrashingScraper", mock_cls, ["python"], limit=5)
        self.assertEqual(results, [])


class TestMultiScraperConcurrencyAndIsolation(unittest.TestCase):
    """Tests multi_scraper concurrency, timeouts, and error resilience."""

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_scrape_all_concurrent_execution_speed(self):
        """6 scrapers sleeping 0.1s each should complete concurrently in < 0.4s."""
        from scraper.multi_scraper import SCRAPERS

        def make_slow_scraper(name):
            mock_cls = MagicMock()
            mock_inst = MagicMock()

            def scrape_side_effect(keywords, limit=10):
                time.sleep(0.1)
                return [{"job_id_on_platform": f"{name}_1", "title": f"{name} Job", "company": "Co"}]

            mock_inst.scrape_jobs.side_effect = scrape_side_effect
            mock_cls.return_value = mock_inst
            return mock_cls

        for portal in ["P1", "P2", "P3", "P4", "P5", "P6"]:
            SCRAPERS[portal] = make_slow_scraper(portal)

        start = time.time()
        jobs = scrape_all(["python"], limit_per_source=5, timeout=5.0)
        elapsed = time.time() - start

        self.assertEqual(len(jobs), 6)
        self.assertLess(elapsed, 0.45, f"Execution took {elapsed:.2f}s, expected concurrency < 0.45s")

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_scrape_all_timeout_enforcement(self):
        """Hanging scraper sleeping 10s is aborted after 0.2s without crashing fast scrapers."""
        from scraper.multi_scraper import SCRAPERS

        fast_cls = MagicMock()
        fast_inst = MagicMock()
        fast_inst.scrape_jobs.return_value = [{"job_id_on_platform": "f1", "title": "Fast Job", "company": "Co"}]
        fast_cls.return_value = fast_inst

        slow_cls = MagicMock()
        slow_inst = MagicMock()

        def hanging_scrape(keywords, limit=10):
            time.sleep(10.0)
            return [{"job_id_on_platform": "s1", "title": "Slow Job", "company": "Co"}]

        slow_inst.scrape_jobs.side_effect = hanging_scrape
        slow_cls.return_value = slow_inst

        SCRAPERS["FastPortal"] = fast_cls
        SCRAPERS["SlowPortal"] = slow_cls

        start = time.time()
        jobs = scrape_all(["python"], limit_per_source=5, timeout=0.2)
        elapsed = time.time() - start

        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Fast Job")

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_scrape_all_error_isolation_mixed_failures(self):
        """Failing scrapers (exceptions, network errors) do not impede successful scrapers."""
        from scraper.multi_scraper import SCRAPERS

        crasher_1 = MagicMock()
        crasher_1.side_effect = ConnectionResetError("Akamai block")

        crasher_2 = MagicMock()
        inst_2 = MagicMock()
        inst_2.scrape_jobs.side_effect = ValueError("Corrupt JSON")
        crasher_2.return_value = inst_2

        success_cls = MagicMock()
        inst_3 = MagicMock()
        inst_3.scrape_jobs.return_value = [
            {"job_id_on_platform": "valid_1", "title": "Lead Architect", "company": "Apex"},
            {"job_id_on_platform": "valid_2", "title": "Cloud Engineer", "company": "Nexus"},
        ]
        success_cls.return_value = inst_3

        SCRAPERS["BlockedPortal"] = crasher_1
        SCRAPERS["CorruptPortal"] = crasher_2
        SCRAPERS["GoodPortal"] = success_cls

        jobs = scrape_all(["cloud"], limit_per_source=5)
        self.assertEqual(len(jobs), 2)
        self.assertEqual({j["job_id_on_platform"] for j in jobs}, {"valid_1", "valid_2"})

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_scrape_all_composite_key_deduplication(self):
        """Duplicate jobs with same (platform, job_id_on_platform) are deduplicated."""
        from scraper.multi_scraper import SCRAPERS

        cls_a = MagicMock()
        inst_a = MagicMock()
        inst_a.scrape_jobs.return_value = [
            {"platform": "Himalayas", "job_id_on_platform": "him_100", "title": "Dev A", "company": "Co A"},
            {"platform": "Himalayas", "job_id_on_platform": "him_100", "title": "Dev A Duplicate", "company": "Co A"},
            {"platform": "Himalayas", "job_id_on_platform": "him_200", "title": "Dev B", "company": "Co B"},
        ]
        cls_a.return_value = inst_a

        cls_b = MagicMock()
        inst_b = MagicMock()
        inst_b.scrape_jobs.return_value = [
            {"platform": "LinkedIn", "job_id_on_platform": "him_100", "title": "Dev A CrossPlatform", "company": "Co A"},
        ]
        cls_b.return_value = inst_b

        SCRAPERS["Himalayas"] = cls_a
        SCRAPERS["LinkedIn"] = cls_b

        jobs = scrape_all(["dev"])
        self.assertEqual(len(jobs), 3)

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_scrape_all_enabled_sources_filtering(self):
        from scraper.multi_scraper import SCRAPERS

        cls_h = MagicMock()
        cls_l = MagicMock()
        SCRAPERS["Himalayas"] = cls_h
        SCRAPERS["LinkedIn"] = cls_l

        scrape_all(["python"], enabled_sources=["Himalayas"])
        cls_h.assert_called_once()
        cls_l.assert_not_called()


class TestIndividualScrapersUnit(unittest.TestCase):
    """Unit tests for individual direct portal scraper helper methods."""

    def test_linkedin_scraper_job_id_extraction(self):
        scraper = LinkedInScraper()
        url1 = "https://www.linkedin.com/jobs/view/senior-software-engineer-at-google-3891029412?position=1"
        url2 = "https://www.linkedin.com/jobs/view/3891029412"
        self.assertEqual(scraper._extract_job_id(url1), "3891029412")
        self.assertEqual(scraper._extract_job_id(url2), "3891029412")

    @patch("requests.get")
    def test_linkedin_scraper_guest_api_parsing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <ul>
            <li>
                <div class="base-card">
                    <h3 class="base-search-card__title">Senior Python Architect</h3>
                    <h4 class="base-search-card__subtitle"><a href="#">MegaTech</a></h4>
                    <span class="job-search-card__location">Remote, US</span>
                    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/senior-python-architect-391029304?refId=123">Link</a>
                    <time datetime="2026-08-28">2 days ago</time>
                    <span class="job-search-card__salary-info">$160k - $200k</span>
                </div>
            </li>
        </ul>
        """
        mock_get.return_value = mock_resp

        scraper = LinkedInScraper()
        with patch.object(scraper, "_fetch_job_description", return_value="Great Python role"):
            jobs = scraper._scrape_guest_api(["python"], limit=5)

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["platform"], "LinkedIn")
        self.assertEqual(job["title"], "Senior Python Architect")
        self.assertEqual(job["company"], "MegaTech")
        self.assertEqual(job["location"], "Remote, US")
        self.assertEqual(job["job_id_on_platform"], "391029304")
        self.assertEqual(job["salary"], "$160k - $200k")
        self.assertEqual(job["date_posted"], "2026-08-28")

    def test_hirist_scraper_slugify_and_id(self):
        scraper = HiristScraper()
        self.assertEqual(scraper._slugify_keyword("Data Science"), "data-science-jobs")
        self.assertEqual(scraper._slugify_keyword("Python & Django Developer"), "python-django-developer-jobs")
        self.assertEqual(scraper._extract_job_id("https://www.hirist.tech/j/senior-developer-123456.html"), "123456")

    def test_naukri_scraper_slugify_and_id(self):
        scraper = NaukriScraper()
        self.assertEqual(scraper._slugify_keyword("Data Engineer"), "data-engineer-jobs")
        self.assertEqual(scraper._extract_job_id("https://www.naukri.com/job-listings-python-dev-987654?src=search", "nauk_987"), "nauk_987")
        self.assertEqual(scraper._extract_job_id("https://www.naukri.com/job-listings-python-dev-987654"), "987654")

    def test_wellfound_scraper_slugify_and_id(self):
        scraper = WellfoundScraper()
        self.assertEqual(scraper._slugify_role("Machine Learning Engineer"), "machine-learning-engineer")
        self.assertEqual(scraper._extract_job_id("https://wellfound.com/jobs/543210-lead-architect"), "543210")


if __name__ == "__main__":
    unittest.main()
