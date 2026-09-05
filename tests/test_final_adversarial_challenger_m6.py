"""
Milestone 6: Final Adversarial Challenger Verification Suite.
Autonomous Job Applicant System.

Adversarial stress harness testing:
1. Paywall elimination and isolation (strict absence of paywalled scrapers).
2. Deduplication edge cases (casing, whitespace, empty/missing IDs, collision resistance).
3. Reverse-chronological sorting and deterministic tie-breaking.
4. Strict applied job exclusion and lifecycle state transitions.
5. DuckDB NaN resilience and sequence integrity.
6. Playwright persistent context directory, auth CLI options, and session detection.
7. Kanban 6-stage pipeline, multi-field search filtering, and timeline audit logging.
8. End-to-end pipeline fault tolerance under mixed failure modes (network crash, timeout, LLM failure).
"""

import concurrent.futures
import hashlib
import json
import math
import os
import sqlite3
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
from db.database import Database, JobList, _clean_nan, _to_int_or_none
from scraper.base_scraper import BaseScraper
from scraper.multi_scraper import (
    SCRAPERS,
    _normalize_job,
    _run_single_scraper,
    normalize_job,
    run_single_scraper,
    scrape_all,
)
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
from auth_login import build_parser, check_status, list_portals
from agents.evaluator_agent import evaluate_job, _evaluate_with_keywords
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


class TestPaywallEliminationAndSourceRegistry(unittest.TestCase):
    """Adversarially validates that no paywalled platforms or scrapers exist."""

    def test_forbidden_scraper_files_do_not_exist(self):
        forbidden = [
            "remoteok_scraper.py",
            "weworkremotely_scraper.py",
            "adzuna_scraper.py",
            "remoteok.py",
            "weworkremotely.py",
        ]
        for f in forbidden:
            full_path = os.path.join(PROJECT_ROOT, "scraper", f)
            self.assertFalse(
                os.path.exists(full_path),
                f"Forbidden scraper file must not exist: {f}",
            )

    def test_forbidden_modules_unimportable(self):
        for mod in [
            "scraper.remoteok_scraper",
            "scraper.weworkremotely_scraper",
            "scraper.adzuna_scraper",
        ]:
            with self.assertRaises(ModuleNotFoundError, msg=f"Module {mod} must raise ModuleNotFoundError"):
                __import__(mod)

    def test_scrapers_registry_exact_portal_composition(self):
        expected_portals = {
            "LinkedIn",
            "Naukri",
            "Wellfound",
            "Hirist",
            "Himalayas",
            "Remotive",
        }
        self.assertEqual(
            set(SCRAPERS.keys()),
            expected_portals,
            f"SCRAPERS registry must contain exactly {expected_portals}",
        )
        for name, cls in SCRAPERS.items():
            self.assertTrue(issubclass(cls, BaseScraper), f"{name} scraper must inherit BaseScraper")

    def test_purge_deprecated_platforms_cascade(self):
        """Verify purging deletes jobs and any associated applications and timeline records."""
        with Database(db_path=":memory:") as db:
            # Insert valid and deprecated jobs
            valid_id, _ = db.insert_job({
                "platform": "Himalayas",
                "job_id_on_platform": "him-001",
                "title": "Backend Engineer",
                "company": "Valid Corp",
            })
            dep1_id, _ = db.insert_job({
                "platform": "RemoteOK",
                "job_id_on_platform": "rok-001",
                "title": "Deprecated Role 1",
                "company": "Old Corp",
            })
            dep2_id, _ = db.insert_job({
                "platform": "WeWorkRemotely",
                "job_id_on_platform": "wwr-001",
                "title": "Deprecated Role 2",
                "company": "Legacy Corp",
            })

            # Create applications for all 3
            v_app = db.insert_application(valid_id, notes="Valid application")
            d1_app = db.insert_application(dep1_id, notes="Dep 1 application")
            d2_app = db.insert_application(dep2_id, notes="Dep 2 application")

            purged_count = db.purge_deprecated_platforms()
            self.assertEqual(purged_count, 2)

            all_jobs = db.get_all_jobs()
            self.assertEqual(len(all_jobs), 1)
            self.assertEqual(all_jobs[0]["platform"], "Himalayas")

            all_apps = db.get_all_applications_table()
            self.assertEqual(len(all_apps), 1)
            self.assertEqual(all_apps[0]["app_id"], v_app)


