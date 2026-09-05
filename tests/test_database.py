"""
Unit and Integration Test Suite for Database Storage, Deduplication,
Sorting, Applied Exclusion, Application Progression, and NaN Safety.
"""

import math
import os
import tempfile
import pytest

from db.database import Database, JobList, _clean_nan, _to_int_or_none


@pytest.fixture
def temp_db():
    """Provides a fresh temporary DuckDB database for each test."""
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_jobs.duckdb")
    db = Database(db_path=db_file)
    yield db
    db.close()
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass


class TestDatabaseInitializationAndSchema:
    """Verifies schema initialization, table structures, sequences, and resets."""

    def test_schema_tables_and_sequences_exist(self, temp_db):
        tables = [r[0] for r in temp_db.conn.execute("SHOW TABLES;").fetchall()]
        assert "Jobs" in tables
        assert "Applications" in tables
        assert "ApplicationTimeline" in tables

    def test_jobs_table_columns(self, temp_db):
        cols_info = temp_db.conn.execute("PRAGMA table_info('Jobs');").fetchall()
        col_names = [c[1] for c in cols_info]
        expected = [
            "id", "platform", "job_id_on_platform", "title", "company",
            "location", "url", "description", "salary", "salary_range",
            "remote_level", "skills", "skills_required", "match_score",
            "match_reasoning", "evaluation_details", "status", "date_posted",
            "scraped_at", "created_at"
        ]
        for col in expected:
            assert col in col_names, f"Missing column {col} in Jobs table"

    def test_applications_table_columns(self, temp_db):
        cols_info = temp_db.conn.execute("PRAGMA table_info('Applications');").fetchall()
        col_names = [c[1] for c in cols_info]
        expected = [
            "id", "job_id", "applied_date", "applied_at", "resume_json",
            "resume_html", "status", "interview_date", "follow_up_date",
            "notes", "history", "created_at", "updated_at"
        ]
        for col in expected:
            assert col in col_names, f"Missing column {col} in Applications table"

    def test_application_timeline_columns(self, temp_db):
        cols_info = temp_db.conn.execute("PRAGMA table_info('ApplicationTimeline');").fetchall()
        col_names = [c[1] for c in cols_info]
        expected = ["id", "application_id", "stage", "note", "created_at"]
        for col in expected:
            assert col in col_names, f"Missing column {col} in ApplicationTimeline table"

    def test_reset_database(self, temp_db):
        # Insert a job
        job_id, is_new = temp_db.insert_job({
            "platform": "LinkedIn",
            "job_id_on_platform": "lk-100",
            "title": "Software Engineer",
            "company": "Tech Corp",
        })
        assert is_new is True
        assert len(temp_db.get_all_jobs()) == 1

        # Reset database
        temp_db.reset_database()
        assert len(temp_db.get_all_jobs()) == 0

        # Verify sequences restart cleanly from 1
        new_id, is_new2 = temp_db.insert_job({
            "platform": "LinkedIn",
            "job_id_on_platform": "lk-100",
            "title": "Software Engineer",
            "company": "Tech Corp",
        })
        assert is_new2 is True
        assert new_id == 1


