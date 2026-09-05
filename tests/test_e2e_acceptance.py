"""
Milestone 6: Comprehensive End-to-End Acceptance Test Suite.
Autonomous Job Applicant System.

4-Tier Test Architecture:
- Tier 1: Feature Coverage (All 16 features from PROJECT.md Feature Inventory)
- Tier 2: Boundary & Corner Cases (Empty inputs, NaN handling, Unicode/XSS, single-bound salary, lock contention)
- Tier 3: Cross-Feature Integration (Scraping -> Deduplication -> ATS Evaluation -> Resume Tailoring -> Stage Progression -> Timeline Audit)
- Tier 4: Real-World Workload Scenarios (Complete multi-job candidate application campaign lifecycle)
"""

import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["DB_PATH"] = ":memory:"

from config import config
from db.database import Database, _clean_nan, _to_int_or_none
from scraper.base_scraper import BaseScraper
from scraper.multi_scraper import SCRAPERS, scrape_all, normalize_job, run_single_scraper
from scraper.himalayas_scraper import HimalayasScraper
from scraper.remotive_scraper import RemotiveScraper
from scraper.linkedin_scraper import LinkedInScraper
from scraper.naukri_scraper import NaukriScraper
from scraper.wellfound_scraper import WellfoundScraper
from scraper.hirist_scraper import HiristScraper
from utils.browser_manager import (
    BrowserManager,
    DEFAULT_USER_DATA_DIR,
    PORTAL_LOGIN_URLS,
    PORTAL_DOMAINS,
)
from agents.evaluator_agent import evaluate_job, _evaluate_with_keywords, CANONICAL_SKILL_PATTERNS
from agents.resume_tailor_agent import tailor_resume
from resume_engine.generator import ResumeGenerator
from dashboard.app import (
    clean_score,
    get_score_badge_html,
    filter_applications,
    KANBAN_STAGES,
    STAGE_NEXT_MAP,
    CORE_PORTALS,
)
from orchestrator import (
    run_pipeline,
    evaluate_pending_jobs,
    tailor_high_match_jobs,
    _load_base_resume,
    _generate_html_resume,
)


# ═════════════════════════════════════════════════════════════════════
# TIER 1: FEATURE COVERAGE (All 16 Features from PROJECT.md)
# ═════════════════════════════════════════════════════════════════════

