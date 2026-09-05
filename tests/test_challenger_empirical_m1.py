"""
Adversarial Empirical Stress Testing & Verification Harness for Milestone 1 (M1).
Authored by: Challenger 2 (Empirical Challenger).

Tests 5 Critical Dimensions:
1. Paywall Elimination & Strict Source Isolation (Zero trace of RemoteOK / WeWorkRemotely / Adzuna)
2. Universal Normalization Invariants, Extreme/Adversarial Input Fuzzing, and SHA-256 Fallback ID Collision Resistance
3. Multi-Scraper Deduplication Invariants (Composite Key, Cross-Platform Collision Safety, Case & Whitespace Handling)
4. Concurrent Execution, Timeout Enforcement, Exception Barriers, and Degraded Scraper Resilience
5. Deep Unit and Mock Parsing Invariant Verification for all 6 Direct Scrapers (LinkedIn, Naukri, Wellfound, Hirist, Himalayas, Remotive)
"""

import hashlib
import html
import math
import os
import re
import sys
import time
import unittest
from typing import Any, Dict, List
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


class TestPaywallEliminationEmpirical(unittest.TestCase):
    """
    Dimension 1: Strict Verification of Paywall Elimination.
    Empirically verifies that RemoteOK, WeWorkRemotely, and Adzuna are completely
    eliminated from runtime modules, SCRAPERS registry, and import paths.
    """

    def test_deprecated_scraper_modules_cannot_be_imported(self):
        """Assert that attempting to import deleted paywalled modules raises ModuleNotFoundError."""
        for module_name in [
            "scraper.remoteok_scraper",
            "scraper.weworkremotely_scraper",
            "scraper.adzuna_scraper",
        ]:
            with self.assertRaises(
                ModuleNotFoundError,
                msg=f"Module {module_name} must NOT exist or be importable.",
            ):
                __import__(module_name)

    def test_scraper_directory_contains_no_deprecated_files(self):
        """Scan scraper directory for physical presence of any deprecated source files."""
        scraper_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scraper"))
        files = os.listdir(scraper_dir)
        forbidden_files = ["remoteok_scraper.py", "weworkremotely_scraper.py", "adzuna_scraper.py"]
        for forbidden in forbidden_files:
            self.assertNotIn(
                forbidden,
                files,
                f"Deprecated file {forbidden} was found in scraper directory!",
            )

    def test_scrapers_registry_exact_composition(self):
        """SCRAPERS registry must contain exactly the 6 active free direct portals."""
        expected_portals = {"LinkedIn", "Naukri", "Wellfound", "Hirist", "Himalayas", "Remotive"}
        actual_portals = set(SCRAPERS.keys())
        self.assertEqual(
            actual_portals,
            expected_portals,
            f"SCRAPERS registry mismatch. Expected {expected_portals}, got {actual_portals}",
        )

    def test_runtime_source_code_has_no_deprecated_references(self):
        """Scan all python runtime files in scraper/ and dashboard/ for hardcoded deprecated strings."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dirs_to_check = [
            os.path.join(project_root, "scraper"),
            os.path.join(project_root, "dashboard"),
        ]
        forbidden_keywords = ["remoteok", "weworkremotely"]

        for d in dirs_to_check:
            if not os.path.exists(d):
                continue
            for root, _, filenames in os.walk(d):
                for fname in filenames:
                    if fname.endswith(".py"):
                        fpath = os.path.join(root, fname)
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read().lower()
                            for kw in forbidden_keywords:
                                self.assertNotIn(
                                    kw,
                                    content,
                                    f"Found forbidden keyword '{kw}' in runtime file: {fpath}",
                                )


class TestDataNormalizationAndAdversarialFuzzing(unittest.TestCase):
    """
    Dimension 2: Normalization Invariants, Extreme Fuzzing & Deterministic SHA-256 Fallbacks.
    """

    REQUIRED_CONTRACT_KEYS = {
        "job_id_on_platform",
        "platform",
        "title",
        "company",
        "location",
        "url",
        "description",
        "salary",
        "date_posted",
        "skills",
        "salary_range",
        "remote_level",
        "skills_required",
    }

    def _assert_valid_contract(self, job: Dict[str, Any]):
        """Helper to assert all schema contract invariants."""
        self.assertIsInstance(job, dict)
        self.assertEqual(set(job.keys()), self.REQUIRED_CONTRACT_KEYS)

        # Required non-empty string fields
        self.assertIsInstance(job["job_id_on_platform"], str)
        self.assertTrue(len(job["job_id_on_platform"]) > 0)

        self.assertIsInstance(job["platform"], str)
        self.assertTrue(len(job["platform"]) > 0)

        self.assertIsInstance(job["title"], str)
        self.assertTrue(len(job["title"]) > 0)

        self.assertIsInstance(job["company"], str)
        self.assertTrue(len(job["company"]) > 0)

        self.assertIsInstance(job["location"], str)
        self.assertTrue(len(job["location"]) > 0)

        self.assertIsInstance(job["url"], str)
        self.assertIsInstance(job["description"], str)
        self.assertLessEqual(len(job["description"]), 3000)

        # Optional fields: str or None
        for opt_key in ["salary", "date_posted", "skills"]:
            val = job[opt_key]
            self.assertTrue(val is None or isinstance(val, str), f"{opt_key} must be str or None, got {type(val)}")

        # Compatibility aliases
        self.assertIsInstance(job["salary_range"], str)
        self.assertIsInstance(job["remote_level"], str)
        self.assertIsInstance(job["skills_required"], str)

    def test_normalize_valid_job(self):
        """Standard valid job dictionary normalizes correctly."""
        raw = {
            "platform": "Remotive",
            "job_id_on_platform": "rem_999",
            "title": "Staff Backend Engineer",
            "company": "NextGen AI",
            "location": "Worldwide",
            "url": "https://remotive.com/jobs/999",
            "description": "Awesome role.",
            "salary": "$170,000 - $200,000",
            "date_posted": "2026-08-25",
            "skills": "Python, Go, Kubernetes",
        }
        norm = _normalize_job(raw, default_platform="Remotive")
        self._assert_valid_contract(norm)
        self.assertEqual(norm["job_id_on_platform"], "rem_999")
        self.assertEqual(norm["title"], "Staff Backend Engineer")
        self.assertEqual(norm["salary"], "$170,000 - $200,000")

    def test_normalize_empty_dictionary(self):
        """Empty input dictionary receives all defaults and a valid 16-char SHA-256 fallback ID."""
        norm = _normalize_job({}, default_platform="LinkedIn")
        self._assert_valid_contract(norm)
        self.assertEqual(norm["platform"], "LinkedIn")
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["company"], "Unknown Company")
        self.assertEqual(norm["location"], "Remote")
        self.assertEqual(norm["url"], "")
        self.assertEqual(norm["description"], "")
        self.assertIsNone(norm["salary"])
        self.assertIsNone(norm["date_posted"])
        self.assertIsNone(norm["skills"])
        self.assertEqual(len(norm["job_id_on_platform"]), 16)
        self.assertTrue(re.match(r"^[0-9a-f]{16}$", norm["job_id_on_platform"]))

    def test_normalize_non_dict_inputs(self):
        """Non-dictionary inputs (None, list, string, int) return empty dict."""
        self.assertEqual(_normalize_job(None), {})
        self.assertEqual(_normalize_job(["invalid"]), {})
        self.assertEqual(_normalize_job("invalid string"), {})
        self.assertEqual(_normalize_job(12345), {})

    def test_normalize_adversarial_null_types(self):
        """Dictionary containing all None values handles safely without TypeError."""
        raw = {k: None for k in ["platform", "job_id_on_platform", "title", "company", "location", "url", "description", "salary", "date_posted", "skills", "salary_range", "remote_level", "skills_required"]}
        norm = _normalize_job(raw, default_platform="Hirist")
        self._assert_valid_contract(norm)
        self.assertEqual(norm["platform"], "Hirist")
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["company"], "Unknown Company")

    def test_normalize_adversarial_non_string_types(self):
        """Handles unexpected types (int, float, list, bool) in scalar fields."""
        raw = {
            "platform": 12345,
            "job_id_on_platform": 987654321,
            "title": 404,
            "company": ["Company", "Name"],
            "location": True,
            "url": 3.14159,
            "description": 100000,
            "salary": 150000,
            "date_posted": 20260830,
            "skills": ["Python", 123, True, None, "Docker"],
        }
        norm = _normalize_job(raw, default_platform="Wellfound")
        self._assert_valid_contract(norm)
        self.assertEqual(norm["job_id_on_platform"], "987654321")
        self.assertEqual(norm["title"], "404")
        self.assertEqual(norm["skills"], "Python, 123, True, Docker")

    def test_normalize_unicode_and_emojis(self):
        """Handles international characters, accents, and emojis in fields and hash seed."""
        raw = {
            "title": "Ingénieur Logiciel Senior 🚀 (Python/Rust)",
            "company": "Société Générale & 科技公司",
            "location": "Montréal, Québec / 東京, 日本",
            "url": "https://example.com/jobs/dév?id=42&lang=fr",
            "description": "Développement de systèmes temps réel avec Python 🐍 et C++ 🚀. 很高兴认识你.",
            "skills": "Python, Rust, 机器学习",
        }
        norm = _normalize_job(raw, default_platform="Naukri")
        self._assert_valid_contract(norm)
        self.assertIn("Ingénieur Logiciel Senior 🚀", norm["title"])
        self.assertIn("Société Générale & 科技公司", norm["company"])
        self.assertIn("Montréal, Québec", norm["location"])
        self.assertEqual(len(norm["job_id_on_platform"]), 16)
        self.assertTrue(re.match(r"^[0-9a-f]{16}$", norm["job_id_on_platform"]))

    def test_normalize_huge_strings_truncation(self):
        """Massive 100,000-character description is safely truncated to 3,000 characters."""
        raw = {
            "title": "Engineer",
            "company": "Corp",
            "description": "A" * 100000,
        }
        norm = _normalize_job(raw, default_platform="Himalayas")
        self._assert_valid_contract(norm)
        self.assertEqual(len(norm["description"]), 3000)
        self.assertEqual(norm["description"], "A" * 3000)

    def test_sha256_fallback_determinism_and_uniqueness(self):
        """
        Stress-tests deterministic SHA-256 fallback job ID generator:
        - Exact same seed produces exact same 16-hex hash 500 times.
        - Distinct permutations produce distinct hashes (collision check across 5,000 items).
        """
        job = {
            "platform": "Remotive",
            "title": "Cloud Architect",
            "company": "SkyHigh Systems",
            "url": "https://remotive.com/jobs/cloud-123",
        }

        first_id = _normalize_job(job)["job_id_on_platform"]
        for _ in range(500):
            self.assertEqual(_normalize_job(job)["job_id_on_platform"], first_id)

        # Generate 5,000 distinct permutations and verify 0 collisions
        seen_hashes = set()
        for i in range(5000):
            job_perm = {
                "platform": "Himalayas",
                "title": f"Software Engineer {i}",
                "company": f"Company {i % 50}",
                "url": f"https://himalayas.app/jobs/{i}",
            }
            hid = _normalize_job(job_perm)["job_id_on_platform"]
            self.assertNotIn(
                hid,
                seen_hashes,
                f"Collision detected at iteration {i} for hash {hid}",
            )
            seen_hashes.add(hid)
        self.assertEqual(len(seen_hashes), 5000)


class TestDeduplicationInvariants(unittest.TestCase):
    """
    Dimension 3: Deduplication Invariants Across Scrapers & Platforms.
    """

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_composite_key_deduplication_exact_match(self):
        """Duplicates on the same platform with the same job_id are deduplicated."""
        from scraper.multi_scraper import SCRAPERS

        cls_mock = MagicMock()
        inst_mock = MagicMock()
        inst_mock.scrape_jobs.return_value = [
            {"platform": "LinkedIn", "job_id_on_platform": "li_101", "title": "Dev 1", "company": "Alpha"},
            {"platform": "LinkedIn", "job_id_on_platform": "li_101", "title": "Dev 1 Dup", "company": "Alpha"},
            {"platform": "LinkedIn", "job_id_on_platform": "li_102", "title": "Dev 2", "company": "Alpha"},
        ]
        cls_mock.return_value = inst_mock
        SCRAPERS["LinkedIn"] = cls_mock

        jobs = scrape_all(["python"])
        self.assertEqual(len(jobs), 2)
        self.assertEqual([j["job_id_on_platform"] for j in jobs], ["li_101", "li_102"])

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_composite_key_cross_platform_same_id_preserved(self):
        """
        Same numeric ID on DIFFERENT platforms must NOT collide.
        E.g., LinkedIn job '99999' and Naukri job '99999' must both be retained.
        """
        from scraper.multi_scraper import SCRAPERS

        cls_li = MagicMock()
        inst_li = MagicMock()
        inst_li.scrape_jobs.return_value = [
            {"platform": "LinkedIn", "job_id_on_platform": "99999", "title": "LI Dev", "company": "LI Corp"}
        ]
        cls_li.return_value = inst_li

        cls_nk = MagicMock()
        inst_nk = MagicMock()
        inst_nk.scrape_jobs.return_value = [
            {"platform": "Naukri", "job_id_on_platform": "99999", "title": "Naukri Dev", "company": "NK Corp"}
        ]
        cls_nk.return_value = inst_nk

        SCRAPERS["LinkedIn"] = cls_li
        SCRAPERS["Naukri"] = cls_nk

        jobs = scrape_all(["dev"])
        self.assertEqual(len(jobs), 2)
        platforms = {j["platform"] for j in jobs}
        self.assertEqual(platforms, {"LinkedIn", "Naukri"})

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_composite_key_case_and_whitespace_insensitivity(self):
        """Deduplication matches platform case-insensitively and strips whitespace in platform & job_id."""
        from scraper.multi_scraper import SCRAPERS

        cls_mock = MagicMock()
        inst_mock = MagicMock()
        inst_mock.scrape_jobs.return_value = [
            {"platform": "Himalayas", "job_id_on_platform": "him_100", "title": "Job A", "company": "Co A"},
            {"platform": "himalayas  ", "job_id_on_platform": "  him_100  ", "title": "Job A Dup", "company": "Co A"},
            {"platform": "HIMALAYAS", "job_id_on_platform": "him_100", "title": "Job A Case", "company": "Co A"},
        ]
        cls_mock.return_value = inst_mock
        SCRAPERS["Himalayas"] = cls_mock

        jobs = scrape_all(["python"])
        self.assertEqual(len(jobs), 1)

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_deduplication_with_sha256_fallbacks(self):
        """Jobs with missing job_id_on_platform but identical platform/title/company/url deduplicate correctly."""
        from scraper.multi_scraper import SCRAPERS

        cls_mock = MagicMock()
        inst_mock = MagicMock()
        inst_mock.scrape_jobs.return_value = [
            {"platform": "Hirist", "title": "DevOps Engineer", "company": "InnoTech", "url": "https://example.com/1"},
            {"platform": "Hirist", "title": "DevOps Engineer", "company": "InnoTech", "url": "https://example.com/1"},
            {"platform": "Hirist", "title": "DevOps Engineer", "company": "InnoTech", "url": "https://example.com/2"},
        ]
        cls_mock.return_value = inst_mock
        SCRAPERS["Hirist"] = cls_mock

        jobs = scrape_all(["devops"])
        self.assertEqual(len(jobs), 2)


class TestConcurrencyTimeoutsAndErrorIsolation(unittest.TestCase):
    """
    Dimension 4: Concurrency, 25-Second Timeout Enforcement, and Complete Exception Barrier.
    """

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_all_6_scrapers_execute_concurrently(self):
        """6 scrapers each taking 0.15s must complete in under 0.6s total."""
        from scraper.multi_scraper import SCRAPERS

        def make_scraper(portal_name):
            mock_cls = MagicMock()
            mock_inst = MagicMock()

            def scrape(keywords, limit=10):
                time.sleep(0.15)
                return [{"platform": portal_name, "job_id_on_platform": f"{portal_name}_1", "title": "Job", "company": "Co"}]

            mock_inst.scrape_jobs.side_effect = scrape
            mock_cls.return_value = mock_inst
            return mock_cls

        portals = ["LinkedIn", "Naukri", "Wellfound", "Hirist", "Himalayas", "Remotive"]
        for p in portals:
            SCRAPERS[p] = make_scraper(p)

        start = time.time()
        jobs = scrape_all(["python"], limit_per_source=5, timeout=5.0)
        elapsed = time.time() - start

        self.assertEqual(len(jobs), 6)
        self.assertLess(elapsed, 0.6, f"Concurrent execution took {elapsed:.2f}s, expected < 0.6s")

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_strict_timeout_enforcement_aborts_hanging_threads(self):
        """When 2 scrapers hang indefinitely, scrape_all returns completed jobs within timeout."""
        from scraper.multi_scraper import SCRAPERS

        fast_cls = MagicMock()
        fast_inst = MagicMock()
        fast_inst.scrape_jobs.return_value = [{"platform": "Fast", "job_id_on_platform": "f1", "title": "Fast", "company": "Co"}]
        fast_cls.return_value = fast_inst

        slow_cls = MagicMock()
        slow_inst = MagicMock()

        def hang(keywords, limit=10):
            time.sleep(10.0)
            return [{"platform": "Slow", "job_id_on_platform": "s1", "title": "Slow", "company": "Co"}]

        slow_inst.scrape_jobs.side_effect = hang
        slow_cls.return_value = slow_inst

        SCRAPERS["Fast"] = fast_cls
        SCRAPERS["Slow1"] = slow_cls
        SCRAPERS["Slow2"] = slow_cls

        start = time.time()
        jobs = scrape_all(["python"], limit_per_source=5, timeout=0.25)
        elapsed = time.time() - start

        self.assertLess(elapsed, 1.0, f"Timeout failed: took {elapsed:.2f}s")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["platform"], "Fast")

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_catastrophic_exception_barriers(self):
        """
        Tests that diverse unhandled exceptions in scrapers (ZeroDivision, MemoryError, TypeError,
        ConnectionResetError, CorruptedData) are completely contained and logged.
        """
        from scraper.multi_scraper import SCRAPERS

        exceptions = [
            ZeroDivisionError("Division by zero in scraper logic"),
            MemoryError("Simulated memory pressure"),
            TypeError("NoneType object is not subscriptable"),
            ConnectionResetError("Remote server disconnected"),
            ValueError("Malformed JSON response"),
        ]

        for i, exc in enumerate(exceptions):
            c_cls = MagicMock()
            c_inst = MagicMock()
            c_inst.scrape_jobs.side_effect = exc
            c_cls.return_value = c_inst
            SCRAPERS[f"Crasher_{i}"] = c_cls

        good_cls = MagicMock()
        good_inst = MagicMock()
        good_inst.scrape_jobs.return_value = [
            {"platform": "Good", "job_id_on_platform": "g_1", "title": "Good Job", "company": "Good Co"}
        ]
        good_cls.return_value = good_inst
        SCRAPERS["GoodPortal"] = good_cls

        jobs = scrape_all(["test"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Good Job")

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_scraper_returning_garbage_data_types(self):
        """Scrapers returning non-dict, non-list, or corrupted objects handle gracefully."""
        from scraper.multi_scraper import SCRAPERS

        c1 = MagicMock()
        c1.return_value.scrape_jobs.return_value = "string not a list"
        c2 = MagicMock()
        c2.return_value.scrape_jobs.return_value = 12345
        c3 = MagicMock()
        c3.return_value.scrape_jobs.return_value = {"dictionary": "instead of list"}
        c4 = MagicMock()
        c4.return_value.scrape_jobs.return_value = [None, "garbage", 999, {}, {"title": "Valid", "company": "Co"}]

        SCRAPERS["C1"] = c1
        SCRAPERS["C2"] = c2
        SCRAPERS["C3"] = c3
        SCRAPERS["C4"] = c4

        jobs = scrape_all(["test"])
        self.assertEqual(len(jobs), 2)  # {} and valid dict both get normalized
        valid_job = [j for j in jobs if j["title"] == "Valid"][0]
        self.assertEqual(valid_job["company"], "Co")

    @patch.dict("scraper.multi_scraper.SCRAPERS", {}, clear=True)
    def test_enabled_sources_filtering_mocked(self):
        """Tests enabled_sources with valid, invalid, and subset lists under mocked scrapers."""
        from scraper.multi_scraper import SCRAPERS

        cls_a = MagicMock()
        cls_a.return_value.scrape_jobs.return_value = [{"title": "Job A", "company": "Co A"}]
        cls_b = MagicMock()
        cls_b.return_value.scrape_jobs.return_value = [{"title": "Job B", "company": "Co B"}]

        SCRAPERS["SourceA"] = cls_a
        SCRAPERS["SourceB"] = cls_b

        # Filter SourceA only
        jobs_a = scrape_all(["python"], enabled_sources=["SourceA"])
        self.assertEqual(len(jobs_a), 1)
        self.assertEqual(jobs_a[0]["platform"], "SourceA")

        # Filter Non-existent source -> empty
        jobs_none = scrape_all(["python"], enabled_sources=["UnknownSource"])
        self.assertEqual(len(jobs_none), 0)


class TestDirectScrapersUnitDeep(unittest.TestCase):
    """
    Dimension 5: Deep Invariant Testing for all 6 Direct Scraper Implementations.
    """

    # --- Himalayas Scraper ---
    def test_himalayas_scraper_resilient_session(self):
        scraper = HimalayasScraper()
        self.assertEqual(scraper.platform_name, "Himalayas")
        self.assertIsNotNone(scraper.session)

    @patch("requests.Session.get")
    def test_himalayas_deep_parsing_and_contract(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jobs": [
                {
                    "title": "Senior AI Engineer",
                    "companyName": "DeepScale Labs",
                    "companySlug": "deepscale-labs",
                    "minSalary": 140000,
                    "maxSalary": 190000,
                    "currency": "USD",
                    "locationRestrictions": ["Worldwide"],
                    "categories": ["Python", "Machine Learning", "LLMs"],
                    "description": "<p>Build state-of-the-art &quot;LLM&quot; pipelines &amp; agents.</p>",
                    "pubDate": 1788086400,
                    "applicationLink": "https://himalayas.app/jobs/deepscale/ai-eng",
                    "guid": "https://himalayas.app/jobs/deepscale/ai-eng-100",
                }
            ]
        }
        mock_get.return_value = mock_resp

        scraper = HimalayasScraper()
        jobs = scraper.scrape_jobs(["python"], limit=5)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["platform"], "Himalayas")
        self.assertEqual(job["title"], "Senior AI Engineer")
        self.assertEqual(job["company"], "DeepScale Labs")
        self.assertEqual(job["job_id_on_platform"], "ai-eng-100")
        self.assertEqual(job["salary"], "USD 140,000 - 190,000")
        self.assertEqual(job["skills"], "Python, Machine Learning, LLMs")
        self.assertEqual(job["description"], "Build state-of-the-art \"LLM\" pipelines & agents.")

    # --- Remotive Scraper ---
    def test_remotive_scraper_resilient_session(self):
        scraper = RemotiveScraper()
        self.assertEqual(scraper.platform_name, "Remotive")
        self.assertIsNotNone(scraper.session)

    @patch("requests.Session.get")
    def test_remotive_deep_parsing_and_contract(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jobs": [
                {
                    "id": 88412,
                    "title": "Principal Rust Engineer",
                    "company_name": "Distributed Co",
                    "category": "Software Development",
                    "tags": ["rust", "distributed-systems", "grpc"],
                    "publication_date": "2026-08-29T10:30:00",
                    "candidate_required_location": "Remote - US/EU",
                    "salary": "$180k - $220k",
                    "description": "<p>High performance distributed systems in Rust.</p>",
                    "url": "https://remotive.com/jobs/88412",
                }
            ]
        }
        mock_get.return_value = mock_resp

        scraper = RemotiveScraper()
        jobs = scraper.scrape_jobs(["rust"], limit=5)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["platform"], "Remotive")
        self.assertEqual(job["job_id_on_platform"], "88412")
        self.assertEqual(job["salary"], "$180k - $220k")
        self.assertEqual(job["date_posted"], "2026-08-29")
        self.assertEqual(job["skills"], "rust, distributed-systems, grpc")
        self.assertEqual(job["description"], "High performance distributed systems in Rust.")

    # --- LinkedIn Scraper ---
    def test_linkedin_job_id_extraction_patterns(self):
        scraper = LinkedInScraper()
        # Direct view URL
        self.assertEqual(
            scraper._extract_job_id("https://www.linkedin.com/jobs/view/4019283746"),
            "4019283746",
        )
        # Slug + ID URL
        self.assertEqual(
            scraper._extract_job_id("https://www.linkedin.com/jobs/view/staff-software-engineer-4019283746?refId=1"),
            "4019283746",
        )
        # Dash number pattern
        self.assertEqual(
            scraper._extract_job_id("https://www.linkedin.com/jobs/search/?currentJobId=4019283746-1234567"),
            "1234567",
        )
        # Non-matching fallback
        fallback = scraper._extract_job_id("https://www.linkedin.com/unknown/path")
        self.assertTrue(fallback.startswith("li_"))

    @patch("requests.get")
    def test_linkedin_guest_api_parsing_comprehensive(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <ul class="jobs-search__results-list">
            <li>
                <div class="base-card">
                    <h3 class="base-search-card__title">Senior Distributed Systems Lead</h3>
                    <h4 class="base-search-card__subtitle"><a href="#">Apex Dynamics</a></h4>
                    <span class="job-search-card__location">Remote, Worldwide</span>
                    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/senior-distributed-systems-lead-4091827364?trackingId=abc">Apply</a>
                    <time datetime="2026-08-29">1 day ago</time>
                    <span class="job-search-card__salary-info">$180,000 - $230,000</span>
                </div>
            </li>
        </ul>
        """
        mock_get.return_value = mock_resp

        scraper = LinkedInScraper()
        with patch.object(scraper, "_fetch_job_description", return_value="Detailed LinkedIn job description."):
            jobs = scraper._scrape_guest_api(["distributed"], limit=5)

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["platform"], "LinkedIn")
        self.assertEqual(job["title"], "Senior Distributed Systems Lead")
        self.assertEqual(job["company"], "Apex Dynamics")
        self.assertEqual(job["location"], "Remote, Worldwide")
        self.assertEqual(job["job_id_on_platform"], "4091827364")
        self.assertEqual(job["salary"], "$180,000 - $230,000")
        self.assertEqual(job["date_posted"], "2026-08-29")
        self.assertEqual(job["description"], "Detailed LinkedIn job description.")

    # --- Naukri Scraper ---
    def test_naukri_slugify_keyword(self):
        scraper = NaukriScraper()
        self.assertEqual(scraper._slugify_keyword("Python Backend"), "python-backend-jobs")
        self.assertEqual(scraper._slugify_keyword("C++ / Rust Developer!"), "c-rust-developer-jobs")
        self.assertEqual(scraper._slugify_keyword("   Machine   Learning   "), "machine-learning-jobs")

    def test_naukri_job_id_extraction(self):
        scraper = NaukriScraper()
        self.assertEqual(scraper._extract_job_id("http://naukri.com/job-12345678", "explicit_id_1"), "explicit_id_1")
        self.assertEqual(scraper._extract_job_id("http://naukri.com/job-listings-python-dev-12345678?src=srp"), "12345678")
        self.assertTrue(scraper._extract_job_id("http://naukri.com/other").startswith("naukri_"))

    # --- Wellfound Scraper ---
    def test_wellfound_slugify_role(self):
        scraper = WellfoundScraper()
        self.assertEqual(scraper._slugify_role("Full Stack Engineer"), "full-stack-engineer")
        self.assertEqual(scraper._slugify_role("AI / ML Researcher"), "ai-ml-researcher")

    def test_wellfound_job_id_extraction(self):
        scraper = WellfoundScraper()
        self.assertEqual(scraper._extract_job_id("https://wellfound.com/jobs/9876543-lead-engineer"), "9876543")
        self.assertTrue(scraper._extract_job_id("https://wellfound.com/jobs/").startswith("wellfound_"))

    # --- Hirist Scraper ---
    def test_hirist_slugify_keyword(self):
        scraper = HiristScraper()
        self.assertEqual(scraper._slugify_keyword("Fullstack Developer"), "fullstack-developer-jobs")
        self.assertEqual(scraper._slugify_keyword("DevOps / Cloud"), "devops-cloud-jobs")

    def test_hirist_job_id_extraction(self):
        scraper = HiristScraper()
        self.assertEqual(scraper._extract_job_id("https://www.hirist.tech/j/backend-engineer-54321.html"), "54321")
        self.assertTrue(scraper._extract_job_id("https://www.hirist.tech/j/invalid.html").startswith("hirist_"))


if __name__ == "__main__":
    unittest.main()
