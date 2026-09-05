"""
DuckDB storage engine for Autonomous Job Applicant.
Handles schema initialization, multi-source job ingestion, composite-key deduplication,
reverse-chronological sorting, strict exclusion of applied listings, 6-stage application
lifecycle tracking, timeline audit logging, and DuckDB 1.0.0 quirk guards.
"""

import hashlib
import json
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import duckdb
from config import config

logger = logging.getLogger(__name__)


def _clean_nan(val: Any, default: Any = None) -> Any:
    """Sanitize float('nan') or None from DuckDB queries."""
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    return val


def _to_int_or_none(val: Any) -> Optional[int]:
    """Safely convert a value to int, guarding against float('nan') and None."""
    cleaned = _clean_nan(val)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


class JobList(list):
    """
    List subclass that provides DataFrame-like convenience properties (empty, iterrows)
    for seamless integration with Streamlit UI while remaining a native Python list of dicts.
    """
    @property
    def empty(self) -> bool:
        return len(self) == 0

    def iterrows(self):
        for idx, item in enumerate(self):
            yield idx, item

    def to_df(self):
        import pandas as pd
        return pd.DataFrame(self)


class Database:
    """
    DuckDB database operations manager.
    Supports persistent and in-memory databases, automatic schema migrations,
    deduplication, lifecycle progression, and audit timeline tracking.
    """

    def __init__(self, db_path: Optional[str] = None, read_only: bool = False):
        self.db_path = db_path or os.getenv("DB_PATH", config.DB_PATH)
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.conn = duckdb.connect(self.db_path, read_only=read_only)
        if not read_only:
            self._init_db()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _init_db(self) -> None:
        """Initialize sequences, tables, indexes, and apply safe migrations."""
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            self.conn.execute(schema_sql)

        # Safe schema migrations for existing databases
        migrations = [
            # Jobs migrations
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS location VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS salary VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS salary_range VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS remote_level VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS skills VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS skills_required VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS match_score INTEGER;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS match_reasoning VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS evaluation_details VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'scraped';",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS date_posted VARCHAR;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE Jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            # Applications migrations
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS applied_date TIMESTAMP;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS interview_date TIMESTAMP;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS follow_up_date TIMESTAMP;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS notes VARCHAR;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS history VARCHAR;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS resume_json VARCHAR;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS resume_html VARCHAR;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'Ready to Apply';",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE Applications ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        ]
        for mig in migrations:
            try:
                self.conn.execute(mig)
            except Exception as e:
                logger.debug(f"Migration notice for '{mig}': {e}")

    def purge_deprecated_platforms(self) -> int:
        """
        Purges all records belonging to deprecated paywalled platforms (RemoteOK and WeWorkRemotely)
        along with any referencing applications and timeline records.

        Returns:
            The number of purged job records.
        """
        deprecated_clause = "LOWER(platform) IN ('remoteok', 'weworkremotely')"

        # Fetch IDs of jobs to purge
        rows = self.conn.execute(
            f"SELECT id FROM Jobs WHERE {deprecated_clause}"
        ).fetchall()
        purged_job_ids = [r[0] for r in rows]
        job_count = len(purged_job_ids)

        if job_count > 0:
            logger.info(f"Purging {job_count} deprecated platform jobs and associated records.")
            # 1. Delete timeline entries for matching applications
            self.conn.execute(f"""
                DELETE FROM ApplicationTimeline
                WHERE application_id IN (
                    SELECT a.id FROM Applications a
                    JOIN Jobs j ON a.job_id = j.id
                    WHERE {deprecated_clause}
                )
            """)

            # 2. Delete applications for matching jobs
            self.conn.execute(f"""
                DELETE FROM Applications
                WHERE job_id IN (
                    SELECT id FROM Jobs WHERE {deprecated_clause}
                )
            """)

            # 3. Delete jobs
            self.conn.execute(f"DELETE FROM Jobs WHERE {deprecated_clause}")

        return job_count

    def reset_database(self) -> None:
        """
        Drops all tables and sequences and re-executes schema.sql.
        Use for clean environment resets and tests.
        """
        self.conn.execute("DROP TABLE IF EXISTS ApplicationTimeline;")
        self.conn.execute("DROP TABLE IF EXISTS Applications;")
        self.conn.execute("DROP TABLE IF EXISTS Jobs;")
        self.conn.execute("DROP SEQUENCE IF EXISTS seq_timeline_id;")
        self.conn.execute("DROP SEQUENCE IF EXISTS seq_app_id;")
        self.conn.execute("DROP SEQUENCE IF EXISTS seq_job_id;")
        self._init_db()

    def insert_job(
        self,
        platform_or_dict: Union[Dict[str, Any], str],
        job_id_on_platform: Optional[str] = None,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        salary_range: Optional[str] = None,
        remote_level: Optional[str] = None,
        skills_required: Optional[str] = None,
        location: Optional[str] = None,
        salary: Optional[str] = None,
        skills: Optional[str] = None,
        date_posted: Optional[str] = None,
        match_score: Optional[int] = None,
        match_reasoning: Optional[str] = None,
        evaluation_details: Optional[Any] = None,
        **kwargs: Any,
    ) -> Tuple[int, bool]:
        """
        Inserts a job listing using composite key (platform, job_id_on_platform) deduplication.
        Performs an explicit existence check before insertion to bypass the DuckDB 1.0.0
        RETURNING sequence bug on conflict.

        Accepts either a single dictionary or positional/keyword arguments.

        Returns:
            Tuple of (job_id: int, is_new: bool).
        """
        if isinstance(platform_or_dict, dict):
            d = platform_or_dict
            platform = str(d.get("platform") or "Unknown").strip()
            raw_job_id = d.get("job_id_on_platform")
            job_id_on_platform = str(raw_job_id).strip() if raw_job_id is not None else ""
            title = str(d.get("title") or "Untitled Position").strip()
            company = str(d.get("company") or "Unknown Company").strip()
            description = str(d.get("description") or "").strip()
            url = str(d.get("url") or "").strip()
            salary = d.get("salary")
            salary_range = str(d.get("salary_range") or salary or "Not specified").strip()
            location = d.get("location")
            remote_level = str(d.get("remote_level") or location or "Remote").strip()
            skills = d.get("skills")
            skills_required = str(d.get("skills_required") or skills or "").strip()
            date_posted = d.get("date_posted")
            match_score = _to_int_or_none(d.get("match_score"))
            match_reasoning = d.get("match_reasoning")
            evaluation_details = d.get("evaluation_details")
        else:
            platform = str(platform_or_dict or "Unknown").strip()
            job_id_on_platform = str(job_id_on_platform).strip() if job_id_on_platform is not None else ""
            title = str(title or "Untitled Position").strip()
            company = str(company or "Unknown Company").strip()
            description = str(description or "").strip()
            url = str(url or "").strip()
            salary = salary or kwargs.get("salary")
            salary_range = str(salary_range or salary or "Not specified").strip()
            location = location or kwargs.get("location")
            remote_level = str(remote_level or location or "Remote").strip()
            skills = skills or kwargs.get("skills")
            skills_required = str(skills_required or skills or "").strip()
            date_posted = date_posted or kwargs.get("date_posted")
            match_score = _to_int_or_none(match_score or kwargs.get("match_score"))
            match_reasoning = match_reasoning or kwargs.get("match_reasoning")
            evaluation_details = evaluation_details or kwargs.get("evaluation_details")

        # Fallback deterministic SHA-256 hash if job_id_on_platform is missing/empty
        if not job_id_on_platform:
            raw_key = f"{platform.lower()}:{company.lower()}:{title.lower()}:{url.lower()}"
            job_id_on_platform = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

        location_str = str(location or remote_level or "Remote").strip()
        salary_str = str(salary or salary_range or "Not specified").strip()
        skills_str = str(skills or skills_required or "").strip()

        if isinstance(evaluation_details, dict):
            eval_str = json.dumps(evaluation_details)
        elif evaluation_details is not None:
            eval_str = str(evaluation_details)
        else:
            eval_str = None

        # 1. Explicit existence check (bypasses DuckDB 1.0.0 RETURNING on conflict bug)
        existing = self.conn.execute(
            "SELECT id FROM Jobs WHERE LOWER(platform) = LOWER(?) AND job_id_on_platform = ?",
            (platform, job_id_on_platform),
        ).fetchone()

        if existing:
            return existing[0], False

        # 2. Insert new record
        self.conn.execute(
            """
            INSERT INTO Jobs (
                platform, job_id_on_platform, title, company, location, url,
                description, salary, salary_range, remote_level, skills, skills_required,
                match_score, match_reasoning, evaluation_details, status, date_posted,
                scraped_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scraped', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                platform,
                job_id_on_platform,
                title,
                company,
                location_str,
                url,
                description,
                salary_str if salary_str != "Not specified" else None,
                salary_range,
                remote_level,
                skills_str if skills_str else None,
                skills_required,
                match_score,
                str(match_reasoning) if match_reasoning else None,
                eval_str,
                str(date_posted) if date_posted else None,
            ),
        )

        # 3. Retrieve new ID
        new_row = self.conn.execute(
            "SELECT id FROM Jobs WHERE LOWER(platform) = LOWER(?) AND job_id_on_platform = ?",
            (platform, job_id_on_platform),
        ).fetchone()

        if new_row:
            return new_row[0], True
        raise RuntimeError("Failed to insert job record into DuckDB.")

    def update_job_score(
        self,
        job_id: int,
        match_score: Optional[int],
        evaluation_details: Optional[Any] = None,
    ) -> None:
        """
        Safely updates match_score and evaluation_details/match_reasoning for a job,
        transitioning its status to 'evaluated'.
        """
        score = _to_int_or_none(match_score)
        if isinstance(evaluation_details, dict):
            details_str = json.dumps(evaluation_details)
            reasoning_str = evaluation_details.get("reasoning") or details_str
        elif evaluation_details is not None:
            details_str = str(evaluation_details)
            reasoning_str = details_str
        else:
            details_str = None
            reasoning_str = None

        self.conn.execute(
            """
            UPDATE Jobs
            SET match_score = ?,
                match_reasoning = ?,
                evaluation_details = ?,
                status = 'evaluated'
            WHERE id = ?
            """,
            (score, reasoning_str, details_str, job_id),
        )

    def update_job_match(self, job_id: int, match_score: int, match_reasoning: str) -> None:
        """Backward compatibility alias for update_job_score."""
        self.update_job_score(job_id, match_score, match_reasoning)

    def update_job_status(self, job_id: int, status: str) -> None:
        """Updates the status column of a job record."""
        self.conn.execute("UPDATE Jobs SET status = ? WHERE id = ?", (status, job_id))

    def get_unevaluated_jobs(self, limit: int = 50) -> JobList:
        """
        Returns active unevaluated jobs sorted reverse-chronologically (newest first).
        Strictly excludes jobs that already have records in Applications.
        """
        query = """
        SELECT
            j.id, j.platform, j.job_id_on_platform, j.title, j.company,
            j.location, j.url, j.description, j.salary, j.salary_range,
            j.remote_level, j.skills, j.skills_required, j.match_score,
            j.match_reasoning, j.evaluation_details, j.status, j.date_posted,
            j.scraped_at, j.created_at
        FROM Jobs j
        WHERE j.status = 'scraped'
          AND j.match_score IS NULL
          AND j.id NOT IN (SELECT job_id FROM Applications)
        ORDER BY COALESCE(j.scraped_at, j.created_at) DESC, j.id DESC
        LIMIT ?
        """
        rows = self.conn.execute(query, (limit,)).fetchall()
        cols = [
            "id", "platform", "job_id_on_platform", "title", "company",
            "location", "url", "description", "salary", "salary_range",
            "remote_level", "skills", "skills_required", "match_score",
            "match_reasoning", "evaluation_details", "status", "date_posted",
            "scraped_at", "created_at"
        ]

        result = JobList()
        for r in rows:
            d = dict(zip(cols, r))
            d["match_score"] = _to_int_or_none(d["match_score"])
            result.append(d)
        return result

    def get_evaluated_jobs_for_application(self, min_score: int = 70, limit: int = 50) -> JobList:
        """
        Returns evaluated jobs meeting the min_score threshold, sorted by match_score DESC
        and newest-first. Strictly excludes jobs already in Applications.
        """
        query = """
        SELECT
            j.id, j.platform, j.job_id_on_platform, j.title, j.company,
            j.location, j.url, j.description, j.salary, j.salary_range,
            j.remote_level, j.skills, j.skills_required, j.match_score,
            j.match_reasoning, j.evaluation_details, j.status, j.date_posted,
            j.scraped_at, j.created_at
        FROM Jobs j
        WHERE (j.status = 'evaluated' OR j.match_score IS NOT NULL)
          AND j.match_score >= ?
          AND j.id NOT IN (SELECT job_id FROM Applications)
        ORDER BY j.match_score DESC, COALESCE(j.scraped_at, j.created_at) DESC, j.id DESC
        LIMIT ?
        """
        rows = self.conn.execute(query, (min_score, limit)).fetchall()
        cols = [
            "id", "platform", "job_id_on_platform", "title", "company",
            "location", "url", "description", "salary", "salary_range",
            "remote_level", "skills", "skills_required", "match_score",
            "match_reasoning", "evaluation_details", "status", "date_posted",
            "scraped_at", "created_at"
        ]

        result = JobList()
        for r in rows:
            d = dict(zip(cols, r))
            d["match_score"] = _to_int_or_none(d["match_score"])
            result.append(d)
        return result

    def get_all_jobs(self, sort_desc: bool = True) -> JobList:
        """
        Returns all jobs in the database sorted reverse-chronologically (or chronologically).
        Guards against NaN match_scores.
        """
        direction = "DESC" if sort_desc else "ASC"
        query = f"""
        SELECT
            id, platform, job_id_on_platform, title, company, location,
            url, description, salary, salary_range, remote_level,
            skills, skills_required, match_score, match_reasoning,
            evaluation_details, status, date_posted, scraped_at, created_at
        FROM Jobs
        ORDER BY COALESCE(scraped_at, created_at) {direction}, id {direction}
        """
        rows = self.conn.execute(query).fetchall()
        cols = [
            "id", "platform", "job_id_on_platform", "title", "company",
            "location", "url", "description", "salary", "salary_range",
            "remote_level", "skills", "skills_required", "match_score",
            "match_reasoning", "evaluation_details", "status", "date_posted",
            "scraped_at", "created_at"
        ]

        result = JobList()
        for r in rows:
            d = dict(zip(cols, r))
            d["match_score"] = _to_int_or_none(d["match_score"])
            result.append(d)
        return result

    def insert_application(
        self,
        job_id: int,
        resume_json: str = "",
        resume_html: str = "",
        status: str = "Ready to Apply",
        notes: Optional[str] = None,
    ) -> int:
        """
        Inserts an application for a given job, setting its initial status,
        logging initial history, creating an ApplicationTimeline audit record,
        and updating the job status.

        Returns:
            The application ID.
        """
        # 1. Check if application already exists for this job
        existing = self.conn.execute(
            "SELECT id FROM Applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing:
            return existing[0]

        # 2. Prepare initial history JSON
        init_history = json.dumps([
            {
                "stage": status,
                "timestamp": datetime.utcnow().isoformat(),
                "note": notes or "Application created",
            }
        ])

        # 3. Insert into Applications
        self.conn.execute(
            """
            INSERT INTO Applications (
                job_id, applied_date, applied_at, resume_json, resume_html,
                status, notes, history, created_at, updated_at
            ) VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (job_id, resume_json, resume_html, status, notes, init_history),
        )

        app_row = self.conn.execute(
            "SELECT id FROM Applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not app_row:
            raise RuntimeError(f"Failed to retrieve application for job_id {job_id}")

        app_id = app_row[0]

        # 4. Insert initial timeline audit record
        self.conn.execute(
            """
            INSERT INTO ApplicationTimeline (application_id, stage, note, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (app_id, status, notes or "Application initialized"),
        )

        # 5. Update job status
        job_status = "ready" if status in ("Ready to Apply", "ready") else status.lower()
        self.update_job_status(job_id, job_status)

        return app_id

    def update_application_stage(
        self,
        app_id: int,
        new_stage: str,
        note: Optional[str] = None,
    ) -> bool:
        """
        Advances an application to a new stage, appends to the history JSON,
        inserts an ApplicationTimeline audit record, and updates the associated job status.

        Returns:
            True if updated successfully, False if application not found.
        """
        row = self.conn.execute(
            "SELECT id, job_id, status, history FROM Applications WHERE id = ?",
            (app_id,),
        ).fetchone()

        if not row:
            return False

        job_id, old_status, raw_history = row[1], row[2], row[3]

        # Parse and append history
        try:
            history_list = json.loads(raw_history) if raw_history else []
        except Exception:
            history_list = []

        history_list.append({
            "stage": new_stage,
            "previous_stage": old_status,
            "timestamp": datetime.utcnow().isoformat(),
            "note": note or f"Stage transitioned to {new_stage}",
        })
        history_json = json.dumps(history_list)

        # Update Applications table
        self.conn.execute(
            """
            UPDATE Applications
            SET status = ?,
                history = ?,
                updated_at = CURRENT_TIMESTAMP,
                applied_at = CASE WHEN ? = 'Applied' AND applied_at IS NULL THEN CURRENT_TIMESTAMP ELSE applied_at END,
                applied_date = CASE WHEN ? = 'Applied' AND applied_date IS NULL THEN CURRENT_TIMESTAMP ELSE applied_date END
            WHERE id = ?
            """,
            (new_stage, history_json, new_stage, new_stage, app_id),
        )

        # Insert audit timeline entry
        self.conn.execute(
            """
            INSERT INTO ApplicationTimeline (application_id, stage, note, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (app_id, new_stage, note or f"Transitioned from {old_status} to {new_stage}"),
        )

        # Update job status
        if job_id:
            job_status = "ready" if new_stage in ("Ready to Apply", "ready") else new_stage.lower()
            self.update_job_status(job_id, job_status)

        return True

    def update_application_notes(
        self,
        app_id: int,
        notes: str,
        interview_date: Optional[str] = None,
        follow_up_date: Optional[str] = None,
        recruiter_info: Optional[str] = None,
    ) -> bool:
        """
        Updates notes, interview dates, follow-up dates, and recruiter information
        for an application, logging an audit record in ApplicationTimeline.

        Returns:
            True if updated successfully, False if application not found.
        """
        row = self.conn.execute(
            "SELECT id, status FROM Applications WHERE id = ?", (app_id,)
        ).fetchone()

        if not row:
            return False

        status = row[1]
        full_notes = notes
        if recruiter_info:
            full_notes = f"{notes}\n[Recruiter: {recruiter_info}]" if notes else f"[Recruiter: {recruiter_info}]"

        self.conn.execute(
            """
            UPDATE Applications
            SET notes = ?,
                interview_date = COALESCE(TRY_CAST(? AS TIMESTAMP), interview_date),
                follow_up_date = COALESCE(TRY_CAST(? AS TIMESTAMP), follow_up_date),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (full_notes, interview_date, follow_up_date, app_id),
        )

        audit_msg = "Updated application notes"
        if interview_date:
            audit_msg += f" (Interview: {interview_date})"
        if follow_up_date:
            audit_msg += f" (Follow-up: {follow_up_date})"

        self.conn.execute(
            """
            INSERT INTO ApplicationTimeline (application_id, stage, note, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (app_id, status, audit_msg),
        )
        return True

    def get_kanban_applications(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetches all applications grouped into the 6 primary Kanban stages:
        'Ready to Apply', 'Applied', 'Reply Received', 'Interview Scheduled', 'Rejected', 'Offer'.
        """
        stages = [
            "Ready to Apply",
            "Applied",
            "Reply Received",
            "Interview Scheduled",
            "Rejected",
            "Offer",
        ]
        kanban_dict: Dict[str, List[Dict[str, Any]]] = {stage: [] for stage in stages}

        query = """
        SELECT
            a.id as app_id, a.job_id, a.status as app_status, a.applied_at, a.applied_date,
            a.interview_date, a.follow_up_date, a.notes, a.history, a.resume_json, a.resume_html,
            a.created_at as app_created_at, a.updated_at as app_updated_at,
            j.platform, j.job_id_on_platform, j.title, j.company, j.location, j.url,
            j.salary, j.salary_range, j.remote_level, j.skills, j.skills_required,
            j.match_score, j.match_reasoning, j.evaluation_details, j.date_posted
        FROM Applications a
        JOIN Jobs j ON a.job_id = j.id
        ORDER BY COALESCE(a.updated_at, a.created_at) DESC, a.id DESC
        """
        rows = self.conn.execute(query).fetchall()
        cols = [
            "app_id", "job_id", "app_status", "applied_at", "applied_date",
            "interview_date", "follow_up_date", "notes", "history", "resume_json", "resume_html",
            "app_created_at", "app_updated_at",
            "platform", "job_id_on_platform", "title", "company", "location", "url",
            "salary", "salary_range", "remote_level", "skills", "skills_required",
            "match_score", "match_reasoning", "evaluation_details", "date_posted"
        ]

        for r in rows:
            item = dict(zip(cols, r))
            item["match_score"] = _to_int_or_none(item["match_score"])

            # Map legacy status strings to canonical Kanban stages
            raw_status = item["app_status"] or "Ready to Apply"
            if raw_status.lower() == "ready":
                canonical_stage = "Ready to Apply"
            elif raw_status.lower() == "applied":
                canonical_stage = "Applied"
            elif raw_status in kanban_dict:
                canonical_stage = raw_status
            else:
                canonical_stage = "Ready to Apply"

            item["app_status"] = canonical_stage
            kanban_dict[canonical_stage].append(item)

        return kanban_dict

    def get_all_applications_table(self) -> JobList:
        """
        Returns a flat, sortable list of all applications joined with their job listings.
        """
        query = """
        SELECT
            a.id as app_id, a.job_id, a.status as app_status, a.applied_at, a.applied_date,
            a.interview_date, a.follow_up_date, a.notes, a.history, a.resume_json, a.resume_html,
            a.created_at as app_created_at, a.updated_at as app_updated_at,
            j.platform, j.job_id_on_platform, j.title, j.company, j.location, j.url,
            j.salary, j.salary_range, j.remote_level, j.skills, j.skills_required,
            j.match_score, j.match_reasoning, j.evaluation_details, j.date_posted
        FROM Applications a
        JOIN Jobs j ON a.job_id = j.id
        ORDER BY COALESCE(a.updated_at, a.created_at) DESC, a.id DESC
        """
        rows = self.conn.execute(query).fetchall()
        cols = [
            "app_id", "job_id", "app_status", "applied_at", "applied_date",
            "interview_date", "follow_up_date", "notes", "history", "resume_json", "resume_html",
            "app_created_at", "app_updated_at",
            "platform", "job_id_on_platform", "title", "company", "location", "url",
            "salary", "salary_range", "remote_level", "skills", "skills_required",
            "match_score", "match_reasoning", "evaluation_details", "date_posted"
        ]

        result = JobList()
        for r in rows:
            d = dict(zip(cols, r))
            d["match_score"] = _to_int_or_none(d["match_score"])
            result.append(d)
        return result

    def get_application_timeline(self, app_id: int) -> List[Dict[str, Any]]:
        """
        Returns the audit trail for a given application sorted chronologically.
        """
        rows = self.conn.execute(
            """
            SELECT id, application_id, stage, note, created_at
            FROM ApplicationTimeline
            WHERE application_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (app_id,),
        ).fetchall()

        cols = ["id", "application_id", "stage", "note", "created_at"]
        return [dict(zip(cols, r)) for r in rows]

    def is_job_applied(self, job_id: int) -> bool:
        """
        Checks if a job has already been advanced past the 'Ready to Apply' / 'ready' stage.
        Returns True if the application exists and is marked Applied, Reply Received, etc.
        """
        row = self.conn.execute(
            "SELECT status FROM Applications WHERE job_id = ?", (job_id,)
        ).fetchone()

        if not row:
            return False

        status = (row[0] or "").strip().lower()
        # 'ready' and 'ready to apply' are pre-submission stages; others indicate applied/in-progress
        return status not in ("ready", "ready to apply")

    def get_ready_applications(self) -> JobList:
        """
        Returns all applications currently in 'Ready to Apply' or 'ready' status,
        sorted by match_score DESC and newest-first.
        """
        query = """
        SELECT
            a.id as app_id,
            j.id as job_id,
            j.platform,
            j.job_id_on_platform,
            j.title,
            j.company,
            j.url,
            j.location,
            j.salary_range,
            j.match_score,
            j.match_reasoning,
            a.resume_json,
            a.resume_html,
            a.status as app_status,
            j.status as job_status,
            a.created_at,
            a.updated_at
        FROM Applications a
        JOIN Jobs j ON a.job_id = j.id
        WHERE LOWER(a.status) IN ('ready to apply', 'ready')
        ORDER BY j.match_score DESC NULLS LAST, COALESCE(a.updated_at, a.created_at) DESC
        """
        rows = self.conn.execute(query).fetchall()
        cols = [
            "app_id", "job_id", "platform", "job_id_on_platform", "title",
            "company", "url", "location", "salary_range", "match_score",
            "match_reasoning", "resume_json", "resume_html", "app_status",
            "job_status", "created_at", "updated_at"
        ]

        result = JobList()
        for r in rows:
            d = dict(zip(cols, r))
            d["match_score"] = _to_int_or_none(d["match_score"])
            result.append(d)
        return result

    def mark_application_applied(self, app_id: int) -> bool:
        """Convenience helper to advance an application to 'Applied'."""
        return self.update_application_stage(app_id, "Applied")

    def close(self) -> None:
        """Closes the DuckDB connection."""
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