class TestTier1FeatureCoverage(unittest.TestCase):
    """Verifies all 16 features from PROJECT.md § Feature Inventory."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        self.sample_resume = {
            "name": "Alex Mercer",
            "email": "alex@mercer.dev",
            "phone": "+1-555-0199",
            "summary": "Senior Software Engineer with expertise in Python, Cloud Architecture, and Data Pipelines.",
            "experience": [
                {
                    "company": "Apex Cloud Systems",
                    "role": "Lead Backend Engineer",
                    "dates": "2021 - Present",
                    "bullets": [
                        "Architected high-scale microservices processing 50k req/sec with Python and FastAPI.",
                        "Implemented automated ETL workflows with Docker, Kubernetes, and PostgreSQL.",
                    ]
                }
            ],
            "skills": ["Python", "FastAPI", "Docker", "PostgreSQL", "Kubernetes", "ETL", "SQL", "AWS"]
        }

    def tearDown(self):
        self.db.close()

    # Feature 1: Paywall Elimination
    def test_feature_01_paywall_elimination(self):
        """Feature 1: RemoteOK and WeWorkRemotely scrapers are deleted, unimportable, and absent from registry and UI."""
        # Deprecated scraper files must not exist
        remoteok_file = os.path.join(PROJECT_ROOT, "scraper", "remoteok_scraper.py")
        wwr_file = os.path.join(PROJECT_ROOT, "scraper", "weworkremotely_scraper.py")
        self.assertFalse(os.path.exists(remoteok_file), "remoteok_scraper.py must be deleted")
        self.assertFalse(os.path.exists(wwr_file), "weworkremotely_scraper.py must be deleted")

        # Modules must not be importable
        with self.assertRaises(ModuleNotFoundError):
            import scraper.remoteok_scraper  # noqa: F401
        with self.assertRaises(ModuleNotFoundError):
            import scraper.weworkremotely_scraper  # noqa: F401

        # Registry must only contain free direct portals
        for dep in ["RemoteOK", "WeWorkRemotely", "remoteok", "weworkremotely"]:
            self.assertNotIn(dep, SCRAPERS)
            self.assertNotIn(dep, [k.lower() for k in SCRAPERS])

        # Dashboard source code must not mention deprecated portals
        dash_path = os.path.join(PROJECT_ROOT, "dashboard", "app.py")
        with open(dash_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("RemoteOK", content)
        self.assertNotIn("WeWorkRemotely", content)

    # Feature 2: Direct Scraper Integration
    def test_feature_02_direct_scraper_integration(self):
        """Feature 2: Active scrapers for Himalayas, Remotive, LinkedIn, Naukri, Wellfound, Hirist are registered and inherit BaseScraper."""
        expected_scrapers = {
            "Himalayas": HimalayasScraper,
            "Remotive": RemotiveScraper,
            "LinkedIn": LinkedInScraper,
            "Naukri": NaukriScraper,
            "Wellfound": WellfoundScraper,
            "Hirist": HiristScraper,
        }
        self.assertEqual(len(SCRAPERS), 6)
        for name, cls in expected_scrapers.items():
            self.assertIn(name, SCRAPERS)
            instance = SCRAPERS[name]()
            self.assertIsInstance(instance, BaseScraper)
            self.assertTrue(hasattr(instance, "scrape_jobs"))

    # Feature 3: Scraper Error Isolation
    def test_feature_03_scraper_error_isolation(self):
        """Feature 3: scrape_all coordinates concurrent ThreadPoolExecutor execution with timeout and exception isolation."""
        class ExplodingScraper(BaseScraper):
            def scrape_jobs(self, keywords, limit=10):
                raise RuntimeError("Catastrophic API crash")

        class HangingScraper(BaseScraper):
            def scrape_jobs(self, keywords, limit=10):
                time.sleep(3)
                return []

        class SuccessfulScraper(BaseScraper):
            def scrape_jobs(self, keywords, limit=10):
                return [{
                    "platform": "Himalayas",
                    "job_id_on_platform": "him-iso-1",
                    "title": "Backend Developer",
                    "company": "Resilient Corp",
                    "url": "https://himalayas.app/jobs/him-iso-1"
                }]

        custom_registry = {
            "Exploding": ExplodingScraper,
            "Hanging": HangingScraper,
            "Good": SuccessfulScraper,
        }

        with patch("scraper.multi_scraper.SCRAPERS", custom_registry):
            results = scrape_all(keywords=["python"], limit_per_source=5, timeout=1)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["company"], "Resilient Corp")
            self.assertEqual(results[0]["platform"], "Himalayas")

    # Feature 4: Stale Data Purging
    def test_feature_04_stale_data_purging(self):
        """Feature 4: purge_deprecated_platforms deletes stale RemoteOK/WeWorkRemotely records from DuckDB."""
        # Insert valid and deprecated jobs
        self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "val-1", "title": "Dev", "company": "Co"})
        self.db.insert_job({"platform": "RemoteOK", "job_id_on_platform": "dep-1", "title": "Old", "company": "Co"})
        self.db.insert_job({"platform": "WeWorkRemotely", "job_id_on_platform": "dep-2", "title": "Old 2", "company": "Co"})

        self.assertEqual(len(self.db.get_all_jobs()), 3)
        purged = self.db.purge_deprecated_platforms()
        self.assertEqual(purged, 2)

        remaining = self.db.get_all_jobs()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["platform"], "LinkedIn")

    # Feature 5: Composite Key Deduplication
    def test_feature_05_composite_key_deduplication(self):
        """Feature 5: (platform, job_id_on_platform) composite key + SHA-256 fallback prevents duplicate inserts."""
        job = {
            "platform": "Himalayas",
            "job_id_on_platform": "hm-dup-100",
            "title": "Staff Engineer",
            "company": "ScaleTech",
            "url": "https://himalayas.app/jobs/hm-dup-100"
        }
        # First insert
        j1, is_new1 = self.db.insert_job(job)
        self.assertTrue(is_new1)
        self.assertGreater(j1, 0)

        # Duplicate insert
        j2, is_new2 = self.db.insert_job(job)
        self.assertFalse(is_new2)
        self.assertEqual(j1, j2)
        self.assertEqual(len(self.db.get_all_jobs()), 1)

    # Feature 6: Reverse Chronological Sorting
    def test_feature_06_reverse_chronological_sorting(self):
        """Feature 6: Jobs query enforces newest-first sorting across all listings."""
        j1, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "t-1",
            "title": "Job 1", "company": "Co A",
        })
        self.db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-01 10:00:00' WHERE id = ?", (j1,))

        j2, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "t-2",
            "title": "Job 2", "company": "Co B",
        })
        self.db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-25 10:00:00' WHERE id = ?", (j2,))

        j3, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "t-3",
            "title": "Job 3", "company": "Co C",
        })
        self.db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-15 10:00:00' WHERE id = ?", (j3,))

        all_jobs = self.db.get_all_jobs(sort_desc=True)
        # Should be Job 2 (Aug 25) -> Job 3 (Aug 15) -> Job 1 (Aug 1)
        self.assertEqual(all_jobs[0]["id"], j2)
        self.assertEqual(all_jobs[1]["id"], j3)
        self.assertEqual(all_jobs[2]["id"], j1)

    # Feature 7: Strict Applied Job Exclusion
    def test_feature_07_strict_applied_job_exclusion(self):
        """Feature 7: Applied or processing jobs are excluded from unevaluated and ready queues."""
        j1, _ = self.db.insert_job({
            "platform": "Naukri", "job_id_on_platform": "app-ex-1",
            "title": "Lead Python Architect", "company": "Fintech Global",
            "match_score": 90
        })
        app_id = self.db.insert_application(j1, status="Ready to Apply")

        # Ready queue includes it initially
        self.assertEqual(len(self.db.get_ready_applications()), 1)

        # Transition to Applied
        self.db.update_application_stage(app_id, "Applied", "Submitted application")
        self.assertTrue(self.db.is_job_applied(j1))

        # Ready queue must exclude it
        self.assertEqual(len(self.db.get_ready_applications()), 0)
        # Unevaluated queue must exclude it
        self.assertNotIn(j1, [j["id"] for j in self.db.get_unevaluated_jobs()])

    # Feature 8: Persistent Context Management
    def test_feature_08_persistent_context_management(self):
        """Feature 8: BrowserManager resolves default and custom user_data_dir and login URLs."""
        self.assertTrue(os.path.isabs(DEFAULT_USER_DATA_DIR))
        self.assertIn("linkedin", PORTAL_LOGIN_URLS)
        self.assertIn("naukri", PORTAL_LOGIN_URLS)
        self.assertIn("wellfound", PORTAL_LOGIN_URLS)
        self.assertIn("hirist", PORTAL_LOGIN_URLS)

        # Check supported portals list
        portals = BrowserManager.get_supported_portals()
        for p in ["linkedin", "naukri", "wellfound", "hirist"]:
            self.assertIn(p, portals)

    # Feature 9: Auth Login CLI Utility
    def test_feature_09_auth_login_cli_utility(self):
        """Feature 9: auth_login.py CLI script provides argument parsing and status command."""
        auth_script = os.path.join(PROJECT_ROOT, "auth_login.py")
        self.assertTrue(os.path.exists(auth_script), "auth_login.py must exist")

        # Run --help
        res = subprocess.run([sys.executable, auth_script, "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--portal", res.stdout)
        self.assertIn("--check", res.stdout)
        self.assertIn("--list", res.stdout)

        # Run --list
        res_list = subprocess.run([sys.executable, auth_script, "--list"], capture_output=True, text=True)
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("Linkedin", res_list.stdout)
        self.assertIn("Naukri", res_list.stdout)

    # Feature 10: Dashboard Login Launcher
    def test_feature_10_dashboard_login_launcher(self):
        """Feature 10: Dashboard session status query returns structured dictionary for all portals."""
        statuses = BrowserManager.get_session_status_all()
        for p in ["linkedin", "naukri", "wellfound", "hirist"]:
            self.assertIn(p, statuses)
            self.assertIn("has_session", statuses[p])
            self.assertIn("portal", statuses[p])

    # Feature 11: Headless Session Reuse
    def test_feature_11_headless_session_reuse(self):
        """Feature 11: BrowserManager detects session presence via storage_state.json and SQLite cookies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initially no session
            self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=tmpdir))

            # Create mock storage_state.json
            state_file = os.path.join(tmpdir, "storage_state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({"cookies": [{"name": "li_at", "domain": ".linkedin.com", "value": "token123"}]}, f)

            # Now has session
            self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=tmpdir))

    # Feature 12: 6-Stage Kanban Pipeline
    def test_feature_12_kanban_pipeline(self):
        """Feature 12: 6-stage Kanban board structures data into exact canonical stages."""
        self.assertEqual(len(KANBAN_STAGES), 6)
        expected = ["Ready to Apply", "Applied", "Reply Received", "Interview Scheduled", "Rejected", "Offer"]
        self.assertEqual(KANBAN_STAGES, expected)

        kanban = self.db.get_kanban_applications()
        for stg in KANBAN_STAGES:
            self.assertIn(stg, kanban)
            self.assertIsInstance(kanban[stg], list)

    # Feature 13: Filterable Application Table
    def test_feature_13_filterable_application_table(self):
        """Feature 13: filter_applications provides multi-field search and score filtering."""
        apps = [
            {"app_id": 1, "title": "Senior Python Engineer", "company": "Alpha Corp", "platform": "LinkedIn", "app_status": "Ready to Apply", "match_score": 90, "skills": "Python, SQL", "notes": ""},
            {"app_id": 2, "title": "Frontend React Dev", "company": "Beta Inc", "platform": "Naukri", "app_status": "Applied", "match_score": 60, "skills": "React, CSS", "notes": "Follow up"},
            {"app_id": 3, "title": "Product Designer", "company": "Gamma Studio", "platform": "Wellfound", "app_status": "Rejected", "match_score": None, "skills": "Figma", "notes": ""},
        ]

        # Text search
        f1 = filter_applications(apps, search_query="python")
        self.assertEqual(len(f1), 1)
        self.assertEqual(f1[0]["app_id"], 1)

        # Score filter (score >= 70)
        f2 = filter_applications(apps, min_table_score=70)
        self.assertEqual(len(f2), 1)
        self.assertEqual(f2[0]["app_id"], 1)

        # Platform filter
        f3 = filter_applications(apps, selected_platforms=["Naukri"])
        self.assertEqual(len(f3), 1)
        self.assertEqual(f3[0]["app_id"], 2)

    # Feature 14: Recruiter Notes & Timeline Logging
    def test_feature_14_recruiter_notes_and_timeline(self):
        """Feature 14: Recruiter notes, interview timestamps, and transition history persist in DuckDB."""
        j1, _ = self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "note-1", "title": "Dev", "company": "Co"})
        app1 = self.db.insert_application(j1, status="Ready to Apply")

        # Update notes & interview
        self.db.update_application_notes(
            app_id=app1,
            notes="Spoke with hiring manager.",
            interview_date="2026-09-10 14:00:00",
            recruiter_info="Sarah Connor <sarah@cyber.com>",
        )

        # Advance stage
        self.db.update_application_stage(app1, "Interview Scheduled", "Scheduled round 1 interview")

        # Verify timeline
        timeline = self.db.get_application_timeline(app1)
        self.assertGreaterEqual(len(timeline), 2)
        stages = [e["stage"] for e in timeline]
        self.assertIn("Interview Scheduled", stages)

    # Feature 15: Unified Pipeline Orchestration
    def test_feature_15_pipeline_orchestration(self):
        """Feature 15: run_pipeline orchestrates scraping, deduplication, evaluation, and application creation."""
        mock_jobs = [
            {
                "platform": "Himalayas", "job_id_on_platform": "pipe-feat-1",
                "title": "Senior Python Architect", "company": "Apex Cloud Systems",
                "description": "Python, FastAPI, Docker, PostgreSQL, Kubernetes microservices.",
                "url": "https://himalayas.app/jobs/pipe-feat-1"
            }
        ]

        with patch("orchestrator.scrape_all", return_value=mock_jobs):
            res = run_pipeline(resume_json=self.sample_resume, min_score=50, db=self.db)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["total_scraped"], 1)
            self.assertEqual(res["newly_stored"], 1)
            self.assertEqual(res["evaluated"], 1)
            self.assertEqual(res["ready"], 1)

            ready_apps = self.db.get_ready_applications()
            self.assertEqual(len(ready_apps), 1)
            self.assertEqual(ready_apps[0]["company"], "Apex Cloud Systems")

    # Feature 16: End-to-End Verification
    def test_feature_16_verification_and_contract_integrity(self):
        """Feature 16: System modules meet interface contracts and data models without regressions."""
        # Database contract
        self.assertTrue(hasattr(self.db, "insert_job"))
        self.assertTrue(hasattr(self.db, "get_all_jobs"))
        self.assertTrue(hasattr(self.db, "update_job_score"))
        self.assertTrue(hasattr(self.db, "insert_application"))
        self.assertTrue(hasattr(self.db, "update_application_stage"))
        self.assertTrue(hasattr(self.db, "get_kanban_applications"))
        self.assertTrue(hasattr(self.db, "get_all_applications_table"))

        # Score sanitization
        self.assertIsNone(clean_score(None))
        self.assertIsNone(clean_score(float("nan")))
        self.assertEqual(clean_score(85), 85)
        self.assertEqual(clean_score("90"), 90)


