"""
Comprehensive Unit & Integration Test Suite for auth_login.py CLI Utility.
Tests:
- CLI argument parsing (--portal, --list, --check, --status, --timeout, --user-data-dir)
- Portal listing output and formatting
- Status checking output and session inspection
- Single portal login execution and error handling
- Batch 'all' portal sequential execution
- Main function exit codes
"""

import io
import sys
import unittest
from unittest.mock import MagicMock, patch

import auth_login
from auth_login import (
    build_parser,
    check_status,
    list_portals,
    main,
    run_login_all,
    run_login_for_portal,
)


class TestAuthLoginArgParsing(unittest.TestCase):
    """Tests argument parser configuration and flag handling."""

    def setUp(self):
        self.parser = build_parser()

    def test_parse_portal_valid(self):
        args = self.parser.parse_args(["--portal", "linkedin"])
        self.assertEqual(args.portal, "linkedin")

        args_all = self.parser.parse_args(["--portal", "all"])
        self.assertEqual(args_all.portal, "all")

    def test_parse_list_flag(self):
        args = self.parser.parse_args(["--list"])
        self.assertTrue(args.list)

    def test_parse_check_and_status_flags(self):
        args_check = self.parser.parse_args(["--check"])
        self.assertTrue(args_check.check)

        args_status = self.parser.parse_args(["--status"])
        self.assertTrue(args_status.check)

    def test_parse_timeout_and_custom_dir(self):
        args = self.parser.parse_args(
            ["--portal", "naukri", "--timeout", "120", "--user-data-dir", "custom/profile"]
        )
        self.assertEqual(args.portal, "naukri")
        self.assertEqual(args.timeout, 120)
        self.assertEqual(args.user_data_dir, "custom/profile")


class TestAuthLoginCommands(unittest.TestCase):
    """Tests CLI action functions: list_portals, check_status, run_login_for_portal, run_login_all."""

    def test_list_portals_output(self):
        captured_output = io.StringIO()
        with patch("sys.stdout", new=captured_output):
            list_portals()

        output = captured_output.getvalue()
        self.assertIn("PORTAL", output)
        self.assertIn("Linkedin", output)
        self.assertIn("https://www.linkedin.com/login", output)
        self.assertIn("Naukri", output)
        self.assertIn("https://www.naukri.com/nlogin/login", output)
        self.assertIn("Wellfound", output)
        self.assertIn("Hirist", output)

    @patch("utils.browser_manager.BrowserManager.has_session_for_portal")
    def test_check_status_display(self, mock_has_session):
        def session_side_effect(portal, user_data_dir=None):
            return portal == "linkedin"

        mock_has_session.side_effect = session_side_effect

        captured_output = io.StringIO()
        with patch("sys.stdout", new=captured_output):
            status_dict = check_status()

        output = captured_output.getvalue()
        self.assertTrue(status_dict["linkedin"])
        self.assertFalse(status_dict["naukri"])
        self.assertIn("AUTHENTICATED", output)
        self.assertIn("NOT LOGGED IN", output)

    @patch("utils.browser_manager.BrowserManager.launch_interactive_login")
    @patch("utils.browser_manager.BrowserManager.has_session_for_portal")
    def test_run_login_for_portal_success(self, mock_has_session, mock_launch):
        mock_launch.return_value = True
        mock_has_session.return_value = True

        captured_output = io.StringIO()
        with patch("sys.stdout", new=captured_output):
            success = run_login_for_portal("linkedin", timeout_seconds=60)

        self.assertTrue(success)
        mock_launch.assert_called_once()
        self.assertIn("SUCCESS", captured_output.getvalue())

    @patch("utils.browser_manager.BrowserManager.launch_interactive_login")
    def test_run_login_for_portal_failure_handled(self, mock_launch):
        mock_launch.side_effect = RuntimeError("Playwright error")

        captured_output = io.StringIO()
        with patch("sys.stdout", new=captured_output):
            success = run_login_for_portal("wellfound", timeout_seconds=60)

        self.assertFalse(success)
        self.assertIn("ERROR", captured_output.getvalue())

    @patch("auth_login.run_login_for_portal")
    @patch("auth_login.check_status")
    def test_run_login_all_invokes_core_portals(self, mock_check, mock_login_portal):
        mock_login_portal.return_value = True

        captured_output = io.StringIO()
        with patch("sys.stdout", new=captured_output):
            success = run_login_all(timeout_seconds=30)

        self.assertTrue(success)
        self.assertEqual(mock_login_portal.call_count, 4)
        called_portals = [call_args[0][0] for call_args in mock_login_portal.call_args_list]
        self.assertEqual(called_portals, ["linkedin", "naukri", "wellfound", "hirist"])
        mock_check.assert_called_once()


class TestAuthLoginMainEntrypoint(unittest.TestCase):
    """Tests CLI main entrypoint exit codes and delegation."""

    def test_main_no_args_shows_help_and_exits_1(self):
        captured_output = io.StringIO()
        with patch("sys.stdout", new=captured_output):
            code = main([])
        self.assertEqual(code, 1)
        self.assertIn("Specify a portal", captured_output.getvalue())

    @patch("auth_login.list_portals")
    def test_main_list_exits_0(self, mock_list):
        code = main(["--list"])
        self.assertEqual(code, 0)
        mock_list.assert_called_once()

    @patch("auth_login.check_status")
    def test_main_check_exits_0(self, mock_check):
        code = main(["--check"])
        self.assertEqual(code, 0)
        mock_check.assert_called_once()

    @patch("auth_login.run_login_for_portal", return_value=True)
    def test_main_single_portal_exits_0_on_success(self, mock_login):
        code = main(["--portal", "hirist"])
        self.assertEqual(code, 0)
        mock_login.assert_called_once()

    @patch("auth_login.run_login_all", return_value=True)
    def test_main_portal_all_exits_0_on_success(self, mock_login_all):
        code = main(["--portal", "all"])
        self.assertEqual(code, 0)
        mock_login_all.assert_called_once()

    @patch("auth_login.run_login_for_portal", return_value=False)
    def test_main_single_portal_exits_1_on_failure(self, mock_login):
        code = main(["--portal", "naukri"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