class TestDeprecatedPlatformPurging:
    """Tests purging of RemoteOK and WeWorkRemotely records and cascade deletion."""

    def test_purge_deprecated_platforms_removes_stale_records(self, temp_db):
        # Insert deprecated jobs
        j1, _ = temp_db.insert_job({
            "platform": "RemoteOK",
            "job_id_on_platform": "rok-1",
            "title": "DevOps Engineer",
            "company": "Legacy Inc",
        })
        j2, _ = temp_db.insert_job({
            "platform": "WeWorkRemotely",
            "job_id_on_platform": "wwr-1",
            "title": "Backend Developer",
            "company": "Old Corp",
        })
        j3, _ = temp_db.insert_job({
            "platform": "weworkremotely",  # lower case test
            "job_id_on_platform": "wwr-2",
            "title": "Frontend Developer",
            "company": "Old Corp",
        })

        # Insert active jobs
        j4, _ = temp_db.insert_job({
            "platform": "Himalayas",
            "job_id_on_platform": "him-1",
            "title": "Python Engineer",
            "company": "Modern Co",
        })
        j5, _ = temp_db.insert_job({
            "platform": "LinkedIn",
            "job_id_on_platform": "li-1",
            "title": "Full Stack Engineer",
            "company": "Global Corp",
        })

        # Create applications and timeline entries for deprecated and valid jobs
        app_dep = temp_db.insert_application(j1, status="Applied")
        app_val = temp_db.insert_application(j4, status="Applied")

        assert len(temp_db.get_all_jobs()) == 5
        assert len(temp_db.get_all_applications_table()) == 2

        # Execute purge
        purged_count = temp_db.purge_deprecated_platforms()
        assert purged_count == 3

        # Verify only valid platforms remain
        remaining_jobs = temp_db.get_all_jobs()
        assert len(remaining_jobs) == 2
        platforms = {j["platform"] for j in remaining_jobs}
        assert platforms == {"Himalayas", "LinkedIn"}

        # Verify applications table cleaned up
        remaining_apps = temp_db.get_all_applications_table()
        assert len(remaining_apps) == 1
        assert remaining_apps[0]["app_id"] == app_val

        # Verify timeline cleaned up
        timelines = temp_db.conn.execute("SELECT application_id FROM ApplicationTimeline").fetchall()
        assert all(t[0] == app_val for t in timelines)

    def test_purge_when_no_deprecated_records(self, temp_db):
        temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "li-10", "title": "Dev", "company": "Co"})
        purged = temp_db.purge_deprecated_platforms()
        assert purged == 0
        assert len(temp_db.get_all_jobs()) == 1


class TestCompositeKeyDeduplication:
    """Verifies composite key (platform, job_id_on_platform) + SHA-256 fallback hashing."""

    def test_insert_job_returns_is_new_flag(self, temp_db):
        job_data = {
            "platform": "Naukri",
            "job_id_on_platform": "nk-12345",
            "title": "Data Scientist",
            "company": "AI Labs",
            "url": "https://naukri.com/job/12345",
        }

        # First insert -> (id, True)
        job_id1, is_new1 = temp_db.insert_job(job_data)
        assert isinstance(job_id1, int)
        assert is_new1 is True

        # Duplicate insert -> (id, False)
        job_id2, is_new2 = temp_db.insert_job(job_data)
        assert job_id2 == job_id1
        assert is_new2 is False

        # Total count must remain 1
        assert len(temp_db.get_all_jobs()) == 1

    def test_case_insensitive_platform_deduplication(self, temp_db):
        j1, is_new1 = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "101", "title": "Dev", "company": "A"})
        j2, is_new2 = temp_db.insert_job({"platform": "linkedin", "job_id_on_platform": "101", "title": "Dev", "company": "A"})

        assert is_new1 is True
        assert is_new2 is False
        assert j1 == j2
        assert len(temp_db.get_all_jobs()) == 1

    def test_cross_platform_same_job_id_allowed(self, temp_db):
        # Same job_id on different platforms should create two distinct records
        j1, is_new1 = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "123", "title": "Dev", "company": "A"})
        j2, is_new2 = temp_db.insert_job({"platform": "Naukri", "job_id_on_platform": "123", "title": "Dev", "company": "A"})

        assert is_new1 is True
        assert is_new2 is True
        assert j1 != j2
        assert len(temp_db.get_all_jobs()) == 2

    def test_fallback_sha256_hashing_for_missing_job_id(self, temp_db):
        job_no_id = {
            "platform": "Wellfound",
            "job_id_on_platform": "",  # Empty ID
            "title": "Founding Engineer",
            "company": "Startup Co",
            "url": "https://wellfound.com/startup/founding-eng",
        }

        job_id1, is_new1 = temp_db.insert_job(job_no_id)
        assert is_new1 is True

        # Check that a 16-char hex string was generated
        stored = temp_db.get_all_jobs()[0]
        assert len(stored["job_id_on_platform"]) == 16
        assert all(c in "0123456789abcdef" for c in stored["job_id_on_platform"])

        # Duplicate with same title/company/url -> should detect as duplicate
        job_id2, is_new2 = temp_db.insert_job(job_no_id)
        assert job_id2 == job_id1
        assert is_new2 is False

    def test_insert_job_supports_positional_and_kwargs(self, temp_db):
        # Positional arguments
        j1, is_new1 = temp_db.insert_job(
            "Hirist", "hirist-1", "Lead Architect", "Cloud Systems",
            "Cloud architecture role", "https://hirist.com/1", "$150k", "Remote", "AWS, Python"
        )
        assert is_new1 is True
        job = temp_db.get_all_jobs()[0]
        assert job["platform"] == "Hirist"
        assert job["title"] == "Lead Architect"
        assert job["salary_range"] == "$150k"

    def test_adversarial_special_chars_and_unicode_ingestion(self, temp_db):
        special_job = {
            "platform": "LinkedIn",
            "job_id_on_platform": "special-999",
            "title": "Senior Engineer 🚀 | 'quotes' & <tags>",
            "company": "O'Reilly & Sons; DROP TABLE Jobs;--",
            "description": "Unicode test: 你好世界 🌟 €100k — 120k",
            "url": "https://example.com/job?id=123&test=true",
        }
        jid, is_new = temp_db.insert_job(special_job)
        assert is_new is True
        stored = temp_db.get_all_jobs()[0]
        assert "🚀" in stored["title"]
        assert "DROP TABLE" in stored["company"]
        assert "你好世界" in stored["description"]


