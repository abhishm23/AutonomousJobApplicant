import html
import time
import unittest
from unittest.mock import MagicMock, patch
import requests

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


class TestAdversarialJobNormalization(unittest.TestCase):
    def test_normalize_job_none_and_primitive_types(self):
        self.assertEqual(_normalize_job(None), {})
        self.assertEqual(_normalize_job("not a dict"), {})
        self.assertEqual(_normalize_job(12345), {})
        self.assertEqual(_normalize_job([{"title": "foo"}]), {})
        self.assertEqual(_normalize_job(True), {})
        self.assertEqual(_normalize_job(float("nan")), {})

    def test_normalize_job_empty_dict(self):
        norm = _normalize_job({}, default_platform="Himalayas")
        self.assertEqual(norm["platform"], "Himalayas")
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["company"], "Unknown Company")
        self.assertEqual(norm["location"], "Remote")
        self.assertEqual(norm["remote_level"], "Remote")
        self.assertEqual(norm["url"], "")
        self.assertEqual(norm["description"], "")
        self.assertIsNone(norm["salary"])
        self.assertEqual(norm["salary_range"], "Not specified")
        self.assertIsNone(norm["date_posted"])
        self.assertIsNone(norm["skills"])
        self.assertEqual(norm["skills_required"], "")
        self.assertTrue(len(norm["job_id_on_platform"]) >= 8)

    def test_normalize_job_adversarial_fields(self):
        raw = {
            "platform": None,
            "title": None,
            "company": "   ",
            "url": None,
            "job_id_on_platform": None,
            "description": "A" * 5000,
            "salary": None,
            "salary_range": None,
            "date_posted": "  2026-08-30  ",
            "skills": ["Python", None, 123, "DuckDB"],
        }
        norm = _normalize_job(raw, default_platform="LinkedIn")
        self.assertEqual(norm["platform"], "LinkedIn")
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["company"], "Unknown Company")
        self.assertEqual(norm["url"], "")
        self.assertTrue(len(norm["job_id_on_platform"]) > 0)
        self.assertEqual(len(norm["description"]), 3000)
        self.assertIsNone(norm["salary"])
        self.assertEqual(norm["date_posted"], "2026-08-30")
        self.assertEqual(norm["skills"], "Python, 123, DuckDB")

    def test_normalize_job_whitespace_platform_defaults_to_unknown(self):
        raw = {"platform": "   ", "title": "Dev"}
        norm = _normalize_job(raw, default_platform="Remotive")
        self.assertEqual(norm["platform"], "Unknown")

    def test_normalize_job_nested_objects_and_extreme_unicode(self):
        raw = {
            "platform": "Himalayas",
            "title": "Senior AI \U0001F916",
            "company": {"nested_name": "DeepMind"},
            "url": "https://example.com/ai-job",
            "job_id_on_platform": 987654321,
            "description": "Unicode test: \x00\x01\x02",
            "salary": 180000,
            "date_posted": 1725000000,
            "skills": {"not_a_list": True},
        }
        norm = _normalize_job(raw)
        self.assertEqual(norm["platform"], "Himalayas")
        self.assertIn("\U0001F916", norm["title"])
        self.assertIn("{'nested_name': 'DeepMind'}", norm["company"])
        self.assertEqual(norm["job_id_on_platform"], "987654321")
        self.assertEqual(norm["salary"], "180000")
        self.assertEqual(norm["date_posted"], "1725000000")

    def test_normalize_job_sha256_stability_and_collision_resistance(self):
        job1 = {"platform": "Remotive", "title": "Backend Engineer", "company": "Acme", "url": "https://example.com/1"}
        job2 = {"platform": "Remotive", "title": "Backend Engineer", "company": "Acme", "url": "https://example.com/1"}
        job3 = {"platform": "Remotive", "title": "Frontend Engineer", "company": "Acme", "url": "https://example.com/1"}

        norm1 = _normalize_job(job1)
        norm2 = _normalize_job(job2)
        norm3 = _normalize_job(job3)

        self.assertEqual(norm1["job_id_on_platform"], norm2["job_id_on_platform"])
        self.assertNotEqual(norm1["job_id_on_platform"], norm3["job_id_on_platform"])


