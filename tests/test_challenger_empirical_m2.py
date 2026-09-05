"""
Empirical Challenger Test Suite for Milestone 2:
Database Schema, Purging, Deduplication, Ordering, Strict Exclusion,
Lifecycle Progression, Timeline Auditing, and DuckDB Quirk Resilience.
"""

import hashlib
import json
import math
import os
import time
from datetime import datetime, timedelta
import pytest

from db.database import Database, JobList, _clean_nan, _to_int_or_none


@pytest.fixture
def clean_db(tmp_path):
    db_file = str(tmp_path / "empirical_m2_test.duckdb")
    db = Database(db_path=db_file)
    yield db
    db.close()


class TestEmpiricalDeduplicationAndConcurrency:
    def test_repeated_duplicate_inserts_preserve_single_record(self, clean_db):
        job = {
            "platform": "LinkedIn",
            "job_id_on_platform": "li-stress-001",
            "title": "Senior AI Architect",
            "company": "Anthropic AI",
            "url": "https://linkedin.com/jobs/view/li-stress-001",
            "salary_range": "$200k - $250k",
            "remote_level": "Remote",
        }
        initial_id, is_new_first = clean_db.insert_job(job)
        assert is_new_first is True
        assert isinstance(initial_id, int)
        for i in range(50):
            jid, is_new = clean_db.insert_job(job)
            assert jid == initial_id
            assert is_new is False
        all_jobs = clean_db.get_all_jobs()
        assert len(all_jobs) == 1
        assert all_jobs[0]["id"] == initial_id
        assert all_jobs[0]["job_id_on_platform"] == "li-stress-001"

    def test_fallback_sha256_hashing_consistency_and_collision_resistance(self, clean_db):
        job_base = {
            "platform": "Wellfound",
            "title": "Founding Lead Engineer",
            "company": "Stealth AI",
            "url": "https://wellfound.com/jobs/founding-lead",
        }

        j1 = dict(job_base)
        jid1, is_new1 = clean_db.insert_job(j1)
        assert is_new1 is True

        j2 = dict(job_base)
        j2["job_id_on_platform"] = ""
        jid2, is_new2 = clean_db.insert_job(j2)
        assert is_new2 is False
        assert jid2 == jid1

        j3 = dict(job_base)
        j3["job_id_on_platform"] = None
        jid3, is_new3 = clean_db.insert_job(j3)
        assert is_new3 is False
        assert jid3 == jid1

        j4 = dict(job_base)
        j4["job_id_on_platform"] = "   "
        jid4, is_new4 = clean_db.insert_job(j4)
        assert is_new4 is False
        assert jid4 == jid1

        expected_raw = "wellfound:stealth ai:founding lead engineer:https://wellfound.com/jobs/founding-lead"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()[:16]

        stored_jobs = clean_db.get_all_jobs()
        assert len(stored_jobs) == 1
        assert stored_jobs[0]["job_id_on_platform"] == expected_hash

    def test_distinct_jobs_with_fallback_hash_do_not_collide(self, clean_db):
        j1 = {"platform": "Wellfound", "title": "Backend Engineer", "company": "Acme", "url": "https://wellfound.com/jobs/backend-1"}
        j2 = {"platform": "Wellfound", "title": "Backend Engineer", "company": "Acme", "url": "https://wellfound.com/jobs/backend-2"}
        jid1, is_new1 = clean_db.insert_job(j1)
        jid2, is_new2 = clean_db.insert_job(j2)
        assert is_new1 is True
        assert is_new2 is True
        assert jid1 != jid2
        assert len(clean_db.get_all_jobs()) == 2

    def test_case_insensitive_platform_collision(self, clean_db):
        variations = ["LinkedIn", "linkedin", "LINKEDIN", "LiNkEdIn"]
        first_id = None
        for i, plat in enumerate(variations):
            jid, is_new = clean_db.insert_job({
                "platform": "LinkedIn",
                "job_id_on_platform": "case-test-101",
                "title": "Platform Engineer",
                "company": "Cloud Corp",
            })
            if i == 0:
                assert is_new is True
                first_id = jid
            else:
                assert is_new is False
                assert jid == first_id
        assert len(clean_db.get_all_jobs()) == 1

    def test_cross_platform_same_job_id_creates_distinct_records(self, clean_db):
        j1, is_new1 = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "9999", "title": "Dev", "company": "A"})
        j2, is_new2 = clean_db.insert_job({"platform": "Naukri", "job_id_on_platform": "9999", "title": "Dev", "company": "A"})
        assert is_new1 is True
        assert is_new2 is True
        assert j1 != j2
        assert len(clean_db.get_all_jobs()) == 2

