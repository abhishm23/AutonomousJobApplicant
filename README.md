# Autonomous Job Applicant 🎯🤖

> **An end-to-end, autonomous multi-portal job harvesting, intelligent resume tailoring, and automated web application submission agent with real-time telemetry.**

---

## 🌟 Overview

**Autonomous Job Applicant** automates the entire lifecycle of software engineering and analytics job hunting. It eliminates manual job-board scouring, custom resume editing, and tedious application form filling by coupling concurrent web scrapers with autonomous LLM evaluation and headless Playwright browser automation.

```
+-----------------------------------------------------------------------------------+
|                            AUTONOMOUS ARCHITECTURE                                |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  [ Multi-Portal Scrapers ]                                                        |
|   ├── LinkedIn Scraper                                                            |
|   ├── Naukri Scraper          Concurrent ThreadPoolExecutor                       |
|   ├── Wellfound Scraper  ───────────────────────────────►  [ SQLite / DuckDB ]   |
|   ├── Hirist Scraper                                                │             |
|   ├── Himalayas Scraper                                             │             |
|   └── Remotive Scraper                                              │             |
|                                                                     ▼             |
|  [ Streamlit Control Hub ]  ◄───────────────────────────  [ Evaluator Agent ]     |
|   ├── Live Job Feed                                       (JD Match Scoring &     |
|   ├── Candidate Profile Editor                             Skills Gap Analysis)   |
|   └── Application Tracker                                           │             |
|                                                                     ▼             |
|  [ Playwright Runner ]  ◄───  [ PDF / HTML Resume ]  ◄──  [ Resume Tailor Agent ] |
|   (Automated Web Apply)       (Dynamic ATS Output)        (JD Keyword Infusion)   |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

---

## ✨ Key Features

1. **Concurrent Multi-Portal Scraper Suite (`scraper/`)**:
   - High-throughput parallel scraping across **LinkedIn**, **Naukri**, **Wellfound (AngelList)**, **Hirist**, **Himalayas**, and **Remotive**.
   - Built on resilient `ThreadPoolExecutor` workers with individual timeouts (25s), request retry headers, and strict normalized data schemas.

2. **Intelligent Match Evaluation (`agents/evaluator_agent.py`)**:
   - Parses incoming Job Descriptions and scores alignment against your master candidate profile.
   - Generates match confidence scores (0-100%), identifies missing critical skills, and flags senior/staff level qualification hurdles.

3. **Autonomous Resume Tailoring (`agents/resume_tailor_agent.py`)**:
   - Dynamically adapts resume bullet points to mirror JD vocabulary and ATS keywords without hallucinating false credentials.
   - Compiles ATS-safe, clean HTML and PDF resumes on the fly.

4. **Interactive Mission Control Dashboard (`dashboard/app.py`)**:
   - Full-featured Streamlit UI for reviewing matching jobs, inspecting scores, previewing tailored resumes, and triggering auto-apply workflows.

5. **Persistent Session & Browser Automation (`auth_login.py`)**:
   - Secure Playwright session manager preserving portal logins and cookies, allowing seamless automated submissions.

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.10+
- Chrome / Chromium (installed via Playwright)

### 2. Installation
```bash
git clone https://github.com/abhishm23/AutonomousJobApplicant.git
cd AutonomousJobApplicant
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 3. Configuration
Create a `.env` file in the root directory:
```env
DB_PATH=data/jobs.db
GEMINI_API_KEY=your_gemini_api_key_here
USER_DATA_DIR=data/browser_user_data
```

### 4. Running the Dashboard
```bash
streamlit run dashboard/app.py
```
Or simply double-click `start.bat`.

---

## 🛠️ Tech Stack & Open Source Credits

We gratefully acknowledge the following open-source frameworks and libraries:

- **[Streamlit](https://streamlit.io/)** — Interactive analytics & control dashboard.
- **[Playwright](https://playwright.dev/)** — Resilient cross-browser web automation and application submission.
- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) & [Requests](https://requests.readthedocs.io/)** — Fast DOM parsing and HTTP scraping.
- **[SQLite3](https://www.sqlite.org/) & [DuckDB](https://duckdb.org/)** — High-performance local storage and analytical querying.
- **[Pydantic](https://docs.pydantic.dev/)** — Strict data contract enforcement across job pipelines.
- **[Google Gemini API](https://ai.google.dev/)** — LLM evaluation and resume contextual adaptation.

---

## 👥 Authors & Contributors

- **Author:** [Abhishek Mishra](https://github.com/abhishm23) — *Senior Analytics & GenAI Engineer*
- **Co-Developer / AI Pair Programmer:** [Google Antigravity](https://antigravity.google/)
