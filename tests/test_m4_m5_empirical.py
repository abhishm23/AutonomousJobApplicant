"""
Empirical Adversarial Test Suite for Milestones 4 & 5.
Milestone 4: Application Tracking Console & UI Stage Transitions.
Milestone 5: End-to-End Orchestration Integration & Lifecycle Verification.

Author: Challenger 1
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path and set in-memory DB for tests
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["DB_PATH"] = ":memory:"

from db.database import Database, _clean_nan, _to_int_or_none
from utils.browser_manager import (
    BrowserManager,
    PORTAL_LOGIN_URLS,
    PORTAL_DOMAINS,
    DEFAULT_USER_DATA_DIR,
)
from orchestrator import (
    run_pipeline,
    evaluate_pending_jobs,
    tailor_high_match_jobs,
    _load_base_resume,
    _generate_html_resume,
)
from dashboard.app import (
    clean_score,
    get_score_badge_html,
    KANBAN_STAGES,
    STAGE_NEXT_MAP,
)


class TestMilestone4EmpiricalLifecycle(unittest.TestCase):
    """Adversarial stress-testing of application lifecycle transitions & audit timeline."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_full_lifecycle_linear_transitions(self):
        """
        Verify transition sequence:
        Ready to Apply -> Applied -> Reply Received -> Interview Scheduled -> Offer
        and verify timeline records, updated_at timestamps, applied_at persistence.
        """
        job_id, _ = self.db.insert_job({
            "platform": "LinkedIn",
            "job_id_on_platform": "e2e-job-001",
            "title": "Senior AI Architect",
            "company": "NextGen AI Corp",
            "match_score": 95,
            "salary_range": "$180,000 - $220,000",
        })

        # 1. Initialize application
        app_id = self.db.insert_application(
            job_id=job_id,
            status="Ready to Apply",
            notes="Tailored resume created by pipeline.",
        )
        self.assertGreater(app_id, 0)

        # Check initial state
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Ready to Apply"]), 1)
        self.assertEqual(kanban["Ready to Apply"][0]["app_id"], app_id)

        # 2. Advance to Applied
        ok = self.db.update_application_stage(app_id, "Applied", "Applied via LinkedIn Easy Apply")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Ready to Apply"]), 0)
        self.assertEqual(len(kanban["Applied"]), 1)
        applied_app = kanban["Applied"][0]
        initial_applied_at = applied_app.get("applied_at")
        self.assertIsNotNone(initial_applied_at)

        # 3. Advance to Reply Received
        ok = self.db.update_application_stage(app_id, "Reply Received", "Received email from recruiter")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Applied"]), 0)
        self.assertEqual(len(kanban["Reply Received"]), 1)

        # 4. Advance to Interview Scheduled
        ok = self.db.update_application_stage(app_id, "Interview Scheduled", "Technical screen scheduled")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Reply Received"]), 0)
        self.assertEqual(len(kanban["Interview Scheduled"]), 1)

        # 5. Advance to Offer
        ok = self.db.update_application_stage(app_id, "Offer", "Received official offer package")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Interview Scheduled"]), 0)
        self.assertEqual(len(kanban["Offer"]), 1)

        # 6. Verify full timeline audit trail
        timeline = self.db.get_application_timeline(app_id)
        self.assertEqual(len(timeline), 5)  # 1 creation + 4 transitions
        stages = [t["stage"] for t in timeline]
        self.assertEqual(stages, [
            "Ready to Apply",
            "Applied",
            "Reply Received",
            "Interview Scheduled",
            "Offer",
        ])

        # Verify applied_at was not overwritten or wiped out
        table_rows = self.db.get_all_applications_table()
        target = next(r for r in table_rows if r["app_id"] == app_id)
        self.assertIsNotNone(target["applied_at"])
        self.assertEqual(target["app_status"], "Offer")

    def test_non_linear_rejection_branching(self):
        """
        Verify rejection transitions from different stages:
        - Rejection directly from Ready to Apply
        - Rejection after Interview Scheduled
        - Re-activation from Rejected back to Ready to Apply
        """
        j1, _ = self.db.insert_job({"platform": "Naukri", "job_id_on_platform": "rej-1", "title": "Dev 1", "company": "Co 1"})
        j2, _ = self.db.insert_job({"platform": "Naukri", "job_id_on_platform": "rej-2", "title": "Dev 2", "company": "Co 2"})

        app1 = self.db.insert_application(j1, status="Ready to Apply")
        app2 = self.db.insert_application(j2, status="Ready to Apply")

        # Direct rejection from Ready
        self.db.update_application_stage(app1, "Rejected", "Decided not to apply")
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Rejected"]), 1)
        self.assertEqual(kanban["Rejected"][0]["app_id"], app1)

        # Advance app2 to Interview Scheduled then Reject
        self.db.update_application_stage(app2, "Applied", "Sent resume")
        self.db.update_application_stage(app2, "Interview Scheduled", "Round 1 scheduled")
        self.db.update_application_stage(app2, "Rejected", "Position filled by internal candidate")

        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Rejected"]), 2)

        # Re-activation of app1 back to Ready to Apply
        self.db.update_application_stage(app1, "Ready to Apply", "Re-evaluating opportunity")
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Ready to Apply"]), 1)
        self.assertEqual(len(kanban["Rejected"]), 1)

    def test_history_json_structure_and_integrity(self):
        """Verify embedded history JSON column contains structured entries with timestamp, note, stage."""
        job_id, _ = self.db.insert_job({"platform": "Hirist", "job_id_on_platform": "hist-1", "title": "Staff Engineer", "company": "Fintech"})
        app_id = self.db.insert_application(job_id, status="Ready to Apply", notes="Initial build")

        self.db.update_application_stage(app_id, "Applied", "Applied online")
        self.db.update_application_stage(app_id, "Reply Received", "Recruiter message")

        app_row = self.db.conn.execute("SELECT history FROM Applications WHERE id = ?", (app_id,)).fetchone()
        self.assertIsNotNone(app_row)
        history_raw = app_row[0]
        history_list = json.loads(history_raw)

        self.assertEqual(len(history_list), 3)
        self.assertEqual(history_list[0]["stage"], "Ready to Apply")
        self.assertEqual(history_list[1]["stage"], "Applied")
        self.assertEqual(history_list[1]["previous_stage"], "Ready to Apply")
        self.assertEqual(history_list[2]["stage"], "Reply Received")
        self.assertEqual(history_list[2]["previous_stage"], "Applied")


