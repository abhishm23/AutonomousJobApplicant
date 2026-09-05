"""
Adversarial Edge-Case and Failure-Mode Reproduction Suite for M4 & M5.
Demonstrates concrete empirical findings and behavioral edge cases.

Author: Challenger 1
"""

import json
import math
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["DB_PATH"] = ":memory:"

from db.database import Database
from agents.evaluator_agent import evaluate_job
from dashboard.app import clean_score, KANBAN_STAGES


class TestAdversarialFindingsM4M5(unittest.TestCase):
    """Empirical verification of discovered vulnerabilities and edge cases."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_evaluator_single_letter_r_false_positive_bug(self):
        """
        VULNERABILITY PROOF:
        evaluator_agent regex strips 'r\\b' to 'r', causing any English text
        with the letter 'r' to match as the programming language 'R', giving
        completely unrelated jobs high or 100% scores.
        """
        # Resume has zero tech skills, but words with letter 'r'
        resume = "Barista and customer service representative at local cafe"
        # Job has zero relation to cafe or tech, but has letter 'r'
        job = "Night security guard for warehouse"

        score, reasoning = evaluate_job(job, resume)
        # Verify fix: Should be 0% match, no false positive on 'r'
        self.assertEqual(score, 0)
        self.assertNotIn("Found: r", reasoning)

    def test_dashboard_table_none_score_bypass_when_slider_is_positive(self):
        """
        EDGE CASE VERIFICATION:
        In dashboard/app.py filter_applications:
            When min_table_score is 90, unevaluated jobs (match_score is None / NaN)
            must be correctly excluded from the high-match filtered table.
        """
        from dashboard.app import filter_applications
        j1, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "uneval-1",
            "title": "Unevaluated Role", "company": "Secret Co",
            "match_score": None
        })
        app1 = self.db.insert_application(j1, status="Ready to Apply")

        all_apps = self.db.get_all_applications_table()
        target = next(a for a in all_apps if a["app_id"] == app1)

        # Unevaluated score is None
        score = clean_score(target.get("match_score"))
        self.assertIsNone(score)

        # Apply hardened filter_applications with min_table_score = 90
        filtered = filter_applications(all_apps, min_table_score=90)
        self.assertEqual(len(filtered), 0, "Unevaluated job must be excluded when min_table_score > 0")

    def test_dashboard_empty_multiselect_bypass(self):
        """
        EDGE CASE VERIFICATION:
        In dashboard/app.py filter_applications:
            When the user deselects all platforms or stages (empty list []),
            filter_applications must return 0 results rather than bypassing filters.
        """
        from dashboard.app import filter_applications
        j1, _ = self.db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "ms-1", "title": "Dev", "company": "Co"})
        app1 = self.db.insert_application(j1, status="Ready to Apply")

        all_apps = self.db.get_all_applications_table()
        self.assertGreaterEqual(len(all_apps), 1)

        # Empty platform selection in UI (user unchecks all)
        filtered = filter_applications(all_apps, selected_platforms=[])
        self.assertEqual(len(filtered), 0, "Empty platforms selection must result in 0 applications shown")

    def test_timeline_note_desynchronization_on_invalid_interview_date(self):
        """
        EDGE CASE PROOF:
        When update_application_notes receives an unparseable timestamp,
        TRY_CAST yields NULL, keeping the old database value, but the
        ApplicationTimeline audit log still records the invalid string.
        """
        j1, _ = self.db.insert_job({"platform": "Naukri", "job_id_on_platform": "sync-1", "title": "Dev", "company": "Co"})
        app1 = self.db.insert_application(j1, status="Ready to Apply")

        # Pass unparseable date
        self.db.update_application_notes(app1, notes="Test note", interview_date="next Monday afternoon")

        # Database interview_date remains NULL
        table = self.db.get_all_applications_table()
        target = next(a for a in table if a["app_id"] == app1)
        self.assertIsNone(target["interview_date"])

        # But timeline recorded the string as if an interview was scheduled
        timeline = self.db.get_application_timeline(app1)
        latest_audit = timeline[-1]
        self.assertIn("Interview: next Monday afternoon", latest_audit["note"])


if __name__ == "__main__":
    unittest.main()
