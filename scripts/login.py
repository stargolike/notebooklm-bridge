#!/usr/bin/env python3
"""NotebookLM Login — saves persistent browser session for subsequent use.

Usage:
    python login.py

Opens a visible Chromium browser navigated to notebooklm.google.com.
Log in with your Google account, then close the browser.
The session (cookies, local storage) is saved to ~/.notebooklm_session/
"""

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_DIR = Path.home() / ".notebooklm_session"
NOTEBOOKLM_URL = "https://notebooklm.google.com"


def main():
    print("=" * 60)
    print("  NotebookLM Bridge — Login")
    print("=" * 60)
    print()
    print(f"Session will be saved to: {SESSION_DIR}")
    print()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )

        context.add_init_script("""
            // Hide automation-related properties
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            // Pretend to be a regular Chrome
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        page = context.new_page()
        page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=30000)

        print("Browser opened. Please:")
        print("  1. Log in with your Google account")
        print("  2. Wait until NotebookLM main page loads")
        print("  3. Close the browser window when done")
        print()
        print(f"Navigate to: {NOTEBOOKLM_URL}")
        print()
        print("The session cookies will be saved automatically.")
        print("Press Ctrl+C to cancel, or just close the browser.")

        try:
            # Wait until user closes the browser
            page.wait_for_event("close", timeout=600000)  # 10 min timeout
        except Exception:
            pass

        context.close()

    print()
    print("Login session saved successfully!")
    print(f"Session directory: {SESSION_DIR}")
    print()
    print("You can now use: python scripts/bridge.py list")


if __name__ == "__main__":
    main()