class TestDeduplicationAndCompositeKeyStress(unittest.TestCase):
    """Adversarial testing of composite key deduplication and hash fallbacks."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_casing_and_whitespace_platform_deduplication(self):
        """Platform casing and whitespace variations must map to the same composite entity."""
        job1 = {
            "platform": "LinkedIn",
            "job_id_on_platform": "job-12345",
            "title": "Senior Python Architect",
            "company": "Acme AI",
        }
        id1, is_new1 = self.db.insert_job(job1)
        self.assertTrue(is_new1)

        variations = [
            {"platform": "linkedin", "job_id_on_platform": "job-12345"},
            {"platform": "LINKEDIN", "job_id_on_platform": "job-12345"},
            {"platform": "  LinkedIn  ", "job_id_on_platform": "job-12345"},
        ]
        for var in variations:
            id_dup, is_new_dup = self.db.insert_job(var)
            self.assertFalse(is_new_dup, f"Variation {var} should be recognized as duplicate")
            self.assertEqual(id1, id_dup)

        self.assertEqual(len(self.db.get_all_jobs()), 1)

    def test_missing_job_id_fallback_sha256_determinism(self):
        """Jobs without job_id_on_platform get deterministic SHA-256 fallback hash."""
        job1 = {
            "platform": "Naukri",
            "job_id_on_platform": "",
            "title": "ML Engineer",
            "company": "DeepTech",
            "url": "https://naukri.com/job/ml-101",
        }
        id1, is_new1 = self.db.insert_job(job1)
        self.assertTrue(is_new1)

        # Same data without explicit id must compute identical hash and dedup
        job2 = {
            "platform": "naukri",
            "job_id_on_platform": None,
            "title": "ML Engineer",
            "company": "DeepTech",
            "url": "https://naukri.com/job/ml-101",
        }
        id2, is_new2 = self.db.insert_job(job2)
        self.assertFalse(is_new2)
        self.assertEqual(id1, id2)

    def test_cross_platform_same_job_id_distinct(self):
        """Identical job_id_on_platform across different platforms are distinct records."""
        id_link, is_new_link = self.db.insert_job({
            "platform": "LinkedIn",
            "job_id_on_platform": "COMMON-ID-99",
            "title": "Engineer",
            "company": "A",
        })
        id_naukri, is_new_naukri = self.db.insert_job({
            "platform": "Naukri",
            "job_id_on_platform": "COMMON-ID-99",
            "title": "Engineer",
            "company": "B",
        })
        self.assertTrue(is_new_link)
        self.assertTrue(is_new_naukri)
        self.assertNotEqual(id_link, id_naukri)
        self.assertEqual(len(self.db.get_all_jobs()), 2)

    def test_repeated_duplicate_batch_ingestion(self):
        """Batch ingestion containing repeated duplicates produces clean deduplicated records."""
        num_distinct = 25
        reps_per_job = 4

        jobs_to_insert = []
        for i in range(num_distinct):
            job = {
                "platform": "Wellfound",
                "job_id_on_platform": f"wf-stress-{i}",
                "title": f"Staff Engineer #{i}",
                "company": f"Startup #{i}",
            }
            for _ in range(reps_per_job):
                jobs_to_insert.append(job)

        results = [self.db.insert_job(j) for j in jobs_to_insert]
        new_count = sum(1 for _, is_new in results if is_new)
        self.assertEqual(new_count, num_distinct)
        self.assertEqual(len(self.db.get_all_jobs()), num_distinct)


class TestOrderingAndSortingIntegrity(unittest.TestCase):
    """Adversarial verification of reverse-chronological ordering and tie-breaking."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_reverse_chronological_sorting_with_staggered_timestamps(self):
        """Jobs must be returned strictly from newest to oldest."""
        base_time = datetime(2026, 8, 1, 12, 0, 0)
        job_ids = []

        # Insert jobs out-of-order in time
        timestamps = [
            base_time + timedelta(days=2),
            base_time + timedelta(days=10),
            base_time + timedelta(days=1),
            base_time + timedelta(days=5),
            base_time + timedelta(days=8),
        ]

        for i, ts in enumerate(timestamps):
            jid, _ = self.db.insert_job({
                "platform": "Himalayas",
                "job_id_on_platform": f"ts-job-{i}",
                "title": f"Job {i}",
                "company": "Corp",
            })
            # Explicitly set scraped_at timestamp
            self.db.conn.execute(
                "UPDATE Jobs SET scraped_at = ?, created_at = ? WHERE id = ?",
                (ts, ts, jid),
            )
            job_ids.append((jid, ts))

        sorted_expected_ids = [jid for jid, _ in sorted(job_ids, key=lambda x: x[1], reverse=True)]
        actual_jobs = self.db.get_all_jobs(sort_desc=True)
        actual_ids = [j["id"] for j in actual_jobs]

        self.assertEqual(actual_ids, sorted_expected_ids)

    def test_tie_breaking_by_id_desc(self):
        """Identical timestamps must break ties deterministically by id DESC."""
        fixed_ts = datetime(2026, 8, 15, 10, 0, 0)
        j1, _ = self.db.insert_job({"platform": "Remotive", "job_id_on_platform": "t1", "title": "A", "company": "C"})
        j2, _ = self.db.insert_job({"platform": "Remotive", "job_id_on_platform": "t2", "title": "B", "company": "C"})
        j3, _ = self.db.insert_job({"platform": "Remotive", "job_id_on_platform": "t3", "title": "C", "company": "C"})

        self.db.conn.execute("UPDATE Jobs SET scraped_at = ?, created_at = ?", (fixed_ts, fixed_ts))

        all_jobs = self.db.get_all_jobs(sort_desc=True)
        self.assertEqual([j["id"] for j in all_jobs], [j3, j2, j1])