class TestAdversarialScraperIsolation(unittest.TestCase):
    def test_run_single_scraper_constructor_explosion(self):
        class ExplodingInitScraper:
            def __init__(self):
                raise ZeroDivisionError("Explosion in constructor!")

        res = _run_single_scraper("ExplodingInit", ExplodingInitScraper, ["python"], 10)
        self.assertEqual(res, [])

    def test_run_single_scraper_scrape_method_explosion(self):
        class ExplodingScrapeScraper:
            def scrape_jobs(self, keywords, limit=10):
                raise RuntimeError("Fatal internal scraper crash!")

        res = _run_single_scraper("ExplodingScrape", ExplodingScrapeScraper, ["python"], 10)
        self.assertEqual(res, [])

    def test_run_single_scraper_returns_malformed_types(self):
        malformed_returns = [
            None,
            12345,
            "string result",
            {"key": "not a list"},
            (1, 2, 3),
        ]

        for bad_return in malformed_returns:
            class BadReturnScraper:
                def scrape_jobs(self, keywords, limit=10):
                    return bad_return

            res = _run_single_scraper("BadReturn", BadReturnScraper, ["python"], 10)
            self.assertEqual(res, [])

    def test_run_single_scraper_returns_corrupt_items(self):
        class CorruptItemsScraper:
            def scrape_jobs(self, keywords, limit=10):
                return [
                    None,
                    1234,
                    "corrupt string",
                    {},
                    {"title": "Valid Job", "company": "Good Corp", "url": "https://example.com/j1"},
                    {"title": None, "company": None},
                ]

        res = _run_single_scraper("CorruptItems", CorruptItemsScraper, ["python"], 10)
        self.assertEqual(len(res), 3)
        self.assertEqual(res[1]["title"], "Valid Job")
        self.assertEqual(res[1]["company"], "Good Corp")
        self.assertEqual(res[2]["title"], "Untitled Position")

    def test_scrape_all_never_raises_on_all_crashing_scrapers(self):
        class Crash1:
            def scrape_jobs(self, k, limit=10): raise MemoryError("OOM")
        class Crash2:
            def scrape_jobs(self, k, limit=10): raise KeyError("Missing key")
        class Crash3:
            def scrape_jobs(self, k, limit=10): raise requests.exceptions.ConnectionError("Host unreachable")
        class Crash4:
            def scrape_jobs(self, k, limit=10): raise ValueError("Invalid parameter")

        fake_registry = {"C1": Crash1, "C2": Crash2, "C3": Crash3, "C4": Crash4}
        with patch.dict("scraper.multi_scraper.SCRAPERS", fake_registry, clear=True):
            results = scrape_all(keywords=["python"], limit_per_source=5, timeout=2.0)
            self.assertEqual(results, [])

    def test_scrape_all_strict_timeout_ceiling_on_hanging_scrapers(self):
        class InfiniteHangScraper:
            def scrape_jobs(self, k, limit=10):
                time.sleep(30.0)
                return [{"title": "Should Never Arrive"}]

        class FastScraper:
            def scrape_jobs(self, k, limit=10):
                return [{"title": "Fast Job", "company": "Swift LLC", "url": "https://swift.com"}]

        fake_registry = {
            "Hang1": InfiniteHangScraper,
            "Hang2": InfiniteHangScraper,
            "Hang3": InfiniteHangScraper,
            "Hang4": InfiniteHangScraper,
            "Fast": FastScraper,
        }

        with patch.dict("scraper.multi_scraper.SCRAPERS", fake_registry, clear=True):
            start_time = time.time()
            results = scrape_all(keywords=["python"], limit_per_source=5, timeout=0.6)
            elapsed = time.time() - start_time

            self.assertLess(elapsed, 2.0, f"scrape_all exceeded timeout ceiling! Elapsed: {elapsed:.2f}s")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["title"], "Fast Job")
            self.assertEqual(results[0]["company"], "Swift LLC")

    def test_scrape_all_mixed_failure_modes_and_schema_contract_compliance(self):
        class NormalScraper:
            def scrape_jobs(self, k, limit=10):
                return [
                    {
                        "job_id_on_platform": "JOB-1",
                        "platform": "Himalayas",
                        "title": "Senior Python Architect",
                        "company": "Tech Corp",
                        "location": "Remote",
                        "url": "https://himalayas.app/jobs/1",
                        "description": "Full description here.",
                        "salary": "$150,000",
                        "date_posted": "2026-08-30",
                        "skills": "Python, SQL",
                    }
                ]

        class ExplodingScraper:
            def scrape_jobs(self, k, limit=10):
                raise requests.exceptions.SSLError("SSL Handshake Failed")

        class SlowHangingScraper:
            def scrape_jobs(self, k, limit=10):
                time.sleep(10.0)
                return [{"title": "Late"}]

        fake_registry = {
            "Good": NormalScraper,
            "Explode": ExplodingScraper,
            "Hang": SlowHangingScraper,
        }

        with patch.dict("scraper.multi_scraper.SCRAPERS", fake_registry, clear=True):
            results = scrape_all(keywords=["architect"], limit_per_source=5, timeout=0.5)
            self.assertEqual(len(results), 1)
            job = results[0]

            expected_fields = [
                "job_id_on_platform", "platform", "title", "company", "location",
                "url", "description", "salary", "date_posted", "skills",
                "salary_range", "remote_level", "skills_required"
            ]
            for f in expected_fields:
                self.assertIn(f, job, f"Missing contract field: {f}")

            self.assertEqual(job["job_id_on_platform"], "JOB-1")
            self.assertEqual(job["title"], "Senior Python Architect")
            self.assertEqual(job["company"], "Tech Corp")

    def test_scrape_all_enabled_sources_filtering_and_edge_cases(self):
        class S1:
            def scrape_jobs(self, k, limit=10): return [{"title": "S1 Job", "url": "http://1"}]
        class S2:
            def scrape_jobs(self, k, limit=10): return [{"title": "S2 Job", "url": "http://2"}]

        fake_registry = {"PortalA": S1, "PortalB": S2}
        with patch.dict("scraper.multi_scraper.SCRAPERS", fake_registry, clear=True):
            res_a = scrape_all(["kw"], enabled_sources=["PortalA"])
            self.assertEqual(len(res_a), 1)
            self.assertEqual(res_a[0]["title"], "S1 Job")

            # Empty enabled sources evaluates to falsey, defaulting to all active scrapers
            res_empty = scrape_all(["kw"], enabled_sources=[])
            self.assertEqual(len(res_empty), 2)

            res_unknown = scrape_all(["kw"], enabled_sources=["NonExistentPlatform"])
            self.assertEqual(res_unknown, [])

    def test_scrape_all_deduplication_integrity(self):
        class DuplicateScraper1:
            def scrape_jobs(self, k, limit=10):
                return [
                    {"platform": "Himalayas", "job_id_on_platform": "DUP-100", "title": "Job 1", "company": "Co A"},
                    {"platform": "Himalayas", "job_id_on_platform": "DUP-101", "title": "Job 2", "company": "Co B"},
                ]

        class DuplicateScraper2:
            def scrape_jobs(self, k, limit=10):
                return [
                    {"platform": "Himalayas", "job_id_on_platform": "DUP-100", "title": "Job 1 Duplicate", "company": "Co A"},
                    {"platform": "Remotive", "job_id_on_platform": "DUP-100", "title": "Job 1 on Remotive", "company": "Co A"},
                ]

        fake_registry = {"S1": DuplicateScraper1, "S2": DuplicateScraper2}
        with patch.dict("scraper.multi_scraper.SCRAPERS", fake_registry, clear=True):
            results = scrape_all(keywords=["engineer"])
            self.assertEqual(len(results), 3)
            platforms_and_ids = [(j["platform"].lower(), j["job_id_on_platform"]) for j in results]
            self.assertIn(("himalayas", "DUP-100"), platforms_and_ids)
            self.assertIn(("himalayas", "DUP-101"), platforms_and_ids)
            self.assertIn(("remotive", "DUP-100"), platforms_and_ids)


