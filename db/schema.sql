-- DuckDB Schema Definition for Autonomous Job Applicant
-- Sequences
CREATE SEQUENCE IF NOT EXISTS seq_job_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_app_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_timeline_id START 1;

-- Jobs Table: Multi-source job listings with comprehensive metadata & deduplication
CREATE TABLE IF NOT EXISTS Jobs (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_job_id'),
    platform VARCHAR NOT NULL,
    job_id_on_platform VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    company VARCHAR NOT NULL,
    location VARCHAR,
    url VARCHAR,
    description VARCHAR,
    salary VARCHAR,
    salary_range VARCHAR,
    remote_level VARCHAR,
    skills VARCHAR,
    skills_required VARCHAR,
    match_score INTEGER,
    match_reasoning VARCHAR,
    evaluation_details VARCHAR,
    status VARCHAR DEFAULT 'scraped',
    date_posted VARCHAR,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_job_id ON Jobs(platform, job_id_on_platform);

-- Applications Table: Full lifecycle tracking, interview scheduling, tailored resumes & notes
CREATE TABLE IF NOT EXISTS Applications (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_app_id'),
    job_id INTEGER REFERENCES Jobs(id),
    applied_date TIMESTAMP,
    applied_at TIMESTAMP,
    resume_json VARCHAR,
    resume_html VARCHAR,
    status VARCHAR DEFAULT 'Ready to Apply',
    interview_date TIMESTAMP,
    follow_up_date TIMESTAMP,
    notes VARCHAR,
    history VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_job_id ON Applications(job_id);

-- ApplicationTimeline Table: Granular audit trail for stage transitions and user notes
CREATE TABLE IF NOT EXISTS ApplicationTimeline (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_timeline_id'),
    application_id INTEGER REFERENCES Applications(id),
    stage VARCHAR NOT NULL,
    note VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
