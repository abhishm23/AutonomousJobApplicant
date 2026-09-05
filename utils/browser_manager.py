"""
Centralized Playwright Persistent Context and Browser Session Manager.

Manages persistent browser sessions in data/browser_user_data for authenticated
direct portal access (LinkedIn, Naukri, Wellfound, Hirist). Provides anti-detection
flags, interactive login launchers, cookie/session detection, and clean context closing.
"""

import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

# Base project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_USER_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "browser_user_data")

# Default anti-detection browser configuration
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_VIEWPORT = {"width": 1280, "height": 900}

DEFAULT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
]

DEFAULT_IGNORE_DEFAULT_ARGS = ["--enable-automation"]

# Supported portal login URLs
PORTAL_LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "naukri": "https://www.naukri.com/nlogin/login",
    "wellfound": "https://wellfound.com/login",
    "hirist": "https://www.hirist.tech/login",
    "indeed": "https://secure.indeed.com/account/login",
}

# Domain patterns associated with supported portals for session verification
PORTAL_DOMAINS = {
    "linkedin": ["linkedin.com", ".linkedin.com", "www.linkedin.com"],
    "naukri": ["naukri.com", ".naukri.com", "www.naukri.com"],
    "wellfound": ["wellfound.com", ".wellfound.com", "angel.co", ".angel.co"],
    "hirist": ["hirist.tech", ".hirist.tech", "hirist.com", ".hirist.com"],
    "indeed": ["indeed.com", ".indeed.com", "www.indeed.com"],
}