class TestEmpiricalStrictAppliedJobExclusion:
    def test_strict_exclusion_across_all_lifecycle_stages(self, clean_db):
        stages = [
            "Ready to Apply",
            "Applied",
            "Reply Received",
            "Interview Scheduled",
            "Rejected",
            "Offer",
        ]
        for idx, stage in enumerate(stages):
            jid, _ = clean_db.insert_job({
                "platform": "Naukri",
                "job_id_on_platform": f"excl-job-{idx}",
                "title": f"Engineer Stage {stage}",
                "company": "Test Co",
            })
            assert jid in [j["id"] for j in clean_db.get_unevaluated_jobs()]
            clean_db.update_job_score(jid, 85, {"reasoning": "High fit"})
            assert jid not in [j["id"] for j in clean_db.get_unevaluated_jobs()]
            assert jid in [j["id"] for j in clean_db.get_evaluated_jobs_for_application(min_score=70)]
            app_id = clean_db.insert_application(jid, status="Ready to Apply")
            if stage != "Ready to Apply":
                clean_db.update_application_stage(app_id, stage)
            assert jid not in [j["id"] for j in clean_db.get_unevaluated_jobs()]
            assert jid not in [j["id"] for j in clean_db.get_evaluated_jobs_for_application(min_score=70)]

    def test_unevaluated_job_manually_applied_is_excluded(self, clean_db):
        jid, _ = clean_db.insert_job({"platform": "Himalayas", "job_id_on_platform": "direct-app-1", "title": "Direct Apply Job", "company": "Direct Co"})
        assert jid in [j["id"] for j in clean_db.get_unevaluated_jobs()]
        clean_db.insert_application(jid, status="Ready to Apply")
        assert jid not in [j["id"] for j in clean_db.get_unevaluated_jobs()]

    def test_ready_applications_view_filters_non_ready(self, clean_db):
        j1, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "r1", "title": "Job 1", "company": "A"})
        j2, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "r2", "title": "Job 2", "company": "B"})
        a1 = clean_db.insert_application(j1, status="Ready to Apply")
        a2 = clean_db.insert_application(j2, status="Ready to Apply")
        ready = clean_db.get_ready_applications()
        assert len(ready) == 2
        clean_db.update_application_stage(a1, "Applied")
        ready_after = clean_db.get_ready_applications()
        assert len(ready_after) == 1
        assert ready_after[0]["app_id"] == a2

    def test_is_job_applied_semantics_for_all_stages(self, clean_db):
        jid, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "is-app-1", "title": "Job", "company": "Co"})
        assert clean_db.is_job_applied(jid) is False
        app_id = clean_db.insert_application(jid, status="Ready to Apply")
        assert clean_db.is_job_applied(jid) is False
        for stage in ["Applied", "Reply Received", "Interview Scheduled", "Rejected", "Offer"]:
            clean_db.update_application_stage(app_id, stage)
            assert clean_db.is_job_applied(jid) is True