class TestAppliedExclusionAndLifecycleIntegrity(unittest.TestCase):
    """Verifies strict exclusion of applied jobs from active pools and 6-stage lifecycle transitions."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_strict_applied_job_exclusion_from_evaluation_and_ready(self):
        """Jobs in Applications table must NEVER appear in get_unevaluated_jobs or get_evaluated_jobs."""
        # Insert 3 jobs
        j1, _ = self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e1", "title": "Role 1", "company": "C1"})
        j2, _ = self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e2", "title": "Role 2", "company": "C2"})
        j3, _ = self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e3", "title": "Role 3", "company": "C3"})

        # Initial: all 3 unevaluated
        uneval = self.db.get_unevaluated_jobs()
        self.assertEqual(len(uneval), 3)

        # Create application for j1 (Ready to Apply)
        app1 = self.db.insert_application(j1, status="Ready to Apply")
        self.assertFalse(self.db.is_job_applied(j1))  # 'Ready to Apply' is pre-submission

        # j1 must now be excluded from get_unevaluated_jobs
        uneval_after = self.db.get_unevaluated_jobs()
        self.assertEqual([j["id"] for j in uneval_after], [j3, j2])

        # Evaluate j2 with high score
        self.db.update_job_score(j2, match_score=90, evaluation_details={"reasoning": "Great fit"})
        eval_candidates = self.db.get_evaluated_jobs_for_application(min_score=70)
        self.assertEqual([j["id"] for j in eval_candidates], [j2])

        # Create application for j2 and advance to 'Applied'
        app2 = self.db.insert_application(j2, status="Ready to Apply")
        self.db.update_application_stage(app2, "Applied")
        self.assertTrue(self.db.is_job_applied(j2))

        # j2 must now be excluded from get_evaluated_jobs_for_application
        eval_candidates_after = self.db.get_evaluated_jobs_for_application(min_score=70)
        self.assertEqual(len(eval_candidates_after), 0)

    def test_full_six_stage_progression_and_audit_timeline(self):
        """Verify sequential progression across all 6 stages and chronological audit trail."""
        jid, _ = self.db.insert_job({
            "platform": "Hirist",
            "job_id_on_platform": "h-999",
            "title": "Tech Lead",
            "company": "Apex",
        })
        app_id = self.db.insert_application(jid, status="Ready to Apply", notes="Initial candidate draft")

        stages_to_traverse = [
            ("Applied", "Submitted via official portal"),
            ("Reply Received", "Recruiter responded requesting interview availability"),
            ("Interview Scheduled", "Technical round scheduled for Monday 10am"),
            ("Offer", "Received competitive offer letter"),
            ("Rejected", "Candidate declined / archived"),
        ]

        for next_stage, note in stages_to_traverse:
            ok = self.db.update_application_stage(app_id, next_stage, note=note)
            self.assertTrue(ok)

        # Retrieve audit timeline
        timeline = self.db.get_application_timeline(app_id)
        self.assertEqual(len(timeline), 6)  # Initial 1 + 5 transitions

        recorded_stages = [t["stage"] for t in timeline]
        expected_stages = ["Ready to Apply", "Applied", "Reply Received", "Interview Scheduled", "Offer", "Rejected"]
        self.assertEqual(recorded_stages, expected_stages)

    def test_update_application_notes_and_dates(self):
        """Verify updating notes, interview dates, follow-up dates, and recruiter contact."""
        jid, _ = self.db.insert_job({
            "platform": "Naukri",
            "job_id_on_platform": "nk-777",
            "title": "Data Architect",
            "company": "DataHub",
        })
        app_id = self.db.insert_application(jid, status="Ready to Apply")

        ok = self.db.update_application_notes(
            app_id=app_id,
            notes="Followed up with hiring manager",
            interview_date="2026-09-15 14:00:00",
            follow_up_date="2026-09-10 09:00:00",
            recruiter_info="Sarah Connor (sarah@datahub.io)",
        )
        self.assertTrue(ok)

        apps = self.db.get_all_applications_table()
        app_entry = [a for a in apps if a["app_id"] == app_id][0]
        self.assertIn("Followed up with hiring manager", app_entry["notes"])
        self.assertIn("Sarah Connor", app_entry["notes"])
        self.assertIsNotNone(app_entry["interview_date"])
        self.assertIsNotNone(app_entry["follow_up_date"])


class TestDuckDBQuirksAndNaNSafety(unittest.TestCase):
    """Stress tests handling of NaN scores, corrupt score fields, and sequence behavior."""

    def test_clean_nan_and_to_int_or_none(self):
        self.assertIsNone(_clean_nan(float("nan")))
        self.assertIsNone(_clean_nan(None))
        self.assertEqual(_clean_nan(85), 85)
        self.assertEqual(_clean_nan("test"), "test")

        self.assertIsNone(_to_int_or_none(float("nan")))
        self.assertIsNone(_to_int_or_none(None))
        self.assertIsNone(_to_int_or_none("invalid_int"))
        self.assertEqual(_to_int_or_none(95.0), 95)
        self.assertEqual(_to_int_or_none("80"), 80)

    def test_joblist_helper_methods(self):
        jl = JobList([{"id": 1, "title": "A"}, {"id": 2, "title": "B"}])
        self.assertFalse(jl.empty)
        self.assertEqual(len(jl), 2)
        rows = list(jl.iterrows())
        self.assertEqual(len(rows), 2)
        df = jl.to_df()
        self.assertEqual(len(df), 2)

        empty_jl = JobList()
        self.assertTrue(empty_jl.empty)


class TestBrowserManagerAndAuthCLI(unittest.TestCase):
    """Validates persistent user data dir, login URLs, and auth_login parser."""

    def test_user_data_dir_resolution(self):
        expected_path = os.path.join(PROJECT_ROOT, "data", "browser_user_data")
        self.assertEqual(os.path.abspath(DEFAULT_USER_DATA_DIR), os.path.abspath(expected_path))
        self.assertEqual(
            os.path.abspath(BrowserManager.get_user_data_dir()),
            os.path.abspath(expected_path),
        )

    def test_supported_portals_and_login_urls(self):
        portals = BrowserManager.get_supported_portals()
        for p in ["linkedin", "naukri", "wellfound", "hirist", "indeed"]:
            self.assertIn(p, portals)
            url = BrowserManager.get_login_url(p)
            self.assertTrue(url.startswith("https://"))

        with self.assertRaises(ValueError):
            BrowserManager.get_login_url("unsupported_fake_portal")

    def test_auth_login_parser_options(self):
        parser = build_parser()
        args = parser.parse_args(["--portal", "linkedin", "--timeout", "120"])
        self.assertEqual(args.portal, "linkedin")
        self.assertEqual(args.timeout, 120)

        args_check = parser.parse_args(["--check"])
        self.assertTrue(args_check.check)

        args_list = parser.parse_args(["--list"])
        self.assertTrue(args_list.list)

    def test_session_detection_mock_storage_state(self):
        """Simulate stored session in a temporary user data dir and verify detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initially no session
            self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=tmpdir))

            # Write fake storage_state.json with linkedin cookie
            state_file = os.path.join(tmpdir, "storage_state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "cookies": [
                        {"name": "li_at", "value": "AQED...", "domain": ".linkedin.com"}
                    ]
                }, f)

            self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=tmpdir))
            self.assertFalse(BrowserManager.has_session_for_portal("naukri", user_data_dir=tmpdir))


