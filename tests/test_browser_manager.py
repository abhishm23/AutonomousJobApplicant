"""
Comprehensive Unit & Integration Test Suite for utils/browser_manager.py.
Tests:
- Directory resolution and creation
- Portal URL mappings and invalid portal handling
- Session detection via SQLite cookies database and JSON storage state
- Anti-detection flags, custom user-agent, and persistent context options
- Lock and error handling (SingletonLock / missing dependencies)
- Interactive login flow and context lifecycle
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from utils.browser_manager import (
    DEFAULT_ARGS,
    DEFAULT_IGNORE_DEFAULT_ARGS,
    DEFAULT_USER_AGENT,
    DEFAULT_USER_DATA_DIR,
    DEFAULT_VIEWPORT,
    PORTAL_LOGIN_URLS,
    BrowserManager,
    get_browser_context,
)


class TestBrowserManagerDirectoryAndUrls(unittest.TestCase):
    """Tests directory resolution, creation, and portal login URL mappings."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_browser_mgr_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_user_data_dir_resolution(self):
        resolved = BrowserManager.get_user_data_dir()
        self.assertTrue(os.path.isabs(resolved))
        self.assertEqual(resolved, os.path.abspath(DEFAULT_USER_DATA_DIR))
        self.assertTrue(os.path.exists(resolved))

    def test_custom_user_data_dir_auto_creation(self):
        custom_path = os.path.join(self.temp_dir, "custom_profile", "subdir")
        self.assertFalse(os.path.exists(custom_path))
        resolved = BrowserManager.get_user_data_dir(custom_path)
        self.assertEqual(resolved, os.path.abspath(custom_path))
        self.assertTrue(os.path.exists(resolved))

    def test_get_supported_portals(self):
        portals = BrowserManager.get_supported_portals()
        self.assertIn("linkedin", portals)
        self.assertIn("naukri", portals)
        self.assertIn("wellfound", portals)
        self.assertIn("hirist", portals)
        self.assertIn("indeed", portals)

    def test_get_login_url_valid_portals(self):
        self.assertEqual(BrowserManager.get_login_url("linkedin"), "https://www.linkedin.com/login")
        self.assertEqual(BrowserManager.get_login_url("LinkedIn"), "https://www.linkedin.com/login")
        self.assertEqual(BrowserManager.get_login_url("  naukri  "), "https://www.naukri.com/nlogin/login")
        self.assertEqual(BrowserManager.get_login_url("wellfound"), "https://wellfound.com/login")
        self.assertEqual(BrowserManager.get_login_url("hirist"), "https://www.hirist.tech/login")
        self.assertEqual(BrowserManager.get_login_url("indeed"), "https://secure.indeed.com/account/login")

    def test_get_login_url_invalid_portal_raises(self):
        with self.assertRaises(ValueError) as ctx:
            BrowserManager.get_login_url("nonexistent_portal")
        self.assertIn("Unknown or unsupported portal", str(ctx.exception))
        self.assertIn("linkedin", str(ctx.exception))