class TestEmpiricalOrderingAndTimestampPatterns:
    def test_reverse_chronological_sorting_with_iso_and_sql_timestamps(self, clean_db):
        base_time = datetime(2026, 8, 1, 12, 0, 0)
        jobs_meta = [
            ("t1", base_time + timedelta(days=1), "Day 1"),
            ("t2", base_time + timedelta(days=5), "Day 5"),
            ("t3", base_time + timedelta(days=2), "Day 2"),
            ("t4", base_time + timedelta(days=10), "Day 10"),
            ("t5", base_time + timedelta(days=3), "Day 3"),
        ]
        for job_id, ts, title in jobs_meta:
            jid, _ = clean_db.insert_job({"platform": "Remotive", "job_id_on_platform": job_id, "title": title, "company": "Company"})
            clean_db.conn.execute("UPDATE Jobs SET scraped_at = ? WHERE id = ?", (ts.strftime("%Y-%m-%d %H:%M:%S"), jid))
        jobs_desc = clean_db.get_all_jobs(sort_desc=True)
        assert [j["title"] for j in jobs_desc] == ["Day 10", "Day 5", "Day 3", "Day 2", "Day 1"]
        jobs_asc = clean_db.get_all_jobs(sort_desc=False)
        assert [j["title"] for j in jobs_asc] == ["Day 1", "Day 2", "Day 3", "Day 5", "Day 10"]

    def test_tie_breaking_by_id_when_timestamps_are_identical(self, clean_db):
        same_ts = "2026-08-15 10:00:00"
        for i in range(1, 6):
            jid, _ = clean_db.insert_job({"platform": "Hirist", "job_id_on_platform": f"tie-{i}", "title": f"Job {i}", "company": "Tie Co"})
            clean_db.conn.execute("UPDATE Jobs SET scraped_at = ?, created_at = ? WHERE id = ?", (same_ts, same_ts, jid))
        jobs_desc = clean_db.get_all_jobs(sort_desc=True)
        assert [j["job_id_on_platform"] for j in jobs_desc] == ["tie-5", "tie-4", "tie-3", "tie-2", "tie-1"]
        jobs_asc = clean_db.get_all_jobs(sort_desc=False)
        assert [j["job_id_on_platform"] for j in jobs_asc] == ["tie-1", "tie-2", "tie-3", "tie-4", "tie-5"]

    def test_evaluated_jobs_ordering_by_score_then_recency(self, clean_db):
        clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e1", "title": "Score 80 Old", "company": "A"})
        clean_db.update_job_score(1, 80)
        clean_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-01 00:00:00' WHERE id = 1")
        clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e2", "title": "Score 90 Old", "company": "B"})
        clean_db.update_job_score(2, 90)
        clean_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-01 00:00:00' WHERE id = 2")
        clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e3", "title": "Score 80 New", "company": "C"})
        clean_db.update_job_score(3, 80)
        clean_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-20 00:00:00' WHERE id = 3")
        clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "e4", "title": "Score 95 New", "company": "D"})
        clean_db.update_job_score(4, 95)
        clean_db.conn.execute("UPDATE Jobs SET scraped_at = '2026-08-25 00:00:00' WHERE id = 4")
        eval_jobs = clean_db.get_evaluated_jobs_for_application(min_score=75)
        titles = [j["title"] for j in eval_jobs]
        assert titles == ["Score 95 New", "Score 90 Old", "Score 80 New", "Score 80 Old"]

class TestEmpiricalLifecycleProgressionAndTimelineAuditing:
    def test_full_six_stage_progression_and_audit_log_verification(self, clean_db):
        jid, _ = clean_db.insert_job({"platform": "Himalayas", "job_id_on_platform": "him-full-001", "title": "Principal Architect", "company": "NextGen Systems"})
        app_id = clean_db.insert_application(job_id=jid, resume_json='{"version": 1}', resume_html='<h1>Resume</h1>', status="Ready to Apply", notes="Initial app prepared.")
        timeline = clean_db.get_application_timeline(app_id)
        assert len(timeline) == 1
        assert timeline[0]["stage"] == "Ready to Apply"
        clean_db.update_application_stage(app_id, "Applied", note="Submitted via Playwright")
        app_data = clean_db.get_all_applications_table()[0]
        assert app_data["app_status"] == "Applied"
        clean_db.update_application_stage(app_id, "Reply Received", note="Recruiter email")
        clean_db.update_application_stage(app_id, "Interview Scheduled", note="Round 1")
        clean_db.update_application_notes(app_id=app_id, notes="Prep design questions", interview_date="2026-09-10 15:30:00", recruiter_info="Alice")
        clean_db.update_application_stage(app_id, "Offer", note="Offer accepted")
        kanban = clean_db.get_kanban_applications()
        assert len(kanban["Offer"] ) == 1
        full_timeline = clean_db.get_application_timeline(app_id)
        assert len(full_timeline) == 6
        history = json.loads(clean_db.get_all_applications_table()[0]["history"])
        assert len(history) == 5
        assert [h["stage"] for h in history] == ["Ready to Apply", "Applied", "Reply Received", "Interview Scheduled", "Offer"]

    def test_rejection_stage_progression(self, clean_db):
        jid, _ = clean_db.insert_job({"platform": "Wellfound", "job_id_on_platform": "w-rej-1", "title": "Dev", "company": "Co"})
        app_id = clean_db.insert_application(jid, status="Ready to Apply")
        clean_db.update_application_stage(app_id, "Applied")
        clean_db.update_application_stage(app_id, "Rejected", note="Position closed")
        kanban = clean_db.get_kanban_applications()
        assert len(kanban["Rejected"]) == 1