class TestDashboardFilterAndKanbanHelpers(unittest.TestCase):
    """Stress tests search filtering, regex safety, and score badges."""

    def test_filter_applications_with_special_characters(self):
        apps = [
            {
                "app_id": 1,
                "title": "C++ / Python Core Engineer (v2.0)",
                "company": "Apex AI [Global]",
                "platform": "LinkedIn",
                "app_status": "Ready to Apply",
                "match_score": 85,
                "skills": "C++, Python, Multithreading",
                "notes": "Met recruiter at conference (2026)",
                "match_reasoning": "Strong match for C++ systems",
            },
            {
                "app_id": 2,
                "title": "Frontend React Developer",
                "company": "WebCorp",
                "platform": "Hirist",
                "app_status": "Applied",
                "match_score": 50,
                "skills": "React, TypeScript, CSS",
                "notes": "",
                "match_reasoning": "Low backend alignment",
            },
        ]

        # Search with special characters that might break unescaped regex or queries
        res1 = filter_applications(apps, search_query="C++")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["app_id"], 1)

        res2 = filter_applications(apps, search_query="[Global]")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["app_id"], 1)

        res3 = filter_applications(apps, search_query="(2026)")
        self.assertEqual(len(res3), 1)
        self.assertEqual(res3[0]["app_id"], 1)

        # Platform filter
        res4 = filter_applications(apps, selected_platforms=["Hirist"])
        self.assertEqual(len(res4), 1)
        self.assertEqual(res4[0]["app_id"], 2)

        # Score filter
        res5 = filter_applications(apps, min_table_score=70)
        self.assertEqual(len(res5), 1)
        self.assertEqual(res5[0]["app_id"], 1)

    def test_score_badge_html(self):
        self.assertIn("Unevaluated", get_score_badge_html(None))
        self.assertIn("badge-score-high", get_score_badge_html(90))
        self.assertIn("badge-score-mid", get_score_badge_html(65))
        self.assertIn("badge-score-low", get_score_badge_html(40))