class TestAdversarialNetworkAndBotShields(unittest.TestCase):
    @patch("requests.Session.get")
    def test_himalayas_rate_limit_429(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_get.return_value = mock_resp

        scraper = HimalayasScraper()
        jobs = scraper.scrape_jobs(["python"])
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_himalayas_server_error_500_and_503(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_get.return_value = mock_resp

        scraper = HimalayasScraper()
        jobs = scraper.scrape_jobs(["python"])
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_himalayas_akamai_anti_bot_html_challenge_interception(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><head><title>Access Denied - Akamai Bot Manager</title></head><body><h1>Challenge</h1></body></html>"
        mock_resp.json.side_effect = ValueError("Invalid JSON payload")
        mock_get.return_value = mock_resp

        scraper = HimalayasScraper()
        jobs = scraper.scrape_jobs(["python"])
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_himalayas_xss_and_html_entity_sanitization(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jobs": [
                {
                    "title": "Lead & Principal Developer",
                    "companyName": "Security Co.",
                    "description": "Building secure systems. alert(1)",
                    "applicationLink": "https://himalayas.app/jobs/123",
                    "minSalary": 150000,
                    "maxSalary": 200000,
                    "currency": "USD",
                    "categories": ["software-dev"],
                    "locationRestrictions": ["Remote"],
                    "pubDate": 1725000000,
                    "guid": "https://himalayas.app/jobs/123",
                }
            ]
        }
        mock_get.return_value = mock_resp

        scraper = HimalayasScraper()
        jobs = scraper.scrape_jobs(["developer"])
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["title"], "Lead & Principal Developer")
        self.assertEqual(job["company"], "Security Co.")

    @patch("requests.Session.get")
    def test_himalayas_network_exceptions_handling(self, mock_get):
        network_errors = [
            requests.exceptions.Timeout("Connection timed out"),
            requests.exceptions.ConnectionError("DNS failure"),
            requests.exceptions.TooManyRedirects("Redirect loop"),
            requests.exceptions.ChunkedEncodingError("Incomplete read"),
        ]
        scraper = HimalayasScraper()
        for err in network_errors:
            mock_get.side_effect = err
            jobs = scraper.scrape_jobs(["python"])
            self.assertEqual(jobs, [], f"Failed to gracefully handle {err}")

    @patch("requests.Session.get")
    def test_remotive_rate_limit_429(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limit exceeded"
        mock_get.return_value = mock_resp

        scraper = RemotiveScraper()
        jobs = scraper.scrape_jobs(["python"])
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_remotive_cloudflare_captcha_block(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><title>Just a moment... Cloudflare</title></html>"
        mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        mock_get.return_value = mock_resp

        scraper = RemotiveScraper()
        jobs = scraper.scrape_jobs(["python"])
        self.assertEqual(jobs, [])

    @patch("requests.Session.get")
    def test_remotive_network_exceptions_handling(self, mock_get):
        network_errors = [
            requests.exceptions.Timeout("Connection timed out"),
            requests.exceptions.ConnectionError("Connection refused"),
            requests.exceptions.SSLError("SSL Verification Failed"),
        ]
        scraper = RemotiveScraper()
        for err in network_errors:
            mock_get.side_effect = err
            jobs = scraper.scrape_jobs(["python"])
            self.assertEqual(jobs, [], f"Failed to gracefully handle {err}")

    @patch("requests.get")
    def test_linkedin_guest_api_rate_limit_and_999_block(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 999
        mock_get.return_value = mock_resp

        scraper = LinkedInScraper()
        with patch.object(scraper, "_scrape_playwright_fallback", return_value=[]):
            jobs = scraper.scrape_jobs(["engineer"])
            self.assertEqual(jobs, [])

    @patch("requests.get")
    def test_linkedin_guest_api_html_parsing_empty_and_broken_dom(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><div>No jobs found or DOM structure changed</div></body></html>"
        mock_get.return_value = mock_resp

        scraper = LinkedInScraper()
        with patch.object(scraper, "_scrape_playwright_fallback", return_value=[]):
            jobs = scraper.scrape_jobs(["engineer"])
            self.assertEqual(jobs, [])

    def test_linkedin_job_id_extraction_edge_cases(self):
        scraper = LinkedInScraper()
        self.assertEqual(scraper._extract_job_id("https://www.linkedin.com/jobs/view/3948291048?trackingId=abc"), "3948291048")
        self.assertEqual(scraper._extract_job_id("https://www.linkedin.com/jobs/view/senior-dev-3948291048"), "3948291048")
        self.assertEqual(scraper._extract_job_id(""), "")
        self.assertTrue(scraper._extract_job_id("https://linkedin.com/custom/path").startswith("li_"))

    def test_naukri_slugify_edge_cases(self):
        scraper = NaukriScraper()
        self.assertEqual(scraper._slugify_keyword("Software Engineer / Backend"), "software-engineer-backend-jobs")
        self.assertEqual(scraper._slugify_keyword("Python & Django Bangalore"), "python-django-bangalore-jobs")
        self.assertEqual(scraper._slugify_keyword("   "), "-jobs")

    def test_hirist_slugify_edge_cases(self):
        scraper = HiristScraper()
        self.assertEqual(scraper._slugify_keyword("Full Stack Developer (React+Node)"), "full-stack-developer-reactnode-jobs")
        self.assertEqual(scraper._slugify_keyword("AI/ML Engineer"), "aiml-engineer-jobs")

    def test_wellfound_slugify_edge_cases(self):
        scraper = WellfoundScraper()
        self.assertEqual(scraper._slugify_role("Senior Backend Engineer (Golang)"), "senior-backend-engineer-golang")
        self.assertEqual(scraper._slugify_role("   Frontend Lead   "), "frontend-lead")


class TestPaywallEliminationInvariants(unittest.TestCase):
    def test_registry_contains_only_free_direct_portals(self):
        expected_portals = {"LinkedIn", "Naukri", "Wellfound", "Hirist", "Himalayas", "Remotive"}
        self.assertEqual(set(SCRAPERS.keys()), expected_portals)

    def test_deprecated_scrapers_strictly_unimportable(self):
        with self.assertRaises(ModuleNotFoundError):
            import scraper.remoteok_scraper  # noqa: F401

        with self.assertRaises(ModuleNotFoundError):
            import scraper.weworkremotely_scraper  # noqa: F401


if __name__ == "__main__":
    unittest.main()
