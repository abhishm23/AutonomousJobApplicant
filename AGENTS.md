# AGENTS.md — Non-obvious Learnings

## DuckDB Quirks
- `RETURNING` + `ON CONFLICT DO NOTHING` is broken in DuckDB 1.0.0: returns next sequence value even for conflicts. Check `rowcount` instead.
- NaN from DuckDB: unevaluated `match_score` returns `float('nan')`. Never `int()` on raw score — use `math.isnan()` first.

## Scraper-Specific Pitfalls
- **WeWorkRemotely** returns RSS/XML, not HTML. Parse with `xml.etree.ElementTree`.
- **Himalayas API** uses camelCase: `companyName`, `applicationLink`, `minSalary`, `maxSalary`.
- **LinkedIn** blocks scrapers. Avoid without Playwright.
- **Wellfound** has minimal HTML — only `a[href*="/jobs/"]` links are reliable. Company names in `img[alt*="company logo"]`.
- **Adzuna** requires API auth (403 without). Use Himalayas instead.
- Best free sources: **RemoteOK** and **Remotive**.

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