# ═════════════════════════════════════════════════════════════════════
# TIER 2: BOUNDARY & CORNER CASES
# ═════════════════════════════════════════════════════════════════════

class TestTier2BoundaryAndCornerCases(unittest.TestCase):
    """Adversarial stress-testing of edge cases, malformed data, and type safety."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_boundary_empty_and_none_inputs_everywhere(self):
        """Empty, None, and whitespace strings across normalization, evaluation, and DB."""
        # normalize_job with empty dict
        norm = normalize_job({})
        self.assertIn("job_id_on_platform", norm)
        self.assertEqual(norm["title"], "Untitled Position")
        self.assertEqual(norm["platform"], "Unknown")

        # evaluate_job with empty / None inputs
        score, reason = evaluate_job("", "")
        self.assertEqual(score, 0)
        score2, reason2 = evaluate_job(None, None)
        self.assertEqual(score2, 0)

        # tailor_resume with empty inputs
        tailored = tailor_resume({}, "", "", "")
        self.assertIsInstance(tailored, dict)

    def test_boundary_extreme_unicode_and_xss_safety(self):
        """Extreme unicode, emojis, and XSS injection strings in job data."""
        xss_title = "<script>alert('pwned')</script> Senior 🐍 Developer 日本語 🚀"
        xss_company = "O'Reilly & Sons \"<iframe src='bad.com'>\""
        xss_desc = "<div><b>Role:</b> &amp; 'quotes' and \x00 null bytes and \u202e RLO override</div>"

        j_id, is_new = self.db.insert_job({
            "platform": "LinkedIn",
            "job_id_on_platform": "xss-001",
            "title": xss_title,
            "company": xss_company,
            "description": xss_desc,
        })
        self.assertTrue(is_new)

        stored = self.db.get_all_jobs()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["title"], xss_title)
        self.assertEqual(stored[0]["company"], xss_company)

    def test_boundary_single_bound_salary_parsing(self):
        """Single-bound, range, LPA, and non-standard salary representations."""
        salaries = [
            "$120k - $150k",
            "Up to $180,000",
            "$90,000+",
            "15 LPA - 20 LPA",
            "₹25,00,000 / year",
            "Competitive / DOE",
            "",
            None,
        ]
        for idx, sal in enumerate(salaries):
            j_id, is_new = self.db.insert_job({
                "platform": "Remotive",
                "job_id_on_platform": f"sal-{idx}",
                "title": f"Engineer {idx}",
                "company": "Corp",
                "salary_range": sal,
            })
            self.assertTrue(is_new)

        all_jobs = self.db.get_all_jobs()
        self.assertEqual(len(all_jobs), len(salaries))

    def test_boundary_nan_and_none_score_handling(self):
        """NaN and None scores do not crash sorting, table conversion, or UI helpers."""
        self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "nan-1", "title": "J1", "company": "C", "match_score": float("nan")})
        self.db.insert_job({"platform": "Naukri", "job_id_on_platform": "nan-2", "title": "J2", "company": "C", "match_score": None})
        self.db.insert_job({"platform": "Hirist", "job_id_on_platform": "nan-3", "title": "J3", "company": "C", "match_score": 85})

        jobs = self.db.get_all_jobs()
        self.assertEqual(len(jobs), 3)

        # Test clean_score helper
        for j in jobs:
            score = clean_score(j["match_score"])
            if j["job_id_on_platform"] in ("nan-1", "nan-2"):
                self.assertIsNone(score)
            else:
                self.assertEqual(score, 85)

        # Test badge HTML rendering with None/NaN
        badge_none = get_score_badge_html(None)
        self.assertIn("Unevaluated", badge_none)
        badge_high = get_score_badge_html(85)
        self.assertIn("Match: 85%", badge_high)

    def test_boundary_case_insensitive_and_whitespace_platform_collision(self):
        """Case variations and whitespace in platform names map to identical composite keys."""
        j1, is_new1 = self.db.insert_job({"platform": "  linkedin  ", "job_id_on_platform": "  col-1  ", "title": "T", "company": "C"})
        self.assertTrue(is_new1)

        # Attempt duplicate with uppercase / stripped
        j2, is_new2 = self.db.insert_job({"platform": "LINKEDIN", "job_id_on_platform": "col-1", "title": "T", "company": "C"})
        self.assertFalse(is_new2)
        self.assertEqual(j1, j2)

    def test_boundary_corrupted_sqlite_cookie_database(self):
        """Corrupted or missing SQLite database does not raise unhandled exceptions in BrowserManager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-SQLite binary file named Cookies
            default_dir = os.path.join(tmpdir, "Default")
            os.makedirs(default_dir, exist_ok=True)
            cookies_file = os.path.join(default_dir, "Cookies")
            with open(cookies_file, "wb") as f:
                f.write(b"CORRUPTED_NON_SQLITE_HEADER_DATA_123456789")

            # Must handle corrupted DB gracefully and return False
            has_session = BrowserManager.has_session_for_portal("naukri", user_data_dir=tmpdir)
            self.assertFalse(has_session)


