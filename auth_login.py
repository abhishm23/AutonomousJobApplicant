#!/usr/bin/env python3
"""
Interactive CLI Login Utility for Direct Job Portals.

Allows users to log in manually via a visible Playwright browser to store
persistent cookies and session tokens in data/browser_user_data for LinkedIn,
Naukri, Wellfound, and Hirist.
"""

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.browser_manager import (
    BrowserManager,
    DEFAULT_USER_DATA_DIR,
    PORTAL_LOGIN_URLS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("auth_login")

CORE_PORTALS = ["linkedin", "naukri", "wellfound", "hirist"]


def list_portals() -> None:
    """Prints a formatted table of all supported portals and login endpoints."""
    print("\n" + "=" * 70)
    print(f"{'PORTAL':<15} {'LOGIN URL':<50}")
    print("=" * 70)
    for portal in BrowserManager.get_supported_portals():
        url = BrowserManager.get_login_url(portal)
        print(f"{portal.capitalize():<15} {url:<50}")
    print("=" * 70 + "\n")


def check_status(user_data_dir: Optional[str] = None) -> Dict[str, bool]:
    """
    Checks and displays the current authentication status for all supported portals.
    """
    target_dir = user_data_dir or DEFAULT_USER_DATA_DIR
    print("\n" + "=" * 75)
    print(f"[STATUS] Browser Session Status Check")
    print(f"Directory: {os.path.abspath(target_dir)}")
    print("=" * 75)
    print(f"{'PORTAL':<15} {'STATUS':<20} {'LOGIN URL':<40}")
    print("-" * 75)

    results: Dict[str, bool] = {}
    for portal in BrowserManager.get_supported_portals():
        has_session = BrowserManager.has_session_for_portal(portal, user_data_dir=target_dir)
        results[portal] = has_session
        status_badge = "[AUTHENTICATED]" if has_session else "[NOT LOGGED IN]"
        url = BrowserManager.get_login_url(portal)
        print(f"{portal.capitalize():<15} {status_badge:<20} {url:<40}")

    print("=" * 75 + "\n")
    return results


def run_login_for_portal(
    portal: str, timeout_seconds: int = 300, user_data_dir: Optional[str] = None
) -> bool:
    """
    Executes interactive login for a single portal.
    """
    portal_key = portal.strip().lower()
    target_dir = user_data_dir or DEFAULT_USER_DATA_DIR
    url = BrowserManager.get_login_url(portal_key)

    print("\n" + "=" * 72)
    print(f"[LOGIN] Starting Interactive Login: {portal_key.upper()}")
    print(f"Target URL: {url}")
    print(f"Session Storage: {os.path.abspath(target_dir)}")
    print("=" * 72)
    print("Instructions:")
    print("  1. A Chrome browser window will open automatically.")
    print("  2. Enter your credentials and complete any OTP, 2FA, or CAPTCHA.")
    print("  3. Navigate until you reach the authenticated home feed / dashboard.")
    print("-" * 72)

    try:
        success = BrowserManager.launch_interactive_login(
            portal=portal_key,
            timeout_seconds=timeout_seconds,
            user_data_dir=target_dir,
        )
        if success:
            has_session = BrowserManager.has_session_for_portal(portal_key, user_data_dir=target_dir)
            if has_session:
                print(f"\n[SUCCESS] Saved active session for {portal_key.capitalize()}!")
            else:
                print(
                    f"\n[NOTE] Browser closed. Profile data updated in {target_dir}."
                )
            return True
        return False
    except Exception as e:
        logger.error(f"[auth_login] Error during login for '{portal_key}': {e}")
        print(f"\n[ERROR] Login failed: {e}")
        return False


def run_login_all(timeout_seconds: int = 300, user_data_dir: Optional[str] = None) -> bool:
    """
    Sequentially launches interactive login for all core direct portals.
    """
    print("\n" + "=" * 72)
    print("[BATCH] Interactive Login for All Direct Portals")
    print(f"Portals: {', '.join([p.capitalize() for p in CORE_PORTALS])}")
    print("=" * 72)

    overall_success = True
    for portal in CORE_PORTALS:
        print(f"\n--- Portal: {portal.upper()} ---")
        ok = run_login_for_portal(portal, timeout_seconds=timeout_seconds, user_data_dir=user_data_dir)
        if not ok:
            overall_success = False

    print("\n" + "=" * 72)
    print("[DONE] Batch Login Routine Finished.")
    check_status(user_data_dir=user_data_dir)
    return overall_success


def build_parser() -> argparse.ArgumentParser:
    """Creates the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Autonomous Job Applicant - Interactive Browser Authentication Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python auth_login.py --portal linkedin
  python auth_login.py --portal naukri
  python auth_login.py --portal all
  python auth_login.py --check
  python auth_login.py --list
        """,
    )
    portal_choices = list(PORTAL_LOGIN_URLS.keys()) + ["all"]
    parser.add_argument(
        "--portal",
        type=str,
        choices=portal_choices,
        help="Portal to authenticate with (linkedin, naukri, wellfound, hirist, or all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all supported portals and their login URLs",
    )
    parser.add_argument(
        "--check",
        "--status",
        action="store_true",
        dest="check",
        help="Check session and cookie status for all portals",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for interactive login (default: 300)",
    )
    parser.add_argument(
        "--user-data-dir",
        type=str,
        default=None,
        help="Custom browser user data directory",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        list_portals()
        return 0

    if args.check:
        check_status(user_data_dir=args.user_data_dir)
        return 0

    if not args.portal:
        parser.print_help()
        print("\n[TIP] Specify a portal using --portal <name> or run --check to inspect session status.")
        return 1

    portal = args.portal.strip().lower()
    if portal == "all":
        success = run_login_all(timeout_seconds=args.timeout, user_data_dir=args.user_data_dir)
        return 0 if success else 1
    else:
        success = run_login_for_portal(
            portal=portal,
            timeout_seconds=args.timeout,
            user_data_dir=args.user_data_dir,
        )
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