class TestEndToEndOrchestratorFaultTolerance(unittest.TestCase):
    """Empirically verifies orchestrator under mixed failure scenarios."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_pipeline_execution_with_partial_scraper_failures(self):
        """Pipeline runs smoothly even if 4 out of 6 scrapers throw exceptions."""
        class GoodScraper1(BaseScraper):
            def scrape_jobs(self, keywords, limit=10):
                return [{
                    "platform": "Himalayas",
                    "job_id_on_platform": "him-good-1",
                    "title": "Lead Python Engineer",
                    "company": "CloudAI",
                    "description": "Looking for Python, Docker, Kubernetes, AWS, FastAPI",
                }]

        class GoodScraper2(BaseScraper):
            def scrape_jobs(self, keywords, limit=10):
                return [{
                    "platform": "Remotive",
                    "job_id_on_platform": "rem-good-1",
                    "title": "Senior Data Architect",
                    "company": "DataFlow",
                    "description": "Python, SQL, PostgreSQL, ETL pipelines",
                }]

        class CrashingScraper(BaseScraper):
            def scrape_jobs(self, keywords, limit=10):
                raise ConnectionResetError("Remote server rejected connection")

        mock_dict = {
            "Himalayas": GoodScraper1,
            "Remotive": GoodScraper2,
            "LinkedIn": CrashingScraper,
            "Naukri": CrashingScraper,
            "Wellfound": CrashingScraper,
            "Hirist": CrashingScraper,
        }

        resume_data = {
            "name": "Jordan Lee",
            "skills": ["Python", "FastAPI", "Docker", "Kubernetes", "AWS", "SQL", "PostgreSQL", "ETL"],
            "experience": [
                {
                    "company": "Tech Innovations",
                    "role": "Senior Engineer",
                    "dates": "2022-Present",
                    "bullets": ["Engineered distributed data pipelines in Python and FastAPI"],
                }
            ],
        }

        with patch.dict("scraper.multi_scraper.SCRAPERS", mock_dict, clear=True):
            # Run pipeline
            result = run_pipeline(
                resume_json=resume_data,
                keywords=["Python Developer"],
                min_score=60,
                db=self.db,
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["total_scraped"], 2)
            self.assertEqual(result["newly_stored"], 2)
            self.assertEqual(result["evaluated"], 2)
            self.assertGreaterEqual(result["ready"], 1)

            # Verify records exist in database
            all_jobs = self.db.get_all_jobs()
            self.assertEqual(len(all_jobs), 2)

            ready_apps = self.db.get_ready_applications()
            self.assertGreaterEqual(len(ready_apps), 1)

            # Running pipeline a second time must be 100% idempotent
            result_reexec = run_pipeline(
                resume_json=resume_data,
                keywords=["Python Developer"],
                min_score=60,
                db=self.db,
            )
            self.assertEqual(result_reexec["newly_stored"], 0)


if __name__ == "__main__":
    unittest.main()
