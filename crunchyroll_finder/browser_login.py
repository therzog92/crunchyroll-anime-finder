"""Open a browser for Crunchyroll login and capture the etp_rt session cookie."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crunchyroll_finder.config import APP_DIR

BROWSER_PROFILE_DIR = APP_DIR / "browser_profile"
PLAYWRIGHT_BROWSERS_PATH = APP_DIR / "playwright_browsers"
LOGIN_URL = "https://www.crunchyroll.com/login"
HOME_URL = "https://www.crunchyroll.com/"


class BrowserLoginError(Exception):
    pass


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _configure_playwright_paths() -> None:
    """Point Playwright at user data dirs; support PyInstaller one-file builds."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_PATH))
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        driver_dir = Path(sys._MEIPASS) / "playwright" / "driver"  # type: ignore[attr-defined]
        if driver_dir.exists():
            os.environ.setdefault("PLAYWRIGHT_DRIVER_PATH", str(driver_dir))


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
    _configure_playwright_paths()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BrowserLoginError(
            "Playwright is not available in this build.\n"
            "Re-download the latest release from GitHub."
        ) from e

    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and Path(path).exists():
                return
    except Exception:
        pass

    PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)
    if _is_frozen():
        try:
            from playwright._impl._driver import compute_driver_executable, get_driver_env

            driver = compute_driver_executable()
            result = subprocess.run(
                [str(driver), "install", "chromium"],
                env=get_driver_env(),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise BrowserLoginError(
                    "Could not download Chromium for login.\n"
                    f"{result.stderr or result.stdout or 'Unknown error'}"
                )
            return
        except BrowserLoginError:
            raise
        except Exception as e:
            raise BrowserLoginError(
                "Could not set up the login browser.\n"
                "Check your internet connection and try Connect again."
            ) from e

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
