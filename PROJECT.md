# Project Specification: Autonomous Job Applicant Refactor & Upgrade

## Architecture
- **Scraper Layer (`scraper/`)**: Modular scrapers (`base_scraper.py`, `himalayas_scraper.py`, `remotive_scraper.py`, `linkedin_scraper.py`, `naukri_scraper.py`, `wellfound_scraper.py`, `hirist_scraper.py`) coordinated by `multi_scraper.py` using concurrent `ThreadPoolExecutor` execution, 25s per-scraper timeouts, normalized job data contracts, and complete error isolation.
- **Persistent Browser & Session Layer (`utils/browser_manager.py`, `auth_login.py`)**: Centralized Playwright persistent context management pointing to `data/browser_user_data`. Supports interactive CLI login (`auth_login.py --portal <name>`), non-blocking UI browser launcher, and automatic session reuse for headless scrapers.
- **Database & Storage Layer (`db/database.py`, `db/schema.sql`, `data/jobs.duckdb`)**: DuckDB storage engine with composite key deduplication `(platform, job_id_on_platform)` + SHA-256 fallback, reverse-chronological sorting, strict exclusion of applied jobs from active views, DuckDB 1.0.0 quirk guards (NaN handling, explicit duplicate checking), and audit timeline logging.
- **Agent Intelligence Layer (`agents/evaluator_agent.py`, `agents/resume_tailor_agent.py`, `agents/resume_parser.py`)**: Google GenAI integration for scoring and tailoring resumes against job descriptions.
- **Application Tracking Console & UI Layer (`dashboard/app.py`)**: Streamlit application featuring 6-stage Kanban board (`Ready to Apply`, `Applied`, `Reply Received`, `Interview Scheduled`, `Rejected`, `Offer`), filterable sortable data table, recruiter notes & interview scheduling logger, manual login launcher, and real-time pipeline status.
- **End-to-End Orchestrator (`orchestrator.py`)**: Master coordinator orchestrating scraping, deduplication, scoring, tailoring, stage transitions, and session management.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Paywall Elimination | Completely deprecate and remove RemoteOK and WeWorkRemotely scrapers and UI badges | M1 | ORIGINAL_REQUEST R1 [DONE] |
| 2 | Direct Scraper Integration | Implement/upgrade scrapers for LinkedIn, Naukri, Wellfound, Hirist, Himalayas, Remotive | M1 | ORIGINAL_REQUEST R1 [DONE] |
| 3 | Scraper Error Isolation | Wrap scraper runs in ThreadPoolExecutor with timeouts, normalization, and per-portal error guards | M1 | ORIGINAL_REQUEST R1 [DONE] |
| 4 | Stale Data Purging | Purge stale mock/test records (especially RemoteOK/WeWorkRemotely) from DuckDB | M2 | ORIGINAL_REQUEST R2 [DONE] |
| 5 | Composite Key Deduplication | Implement (platform, job_id_on_platform) composite key + SHA-256 fallback with explicit is_new checking | M2 | ORIGINAL_REQUEST R2 [DONE] |
| 6 | Reverse Chronological Sorting | Enforce newest-first sorting across all job queries | M2 | ORIGINAL_REQUEST R2 [DONE] |
| 7 | Strict Applied Job Exclusion | Exclude applied/processed jobs from active evaluation and "Ready to Apply" views | M2 | ORIGINAL_REQUEST R2 [DONE] |
| 8 | Persistent Context Management | Implement Playwright persistent browser context in `data/browser_user_data` | M3 | ORIGINAL_REQUEST R3 [DONE] |
| 9 | Auth Login CLI Utility | Create `auth_login.py --portal <name>` for manual login / OTP sessions | M3 | ORIGINAL_REQUEST R3 [DONE] |
| 10 | Dashboard Login Launcher | Add non-blocking "Launch Login Browser" button and session status indicator to Streamlit UI | M3 | ORIGINAL_REQUEST R3 [DONE] |
| 11 | Headless Session Reuse | Automatically load stored persistent cookies/tokens during scraping and auto-fill | M3 | ORIGINAL_REQUEST R3 [DONE] |
| 12 | 6-Stage Kanban Pipeline | Build visual Kanban board with 6 lifecycle stages and quick stage advancement | M4 | ORIGINAL_REQUEST R4 [DONE] |
| 13 | Filterable Application Table | Search, sort, and filter applications with match slider and quick stage dropdowns | M4 | ORIGINAL_REQUEST R4 [DONE] |
| 14 | Recruiter Notes & Timeline | Record notes, interview timestamps, reminders, and chronological history logs in DuckDB | M4 | ORIGINAL_REQUEST R4 [DONE] |
| 15 | Unified Pipeline Orchestration | Integrate multi_scraper, database, persistent sessions, agents, and dashboard into cohesive flow | M5 | ORIGINAL_REQUEST R5 [DONE] |
| 16 | End-to-End Verification | Comprehensive testing across Tiers 1-5, verifying all acceptance criteria and integrity | M6 | ORIGINAL_REQUEST Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Scraper Streamlining & Paywall Elimination | Remove RemoteOK/WeWorkRemotely, implement 6 free direct scrapers, add ThreadPool isolation | none | DONE |
| M2 | Database Schema, Purging & Deduplication | Purge stale data, update schema, composite key dedup, newest-first sort, applied exclusion | none | DONE |
| M3 | Persistent Authenticated Browser Sessions | Playwright persistent context, auth_login.py CLI, UI login launcher, session reuse | M1 | DONE |
| M4 | Application Tracking Console & Stage Progression | 6-stage Kanban board, filterable data table, notes/interview scheduling in Streamlit | M2 | DONE |
| M5 | Pipeline Orchestration & End-to-End Integration | Connect multi_scraper, database, persistent sessions, agents, and UI into unified flow | M1, M2, M3, M4 | DONE |
| M6 | E2E Testing & Acceptance Verification | Opaque-box + white-box testing, adversarial coverage hardening, AC sign-off | M5 | IN_PROGRESS |

