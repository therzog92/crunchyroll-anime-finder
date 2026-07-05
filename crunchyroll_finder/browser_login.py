"""Open a browser for Crunchyroll login and capture the etp_rt session cookie."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from crunchyroll_finder.config import APP_DIR

BROWSER_PROFILE_DIR = APP_DIR / "browser_profile"
LOGIN_URL = "https://www.crunchyroll.com/login"
HOME_URL = "https://www.crunchyroll.com/"


class BrowserLoginError(Exception):
    pass


def _find_etp_rt(cookies: list[dict]) -> str | None:
    for cookie in cookies:
        if cookie.get("name") != "etp_rt":
            continue
        value = (cookie.get("value") or "").strip()
        if not value:
            continue
        domain = cookie.get("domain", "")
        if "crunchyroll.com" in domain:
            return value
    return None


def ensure_playwright_browser() -> None:
    """Install Chromium for Playwright if missing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BrowserLoginError(
            "Playwright is not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from e

    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and Path(path).exists():
                return
    except Exception:
        pass

    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
        capture_output=True,
        text=True,
    )


def capture_etp_rt(timeout_seconds: int = 300) -> str:
    """
    Launch Chromium, let the user sign in on Crunchyroll, return etp_rt when set.
    Uses a persistent profile so repeat sign-ins are usually instant.
    """
    ensure_playwright_browser()
    from playwright.sync_api import sync_playwright

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=False,
            viewport={"width": 1100, "height": 820},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(HOME_URL, wait_until="domcontentloaded")

            existing = _find_etp_rt(context.cookies())
            if existing:
                return existing

            if "/login" not in page.url:
                page.goto(LOGIN_URL, wait_until="domcontentloaded")

            for _ in range(timeout_seconds):
                cookie = _find_etp_rt(context.cookies())
                url = page.url or ""
                on_login = "/login" in url or "/activate" in url
                if cookie and not on_login:
                    # Brief pause so Crunchyroll finishes writing the session cookie.
                    page.wait_for_timeout(2000)
                    cookie = _find_etp_rt(context.cookies()) or cookie
                    return cookie
                page.wait_for_timeout(1000)

            raise BrowserLoginError(
                "Timed out waiting for login.\n"
                "Finish signing in on Crunchyroll, then try again."
            )
        finally:
            context.close()
