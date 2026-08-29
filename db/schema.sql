CREATE SEQUENCE IF NOT EXISTS seq_job_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_app_id START 1;

CREATE TABLE IF NOT EXISTS Jobs (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_job_id'),
    platform VARCHAR,
    job_id_on_platform VARCHAR,
    title VARCHAR,
    company VARCHAR,
    description VARCHAR,
    url VARCHAR,
    salary_range VARCHAR,
    remote_level VARCHAR,
    skills_required VARCHAR,
    match_score INTEGER,
    match_reasoning VARCHAR,
    status VARCHAR DEFAULT 'scraped',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Applications (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_app_id'),
    job_id INTEGER REFERENCES Jobs(id),
    applied_date TIMESTAMP,
    resume_json VARCHAR,
    resume_html VARCHAR,
    status VARCHAR DEFAULT 'ready',
    notes VARCHAR
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_job_id ON Jobs(platform, job_id_on_platform);