class TestReverseChronologicalSorting:
    """Verifies that all job listings queries return newest items first."""

    def test_get_all_jobs_sorted_newest_first(self, temp_db):
        # Insert 3 jobs with staggered timestamps
        temp_db.insert_job({"platform": "Remotive", "job_id_on_platform": "1", "title": "Old Job", "company": "A"})
        temp_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-01 10:00:00' WHERE job_id_on_platform = '1'")

        temp_db.insert_job({"platform": "Remotive", "job_id_on_platform": "2", "title": "New Job", "company": "B"})
        temp_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-30 12:00:00' WHERE job_id_on_platform = '2'")

        temp_db.insert_job({"platform": "Remotive", "job_id_on_platform": "3", "title": "Middle Job", "company": "C"})
        temp_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-15 10:00:00' WHERE job_id_on_platform = '3'")

        jobs = temp_db.get_all_jobs(sort_desc=True)
        titles = [j["title"] for j in jobs]
        assert titles == ["New Job", "Middle Job", "Old Job"]

        jobs_asc = temp_db.get_all_jobs(sort_desc=False)
        titles_asc = [j["title"] for j in jobs_asc]
        assert titles_asc == ["Old Job", "Middle Job", "New Job"]

    def test_get_unevaluated_jobs_sorted_newest_first(self, temp_db):
        temp_db.insert_job({"platform": "Himalayas", "job_id_on_platform": "u1", "title": "First", "company": "X"})
        temp_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-01 00:00:00' WHERE job_id_on_platform = 'u1'")

        temp_db.insert_job({"platform": "Himalayas", "job_id_on_platform": "u2", "title": "Latest", "company": "Y"})
        temp_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-30 00:00:00' WHERE job_id_on_platform = 'u2'")

        uneval = temp_db.get_unevaluated_jobs()
        assert [j["title"] for j in uneval] == ["Latest", "First"]


