"""
Empirical Adversarial Stress-Testing & Verification Harness for Milestone 3 (M3).
Authored by: Challenger 1 (Empirical Challenger).

Tests 5 Critical Dimensions:
1. Session Detection Invariants under File System Adversity & Corruption (Corrupted SQLite DBs, malformed JSON states, locked files, SQL injection, schema drift)
2. Live Playwright Persistent Browser Execution & Anti-Bot Stealth Invariants (navigator.webdriver === undefined, window.chrome.runtime, navigation persistence, custom UA/viewport)
3. Concurrency, Multi-Threading, and Browser Process Lock Contention (SingletonLock handling, lock release & re-acquisition, thread safety)
4. CLI Utility (auth_login.py) Argument Parsing, Flag Combinations, Exit Codes, Output Contracts, and Non-Interactive Degradation
5. End-to-End Session Export, Multi-Domain Matching Invariants, and Portal Lifecycle Verification
"""

import concurrent.futures
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import sync_playwright

import auth_login
from auth_login import (
    CORE_PORTALS,
    build_parser,
    check_status,
    list_portals,
    main,
    run_login_all,
    run_login_for_portal,
)
from utils.browser_manager import (
    DEFAULT_ARGS,
    DEFAULT_IGNORE_DEFAULT_ARGS,
    DEFAULT_USER_AGENT,
    DEFAULT_USER_DATA_DIR,
    DEFAULT_VIEWPORT,
    PORTAL_DOMAINS,
    PORTAL_LOGIN_URLS,
    BrowserManager,
    get_browser_context,
)


