"""
Unit and Integration Test Suite for Application Tracking Console (Milestone 4).

Verifies:
1. 6-stage Kanban board data structuring and bucket distribution.
2. Complete 6-stage lifecycle transitions (Ready to Apply -> Applied -> Reply Received -> Interview Scheduled -> Offer / Rejected).
3. Notes, recruiter contact info, interview dates, and immutable timeline audit trails.
4. Filterable & sortable data table query logic, text search across title, company, skills, notes.
5. Browser session management status checks and portal metadata.
6. Score sanitization, NaN safety, and UI data integrity.
"""

import json
import math
import os
import sys
import unittest
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db.database import Database, _clean_nan, _to_int_or_none
from utils.browser_manager import BrowserManager
from dashboard.app import clean_score, get_score_badge_html, KANBAN_STAGES, STAGE_NEXT_MAP


class TestDashboardKanbanIntegration(unittest.TestCase):
    """Integration tests for 6-stage Kanban data structuring and transitions."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_kanban_returns_all_six_canonical_stages(self):
        """Kanban dictionary must always include all 6 canonical stages."""
        kanban = self.db.get_kanban_applications()
        for stage in KANBAN_STAGES:
            self.assertIn(stage, kanban, f"Stage '{stage}' missing from Kanban dictionary.")
            self.assertIsInstance(kanban[stage], list)

    def test_kanban_stage_population_and_ordering(self):
        """Applications inserted across different stages must appear in correct Kanban buckets."""
        # Insert 3 jobs
        j1, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "lk-101",
            "title": "Backend Python Engineer", "company": "Tech Corp",
            "match_score": 90, "salary_range": "$120k - $150k"
        })
        j2, _ = self.db.insert_job({
            "platform": "Naukri", "job_id_on_platform": "nk-202",
            "title": "Data Architect", "company": "Data Inc",
            "match_score": 80, "salary_range": "$140k"
        })
        j3, _ = self.db.insert_job({
            "platform": "Himalayas", "job_id_on_platform": "hm-303",
            "title": "AI Specialist", "company": "AI Labs",
            "match_score": 95, "salary_range": "$160k"
        })

        # Insert applications in different stages
        app1 = self.db.insert_application(j1, status="Ready to Apply", notes="Initial review")
        app2 = self.db.insert_application(j2, status="Applied", notes="Submitted online")
        app3 = self.db.insert_application(j3, status="Interview Scheduled", notes="Round 1 scheduled")

        kanban = self.db.get_kanban_applications()
        ready_ids = [a["app_id"] for a in kanban["Ready to Apply"]]
        applied_ids = [a["app_id"] for a in kanban["Applied"]]
        interview_ids = [a["app_id"] for a in kanban["Interview Scheduled"]]

        self.assertIn(app1, ready_ids)
        self.assertIn(app2, applied_ids)
        self.assertIn(app3, interview_ids)

    def test_full_six_stage_lifecycle_progression(self):
        """Test transitioning an application through all 6 stages sequentially with audit trails."""
        job_id, _ = self.db.insert_job({
            "platform": "Wellfound", "job_id_on_platform": "wf-999",
            "title": "Full Stack Engineer", "company": "Startup Hub",
            "match_score": 88
        })

        app_id = self.db.insert_application(job_id, status="Ready to Apply", notes="Created")
        self.assertGreater(app_id, 0)

        # Stage 1 -> Stage 2: Applied
        ok = self.db.update_application_stage(app_id, "Applied", "Applied via company website")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Applied"]), 1)
        self.assertEqual(len(kanban["Ready to Apply"]), 0)

        # Stage 2 -> Stage 3: Reply Received
        ok = self.db.update_application_stage(app_id, "Reply Received", "HR contacted via email")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Reply Received"]), 1)
        self.assertEqual(len(kanban["Applied"]), 0)

        # Stage 3 -> Stage 4: Interview Scheduled
        ok = self.db.update_application_stage(app_id, "Interview Scheduled", "Technical round scheduled")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Interview Scheduled"]), 1)

        # Stage 4 -> Stage 5: Offer
        ok = self.db.update_application_stage(app_id, "Offer", "Offer letter received: $150k base")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Offer"]), 1)

        # Stage 5 -> Stage 6: Rejected (alternative terminal transition)
        ok = self.db.update_application_stage(app_id, "Rejected", "Declined or position cancelled")
        self.assertTrue(ok)
        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Rejected"]), 1)

        # Verify full timeline audit trail contains all 6 events
        timeline = self.db.get_application_timeline(app_id)
        self.assertGreaterEqual(len(timeline), 6)
        stages_in_timeline = [t["stage"] for t in timeline]
        self.assertIn("Ready to Apply", stages_in_timeline)
        self.assertIn("Applied", stages_in_timeline)
        self.assertIn("Reply Received", stages_in_timeline)
        self.assertIn("Interview Scheduled", stages_in_timeline)
        self.assertIn("Offer", stages_in_timeline)
        self.assertIn("Rejected", stages_in_timeline)

    def test_legacy_status_mapping_to_canonical_stages(self):
        """Legacy status strings ('ready', 'applied') should map cleanly to canonical stages."""
        j1, _ = self.db.insert_job({"platform": "Hirist", "job_id_on_platform": "h-1", "title": "DevOps", "company": "Cloud Co"})
        app1 = self.db.insert_application(j1, status="ready")

        kanban = self.db.get_kanban_applications()
        self.assertEqual(len(kanban["Ready to Apply"]), 1)
        self.assertEqual(kanban["Ready to Apply"][0]["app_id"], app1)


class TestDashboardNotesAndTimelineIntegration(unittest.TestCase):
    """Integration tests for recruiter contact info, interview dates, and notes audit logging."""

    def setUp(self):
        self.db = Database(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_update_notes_and_recruiter_info(self):
        """Updating notes with recruiter contact and interview date must persist and record timeline."""
        job_id, _ = self.db.insert_job({
            "platform": "LinkedIn", "job_id_on_platform": "lk-777",
            "title": "ML Engineer", "company": "AI Innovations"
        })
        app_id = self.db.insert_application(job_id, status="Ready to Apply")

        # Update notes with recruiter details and interview date
        ok = self.db.update_application_notes(
            app_id=app_id,
            notes="Passed resume screen.",
            interview_date="2026-09-15 10:00:00",
            follow_up_date="2026-09-16 12:00:00",
            recruiter_info="Sarah Connor (sarah@ai.com)"
        )
        self.assertTrue(ok)

        # Retrieve application and verify fields
        table = self.db.get_all_applications_table()
        target = next((a for a in table if a["app_id"] == app_id), None)
        self.assertIsNotNone(target)
        self.assertIn("Sarah Connor", target["notes"])
        self.assertIn("Passed resume screen", target["notes"])
        self.assertIsNotNone(target["interview_date"])
        self.assertIsNotNone(target["follow_up_date"])

        # Check timeline entry
        timeline = self.db.get_application_timeline(app_id)
        self.assertGreaterEqual(len(timeline), 2)
        latest_audit = timeline[-1]
        self.assertIn("Updated application notes", latest_audit["note"])
        self.assertIn("2026-09-15", latest_audit["note"])

    def test_update_notes_nonexistent_application_returns_false(self):
        """Updating a nonexistent application ID returns False without crashing."""
        ok = self.db.update_application_notes(app_id=999999, notes="Some note")
        self.assertFalse(ok)


class TestDashboardTableSearchAndFiltering(unittest.TestCase):
    """Integration tests for application table search, multi-field filtering, and sorting."""

    def setUp(self):
        self.db = Database(db_path=":memory:")
        # Seed test dataset
        self.jobs_data = [
            {"platform": "LinkedIn", "job_id_on_platform": "lk-1", "title": "Senior Python Developer", "company": "Alpha Corp", "skills": "Python, Django, AWS", "match_score": 92, "salary_range": "$130k"},
            {"platform": "Naukri", "job_id_on_platform": "nk-1", "title": "Data Engineer", "company": "Beta Analytics", "skills": "Python, SQL, Spark", "match_score": 85, "salary_range": "$110k"},
            {"platform": "Wellfound", "job_id_on_platform": "wf-1", "title": "Frontend React Engineer", "company": "Gamma Startups", "skills": "React, TypeScript", "match_score": 60, "salary_range": "$95k"},
            {"platform": "Himalayas", "job_id_on_platform": "hm-1", "title": "Full Stack Python/Vue", "company": "Delta Remote", "skills": "Python, Vue.js, Docker", "match_score": 78, "salary_range": "$120k"},
            {"platform": "Hirist", "job_id_on_platform": "hr-1", "title": "DevOps Architect", "company": "Epsilon Systems", "skills": "Kubernetes, Terraform", "match_score": 45, "salary_range": "$140k"},
        ]
        self.app_ids = []
        for j in self.jobs_data:
            jid, _ = self.db.insert_job(j)
            aid = self.db.insert_application(jid, status="Ready to Apply", notes=f"Initial application for {j['title']}")
            self.app_ids.append(aid)

        # Transition two applications to different stages and record notes
        self.db.update_application_stage(self.app_ids[1], "Applied", "Applied on Naukri")
        self.db.update_application_notes(self.app_ids[1], notes="Applied on Naukri via portal")
        self.db.update_application_stage(self.app_ids[3], "Interview Scheduled", "Interview on Himalayas role")

    def tearDown(self):
        self.db.close()

    def test_text_search_filtering_across_fields(self):
        """Search query matches title, company, skills, or notes."""
        table = self.db.get_all_applications_table()

        # Search by Title
        python_matches = [a for a in table if "python" in (a["title"] or "").lower() or "python" in (a["skills"] or "").lower()]
        self.assertEqual(len(python_matches), 3)

        # Search by Company
        beta_matches = [a for a in table if "beta" in (a["company"] or "").lower()]
        self.assertEqual(len(beta_matches), 1)
        self.assertEqual(beta_matches[0]["company"], "Beta Analytics")

        # Search by Notes
        naukri_note_matches = [a for a in table if "applied on naukri" in (a.get("notes") or "").lower()]
        self.assertEqual(len(naukri_note_matches), 1)

    def test_platform_and_stage_multi_filtering(self):
        """Filtering by platform and stage correctly narrows application results."""
        table = self.db.get_all_applications_table()

        # Filter by platform: LinkedIn & Wellfound
        filtered_by_platform = [a for a in table if a["platform"] in ["LinkedIn", "Wellfound"]]
        self.assertEqual(len(filtered_by_platform), 2)

        # Filter by stage: Applied only
        applied_only = [a for a in table if a["app_status"] == "Applied"]
        self.assertEqual(len(applied_only), 1)
        self.assertEqual(applied_only[0]["company"], "Beta Analytics")

        # Filter by minimum match score >= 80
        high_score = [a for a in table if (clean_score(a["match_score"]) or 0) >= 80]
        self.assertEqual(len(high_score), 2)

    def test_sorting_applications(self):
        """Applications can be sorted by match score, company, and title."""
        table = self.db.get_all_applications_table()

        # Sort by Match Score Descending
        sorted_by_score = sorted(table, key=lambda x: clean_score(x["match_score"]) or 0, reverse=True)
        scores = [clean_score(a["match_score"]) for a in sorted_by_score]
        self.assertEqual(scores, [92, 85, 78, 60, 45])

        # Sort by Company A-Z
        sorted_by_company = sorted(table, key=lambda x: (x["company"] or "").lower())
        companies = [a["company"] for a in sorted_by_company]
        self.assertEqual(companies, ["Alpha Corp", "Beta Analytics", "Delta Remote", "Epsilon Systems", "Gamma Startups"])


class TestDashboardBrowserAuthAndHelpers(unittest.TestCase):
    """Unit tests for browser session status, score cleaning, and stage helper maps."""

    def test_clean_score_helper_with_nan_none_and_numbers(self):
        """clean_score must return int or None without crashing on NaN/strings."""
        self.assertEqual(clean_score(95), 95)
        self.assertEqual(clean_score("88"), 88)
        self.assertIsNone(clean_score(None))
        self.assertIsNone(clean_score(float("nan")))
        self.assertIsNone(clean_score("invalid_score"))

    def test_get_score_badge_html_rendering(self):
        """get_score_badge_html produces valid HTML with appropriate color classes."""
        high_html = get_score_badge_html(90)
        self.assertIn("badge-score-high", high_html)
        self.assertIn("90%", high_html)

        mid_html = get_score_badge_html(70)
        self.assertIn("badge-score-mid", mid_html)
        self.assertIn("70%", mid_html)

        low_html = get_score_badge_html(40)
        self.assertIn("badge-score-low", low_html)
        self.assertIn("40%", low_html)

        none_html = get_score_badge_html(None)
        self.assertIn("Unevaluated", none_html)

    def test_stage_next_map_continuity(self):
        """STAGE_NEXT_MAP must define sequential advancement paths for all 6 stages."""
        for stage in KANBAN_STAGES:
            self.assertIn(stage, STAGE_NEXT_MAP)
        self.assertEqual(STAGE_NEXT_MAP["Ready to Apply"], "Applied")
        self.assertEqual(STAGE_NEXT_MAP["Applied"], "Reply Received")
        self.assertEqual(STAGE_NEXT_MAP["Reply Received"], "Interview Scheduled")
        self.assertEqual(STAGE_NEXT_MAP["Interview Scheduled"], "Offer")

    def test_browser_session_status_dictionary(self):
        """BrowserManager.get_session_status_all returns valid status entries for core portals."""
        statuses = BrowserManager.get_session_status_all()
        for portal in ["linkedin", "naukri", "wellfound", "hirist", "indeed"]:
            self.assertIn(portal, statuses)
            self.assertIn("has_session", statuses[portal])
            self.assertIn("login_url", statuses[portal])
            self.assertTrue(statuses[portal]["login_url"].startswith("http"))


if __name__ == "__main__":
    unittest.main()