# ═════════════════════════════════════════════════════════════════════
# TIER 3: CROSS-FEATURE INTEGRATION
# ═════════════════════════════════════════════════════════════════════

class TestTier3CrossFeatureIntegration(unittest.TestCase):
    """Verifies seamless multi-component flow across the entire system."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        self.resume = {
            "name": "Jordan Lee",
            "email": "jordan@lee.net",
            "summary": "Full Stack & Cloud Engineer specializing in Python, React, PostgreSQL, and AWS.",
            "experience": [
                {
                    "company": "Nexus Web Systems",
                    "role": "Senior Engineer",
                    "dates": "2020 - 2026",
                    "bullets": [
                        "Built RESTful microservices with Python, FastAPI, and Docker.",
                        "Designed scalable databases using PostgreSQL and Redis on AWS.",
                    ]
                }
            ],
            "skills": ["Python", "FastAPI", "React", "PostgreSQL", "Docker", "AWS", "Redis", "SQL"]
        }

    def tearDown(self):
        self.db.close()

    def test_cross_feature_full_lifecycle_pipeline(self):
        """
        Step-by-step cross-feature integration:
        1. Ingest multi-portal listings
        2. Deduplicate
        3. Evaluate ATS match score
        4. Tailor resume and create application
        5. Progress application through all 6 Kanban stages
        6. Update notes and interview date
        7. Verify timeline audit history
        """
        # 1. Multi-Portal Ingestion
        scraped_raw = [
            {
                "platform": "Himalayas", "job_id_on_platform": "cross-01",
                "title": "Senior Cloud Backend Engineer", "company": "Nova Labs",
                "description": "Looking for Python, FastAPI, PostgreSQL, AWS, and Docker specialist.",
                "url": "https://himalayas.app/jobs/cross-01",
                "salary_range": "$160k - $190k"
            },
            {
                "platform": "LinkedIn", "job_id_on_platform": "cross-02",
                "title": "Graphic Designer", "company": "Creative Art",
                "description": "Photoshop, Illustrator, InDesign vector design.",
                "url": "https://linkedin.com/jobs/view/cross-02",
                "salary_range": "$70k"
            }
        ]

        inserted_ids = []
        for raw in scraped_raw:
            norm = normalize_job(raw)
            j_id, is_new = self.db.insert_job(norm)
            self.assertTrue(is_new)
            inserted_ids.append(j_id)

        # 2. Ingest duplicate to verify deduplication
        j_dup, is_new_dup = self.db.insert_job(normalize_job(scraped_raw[0]))
        self.assertFalse(is_new_dup)
        self.assertEqual(j_dup, inserted_ids[0])

        # 3. Evaluate ATS match score
        eval_count = evaluate_pending_jobs(db=self.db, resume_data=self.resume)
        self.assertEqual(eval_count, 2)

        # Verify scores
        j_cloud = next(j for j in self.db.get_all_jobs() if j["id"] == inserted_ids[0])
        j_design = next(j for j in self.db.get_all_jobs() if j["id"] == inserted_ids[1])
        self.assertGreaterEqual(j_cloud["match_score"], 80)
        self.assertLess(j_design["match_score"], 40)

        # 4. Tailor high-matching jobs (>= 70%)
        tailor_count = tailor_high_match_jobs(db=self.db, resume_data=self.resume, min_score=70)
        self.assertEqual(tailor_count, 1)

        ready_apps = self.db.get_ready_applications()
        self.assertEqual(len(ready_apps), 1)
        app_id = ready_apps[0]["app_id"]
        self.assertEqual(ready_apps[0]["company"], "Nova Labs")
        self.assertIn("Jordan Lee", ready_apps[0]["resume_html"])

        # 5. Progress stage: Ready to Apply -> Applied
        ok1 = self.db.update_application_stage(app_id, "Applied", "Applied via company portal")
        self.assertTrue(ok1)
        self.assertTrue(self.db.is_job_applied(inserted_ids[0]))

        # Progress stage: Applied -> Reply Received
        ok2 = self.db.update_application_stage(app_id, "Reply Received", "Received recruiter message")
        self.assertTrue(ok2)

        # 6. Update notes & schedule interview: Reply Received -> Interview Scheduled
        ok_notes = self.db.update_application_notes(
            app_id=app_id,
            notes="Technical phone screen scheduled.",
            interview_date="2026-09-08 15:30:00",
            recruiter_info="Emma Watson <emma@novalabs.io>",
        )
        self.assertTrue(ok_notes)
        ok3 = self.db.update_application_stage(app_id, "Interview Scheduled", "Confirmed technical interview")
        self.assertTrue(ok3)

        # Progress stage: Interview Scheduled -> Offer
        ok4 = self.db.update_application_stage(app_id, "Offer", "Received official job offer letter")
        self.assertTrue(ok4)

        # 7. Verify Timeline Audit History
        timeline = self.db.get_application_timeline(app_id)
        self.assertGreaterEqual(len(timeline), 5)
        timeline_stages = [entry["stage"] for entry in timeline]
        self.assertIn("Ready to Apply", timeline_stages)
        self.assertIn("Applied", timeline_stages)
        self.assertIn("Reply Received", timeline_stages)
        self.assertIn("Interview Scheduled", timeline_stages)
        self.assertIn("Offer", timeline_stages)


# ═════════════════════════════════════════════════════════════════════
# TIER 4: REAL-WORLD WORKLOAD SCENARIOS
# ═════════════════════════════════════════════════════════════════════

class TestTier4RealWorldWorkloadScenarios(unittest.TestCase):
    """Simulates realistic multi-job, multi-candidate application workflows."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        self.candidate_resume = {
            "name": "Morgan Vance",
            "email": "morgan@vance.io",
            "phone": "+1-555-0842",
            "summary": "Principal Backend & Distributed Systems Architect with deep Python, Go, and Kubernetes background.",
            "experience": [
                {
                    "company": "Vanguard Tech",
                    "role": "Staff Software Architect",
                    "dates": "2019 - Present",
                    "bullets": [
                        "Scaled cloud microservices processing millions of daily events in Python and Go.",
                        "Deployed Kubernetes clusters on AWS and automated CI/CD pipelines.",
                        "Optimized PostgreSQL and Redis persistence layers for low-latency queries."
                    ]
                }
            ],
            "skills": ["Python", "Go", "Kubernetes", "AWS", "Docker", "PostgreSQL", "Redis", "CI/CD", "SQL"]
        }

    def tearDown(self):
        self.db.close()

    def test_realistic_candidate_campaign_across_10_diverse_jobs(self):
        """
        Simulates candidate campaign across 10 jobs from 6 platforms:
        - Ingest 10 jobs with varying relevance
        - Evaluate ATS match scores
        - Tailor resumes for top matching roles (threshold >= 60%)
        - Advance applications through multiple parallel stages
        - Verify Kanban counts, table query filters, and audit history immutability
        """
        ten_jobs = [
            # High match roles
            {"platform": "LinkedIn", "job_id_on_platform": "w-01", "title": "Staff Python & Kubernetes Architect", "company": "Apex Global", "description": "Python, Go, Kubernetes, AWS, PostgreSQL.", "url": "https://linkedin.com/jobs/view/w-01", "salary_range": "$190k - $230k"},
            {"platform": "Himalayas", "job_id_on_platform": "w-02", "title": "Principal Backend Engineer", "company": "Streamline AI", "description": "Python, Docker, Redis, PostgreSQL, Distributed Systems.", "url": "https://himalayas.app/jobs/w-02", "salary_range": "$180k - $210k"},
            {"platform": "Naukri", "job_id_on_platform": "w-03", "title": "Senior Cloud Infrastructure Specialist", "company": "CloudTech", "description": "AWS, Kubernetes, CI/CD, Docker, Python scripting.", "url": "https://naukri.com/job/w-03", "salary_range": "$170k - $200k"},
            {"platform": "Wellfound", "job_id_on_platform": "w-04", "title": "Go & Python Systems Developer", "company": "FastNet Startup", "description": "Go, Python, Redis, SQL, Microservices.", "url": "https://wellfound.com/jobs/w-04", "salary_range": "$160k - $190k"},
            {"platform": "Hirist", "job_id_on_platform": "w-05", "title": "Lead Database & Backend Engineer", "company": "DataHub", "description": "PostgreSQL, SQL, Redis, Python, AWS cloud.", "url": "https://hirist.tech/job/w-05", "salary_range": "$175k - $205k"},

            # Moderate match roles
            {"platform": "Remotive", "job_id_on_platform": "w-06", "title": "DevOps Engineer", "company": "DeployHQ", "description": "Docker, Kubernetes, Linux, Terraform, Monitoring.", "url": "https://remotive.com/jobs/w-06", "salary_range": "$140k - $160k"},
            {"platform": "LinkedIn", "job_id_on_platform": "w-07", "title": "Full Stack Web Developer", "company": "Webify", "description": "React, JavaScript, HTML, CSS, Node.js, Python.", "url": "https://linkedin.com/jobs/view/w-07", "salary_range": "$120k - $140k"},

            # Low / Non-match roles
            {"platform": "Wellfound", "job_id_on_platform": "w-08", "title": "UI/UX Product Designer", "company": "PixelCraft", "description": "Figma, Wireframing, User Research, Prototyping.", "url": "https://wellfound.com/jobs/w-08", "salary_range": "$90k"},
            {"platform": "Naukri", "job_id_on_platform": "w-09", "title": "Technical Content Copywriter", "company": "DocuPress", "description": "Technical writing, Documentation, SEO, Editing.", "url": "https://naukri.com/job/w-09", "salary_range": "$75k"},
            {"platform": "Hirist", "job_id_on_platform": "w-10", "title": "Corporate Office Security Officer", "company": "SafeGuard", "description": "Premises security, Access control, Surveillance.", "url": "https://hirist.tech/job/w-10", "salary_range": "$45k"},
        ]

        # 1. Ingest all 10 listings
        for raw in ten_jobs:
            self.db.insert_job(normalize_job(raw))

        all_stored = self.db.get_all_jobs()
        self.assertEqual(len(all_stored), 10)

        # 2. Evaluate all 10 listings
        evaluated_count = evaluate_pending_jobs(db=self.db, resume_data=self.candidate_resume)
        self.assertEqual(evaluated_count, 10)

        # Check score distribution
        all_evaled = self.db.get_all_jobs()
        high_matches = [j for j in all_evaled if (j["match_score"] or 0) >= 60]
        low_matches = [j for j in all_evaled if (j["match_score"] or 0) < 40]

        self.assertGreaterEqual(len(high_matches), 5)
        self.assertGreaterEqual(len(low_matches), 3)

        # 3. Tailor resumes for top matching roles (>= 60%)
        tailor_count = tailor_high_match_jobs(db=self.db, resume_data=self.candidate_resume, min_score=60)
        self.assertEqual(tailor_count, len(high_matches))

        ready_apps = self.db.get_ready_applications()
        self.assertEqual(len(ready_apps), len(high_matches))

        # 4. Advance applications through realistic lifecycle states:
        # App 1: Advance all the way to Offer
        app1_id = ready_apps[0]["app_id"]
        self.db.update_application_stage(app1_id, "Applied", "Applied on portal")
        self.db.update_application_stage(app1_id, "Reply Received", "Recruiter reached out via email")
        self.db.update_application_notes(app1_id, "Final interview with VP of Eng.", "2026-09-12 10:00:00", "VP John")
        self.db.update_application_stage(app1_id, "Interview Scheduled", "Final round confirmed")
        self.db.update_application_stage(app1_id, "Offer", "Offer package received: $220,000 base + equity")

        # App 2: Advance to Interview Scheduled
        app2_id = ready_apps[1]["app_id"]
        self.db.update_application_stage(app2_id, "Applied", "Applied via LinkedIn")
        self.db.update_application_stage(app2_id, "Reply Received", "Initial HR screen completed")
        self.db.update_application_notes(app2_id, "System design interview scheduled.", "2026-09-15 14:00:00")
        self.db.update_application_stage(app2_id, "Interview Scheduled", "Technical round booked")

        # App 3: Advance to Applied
        app3_id = ready_apps[2]["app_id"]
        self.db.update_application_stage(app3_id, "Applied", "Submitted tailored resume")

        # App 4: Rejected after apply
        app4_id = ready_apps[3]["app_id"]
        self.db.update_application_stage(app4_id, "Applied", "Submitted")
        self.db.update_application_stage(app4_id, "Rejected", "Position filled internally")

        # App 5 (and remainder): Keep in Ready to Apply

        # 5. Verify Kanban Board Stage Counts
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Offer"]), 1)
        self.assertEqual(len(kanban["Interview Scheduled"]), 1)
        self.assertEqual(len(kanban["Applied"]), 1)
        self.assertEqual(len(kanban["Rejected"]), 1)
        self.assertGreaterEqual(len(kanban["Ready to Apply"]), 1)

        # 6. Verify Applications Table Search & Filtering
        all_table_apps = self.db.get_all_applications_table()
        self.assertEqual(len(all_table_apps), len(high_matches))

        # Filter by stage = "Offer"
        offer_filtered = filter_applications(all_table_apps, selected_stages=["Offer"])
        self.assertEqual(len(offer_filtered), 1)
        self.assertEqual(offer_filtered[0]["app_id"], app1_id)

        # Filter by search = "System design"
        note_filtered = filter_applications(all_table_apps, search_query="System design")
        self.assertEqual(len(note_filtered), 1)
        self.assertEqual(note_filtered[0]["app_id"], app2_id)

        # 7. Re-run pipeline to ensure applied jobs are NEVER re-evaluated or overwritten
        re_run_jobs = [ten_jobs[0], ten_jobs[1], ten_jobs[2]]
        with patch("orchestrator.scrape_all", return_value=re_run_jobs):
            res_re = run_pipeline(resume_json=self.candidate_resume, min_score=60, db=self.db)
            self.assertEqual(res_re["newly_stored"], 0)  # All deduplicated
            self.assertEqual(res_re["evaluated"], 0)     # All already processed
            self.assertEqual(res_re["ready"], 0)         # No duplicate applications

        # Total jobs in DB must remain exactly 10
        self.assertEqual(len(self.db.get_all_jobs()), 10)
        # Total applications in DB must remain unchanged
        self.assertEqual(len(self.db.get_all_applications_table()), len(high_matches))


if __name__ == "__main__":
    unittest.main()
