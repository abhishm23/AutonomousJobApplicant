# AGENTS.md — Non-obvious Learnings

## DuckDB Quirks
- `RETURNING` + `ON CONFLICT DO NOTHING` is broken in DuckDB 1.0.0: returns next sequence value even for conflicts. Check `rowcount` instead.
- NaN from DuckDB: unevaluated `match_score` returns `float('nan')`. Never `int()` on raw score — use `math.isnan()` first.

## Scraper-Specific Pitfalls
- **WeWorkRemotely & RemoteOK**: Do NOT use or scrape RemoteOK or WeWorkRemotely as they require paid subscriptions. Use Himalayas, Remotive, LinkedIn, Naukri, Hirist, and Wellfound instead.
- **Himalayas API** uses camelCase: `companyName`, `applicationLink`, `minSalary`, `maxSalary`.
- **LinkedIn, Naukri, Hirist & Wellfound**: Use persistent browser context with Playwright to preserve authenticated login cookies and avoid anti-bot blocks.
- **Adzuna** requires API auth (403 without). Use Himalayas instead.

## Job Ingestion & Deduplication
- **Deduplication & Primary Key**: Always track jobs by `job_id` / platform composite key. Never re-surface jobs that have already been marked as `applied`.
- **Sorting**: Display and evaluate jobs in reverse chronological order (newest first).
- **Fault-Tolerant Scraping**: Individual scraper failures must degrade gracefully, allowing the pipeline to proceed without terminating.

## Resume Parsing
- PDF section headers vary wildly. Maintain a broad header list.
- Pipe-delimited format (`Company | Role Dates | Location`) is common. Always try pipe-split first.

## Streamlit Specifics
- `st.link_button()` does NOT accept `key=` in Streamlit 1.36.0.
- `asyncio.run()` is safe in Streamlit's synchronous context.
- Dashboard must add project root to `sys.path` for imports.

## Architecture Notes
- Monolithic pipeline: scrape → evaluate → tailor sequentially. Blocks UI.
- Resume parser regex is fragile. Gemini can replace it.
- Canonical schema: `{ personal_info, experience, skills, education, summary, certifications }`.