class TestSessionDetection(unittest.TestCase):
    """Tests session detection across SQLite cookie databases and JSON state files."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_session_detect_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_has_session_nonexistent_or_empty_dir(self):
        non_existent = os.path.join(self.temp_dir, "does_not_exist")
        self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=non_existent))

        empty_dir = os.path.join(self.temp_dir, "empty")
        os.makedirs(empty_dir, exist_ok=True)
        self.assertFalse(BrowserManager.has_session_for_portal("linkedin", user_data_dir=empty_dir))

    def test_has_session_via_storage_state_json(self):
        state_file = os.path.join(self.temp_dir, "storage_state.json")
        state_data = {
            "cookies": [
                {"name": "li_at", "value": "secret_token", "domain": ".linkedin.com", "path": "/"},
                {"name": "test_cookie", "value": "123", "domain": ".example.com", "path": "/"},
            ]
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))
        self.assertFalse(BrowserManager.has_session_for_portal("naukri", user_data_dir=self.temp_dir))

    def test_has_session_via_portal_specific_storage_state(self):
        state_file = os.path.join(self.temp_dir, "storage_state_naukri.json")
        state_data = {
            "cookies": [
                {"name": "nauk_at", "value": "token_abc", "domain": "www.naukri.com", "path": "/"},
            ]
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        self.assertTrue(BrowserManager.has_session_for_portal("naukri", user_data_dir=self.temp_dir))
        self.assertFalse(BrowserManager.has_session_for_portal("hirist", user_data_dir=self.temp_dir))

    def _create_mock_cookie_db(self, path: str, rows: list):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE cookies (
                creation_utc INTEGER NOT NULL,
                host_key TEXT NOT NULL,
                top_frame_site_key TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                encrypted_value BLOB NOT NULL DEFAULT '',
                path TEXT NOT NULL,
                expires_utc INTEGER NOT NULL,
                is_secure INTEGER NOT NULL,
                is_httponly INTEGER NOT NULL,
                last_access_utc INTEGER NOT NULL,
                has_expires INTEGER NOT NULL,
                is_persistent INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                samesite INTEGER NOT NULL,
                source_scheme INTEGER NOT NULL,
                source_port INTEGER NOT NULL,
                is_same_party INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        for host, name, val in rows:
            cursor.execute(
                """
                INSERT INTO cookies (creation_utc, host_key, name, value, path, expires_utc, is_secure, is_httponly, last_access_utc, has_expires, is_persistent, priority, samesite, source_scheme, source_port)
                VALUES (1000, ?, ?, ?, '/', 2000, 1, 1, 1000, 1, 1, 1, 0, 1, 443)
                """,
                (host, name, val),
            )
        conn.commit()
        conn.close()

    def test_has_session_via_sqlite_cookies_db(self):
        cookie_db_path = os.path.join(self.temp_dir, "Default", "Network", "Cookies")
        self._create_mock_cookie_db(
            cookie_db_path,
            [
                (".linkedin.com", "li_at", "token_12345"),
                (".wellfound.com", "remember_user_token", "wf_token"),
                (".hirist.tech", "auth_token", "hirist_jwt"),
            ],
        )

        self.assertTrue(BrowserManager.has_session_for_portal("linkedin", user_data_dir=self.temp_dir))
        self.assertTrue(BrowserManager.has_session_for_portal("wellfound", user_data_dir=self.temp_dir))
        self.assertTrue(BrowserManager.has_session_for_portal("hirist", user_data_dir=self.temp_dir))
        self.assertFalse(BrowserManager.has_session_for_portal("naukri", user_data_dir=self.temp_dir))

    def test_get_session_status_all(self):
        cookie_db_path = os.path.join(self.temp_dir, "Default", "Cookies")
        self._create_mock_cookie_db(
            cookie_db_path,
            [(".naukri.com", "nauk_at", "sample_naukri_token")],
        )

        status_all = BrowserManager.get_session_status_all(user_data_dir=self.temp_dir)
        self.assertIsInstance(status_all, dict)
        self.assertTrue(status_all["naukri"]["has_session"])
        self.assertFalse(status_all["linkedin"]["has_session"])
        self.assertEqual(status_all["naukri"]["login_url"], "https://www.naukri.com/nlogin/login")


class TestBrowserContextAndAntiDetection(unittest.TestCase):
    """Tests launch_persistent_context parameters, anti-detection flags, and stealth script injection."""

    def test_get_persistent_context_default_args(self):
        mock_playwright = MagicMock()
        mock_context = MagicMock()
        mock_playwright.chromium.launch_persistent_context.return_value = mock_context

        target_dir = tempfile.mkdtemp(prefix="test_ctx_")
        try:
            context = BrowserManager.get_persistent_context(
                mock_playwright,
                headless=True,
                user_data_dir=target_dir,
            )
            self.assertEqual(context, mock_context)
            mock_playwright.chromium.launch_persistent_context.assert_called_once()
            _, kwargs = mock_playwright.chromium.launch_persistent_context.call_args

            self.assertEqual(kwargs["user_data_dir"], os.path.abspath(target_dir))
            self.assertTrue(kwargs["headless"])
            self.assertEqual(kwargs["user_agent"], DEFAULT_USER_AGENT)
            self.assertEqual(kwargs["viewport"], DEFAULT_VIEWPORT)
            self.assertEqual(kwargs["args"], DEFAULT_ARGS)
            self.assertEqual(kwargs["ignore_default_args"], DEFAULT_IGNORE_DEFAULT_ARGS)

            # Check stealth script injection
            mock_context.add_init_script.assert_called_once()
            script_injected = mock_context.add_init_script.call_args[0][0]
            self.assertIn("webdriver", script_injected)
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)

    def test_get_persistent_context_custom_overrides(self):
        mock_playwright = MagicMock()
        mock_context = MagicMock()
        mock_playwright.chromium.launch_persistent_context.return_value = mock_context

        custom_ua = "CustomBot/1.0"
        custom_vp = {"width": 1920, "height": 1080}
        custom_args = ["--custom-flag"]

        target_dir = tempfile.mkdtemp(prefix="test_ctx_custom_")
        try:
            BrowserManager.get_persistent_context(
                mock_playwright,
                headless=False,
                user_data_dir=target_dir,
                user_agent=custom_ua,
                viewport=custom_vp,
                args=custom_args,
                ignore_default_args=[],
            )
            _, kwargs = mock_playwright.chromium.launch_persistent_context.call_args
            self.assertFalse(kwargs["headless"])
            self.assertEqual(kwargs["user_agent"], custom_ua)
            self.assertEqual(kwargs["viewport"], custom_vp)
            self.assertEqual(kwargs["args"], custom_args)
            self.assertEqual(kwargs["ignore_default_args"], [])
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)

    def test_lock_handling_raises_informative_error(self):
        mock_playwright = MagicMock()
        mock_playwright.chromium.launch_persistent_context.side_effect = Exception(
            "Browser error: Process SingletonLock is already held by another process."
        )

        with self.assertRaises(RuntimeError) as ctx:
            BrowserManager.get_persistent_context(mock_playwright)
        self.assertIn("locked by another instance", str(ctx.exception))

    def test_persistent_context_lifecycle_and_cleanup(self):
        mock_context = MagicMock()

        with patch("utils.browser_manager.BrowserManager.get_persistent_context", return_value=mock_context):
            with patch("playwright.sync_api.sync_playwright") as mock_sync_pw:
                mock_pw_inst = MagicMock()
                mock_sync_pw.return_value.__enter__.return_value = mock_pw_inst

                with BrowserManager.persistent_context(headless=True) as ctx:
                    self.assertEqual(ctx, mock_context)

                mock_context.close.assert_called_once()

    def test_standalone_get_browser_context_helper(self):
        mock_context = MagicMock()

        with patch("utils.browser_manager.BrowserManager.persistent_context") as mock_pm:
            mock_pm.return_value.__enter__.return_value = mock_context
            mock_pm.return_value.__exit__.return_value = None

            with get_browser_context(headless=False) as ctx:
                self.assertEqual(ctx, mock_context)

            mock_pm.assert_called_once_with(headless=False, user_data_dir=None)


class TestInteractiveLogin(unittest.TestCase):
    """Tests interactive login flow, page navigation, callbacks, and storage snapshots."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_interactive_login_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_launch_interactive_login_with_callback(self):
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]

        callback_executed = {"done": False}

        def mock_callback(page, context):
            self.assertEqual(page, mock_page)
            self.assertEqual(context, mock_context)
            callback_executed["done"] = True

        with patch("utils.browser_manager.BrowserManager.get_persistent_context", return_value=mock_context):
            with patch("playwright.sync_api.sync_playwright") as mock_sync_pw:
                mock_sync_pw.return_value.__enter__.return_value = MagicMock()

                res = BrowserManager.launch_interactive_login(
                    portal="linkedin",
                    timeout_seconds=5,
                    on_ready_callback=mock_callback,
                    user_data_dir=self.temp_dir,
                )

                self.assertTrue(res)
                self.assertTrue(callback_executed["done"])
                mock_page.goto.assert_called_once_with(
                    "https://www.linkedin.com/login",
                    timeout=30000,
                    wait_until="domcontentloaded",
                )
                mock_context.storage_state.assert_called_once()
                mock_context.close.assert_called_once()

    def test_launch_interactive_login_invalid_portal_raises(self):
        with self.assertRaises(ValueError):
            BrowserManager.launch_interactive_login("invalid_portal_xyz")


if __name__ == "__main__":
    unittest.main()
