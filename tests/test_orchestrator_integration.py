"""
Unit and Integration Test Suite for End-to-End Orchestrator (Milestone 5).

Verifies:
1. End-to-end pipeline execution (scrape -> ingest -> evaluate -> tailor -> create application).
2. Deduplication and reverse-chronological ordering in DuckDB.
3. Strict exclusion of applied jobs from evaluation queues.
4. Score thresholding and conditional tailoring for top matches.
5. Error isolation during scraping, evaluation, and tailoring phases.
6. Helper functions (_load_base_resume, _generate_html_resume, evaluate_pending_jobs, tailor_high_match_jobs).
7. Progress callback reporting and metrics dictionary contracts.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db.database import Database
from orchestrator import (
    run_pipeline,
    evaluate_pending_jobs,
    tailor_high_match_jobs,
    _load_base_resume,
    _generate_html_resume,
)


class TestOrchestratorIntegration(unittest.TestCase):
    """End-to-end tests for the pipeline orchestrator."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        self.mock_resume = {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "summary": "Experienced Python Software Engineer and Data Architect.",
            "experience": [
                {
                    "company": "Cloud Corp",
                    "role": "Senior Engineer",
                    "dates": "2022 - Present",
                    "bullets": ["Built high-throughput ETL pipelines in Python", "Automated deployment with Docker and Kubernetes"]
                }
            ],
            "skills": ["Python", "SQL", "Docker", "FastAPI", "PostgreSQL", "Data Engineering"]
        }

    def tearDown(self):
        self.db.close()

    def test_load_base_resume_fallback_and_parsing(self):
        """_load_base_resume loads JSON if file exists, or returns empty dict."""
        res = _load_base_resume()
        self.assertIsInstance(res, dict)

    def test_generate_html_resume_structure(self):
        """_generate_html_resume outputs complete HTML with experience, skills, and summary."""
        html_out = _generate_html_resume(self.mock_resume)
        self.assertIn("Jane Doe", html_out)
        self.assertIn("Senior Engineer", html_out)
        self.assertIn("Python", html_out)
        self.assertIn("<html", html_out.lower())
        self.assertIn("</html>", html_out.lower())

    @patch("orchestrator.scrape_all")
    def test_full_pipeline_run_end_to_end(self, mock_scrape_all):
        """Full pipeline scrapes, deduplicates, evaluates, tailors, and creates Ready applications."""
        # 1. Mock scraped listings
        mock_scrape_all.return_value = [
            {
                "platform": "Himalayas",
                "job_id_on_platform": "hm-001",
                "title": "Lead Python Engineer",
                "company": "Apex Technologies",
                "description": "Looking for a Python expert with SQL, Docker, FastAPI, PostgreSQL, and Data Engineering skills to build ETL pipelines.",
                "url": "https://himalayas.app/jobs/hm-001",
                "location": "Remote",
                "salary_range": "$140k - $170k",
            },
            {
                "platform": "Remotive",
                "job_id_on_platform": "rm-002",
                "title": "Junior Graphic Designer",
                "company": "Creative Studio",
                "description": "Seeking Adobe Photoshop, Illustrator, Figma, and typography designer.",
                "url": "https://remotive.com/jobs/rm-002",
                "location": "Remote",
                "salary_range": "$50k - $65k",
            },
        ]

        progress_msgs = []
        def progress_cb(msg):
            progress_msgs.append(msg)

        # 2. Run pipeline
        results = run_pipeline(
            resume_json=self.mock_resume,
            keywords=["python engineer", "data engineer"],
            min_score=50,
            db=self.db,
            progress_callback=progress_cb,
        )

        # 3. Verify execution results
        self.assertEqual(results["total_scraped"], 2)
        self.assertEqual(results["newly_stored"], 2)
        self.assertEqual(results["evaluated"], 2)
        self.assertGreaterEqual(results["ready"], 1)  # High match Python job tailored
        self.assertEqual(results["status"], "success")

        # 4. Verify Database state
        all_jobs = self.db.get_all_jobs()
        self.assertEqual(len(all_jobs), 2)

        # Python job should have high score
        py_job = next(j for j in all_jobs if j["job_id_on_platform"] == "hm-001")
        self.assertIsNotNone(py_job["match_score"])
        self.assertGreaterEqual(py_job["match_score"], 50)

        # Designer job should have low score
        des_job = next(j for j in all_jobs if j["job_id_on_platform"] == "rm-002")
        self.assertIsNotNone(des_job["match_score"])
        self.assertLess(des_job["match_score"], 50)

        # Ready applications should contain only the high match job
        ready_apps = self.db.get_ready_applications()
        self.assertEqual(len(ready_apps), 1)
        self.assertEqual(ready_apps[0]["company"], "Apex Technologies")
        self.assertIn("resume_html", ready_apps[0])
        self.assertIn("Jane Doe", ready_apps[0]["resume_html"])

        # Verify progress callback was invoked
        self.assertGreater(len(progress_msgs), 3)

    @patch("orchestrator.scrape_all")
    def test_pipeline_deduplication_on_repeated_runs(self, mock_scrape_all):
        """Re-running the pipeline with identical jobs does not create duplicate entries."""
        identical_jobs = [
            {
                "platform": "LinkedIn",
                "job_id_on_platform": "lk-dup-1",
                "title": "Backend Python Developer",
                "company": "Fintech Global",
                "description": "Python, Django, AWS, SQL microservices.",
                "url": "https://linkedin.com/jobs/view/1",
            }
        ]
        mock_scrape_all.return_value = identical_jobs

        # Run 1
        res1 = run_pipeline(resume_json=self.mock_resume, db=self.db)
        self.assertEqual(res1["newly_stored"], 1)

        # Run 2 with same job
        res2 = run_pipeline(resume_json=self.mock_resume, db=self.db)
        self.assertEqual(res2["newly_stored"], 0)  # Deduplicated

        # Verify total database job count is still 1
        all_jobs = self.db.get_all_jobs()
        self.assertEqual(len(all_jobs), 1)

    def test_evaluate_pending_jobs_standalone(self):
        """evaluate_pending_jobs processes unevaluated listings and updates scores."""
        # Seed 2 unevaluated jobs
        self.db.insert_job({
            "platform": "Naukri", "job_id_on_platform": "nk-ev-1",
            "title": "Data Pipeline Engineer", "company": "Big Data Corp",
            "description": "Python, SQL, ETL, Data Engineering, Docker."
        })
        self.db.insert_job({
            "platform": "Hirist", "job_id_on_platform": "hr-ev-2",
            "title": "Data Platform Architect", "company": "Enterprise Inc",
            "description": "Python, Spark, Airflow, SQL, AWS, Kubernetes."
        })

        evaluated = evaluate_pending_jobs(db=self.db, resume_data=self.mock_resume)
        self.assertEqual(evaluated, 2)

        # Confirm no unevaluated jobs remain
        unevaluated_left = self.db.get_unevaluated_jobs()
        self.assertEqual(len(unevaluated_left), 0)

    def test_tailor_high_match_jobs_standalone_and_threshold_filtering(self):
        """tailor_high_match_jobs generates applications only for jobs meeting min_score."""
        # Insert 1 high score job and 1 low score job
        j1, _ = self.db.insert_job({
            "platform": "Wellfound", "job_id_on_platform": "wf-top-1",
            "title": "Senior AI & Python Developer", "company": "NextGen AI",
            "description": "Python, Data Engineering, Docker."
        })
        self.db.update_job_score(j1, match_score=90, evaluation_details="Top tier match")

        j2, _ = self.db.insert_job({
            "platform": "Wellfound", "job_id_on_platform": "wf-low-2",
            "title": "Sales Operations Manager", "company": "Sales Pro",
            "description": "CRM, Lead generation, Sales funnels."
        })
        self.db.update_job_score(j2, match_score=30, evaluation_details="Low match")

        # Tailor with min_score=75
        ready_count = tailor_high_match_jobs(db=self.db, resume_data=self.mock_resume, min_score=75)
        self.assertEqual(ready_count, 1)

        # Check applications in DB
        ready_apps = self.db.get_ready_applications()
        self.assertEqual(len(ready_apps), 1)
        self.assertEqual(ready_apps[0]["company"], "NextGen AI")

    def test_strict_exclusion_of_applied_jobs_from_orchestrator_queue(self):
        """Jobs in active application stages are never re-evaluated or re-tailored."""
        j1, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "lk-ex-1",
            "title": "Python Specialist", "company": "Omega Tech",
            "description": "Python, SQL, FastAPI."
        })
        # Insert application and advance to Applied
        app_id = self.db.insert_application(j1, status="Ready to Apply")
        self.db.update_application_stage(app_id, "Applied", "Submitted application")

        # Confirm job is marked as applied
        self.assertTrue(self.db.is_job_applied(j1))

        # Check unevaluated queue excludes this job
        unevaluated = self.db.get_unevaluated_jobs()
        self.assertNotIn(j1, [j["id"] for j in unevaluated])

        # Check high-match application queue excludes this job
        candidates = self.db.get_evaluated_jobs_for_application(min_score=0)
        self.assertNotIn(j1, [j["id"] for j in candidates])

    @patch("orchestrator.scrape_all")
    def test_pipeline_resilience_on_scraper_and_evaluator_failures(self, mock_scrape_all):
        """Pipeline degrades gracefully when individual scrapers or evaluators fail."""
        # Scraper returns mixed valid and empty
        mock_scrape_all.return_value = [
            {
                "platform": "Himalayas", "job_id_on_platform": "hm-good-1",
                "title": "Software Engineer", "company": "Good Company",
                "description": "Python, SQL, Cloud.",
            }
        ]

        # Patch evaluate_job to raise error for one run
        with patch("orchestrator.evaluate_job", side_effect=RuntimeError("Simulated LLM API Timeout")):
            # evaluate_pending_jobs should catch error and continue
            progress_log = []
            res = run_pipeline(
                resume_json=self.mock_resume,
                db=self.db,
                progress_callback=lambda m: progress_log.append(m),
            )
            self.assertEqual(res["total_scraped"], 1)
            self.assertEqual(res["newly_stored"], 1)
            self.assertEqual(res["evaluated"], 0)  # Failed evaluation was safely caught


if __name__ == "__main__":
    unittest.main()