class TestSessionDetectionAdversarialCorruptedStorage(unittest.TestCase):
    """
    Dimension 1: Session Detection Resilience under File System Corruption,
    Schema Drift, Empty/Truncated Files, OS File Locks, and SQL Injections.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_empirical_m3_corrupt_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_and_nonexistent_directory(self):
        """Verify has_session_for_portal returns False for non-existent and empty directories."""
        non_existent = os.path.join(self.temp_dir, "non_existent_folder")
        for portal in BrowserManager.get_supported_portals():
            self.assertFalse(
                BrowserManager.has_session_for_portal(portal, user_data_dir=non_existent),
                f"Expected False for non-existent folder on portal {portal}",
            )

        empty_folder = os.path.join(self.temp_dir, "empty_folder")
        os.makedirs(empty_folder, exist_ok=True)
        for portal in BrowserManager.get_supported_portals():
            self.assertFalse(
                BrowserManager.has_session_for_portal(portal, user_data_dir=empty_folder),
                f"Expected False for empty folder on portal {portal}",
            )

    def test_corrupted_json_state_files(self):
        """Empirically test zero-byte, truncated, binary garbage, and malformed JSON state files."""
        corrupted_cases = [
            ("storage_state.json", b""),  # 0-byte file
            ("storage_state_linkedin.json", b"{ invalid json string ::: "),  # Syntax error
            ("storage_state_naukri.json", b"\x00\xff\xfe\x00\x12\x34\x56\x78"),  # Binary garbage
            ("cookies.json", b"null"),  # JSON null
            ("storage_state.json", b"42"),  # JSON integer
            ("storage_state.json", b"\"just a string\""),  # JSON string
            ("storage_state.json", b"[]"),  # Empty array
            ("storage_state.json", b"[1, 2, 3, null, false]"),  # Array of primitives
            ("storage_state.json", b"{\"cookies\": null}"),  # cookies = None
            ("storage_state.json", b"{\"cookies\": \"not a list\"}"),  # cookies is string
            ("storage_state.json", b"{\"cookies\": [null, 123, true, \"abc\"]}"),  # invalid cookie items
            ("storage_state.json", b"{\"cookies\": [{\"domain\": 12345}]}"),  # domain is not a string
            ("storage_state.json", b"{\"cookies\": [{}]}"),  # cookie missing domain
        ]

        for fname, content in corrupted_cases:
            test_sub_dir = tempfile.mkdtemp(dir=self.temp_dir)
            fpath = os.path.join(test_sub_dir, fname)
            with open(fpath, "wb") as f:
                f.write(content)

            # Must degrade gracefully to False without raising exceptions
            for portal in ["linkedin", "naukri", "wellfound", "hirist", "indeed"]:
                result = BrowserManager.has_session_for_portal(portal, user_data_dir=test_sub_dir)
                self.assertFalse(
                    result,
                    f"Expected False for corrupted JSON file '{fname}' with content {content!r} on portal {portal}",
                )

    def test_corrupted_and_truncated_sqlite_databases(self):
        """Empirically test zero-byte, random binary, truncated header, and schema-drifted SQLite DBs."""
        sqlite_paths = [
            os.path.join(self.temp_dir, "Default", "Network", "Cookies"),
            os.path.join(self.temp_dir, "Default", "Cookies"),
            os.path.join(self.temp_dir, "Network", "Cookies"),
            os.path.join(self.temp_dir, "Cookies"),
        ]

        for p in sqlite_paths:
            test_dir = os.path.dirname(p)
            os.makedirs(test_dir, exist_ok=True)

            # 1. Zero-byte file
            with open(p, "wb") as f:
                f.write(b"")
            self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))

            # 2. Random binary garbage
            with open(p, "wb") as f:
                f.write(os.urandom(1024))
            self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))

            # 3. Truncated SQLite header
            with open(p, "wb") as f:
                f.write(b"SQLite format 3\x00truncated bytes")
            self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))

            os.remove(p)

    def test_sqlite_schema_drift_and_missing_tables(self):
        """Verify handling when SQLite database exists but lacks cookies table or host_key column."""
        cookie_db_path = os.path.join(self.temp_dir, "Default", "Network", "Cookies")
        os.makedirs(os.path.dirname(cookie_db_path), exist_ok=True)

        # Database with completely different table
        conn = sqlite3.connect(cookie_db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);")
        conn.execute("INSERT INTO users VALUES (1, 'admin');")
        conn.commit()
        conn.close()

        self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))

        # Database with cookies table but mismatched columns (no host_key)
        os.remove(cookie_db_path)
        conn = sqlite3.connect(cookie_db_path)
        conn.execute("CREATE TABLE cookies (cookie_id INTEGER PRIMARY KEY, val TEXT);")
        conn.execute("INSERT INTO cookies VALUES (1, 'linkedin.com');")
        conn.commit()
        conn.close()

        self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))

    def test_sql_injection_resilience_in_portal_query(self):
        """Empirically test that adversarial portal strings with SQL injection payloads fail safely."""
        cookie_db_path = os.path.join(self.temp_dir, "Default", "Network", "Cookies")
        os.makedirs(os.path.dirname(cookie_db_path), exist_ok=True)

        conn = sqlite3.connect(cookie_db_path)
        conn.execute("CREATE TABLE cookies (host_key TEXT NOT NULL);")
        conn.execute("INSERT INTO cookies (host_key) VALUES ('.example.com');")
        conn.commit()
        conn.close()

        malicious_portals = [
            "' OR '1'='1",
            "'; DROP TABLE cookies; --",
            "linkedin' UNION SELECT 1,2,3 --",
            "%' OR host_key LIKE '%",
        ]

        for injection in malicious_portals:
            # Should safely return False or handle parameterized query properly
            result = BrowserManager.has_session_for_portal(injection, user_data_dir=self.temp_dir)
            self.assertFalse(result, f"Injection '{injection}' should not match unexpected records.")


class TestLivePlaywrightBrowserAndAntiBotStealth(unittest.TestCase):
    """
    Dimension 2: Live Playwright Persistent Browser Execution, Anti-Bot
    Stealth Injections, User Agent Verification, and Viewport Configuration.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_empirical_m3_stealth_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_live_navigator_webdriver_stealth_removal(self):
        """
        Empirically launch real Chromium via BrowserManager and verify:
        1. navigator.webdriver === undefined (NOT true, NOT false)
        2. window.chrome.runtime is an object
        3. Stealth persists across new pages and client navigations.
        """
        with sync_playwright() as p:
            context = BrowserManager.get_persistent_context(
                p,
                headless=True,
                user_data_dir=self.temp_dir,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()

                # Navigate to a real blank page
                page.goto("data:text/html,<html><body><h1>Stealth Test</h1></body></html>")

                # 1. Assert navigator.webdriver is undefined
                webdriver_val = page.evaluate("() => navigator.webdriver")
                self.assertIsNone(
                    webdriver_val,
                    f"navigator.webdriver must evaluate to None/undefined in Python, got {webdriver_val!r}",
                )

                # Verify via JavaScript typeof
                typeof_webdriver = page.evaluate("() => typeof navigator.webdriver")
                self.assertEqual(
                    typeof_webdriver,
                    "undefined",
                    f"typeof navigator.webdriver must be 'undefined', got '{typeof_webdriver}'",
                )

                # 2. Assert window.chrome.runtime exists
                has_chrome_runtime = page.evaluate("() => typeof window.chrome === 'object' && typeof window.chrome.runtime === 'object'")
                self.assertTrue(
                    has_chrome_runtime,
                    "window.chrome.runtime must be defined as an object for Chromium compatibility.",
                )

                # 3. Open a second page in the same context and verify stealth persists
                page2 = context.new_page()
                page2.goto("data:text/html,<html><body><h2>Page 2</h2></body></html>")

                typeof_webdriver_p2 = page2.evaluate("() => typeof navigator.webdriver")
                self.assertEqual(
                    typeof_webdriver_p2,
                    "undefined",
                    "Stealth init script must automatically apply to all newly created pages in context.",
                )
                page2.close()
            finally:
                context.close()

    def test_live_user_agent_and_viewport_configuration(self):
        """Empirically verify default and custom User-Agent and Viewport configurations."""
        # 1. Default configuration
        with sync_playwright() as p:
            ctx = BrowserManager.get_persistent_context(
                p,
                headless=True,
                user_data_dir=self.temp_dir,
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("data:text/html,<html><body></body></html>")

                ua = page.evaluate("() => navigator.userAgent")
                self.assertEqual(ua, DEFAULT_USER_AGENT)

                vp_w = page.evaluate("() => window.innerWidth")
                vp_h = page.evaluate("() => window.innerHeight")
                self.assertEqual(vp_w, DEFAULT_VIEWPORT["width"])
                self.assertEqual(vp_h, DEFAULT_VIEWPORT["height"])
            finally:
                ctx.close()

        # 2. Custom configuration overrides
        custom_dir = os.path.join(self.temp_dir, "custom_profile")
        custom_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutonomousJobApplicantBot/3.0"
        custom_vp = {"width": 1440, "height": 960}

        with sync_playwright() as p:
            ctx_custom = BrowserManager.get_persistent_context(
                p,
                headless=True,
                user_data_dir=custom_dir,
                user_agent=custom_ua,
                viewport=custom_vp,
            )
            try:
                page = ctx_custom.pages[0] if ctx_custom.pages else ctx_custom.new_page()
                page.goto("data:text/html,<html><body></body></html>")

                ua = page.evaluate("() => navigator.userAgent")
                self.assertEqual(ua, custom_ua)

                vp_w = page.evaluate("() => window.innerWidth")
                vp_h = page.evaluate("() => window.innerHeight")
                self.assertEqual(vp_w, custom_vp["width"])
                self.assertEqual(vp_h, custom_vp["height"])
            finally:
                ctx_custom.close()

    def test_persistent_context_manager_lifecycle(self):
        """Empirically test BrowserManager.persistent_context and get_browser_context clean exit."""
        with BrowserManager.persistent_context(headless=True, user_data_dir=self.temp_dir) as ctx:
            self.assertIsNotNone(ctx)
            page = ctx.new_page()
            page.goto("data:text/html,<html><body>Test Lifecycle</body></html>")
            self.assertEqual(page.title(), "")

        # Convenience standalone helper
        with get_browser_context(headless=True, user_data_dir=self.temp_dir) as ctx2:
            self.assertIsNotNone(ctx2)
            page2 = ctx2.new_page()
            page2.goto("data:text/html,<html><body>Test Convenience Helper</body></html>")


class TestConcurrencyAndLockContention(unittest.TestCase):
    """
    Dimension 3: Concurrency, Multithreading, Lock Contention,
    and SingletonLock Detection under Multiple Processes.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_empirical_m3_lock_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persistent_context_singleton_lock_error_translation(self):
        """
        Empirically verify that SingletonLock / Directory in use errors
        from Chromium are intercepted and converted to an informative RuntimeError.
        """
        mock_p = MagicMock()
        mock_p.chromium.launch_persistent_context.side_effect = Exception(
            "Browser error: Process SingletonLock is already held by another process."
        )

        with self.assertRaises(RuntimeError) as exc_info:
            BrowserManager.get_persistent_context(
                mock_p,
                headless=True,
                user_data_dir=self.temp_dir,
            )
        self.assertIn("locked by another instance", str(exc_info.exception).lower())

        # Also test "directory is already in use" variation
        mock_p.chromium.launch_persistent_context.side_effect = Exception(
            "Target page, context or browser has been closed: directory is already in use"
        )
        with self.assertRaises(RuntimeError) as exc_info2:
            BrowserManager.get_persistent_context(
                mock_p,
                headless=True,
                user_data_dir=self.temp_dir,
            )
        self.assertIn("locked by another instance", str(exc_info2.exception).lower())

    def test_consecutive_and_reentrant_persistent_context_lifecycle(self):
        """
        Empirically verify that persistent context can be launched, used to write data,
        closed, and cleanly re-acquired across multiple cycles without corrupting user_data_dir.
        """
        # Cycle 1: Launch and create page
        with sync_playwright() as p:
            ctx1 = BrowserManager.get_persistent_context(
                p,
                headless=True,
                user_data_dir=self.temp_dir,
            )
            page1 = ctx1.new_page()
            page1.goto("data:text/html,<html><body><h1>Cycle 1</h1></body></html>")
            ctx1.add_cookies([{"name": "cycle1", "value": "val1", "domain": ".linkedin.com", "path": "/"}])
            ctx1.storage_state(path=os.path.join(self.temp_dir, "storage_state_linkedin.json"))
            ctx1.close()

        # Verify session is detectable from user_data_dir
        self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))

        # Cycle 2: Re-acquire persistent context in same directory
        with sync_playwright() as p:
            ctx2 = BrowserManager.get_persistent_context(
                p,
                headless=True,
                user_data_dir=self.temp_dir,
            )
            page2 = ctx2.new_page()
            page2.goto("data:text/html,<html><body><h1>Cycle 2</h1></body></html>")
            ctx2.close()

    def test_multithreaded_concurrent_session_status_queries(self):
        """
        Empirically test concurrent reading of session status across 20 worker threads
        while cookies are populated. Ensures no race conditions, SQLite busy locks, or crashes.
        """
        # Create a valid cookie database in Default/Network/Cookies
        cookie_db_path = os.path.join(self.temp_dir, "Default", "Network", "Cookies")
        os.makedirs(os.path.dirname(cookie_db_path), exist_ok=True)
        conn = sqlite3.connect(cookie_db_path)
        conn.execute("CREATE TABLE cookies (host_key TEXT NOT NULL, name TEXT, value TEXT);")
        conn.execute("INSERT INTO cookies VALUES ('.linkedin.com', 'li_at', 'tok_123');")
        conn.execute("INSERT INTO cookies VALUES ('.naukri.com', 'nauk_at', 'tok_456');")
        conn.commit()
        conn.close()

        # Also write a JSON storage state
        json_state_path = os.path.join(self.temp_dir, "storage_state_wellfound.json")
        with open(json_state_path, "w", encoding="utf-8") as f:
            json.dump({"cookies": [{"name": "wf_auth", "domain": "wellfound.com"}]}, f)

        errors = []

        def worker_query(worker_id: int):
            try:
                for _ in range(15):
                    has_li = BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir)
                    has_nk = BrowserManager.has_session_for_portal("naukri", user_data_dir=self.temp_dir)
                    has_wf = BrowserManager.has_session_for_portal("wellfound", user_data_dir=self.temp_dir)
                    has_hir = BrowserManager.has_session_for_portal("hirist", user_data_dir=self.temp_dir)
                    status_all = BrowserManager.get_session_status_all(user_data_dir=self.temp_dir)

                    if not has_li or not has_nk or not has_wf or has_hir:
                        errors.append(f"Worker {worker_id}: Incorrect session flags")
                    if not status_all["linkedin"]["has_session"] or not status_all["wellfound"]["has_session"]:
                        errors.append(f"Worker {worker_id}: Incorrect status_all")
            except Exception as e:
                errors.append(f"Worker {worker_id} exception: {e}")

        threads = [threading.Thread(target=worker_query, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Encountered thread errors during concurrent read: {errors}")


class TestCLIAndAuthLoginAdversarial(unittest.TestCase):
    """
    Dimension 4: CLI Utility (auth_login.py) Argument Parsing, Flag
    Combinations, Exit Codes, Output Formatting, and Batch Sequential Execution.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_empirical_m3_cli_")
        self.parser = build_parser()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_flags_help_and_no_arguments_exit_1(self):
        """Empirically test that running without arguments prints help and returns exit code 1."""
        captured_out = io.StringIO()
        with patch("sys.stdout", new=captured_out):
            code = main([])
        self.assertEqual(code, 1)
        output = captured_out.getvalue()
        self.assertIn("Specify a portal using --portal", output)
        self.assertIn("usage:", output.lower())

    def test_cli_list_flag_exact_portals(self):
        """Empirically test --list flag outputs all 5 supported portals and returns exit code 0."""
        captured_out = io.StringIO()
        with patch("sys.stdout", new=captured_out):
            code = main(["--list"])
        self.assertEqual(code, 0)
        output = captured_out.getvalue()
        for portal in ["linkedin", "naukri", "wellfound", "hirist", "indeed"]:
            self.assertIn(portal.capitalize(), output)
            self.assertIn(PORTAL_LOGIN_URLS[portal], output)

    def test_cli_check_and_status_flags(self):
        """Empirically test --check and alias --status flags return exit code 0 and format table."""
        # Create a mock session for hirist
        json_state = os.path.join(self.temp_dir, "storage_state_hirist.json")
        with open(json_state, "w", encoding="utf-8") as f:
            json.dump({"cookies": [{"domain": ".hirist.tech", "name": "h_tok", "value": "xyz"}]}, f)

        for flag in ["--check", "--status"]:
            captured_out = io.StringIO()
            with patch("sys.stdout", new=captured_out):
                code = main([flag, "--user-data-dir", self.temp_dir])
            self.assertEqual(code, 0)
            output = captured_out.getvalue()
            self.assertIn("Browser Session Status Check", output)
            self.assertIn("Hirist", output)
            self.assertIn("[AUTHENTICATED]", output)
            self.assertIn("Linkedin", output)
            self.assertIn("[NOT LOGGED IN]", output)

    def test_cli_invalid_portal_flag_raises_system_exit_2(self):
        """Empirically test that invalid portal arguments cause argparse to raise SystemExit code 2."""
        with patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                self.parser.parse_args(["--portal", "invalid_portal_xyz"])
            self.assertEqual(cm.exception.code, 2)

    def test_cli_single_portal_login_success_and_failure(self):
        """Empirically test single portal login success (0) and failure (1) paths."""
        with patch("utils.browser_manager.BrowserManager.launch_interactive_login", return_value=True):
            with patch("utils.browser_manager.BrowserManager.has_session_for_portal", return_value=True):
                captured = io.StringIO()
                with patch("sys.stdout", new=captured):
                    code = main(["--portal", "wellfound", "--user-data-dir", self.temp_dir])
                self.assertEqual(code, 0)
                self.assertIn("[SUCCESS] Saved active session for Wellfound", captured.getvalue())

        with patch("utils.browser_manager.BrowserManager.launch_interactive_login", side_effect=Exception("Browser launch failed")):
            captured = io.StringIO()
            with patch("sys.stdout", new=captured):
                code = main(["--portal", "wellfound", "--user-data-dir", self.temp_dir])
            self.assertEqual(code, 1)
            self.assertIn("[ERROR] Login failed: Browser launch failed", captured.getvalue())

    def test_cli_portal_all_batch_execution(self):
        """Empirically test --portal all iterates sequentially across CORE_PORTALS."""
        called_portals = []

        def mock_launch(portal, timeout_seconds=300, user_data_dir=None):
            called_portals.append(portal)
            return True

        with patch("utils.browser_manager.BrowserManager.launch_interactive_login", side_effect=mock_launch):
            with patch("utils.browser_manager.BrowserManager.has_session_for_portal", return_value=True):
                captured = io.StringIO()
                with patch("sys.stdout", new=captured):
                    code = main(["--portal", "all", "--user-data-dir", self.temp_dir])
                self.assertEqual(code, 0)
                self.assertEqual(called_portals, CORE_PORTALS)
                self.assertIn("[DONE] Batch Login Routine Finished.", captured.getvalue())


class TestSessionPersistenceAndMultiDomainMatching(unittest.TestCase):
    """
    Dimension 5: Multi-Domain Cookie Matching, Storage State Snapshots,
    and Full Browser Session Life-Cycle Verification.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_empirical_m3_persistence_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multi_domain_aliases_for_portals(self):
        """
        Verify all portal domain aliases (e.g. angel.co for Wellfound,
        hirist.com / hirist.tech for Hirist) match correctly.
        """
        domain_test_cases = [
            ("wellfound", "angel.co", True),
            ("wellfound", ".angel.co", True),
            ("wellfound", "wellfound.com", True),
            ("wellfound", "sub.wellfound.com", True),
            ("wellfound", "unrelated.com", False),
            ("hirist", "hirist.com", True),
            ("hirist", "hirist.tech", True),
            ("hirist", "subdomain.hirist.tech", True),
            ("hirist", "google.com", False),
            ("linkedin", ".linkedin.com", True),
            ("linkedin", "www.linkedin.com", True),
            ("linkedin", "linkedin.cn", False),
            ("naukri", "naukri.com", True),
            ("naukri", "sub.naukri.com", True),
            ("indeed", "indeed.com", True),
            ("indeed", "secure.indeed.com", True),
        ]

        for portal, domain, expected in domain_test_cases:
            sub_dir = tempfile.mkdtemp(dir=self.temp_dir)
            json_file = os.path.join(sub_dir, "storage_state.json")
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump({"cookies": [{"domain": domain, "name": "session_id", "value": "abc"}]}, f)

            matched = BrowserManager.has_session_for_portal(portal, user_data_dir=sub_dir)
            self.assertEqual(
                matched,
                expected,
                f"Portal '{portal}' with cookie domain '{domain}' expected match={expected}, got match={matched}",
            )

    def test_interactive_login_non_interactive_fallback(self):
        """Empirically test launch_interactive_login in headless/non-interactive test harness."""
        # Using on_ready_callback to verify page and context without blocking
        callback_called = {"ran": False, "url": None}

        def on_ready(page, context):
            callback_called["ran"] = True
            callback_called["url"] = page.url
            # Add a mock cookie into context
            context.add_cookies([
                {"name": "li_at", "value": "auth_token_empirical", "domain": ".linkedin.com", "path": "/"}
            ])

        success = BrowserManager.launch_interactive_login(
            portal="linkedin",
            timeout_seconds=2,
            on_ready_callback=on_ready,
            user_data_dir=self.temp_dir,
        )

        self.assertTrue(success)
        self.assertTrue(callback_called["ran"])
        self.assertIn("linkedin.com", callback_called["url"])

        # Check that storage state snapshot was saved
        state_path = os.path.join(self.temp_dir, "storage_state_linkedin.json")
        self.assertTrue(os.path.exists(state_path))
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookie_names = [c["name"] for c in data.get("cookies", [])]
        self.assertIn("li_at", cookie_names)

        # Confirm session detection recognizes this state
        self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))
        self.assertFalse(BrowserManager.has_session_for_portal("naukri", user_data_dir=self.temp_dir))


if __name__ == "__main__":
    unittest.main()