## Interface Contracts

### Scraper Module Contract (`scraper/base_scraper.py` & scrapers)
```python
class BaseScraper(ABC):
    @abstractmethod
    def scrape_jobs(self, keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]: ...
```

### Database Module Contract (`db/database.py`)
```python
class Database:
    def __init__(self, db_path: str = "data/jobs.duckdb"): ...
    def purge_deprecated_platforms(self) -> int: ...
    def reset_database(self) -> None: ...
    def insert_job(self, job_dict: Dict[str, Any]) -> Tuple[int, bool]:
        """Returns (job_id, is_new: bool)"""
        ...
    def get_unevaluated_jobs(self, limit: int = 50) -> List[Dict[str, Any]]: ...
    def get_all_jobs(self, sort_desc: bool = True) -> List[Dict[str, Any]]: ...
    def update_job_score(self, job_id: int, match_score: int, evaluation_details: Dict) -> None: ...
    def insert_application(self, job_id: int, resume_json: str, resume_html: str, status: str = "Ready to Apply") -> int: ...
    def update_application_stage(self, app_id: int, new_stage: str, note: Optional[str] = None) -> bool: ...
    def update_application_notes(self, app_id: int, notes: str, interview_date: Optional[str] = None, recruiter_info: Optional[str] = None) -> bool: ...
    def get_kanban_applications(self) -> Dict[str, List[Dict[str, Any]]]: ...
    def get_all_applications_table(self) -> List[Dict[str, Any]]: ...
    def is_job_applied(self, job_id: int) -> bool: ...
```

### Browser Manager Contract (`utils/browser_manager.py`)
```python
class BrowserManager:
    USER_DATA_DIR = r"c:\AutonomousJobApplicant\data\browser_user_data"
    
    @classmethod
    def get_persistent_context(cls, playwright_instance, headless: bool = True): ...
    @classmethod
    def launch_interactive_login(cls, portal: str) -> None: ...
    @classmethod
    def has_session_for_portal(cls, portal: str) -> bool: ...
```

## Code Layout
- `scraper/`:
  - `base_scraper.py`: Abstract scraper class
  - `multi_scraper.py`: Coordinator with ThreadPoolExecutor and error isolation
  - `himalayas_scraper.py`: Himalayas REST scraper
  - `remotive_scraper.py`: Remotive REST scraper
  - `linkedin_scraper.py`: LinkedIn guest API + persistent Playwright scraper
  - `naukri_scraper.py`: Naukri persistent Playwright scraper
  - `wellfound_scraper.py`: Wellfound persistent Playwright scraper
  - `hirist_scraper.py`: Hirist category scraper
- `db/`:
  - `schema.sql`: Enhanced DDL schema
  - `database.py`: DuckDB operations with deduplication, sorting, and state tracking
- `utils/`:
  - `browser_manager.py`: Persistent Playwright context and cookie manager
- `agents/`:
  - `evaluator_agent.py`: Match score evaluator
  - `resume_tailor_agent.py`: Resume customizer
  - `resume_parser.py`: Resume extractor
- `dashboard/`:
  - `app.py`: Streamlit UI with 6-stage Kanban, filterable table, notes logger, and auth launcher
- `auth_login.py`: Standalone CLI utility for manual login / OTP
- `orchestrator.py`: Top-level pipeline orchestrator
- `tests/`:
  - Comprehensive unit, integration, and E2E test suites