class TestEmpiricalNaNSafetyAndDuckDBQuirks:
    def test_nan_match_score_does_not_corrupt_filtering_or_sorting(self, clean_db):
        j1, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "nan-1", "title": "NaN 1", "company": "A", "match_score": float('nan')})
        j2, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "none-2", "title": "None 2", "company": "B", "match_score": None})
        j3, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "valid-3", "title": "Valid 3", "company": "C", "match_score": 85})
        j4, _ = clean_db.insert_job({"platform": "LinkedIn", "job_id_on_platform": "nan-4", "title": "NaN 4", "company": "D"})
        clean_db.update_job_score(j4, float('nan'), {"reasoning": "NaN update"})
        all_jobs = clean_db.get_all_jobs()
        assert len(all_jobs) == 4
        for job in all_jobs:
            score = job["match_score"]
            assert score is None or isinstance(score, int)
            if score is not None:
                assert not math.isnan(score)
        uneval = clean_db.get_unevaluated_jobs()
        uneval_ids = [j["id"] for j in uneval]
        assert j1 in uneval_ids
        assert j2 in uneval_ids
        assert j3 not in uneval_ids
        eval_jobs = clean_db.get_evaluated_jobs_for_application(min_score=70)
        assert len(eval_jobs) == 1
        assert eval_jobs[0]["id"] == j3

    def test_duckdb_sequence_continuity_under_duplicate_attempts(self, clean_db):
        j_a = {"platform": "Hirist", "job_id_on_platform": "seq-1", "title": "Job A", "company": "A"}
        j_b = {"platform": "Hirist", "job_id_on_platform": "seq-2", "title": "Job B", "company": "B"}
        id_a1, is_new_a1 = clean_db.insert_job(j_a)
        assert is_new_a1 is True
        assert id_a1 == 1
        for _ in range(5):
            id_dup, is_new_dup = clean_db.insert_job(j_a)
            assert is_new_dup is False
            assert id_dup == 1
        id_b, is_new_b = clean_db.insert_job(j_b)
        assert is_new_b is True
        assert id_b == 2

class TestEmpiricalLargeScaleVolumeAndPerformance:
    def test_volume_ingestion_and_query_integrity(self, clean_db):
        start_time = time.time()
        platforms = ["LinkedIn", "Naukri", "Hirist", "Wellfound", "Himalayas"]
        for i in range(1000):
            plat = platforms[i % len(platforms)]
            jid, is_new = clean_db.insert_job({
                "platform": plat,
                "job_id_on_platform": f"vol-{i}",
                "title": f"Software Engineer #{i}",
                "company": f"Company {i % 50}",
                "salary_range": f"${100 + (i % 50)}k",
                "location": "Remote",
            })
            assert is_new is True
        for i in range(500):
            plat = platforms[i % len(platforms)]
            jid, is_new = clean_db.insert_job({
                "platform": plat,
                "job_id_on_platform": f"vol-{i}",
                "title": f"Software Engineer #{i}",
                "company": f"Company {i % 50}",
            })
            assert is_new is False
        elapsed = time.time() - start_time
        assert elapsed < 10.0
        assert len(clean_db.get_all_jobs()) == 1000
        for i in range(200):
            clean_db.update_job_score(i + 1, 60 + (i % 40))
        for i in range(50):
            clean_db.insert_application(i + 1, status="Ready to Apply")
        assert len(clean_db.get_unevaluated_jobs(limit=1000)) == 800
        eval_avail = clean_db.get_evaluated_jobs_for_application(min_score=70, limit=1000)
        assert len(eval_avail) > 0
        eval_ids = {j["id"] for j in eval_avail}
        for app_id in range(1, 51):
            assert app_id not in eval_ids
        kanban = clean_db.get_kanban_applications()
        assert len(kanban["Ready to Apply"]) == 50