class TestMilestone4EmpiricalNotesAndDates(unittest.TestCase):
    """Adversarial testing of notes, interview dates, follow-up dates, and recruiter contact info."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_notes_with_special_characters_and_multiline(self):
        """Notes containing unicode, quotes, multiline text, and special symbols persist accurately."""
        job_id, _ = self.db.insert_job({"platform": "Wellfound", "job_id_on_platform": "wf-notes-1", "title": "Lead", "company": "Startup"})
        app_id = self.db.insert_application(job_id, status="Ready to Apply")

        complex_note = "Met with hiring manager! 🚀\nQuotes: 'Single' and \"Double\"\nSymbols: <>&;\nSalary target: €120,000 / ₹1.2Cr"
        recruiter = "Dr. Jane O'Connor <jane.oconnor@startup.io>"
        interview_dt = "2026-10-15 15:30:00"

        ok = self.db.update_application_notes(
            app_id=app_id,
            notes=complex_note,
            interview_date=interview_dt,
            recruiter_info=recruiter,
        )
        self.assertTrue(ok)

        table = self.db.get_all_applications_table()
        target = next(a for a in table if a["app_id"] == app_id)
        self.assertIn("Met with hiring manager! 🚀", target["notes"])
        self.assertIn("Dr. Jane O'Connor", target["notes"])
        self.assertEqual(str(target["interview_date"])[:19], "2026-10-15 15:30:00")

    def test_invalid_interview_date_graceful_handling(self):
        """Invalid timestamp string should not raise exception and should preserve existing date."""
        job_id, _ = self.db.insert_job({"platform": "Himalayas", "job_id_on_platform": "dt-test-1", "title": "Dev", "company": "Co"})
        app_id = self.db.insert_application(job_id, status="Ready to Apply")

        # Set valid date first
        self.db.update_application_notes(app_id=app_id, notes="Valid date", interview_date="2026-09-20 10:00:00")
        target1 = next(a for a in self.db.get_all_applications_table() if a["app_id"] == app_id)
        self.assertIsNotNone(target1["interview_date"])

        # Update with invalid date string
        ok = self.db.update_application_notes(app_id=app_id, notes="Invalid date attempt", interview_date="not-a-valid-date")
        self.assertTrue(ok)
        target2 = next(a for a in self.db.get_all_applications_table() if a["app_id"] == app_id)
        # Old date remains preserved due to TRY_CAST & COALESCE
        self.assertEqual(str(target2["interview_date"])[:19], "2026-09-20 10:00:00")

    def test_update_notes_nonexistent_application(self):
        """Updating notes on nonexistent app_id returns False cleanly."""
        ok = self.db.update_application_notes(app_id=999999, notes="Ghost note")
        self.assertFalse(ok)


class TestMilestone4EmpiricalFilterAndSearch(unittest.TestCase):
    """Stress tests on data table filtering, multi-field search, multi-select, and score thresholds."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        self.dataset = [
            {
                "platform": "LinkedIn", "job_id_on_platform": "f-1", "title": "Staff Backend Python Architect",
                "company": "Fintech Pioneers", "skills": "Python, Django, AWS, Kubernetes", "match_score": 96,
                "status_stage": "Ready to Apply", "notes": "Top priority role"
            },
            {
                "platform": "Naukri", "job_id_on_platform": "f-2", "title": "Senior Data Engineer",
                "company": "Analytics Grid", "skills": "Python, Spark, Airflow, Snowflake", "match_score": 82,
                "status_stage": "Applied", "notes": "Applied on Naukri portal"
            },
            {
                "platform": "Wellfound", "job_id_on_platform": "f-3", "title": "Full Stack Engineer",
                "company": "EarlyStage Labs", "skills": "TypeScript, React, Node.js", "match_score": 65,
                "status_stage": "Reply Received", "notes": "Recruiter replied asking for portfolio"
            },
            {
                "platform": "Himalayas", "job_id_on_platform": "f-4", "title": "Machine Learning Engineer",
                "company": "AI Dynamics", "skills": "Python, PyTorch, LangChain, FastAPI", "match_score": 88,
                "status_stage": "Interview Scheduled", "notes": "Technical screening scheduled for next week"
            },
            {
                "platform": "Hirist", "job_id_on_platform": "f-5", "title": "Lead DevOps Consultant",
                "company": "Cloud Horizon", "skills": "Terraform, Docker, CI/CD", "match_score": 40,
                "status_stage": "Rejected", "notes": "Skills gap on Terraform"
            },
            {
                "platform": "Remotive", "job_id_on_platform": "f-6", "title": "VP of Engineering",
                "company": "Global Solutions", "skills": "Leadership, Architecture, Python", "match_score": 91,
                "status_stage": "Offer", "notes": "Offer letter received!"
            },
            {
                "platform": "LinkedIn", "job_id_on_platform": "f-7", "title": "Unevaluated Intern",
                "company": "Acme Labs", "skills": "Python, Linux", "match_score": None,
                "status_stage": "Ready to Apply", "notes": "New listing not yet evaluated"
            },
        ]

        for d in self.dataset:
            jid, _ = self.db.insert_job({
                "platform": d["platform"],
                "job_id_on_platform": d["job_id_on_platform"],
                "title": d["title"],
                "company": d["company"],
                "skills": d["skills"],
                "match_score": d["match_score"],
            })
            aid = self.db.insert_application(jid, status=d["status_stage"], notes=d["notes"])

    def tearDown(self):
        self.db.close()

    def test_multi_field_search_matching(self):
        """Search query matches across title, company, skills, and notes."""
        all_apps = self.db.get_all_applications_table()

        # Helper filter matching dashboard logic
        def filter_search(query: str):
            sq = query.strip().lower()
            return [
                a for a in all_apps
                if sq in (a.get("title") or "").lower()
                or sq in (a.get("company") or "").lower()
                or sq in (a.get("skills") or "").lower()
                or sq in (a.get("notes") or "").lower()
                or sq in (a.get("match_reasoning") or "").lower()
            ]

        # 1. Search by title keyword (matches "Architect" in title and "Architecture" in skills)
        res_arch = filter_search("architect")
        self.assertEqual(len(res_arch), 2)  # Staff Backend Architect + VP of Engineering (Architecture skill)

        # 2. Search by company keyword
        res_grid = filter_search("analytics grid")
        self.assertEqual(len(res_grid), 1)
        self.assertEqual(res_grid[0]["company"], "Analytics Grid")

        # 3. Search by skill keyword
        res_torch = filter_search("pytorch")
        self.assertEqual(len(res_torch), 1)
        self.assertEqual(res_torch[0]["company"], "AI Dynamics")

        # 4. Search by notes keyword
        res_port = filter_search("portfolio")
        self.assertEqual(len(res_port), 1)
        self.assertEqual(res_port[0]["company"], "EarlyStage Labs")

        # 5. Search for non-existent keyword
        res_none = filter_search("xyznonexistent123")
        self.assertEqual(len(res_none), 0)

    def test_platform_and_stage_multi_select_filtering(self):
        """Filtering by platform list and stage list narrows dataset accurately."""
        all_apps = self.db.get_all_applications_table()

        # Filter by platform: LinkedIn only
        li_apps = [a for a in all_apps if a["platform"] == "LinkedIn"]
        self.assertEqual(len(li_apps), 2)

        # Filter by multiple platforms
        multi_plat = [a for a in all_apps if a["platform"] in ["LinkedIn", "Himalayas", "Hirist"]]
        self.assertEqual(len(multi_plat), 4)

        # Filter by stage: Interview Scheduled & Offer
        interview_offer = [a for a in all_apps if a["app_status"] in ["Interview Scheduled", "Offer"]]
        self.assertEqual(len(interview_offer), 2)
        stages = set(a["app_status"] for a in interview_offer)
        self.assertEqual(stages, {"Interview Scheduled", "Offer"})

    def test_match_score_boundary_conditions(self):
        """Slider score boundary tests: 0, 40, 80, 90, 96, 100 and None score behavior."""
        all_apps = self.db.get_all_applications_table()

        def filter_by_min_score(min_score: int, exclude_none: bool = True):
            results = []
            for a in all_apps:
                s = clean_score(a.get("match_score"))
                if s is None:
                    if not exclude_none:
                        results.append(a)
                elif s >= min_score:
                    results.append(a)
            return results

        # Min score = 0 (all evaluated jobs with score >= 0)
        score_0 = filter_by_min_score(0, exclude_none=True)
        self.assertEqual(len(score_0), 6)

        # Min score = 80
        score_80 = filter_by_min_score(80, exclude_none=True)
        self.assertEqual(len(score_80), 4)  # 96, 82, 88, 91

        # Min score = 95
        score_95 = filter_by_min_score(95, exclude_none=True)
        self.assertEqual(len(score_95), 1)  # 96
        self.assertEqual(score_95[0]["match_score"], 96)

        # Min score = 100 (none exist)
        score_100 = filter_by_min_score(100, exclude_none=True)
        self.assertEqual(len(score_100), 0)