class BrowserManager:
    """
    Centralized manager for Playwright persistent browser contexts,
    authentication sessions, and portal interactions.
    """

    USER_DATA_DIR = DEFAULT_USER_DATA_DIR

    @classmethod
    def get_user_data_dir(cls, custom_dir: Optional[str] = None) -> str:
        """
        Returns the resolved absolute path to the user data directory.
        Creates the directory if it does not exist.
        """
        dir_path = os.path.abspath(custom_dir) if custom_dir else os.path.abspath(cls.USER_DATA_DIR)
        os.makedirs(dir_path, exist_ok=True)
        return dir_path

    @classmethod
    def get_supported_portals(cls) -> List[str]:
        """Returns a list of supported portal identifiers."""
        return list(PORTAL_LOGIN_URLS.keys())

    @classmethod
    def get_login_url(cls, portal: str) -> str:
        """
        Returns the login URL for the specified portal.
        Raises ValueError if portal is unsupported or unknown.
        """
        key = portal.strip().lower()
        if key in PORTAL_LOGIN_URLS:
            return PORTAL_LOGIN_URLS[key]
        supported = ", ".join(cls.get_supported_portals())
        raise ValueError(f"Unknown or unsupported portal '{portal}'. Supported portals: {supported}")

    @classmethod
    def inject_stealth(cls, target: Any) -> None:
        """
        Injects stealth scripts to evade basic automated bot detection.
        Compatible with Page or BrowserContext objects.
        """
        script = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """
        try:
            if hasattr(target, "add_init_script"):
                target.add_init_script(script)
        except Exception as e:
            logger.debug(f"[BrowserManager] Failed to inject stealth script: {e}")

    @classmethod
    def get_persistent_context(
        cls,
        playwright: Any,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        user_agent: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
        args: Optional[List[str]] = None,
        ignore_default_args: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Initializes and returns a Playwright persistent BrowserContext configured with
        anti-detection flags and user-data persistence.
        """
        target_dir = cls.get_user_data_dir(user_data_dir)
        ua = user_agent or DEFAULT_USER_AGENT
        vp = viewport or DEFAULT_VIEWPORT
        browser_args = list(DEFAULT_ARGS) if args is None else list(args)
        ign_args = (
            list(DEFAULT_IGNORE_DEFAULT_ARGS)
            if ignore_default_args is None
            else list(ignore_default_args)
        )

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=target_dir,
                headless=headless,
                user_agent=ua,
                viewport=vp,
                args=browser_args,
                ignore_default_args=ign_args,
                **kwargs,
            )
            cls.inject_stealth(context)
            return context
        except Exception as err:
            err_str = str(err).lower()
            if (
                "singletonlock" in err_str
                or "directory is already in use" in err_str
                or "process singleton" in err_str
            ):
                logger.error(
                    f"[BrowserManager] User data directory locked: {target_dir}. "
                    f"Ensure any running browser instances are closed. Error: {err}"
                )
                raise RuntimeError(
                    f"Browser user data directory is locked by another instance: {err}"
                ) from err
            logger.error(f"[BrowserManager] Failed to launch persistent context: {err}")
            raise

    @classmethod
    @contextmanager
    def persistent_context(
        cls,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        **kwargs: Any,
    ) -> Generator[Any, None, None]:
        """
        Context manager for automatically acquiring and closing a persistent Playwright context.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run `pip install playwright && playwright install chromium`."
            )

        with sync_playwright() as p:
            context = cls.get_persistent_context(
                p, headless=headless, user_data_dir=user_data_dir, **kwargs
            )
            try:
                yield context
            finally:
                try:
                    context.close()
                except Exception as e:
                    logger.debug(f"[BrowserManager] Error closing context: {e}")

    @classmethod
    def _find_cookie_db_files(cls, user_data_dir: str) -> List[str]:
        """Scans user_data_dir for SQLite cookie database files."""
        candidates = [
            os.path.join(user_data_dir, "Default", "Network", "Cookies"),
            os.path.join(user_data_dir, "Default", "Cookies"),
            os.path.join(user_data_dir, "Network", "Cookies"),
            os.path.join(user_data_dir, "Cookies"),
        ]
        found = [p for p in candidates if os.path.isfile(p)]
        if not found:
            for root, _, files in os.walk(user_data_dir):
                for f in files:
                    if f.lower() == "cookies" or f.lower().endswith(".cookies"):
                        full_p = os.path.join(root, f)
                        if full_p not in found:
                            found.append(full_p)
        return found

    @classmethod
    def has_session_for_portal(
        cls, portal: str, user_data_dir: Optional[str] = None
    ) -> bool:
        """
        Checks if persistent storage contains valid cookies or active session records for the portal.
        Supports SQLite cookie databases and JSON storage state files.
        """
        target_dir = os.path.abspath(user_data_dir) if user_data_dir else os.path.abspath(cls.USER_DATA_DIR)
        if not os.path.exists(target_dir) or not os.listdir(target_dir):
            return False

        key = portal.strip().lower()
        domains = PORTAL_DOMAINS.get(key, [f"%{key}%"])

        # 1. Check storage_state.json or portal-specific state file
        json_candidates = [
            os.path.join(target_dir, "storage_state.json"),
            os.path.join(target_dir, f"storage_state_{key}.json"),
            os.path.join(target_dir, "cookies.json"),
        ]
        for json_path in json_candidates:
            if os.path.isfile(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    cookies = data.get("cookies", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for cookie in cookies:
                        domain = cookie.get("domain", "").lower()
                        for d in domains:
                            if d.lstrip(".").lower() in domain:
                                return True
                except Exception as e:
                    logger.debug(f"[BrowserManager] Error reading JSON state {json_path}: {e}")

        # 2. Check Chromium SQLite Cookie databases
        db_files = cls._find_cookie_db_files(target_dir)
        for db_file in db_files:
            # First attempt: URI read-only query
            try:
                norm_db_path = os.path.abspath(db_file).replace("\\", "/")
                uri = f"file:{norm_db_path}?mode=ro&immutable=1"
                conn = sqlite3.connect(uri, uri=True, timeout=1.0)
                try:
                    cursor = conn.cursor()
                    for d in domains:
                        query_pattern = f"%{d.lstrip('.')}%"
                        cursor.execute("SELECT count(*) FROM cookies WHERE host_key LIKE ?", (query_pattern,))
                        row = cursor.fetchone()
                        if row and row[0] > 0:
                            return True
                finally:
                    conn.close()
            except Exception:
                # Fallback: copy to temporary file and query (prevents locked database errors)
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp_file:
                        tmp_path = tmp_file.name
                    with open(db_file, "rb") as src, open(tmp_path, "wb") as dst:
                        dst.write(src.read())
                    conn = sqlite3.connect(tmp_path, timeout=1.0)
                    try:
                        cursor = conn.cursor()
                        for d in domains:
                            query_pattern = f"%{d.lstrip('.')}%"
                            cursor.execute("SELECT count(*) FROM cookies WHERE host_key LIKE ?", (query_pattern,))
                            row = cursor.fetchone()
                            if row and row[0] > 0:
                                return True
                    finally:
                        conn.close()
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                except Exception as e:
                    logger.debug(f"[BrowserManager] SQLite query failed on {db_file}: {e}")

        return False

    @classmethod
    def get_session_status_all(
        cls, user_data_dir: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Returns a dictionary summarizing authentication status across all supported portals.
        """
        statuses = {}
        for portal in cls.get_supported_portals():
            statuses[portal] = {
                "portal": portal,
                "login_url": cls.get_login_url(portal),
                "has_session": cls.has_session_for_portal(portal, user_data_dir=user_data_dir),
            }
        return statuses

    @classmethod
    def launch_interactive_login(
        cls,
        portal: str,
        timeout_seconds: int = 300,
        on_ready_callback: Optional[Callable[[Any, Any], None]] = None,
        user_data_dir: Optional[str] = None,
    ) -> bool:
        """
        Launches a headful browser session pointing to the portal login URL.
        Allows the user to complete login, OTP, 2FA, or CAPTCHA manually.
        Saves session cookies and profile data into user_data_dir.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run `pip install playwright && playwright install chromium`."
            )

        login_url = cls.get_login_url(portal)
        target_dir = cls.get_user_data_dir(user_data_dir)

        logger.info(f"[BrowserManager] Launching interactive login for '{portal}' -> {login_url}")
        logger.info(f"[BrowserManager] Using persistent directory: {target_dir}")

        with sync_playwright() as p:
            context = cls.get_persistent_context(
                p,
                headless=False,
                user_data_dir=target_dir,
                viewport={"width": 1280, "height": 900},
            )
            page = context.pages[0] if context.pages else context.new_page()

            try:
                page.goto(login_url, timeout=30000, wait_until="domcontentloaded")

                if on_ready_callback is not None:
                    on_ready_callback(page, context)
                else:
                    # Interactive terminal guidance
                    print("\n" + "=" * 64)
                    print(f"[AUTH LOGIN] Interactive Login: {portal.upper()}")
                    print(f"URL: {login_url}")
                    print(f"Storage: {target_dir}")
                    print("=" * 64)
                    print("1. Complete your login credentials, OTP / 2FA, and CAPTCHA in the opened window.")
                    print("2. Navigate to your homepage / dashboard.")
                    print("-" * 64)

                    if sys.stdin.isatty():
                        try:
                            input("Press [ENTER] here once you have successfully logged in...")
                        except (EOFError, KeyboardInterrupt):
                            logger.info("[BrowserManager] Interactive prompt cancelled by user.")
                    else:
                        logger.info(
                            f"[BrowserManager] Non-interactive mode detected. Waiting {min(timeout_seconds, 15)}s for page operations..."
                        )
                        page.wait_for_timeout(min(timeout_seconds, 15) * 1000)

                # Persist storage state snapshot
                try:
                    state_path = os.path.join(target_dir, f"storage_state_{portal.strip().lower()}.json")
                    context.storage_state(path=state_path)
                    logger.info(f"[BrowserManager] Saved storage state snapshot to {state_path}")
                except Exception as e:
                    logger.debug(f"[BrowserManager] Could not export storage_state snapshot: {e}")

                return True
            finally:
                try:
                    context.close()
                except Exception as e:
                    logger.debug(f"[BrowserManager] Context close error: {e}")


@contextmanager
def get_browser_context(
    headless: bool = True, user_data_dir: Optional[str] = None, **kwargs: Any
) -> Generator[Any, None, None]:
    """
    Convenience standalone context manager yielding a persistent Playwright browser context.
    """
    with BrowserManager.persistent_context(
        headless=headless, user_data_dir=user_data_dir, **kwargs
    ) as context:
        yield context
