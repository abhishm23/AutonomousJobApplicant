import duckdb
import os
from config import config

class Database:
    def __init__(self, db_path=None, read_only=False):
        self.db_path = db_path or os.getenv("DB_PATH", config.DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = duckdb.connect(self.db_path, read_only=read_only)
        if not read_only:
            self._init_db()

    def _init_db(self):
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        if os.path.exists(schema_path):
            with open(schema_path, 'r') as f:
                schema_sql = f.read()
            self.conn.execute(schema_sql)

    def insert_job(self, platform, job_id_on_platform, title, company, description, url, salary_range, remote_level, skills_required):
        query = """
        INSERT INTO Jobs (platform, job_id_on_platform, title, company, description, url, salary_range, remote_level, skills_required)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (platform, job_id_on_platform) DO NOTHING;
        """
        self.conn.execute(query, (platform, job_id_on_platform, title, company, description, url, salary_range, remote_level, skills_required))
        result = self.conn.execute(
            "SELECT id FROM Jobs WHERE platform = ? AND job_id_on_platform = ?",
            (platform, job_id_on_platform)
        ).fetchone()
        return result[0] if result else None

    def update_job_match(self, job_id, match_score, match_reasoning):
        query = """
        UPDATE Jobs
        SET match_score = ?, match_reasoning = ?, status = 'evaluated'
        WHERE id = ?
        """
        self.conn.execute(query, (match_score, match_reasoning, job_id))

    def update_job_status(self, job_id, status):
        query = "UPDATE Jobs SET status = ? WHERE id = ?"
        self.conn.execute(query, (status, job_id))

    def insert_application(self, job_id, resume_json, resume_html, status='ready'):
        query = """
        INSERT INTO Applications (job_id, resume_json, resume_html, status)
        VALUES (?, ?, ?, ?)
        RETURNING id;
        """
        result = self.conn.execute(query, (job_id, resume_json, resume_html, status)).fetchone()
        self.update_job_status(job_id, 'ready')
        return result[0]

    def mark_application_applied(self, app_id):
        self.conn.execute("UPDATE Applications SET status = 'applied', applied_date = CURRENT_TIMESTAMP WHERE id = ?", (app_id,))
        job_id = self.conn.execute("SELECT job_id FROM Applications WHERE id = ?", (app_id,)).fetchone()
        if job_id:
            self.update_job_status(job_id[0], 'applied')

    def get_unevaluated_jobs(self):
        query = "SELECT id, title, company, description FROM Jobs WHERE status = 'scraped'"
        return self.conn.execute(query).fetchall()

    def get_evaluated_jobs_for_application(self, min_score=70):
        query = """
        SELECT j.id, j.title, j.company, j.description, j.url
        FROM Jobs j
        WHERE j.status = 'evaluated' AND j.match_score >= ?
        AND j.id NOT IN (SELECT job_id FROM Applications)
        """
        return self.conn.execute(query, (min_score,)).fetchall()

    def get_ready_applications(self):
        query = """
        SELECT
            a.id as app_id,
            j.id as job_id,
            j.title,
            j.company,
            j.url,
            j.salary_range,
            j.match_score,
            j.match_reasoning,
            a.resume_json,
            a.resume_html,
            a.status as app_status,
            j.status as job_status
        FROM Applications a
        JOIN Jobs j ON a.job_id = j.id
        ORDER BY j.match_score DESC
        """
        return self.conn.execute(query).fetchdf()

    def get_all_jobs(self):
        return self.conn.execute("SELECT * FROM Jobs").fetchdf()

    def close(self):
        self.conn.close()