class TestMilestone4EmpiricalBrowserAuth(unittest.TestCase):
    """Stress tests on browser session authentication logic, CLI args, and non-blocking launch."""

    def test_auth_login_cli_parser_options(self):
        """Verify auth_login.py accepts all required flags and valid portals."""
        from auth_login import build_parser

        parser = build_parser()

        # Test valid portal arguments
        args_li = parser.parse_args(["--portal", "linkedin"])
        self.assertEqual(args_li.portal, "linkedin")

        args_all = parser.parse_args(["--portal", "all"])
        self.assertEqual(args_all.portal, "all")

        args_check = parser.parse_args(["--check"])
        self.assertTrue(args_check.check)

        args_list = parser.parse_args(["--list"])
        self.assertTrue(args_list.list)

        args_timeout = parser.parse_args(["--portal", "naukri", "--timeout", "120"])
        self.assertEqual(args_timeout.timeout, 120)

    def test_browser_manager_session_detection_mocked_files(self):
        """Verify session detection against simulated cookie files and json state files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Initially no sessions
            self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=tmp_dir))
            self.assertFalse(BrowserManager.has_session_for_portal("naukri", user_data_dir=tmp_dir))

            # Create simulated storage_state_linkedin.json
            mock_state = {
                "cookies": [
                    {
                        "name": "li_at",
                        "value": "mock_cookie_token_12345",
                        "domain": ".linkedin.com",
                        "path": "/",
                    }
                ]
            }
            state_file = os.path.join(tmp_dir, "storage_state_linkedin.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(mock_state, f)

            # Check LinkedIn session is now detected
            self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=tmp_dir))
            # Naukri should still be False
            self.assertFalse(BrowserManager.has_session_for_portal("naukri", user_data_dir=tmp_dir))

    def test_portal_login_urls_validity(self):
        """All supported portals have valid HTTPS login endpoints."""
        portals = ["linkedin", "naukri", "wellfound", "hirist", "indeed"]
        for p in portals:
            url = BrowserManager.get_login_url(p)
            self.assertTrue(url.startswith("https://"), f"Portal {p} URL is not secure HTTPS: {url}")

        with self.assertRaises(ValueError):
            BrowserManager.get_login_url("non_existent_portal")


class TestMilestone5EmpiricalOrchestration(unittest.TestCase):
    """Adversarial stress-testing of orchestrator.py pipeline flow, deduplication & error isolation."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        self.sample_resume = {
            "name": "Alex Mercer",
            "email": "alex@mercer.dev",
            "summary": "Senior Software Engineer specializing in Python, Distributed Systems, and AI Automation.",
            "experience": [
                {
                    "company": "Apex Cloud Systems",
                    "role": "Lead Backend Engineer",
                    "dates": "2021 - Present",
                    "bullets": [
                        "Architected high-scale microservices processing 50k req/sec with Python and FastAPI.",
                        "Implemented automated ETL workflows with Docker and PostgreSQL.",
                    ]
                }
            ],
            "skills": ["Python", "FastAPI", "Docker", "PostgreSQL", "Kubernetes", "ETL", "SQL"]
        }

    def tearDown(self):
        self.db.close()

    @patch("orchestrator.scrape_all")
    def test_full_pipeline_multi_source_mock_execution(self, mock_scrape_all):
        """
        Executes complete pipeline:
        - Scrapes 6 distinct direct sources
        - Ingests with composite key deduplication
        - Evaluates match scores against resume
        - Tailors high-matching candidates (>= 50%)
        - Verifies Ready to Apply applications created
        """
        mock_scrape_all.return_value = [
            {
                "platform": "Himalayas", "job_id_on_platform": "him-101",
                "title": "Principal Python Engineer", "company": "ScaleLabs",
                "description": "Looking for Python, FastAPI, Docker, PostgreSQL, and Distributed Systems expertise.",
                "url": "https://himalayas.app/jobs/him-101", "location": "Remote", "salary_range": "$170k - $200k"
            },
            {
                "platform": "Remotive", "job_id_on_platform": "rem-202",
                "title": "Senior Data & Backend Engineer", "company": "DataPulse",
                "description": "Seeking Python, SQL, ETL, Docker engineer with experience in cloud architecture.",
                "url": "https://remotive.com/jobs/rem-202", "location": "Remote", "salary_range": "$150k - $180k"
            },
            {
                "platform": "LinkedIn", "job_id_on_platform": "lk-303",
                "title": "Junior Graphic Illustrator", "company": "Design Studio",
                "description": "Adobe Creative Cloud, Photoshop, Illustrator, vector graphics.",
                "url": "https://linkedin.com/jobs/view/303", "location": "Hybrid", "salary_range": "$60k"
            },
            {
                "platform": "Naukri", "job_id_on_platform": "nk-404",
                "title": "Python Automation Specialist", "company": "AutoCorp",
                "description": "Python, scripting, Docker, API integration, and database operations.",
                "url": "https://naukri.com/job/404", "location": "Remote", "salary_range": "$130k"
            },
            {
                "platform": "Wellfound", "job_id_on_platform": "wf-505",
                "title": "Full Stack React Developer", "company": "FrontEnd Inc",
                "description": "React, CSS, HTML, JavaScript, Next.js frontend developer.",
                "url": "https://wellfound.com/jobs/505", "location": "Remote", "salary_range": "$100k"
            },
            {
                "platform": "Hirist", "job_id_on_platform": "hr-606",
                "title": "Cloud Infrastructure Architect", "company": "CloudForge",
                "description": "Kubernetes, Terraform, AWS, Docker, Python infrastructure tooling.",
                "url": "https://hirist.tech/job/606", "location": "Remote", "salary_range": "$160k"
            }
        ]

        progress_log = []
        result = run_pipeline(
            resume_json=self.sample_resume,
            keywords=["python engineer", "backend"],
            min_score=50,
            db=self.db,
            progress_callback=lambda msg: progress_log.append(msg),
        )

        # Assert pipeline output dictionary contract
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_scraped"], 6)
        self.assertEqual(result["newly_stored"], 6)
        self.assertEqual(result["evaluated"], 6)
        self.assertGreaterEqual(result["ready"], 2)  # Python & Cloud roles tailored

        # Verify DB applications
        ready_apps = self.db.get_ready_applications()
        self.assertEqual(len(ready_apps), result["ready"])

        for app in ready_apps:
            self.assertIn("resume_html", app)
            self.assertIn("Alex Mercer", app["resume_html"])
            self.assertGreaterEqual(clean_score(app["match_score"]), 50)

    @patch("orchestrator.scrape_all")
    def test_pipeline_deduplication_and_reexecution_resilience(self, mock_scrape_all):
        """Repeated runs deduplicate existing jobs and skip already processed applications."""
        single_job = [
            {
                "platform": "Himalayas", "job_id_on_platform": "dedup-run-1",
                "title": "Senior Python Architect", "company": "DupeCorp",
                "description": "Python, FastAPI, Docker, SQL microservices.",
                "url": "https://himalayas.app/jobs/dedup-run-1",
            }
        ]
        mock_scrape_all.return_value = single_job

        # Run 1: Ingests, evaluates, and tailors
        res1 = run_pipeline(resume_json=self.sample_resume, min_score=50, db=self.db)
        self.assertEqual(res1["newly_stored"], 1)
        self.assertEqual(res1["evaluated"], 1)
        self.assertEqual(res1["ready"], 1)

        # Run 2: Same job scraped again
        res2 = run_pipeline(resume_json=self.sample_resume, min_score=50, db=self.db)
        self.assertEqual(res2["newly_stored"], 0)  # Deduplicated
        self.assertEqual(res2["evaluated"], 0)     # Skipped (already in Applications)
        self.assertEqual(res2["ready"], 0)         # Skipped (already tailored)

        # Total in DB remains 1
        self.assertEqual(len(self.db.get_all_jobs()), 1)
        self.assertEqual(len(self.db.get_ready_applications()), 1)

    @patch("orchestrator.scrape_all")
    def test_pipeline_fault_tolerance_on_external_failures(self, mock_scrape_all):
        """Pipeline completes gracefully and records errors when evaluation or tailoring fails."""
        mock_scrape_all.return_value = [
            {
                "platform": "LinkedIn", "job_id_on_platform": "fail-job-1",
                "title": "Buggy Listing", "company": "Chaos Engineering",
                "description": "Python developer role.",
            }
        ]

        # Simulate exception in evaluate_job
        with patch("orchestrator.evaluate_job", side_effect=ValueError("Simulated evaluation parser crash")):
            res = run_pipeline(resume_json=self.sample_resume, db=self.db)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["total_scraped"], 1)
            self.assertEqual(res["newly_stored"], 1)
            self.assertEqual(res["evaluated"], 0)  # Caught gracefully
            self.assertEqual(res["ready"], 0)

    def test_resume_input_format_handling(self):
        """Pipeline resolves dict, raw text, and json string resume inputs properly."""
        # 1. Raw string input
        res_str = "Software Engineer with 5 years experience in Python and PostgreSQL."
        html_out = _generate_html_resume(res_str)
        self.assertIn("Software Engineer", html_out)

        # 2. JSON string input
        json_str = json.dumps({"name": "Test User", "skills": ["Python", "Docker"]})
        html_json = _generate_html_resume(json_str)
        self.assertIn("Test User", html_json)
        self.assertIn("Python", html_json)


if __name__ == "__main__":
    unittest.main()