class TestStrictAppliedJobExclusion:
    """Verifies that jobs already in Applications are strictly excluded from unevaluated/evaluated queues."""

    def test_applied_jobs_excluded_from_unevaluated_and_evaluated(self, temp_db):
        # Insert 4 jobs
        j1, _ = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "j1", "title": "Job 1", "company": "A"})
        j2, _ = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "j2", "title": "Job 2", "company": "B"})
        j3, _ = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "j3", "title": "Job 3", "company": "C"})
        j4, _ = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "j4", "title": "Job 4", "company": "D"})

        # Initial unevaluated list has all 4
        assert len(temp_db.get_unevaluated_jobs()) == 4

        # Evaluate jobs 1, 2, 3
        temp_db.update_job_score(j1, 85, {"reasoning": "Great fit"})
        temp_db.update_job_score(j2, 90, {"reasoning": "Super fit"})
        temp_db.update_job_score(j3, 60, {"reasoning": "Low fit"})

        # Unevaluated should now only have j4
        uneval = temp_db.get_unevaluated_jobs()
        assert len(uneval) == 1
        assert uneval[0]["id"] == j4

        # Evaluated for application (min_score=70) should have j2 (90) and j1 (85)
        eval_jobs = temp_db.get_evaluated_jobs_for_application(min_score=70)
        assert len(eval_jobs) == 2
        assert [j["id"] for j in eval_jobs] == [j2, j1]

        # Apply to j2
        app_id = temp_db.insert_application(j2, status="Ready to Apply")
        assert app_id is not None

        # Now j2 MUST be excluded from evaluated jobs queue
        eval_jobs_after = temp_db.get_evaluated_jobs_for_application(min_score=70)
        assert len(eval_jobs_after) == 1
        assert eval_jobs_after[0]["id"] == j1

        # Even if unevaluated job j4 is manually placed in applications, it must vanish from unevaluated
        temp_db.insert_application(j4, status="Ready to Apply")
        assert len(temp_db.get_unevaluated_jobs()) == 0

    def test_is_job_applied_semantics(self, temp_db):
        j1, _ = temp_db.insert_job({"platform": "Naukri", "job_id_on_platform": "n1", "title": "Engineer", "company": "X"})
        assert temp_db.is_job_applied(j1) is False

        # Pre-submission stage: 'Ready to Apply'
        app_id = temp_db.insert_application(j1, status="Ready to Apply")
        assert temp_db.is_job_applied(j1) is False

        # Transition to 'Applied'
        temp_db.update_application_stage(app_id, "Applied")
        assert temp_db.is_job_applied(j1) is True

        # Transition to 'Interview Scheduled'
        temp_db.update_application_stage(app_id, "Interview Scheduled")
        assert temp_db.is_job_applied(j1) is True


class TestNaNSafetyAndScoreHandling:
    """Verifies that float('nan') values from DuckDB or scoring do not crash queries."""

    def test_clean_nan_helpers(self):
        assert _clean_nan(float("nan"), default=None) is None
        assert _clean_nan(None, default=0) == 0
        assert _clean_nan(42) == 42
        assert _clean_nan("valid_str") == "valid_str"

        assert _to_int_or_none(float("nan")) is None
        assert _to_int_or_none(None) is None
        assert _to_int_or_none(85.0) == 85
        assert _to_int_or_none("90") == 90

    def test_update_job_score_with_nan_and_none(self, temp_db):
        j1, _ = temp_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "nan-1", "title": "Test", "company": "Co"})

        # Update with NaN
        temp_db.update_job_score(j1, float("nan"), {"reasoning": "Unknown"})
        job = temp_db.get_all_jobs()[0]
        assert job["match_score"] is None

        # Update with valid int
        temp_db.update_job_score(j1, 88, {"reasoning": "Strong match"})
        job = temp_db.get_all_jobs()[0]
        assert job["match_score"] == 88

    def test_job_list_dataframe_interface(self):
        jl = JobList([{"id": 1, "title": "Dev"}, {"id": 2, "title": "QA"}])
        assert jl.empty is False
        assert len(jl) == 2

        items = list(jl.iterrows())
        assert len(items) == 2
        assert items[0][1]["title"] == "Dev"

        empty_jl = JobList()
        assert empty_jl.empty is True

        df = jl.to_df()
        assert len(df) == 2
        assert list(df["title"]) == ["Dev", "QA"]


class TestApplicationLifecycleAndTimelineAudit:
    """Verifies 6-stage Kanban transitions, history JSON logging, and timeline audit entries."""

    def test_full_application_lifecycle_and_audit(self, temp_db):
        j1, _ = temp_db.insert_job({
            "platform": "Himalayas",
            "job_id_on_platform": "him-app-1",
            "title": "Staff Backend Engineer",
            "company": "ScaleUp",
        })

        # 1. Insert Application (Stage: Ready to Apply)
        app_id = temp_db.insert_application(
            job_id=j1,
            resume_json='{"name": "Alice"}',
            resume_html='<html>Alice</html>',
            status="Ready to Apply",
            notes="Tailored with keywords"
        )
        assert app_id == 1

        # Check initial timeline
        timeline = temp_db.get_application_timeline(app_id)
        assert len(timeline) == 1
        assert timeline[0]["stage"] == "Ready to Apply"

        # Check Ready applications
        ready_apps = temp_db.get_ready_applications()
        assert len(ready_apps) == 1
        assert ready_apps[0]["app_id"] == app_id

        # 2. Stage Progression: Ready to Apply -> Applied
        ok = temp_db.update_application_stage(app_id, "Applied", note="Submitted via portal")
        assert ok is True

        # Ready applications should now be empty
        assert len(temp_db.get_ready_applications()) == 0

        # 3. Stage Progression: Applied -> Reply Received
        temp_db.update_application_stage(app_id, "Reply Received", note="Recruiter contacted via email")

        # 4. Stage Progression: Reply Received -> Interview Scheduled
        temp_db.update_application_stage(app_id, "Interview Scheduled", note="Round 1 booked")
        temp_db.update_application_notes(
            app_id,
            notes="Prep system design questions",
            interview_date="2026-09-05 14:00:00",
            recruiter_info="Sarah (recruiter@scaleup.com)"
        )

        # 5. Stage Progression: Interview Scheduled -> Offer
        temp_db.update_application_stage(app_id, "Offer", note="Received official offer letter")

        # Verify Kanban structure
        kanban = temp_db.get_kanban_applications()
        assert len(kanban["Offer"]) == 1
        assert kanban["Offer"][0]["app_id"] == app_id
        assert len(kanban["Ready to Apply"]) == 0
        assert len(kanban["Applied"]) == 0

        # Verify Full Timeline Audit Trail
        full_timeline = temp_db.get_application_timeline(app_id)
        stages_in_timeline = [t["stage"] for t in full_timeline]
        assert "Ready to Apply" in stages_in_timeline
        assert "Applied" in stages_in_timeline
        assert "Reply Received" in stages_in_timeline
        assert "Interview Scheduled" in stages_in_timeline
        assert "Offer" in stages_in_timeline
        assert len(full_timeline) >= 6  # 5 stage updates + 1 notes update

        # Verify History JSON in Applications record
        app_record = temp_db.get_all_applications_table()[0]
        import json
        history_entries = json.loads(app_record["history"])
        assert len(history_entries) == 5
        assert history_entries[-1]["stage"] == "Offer"
        assert "[Recruiter: Sarah" in app_record["notes"]

    def test_context_manager_usage(self, tmp_path):
        db_file = str(tmp_path / "ctx_test.duckdb")
        with Database(db_path=db_file) as db:
            jid, is_new = db.insert_job({"platform": "Hirist", "job_id_on_platform": "h1", "title": "Dev", "company": "Co"})
            assert is_new is True
            assert len(db.get_all_jobs()) == 1
