# demo_helpers.py
"""
Shared helpers for SimpleChat demo tests.
Version: 0.250.012
Implemented in: 0.250.003; presenter wait helpers added in 0.250.011; storage-state auth guard added in 0.250.012

These helpers keep the presentation tests focused on the behavior being
demonstrated: local headed Playwright, optional storage-state reuse, and
manual login when the presenter wants to show the browser flow live.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse


DEMO_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = Path(os.getenv("SIMPLECHAT_DEMO_ARTIFACT_DIR", DEMO_DIR / "artifacts"))
DEFAULT_BASE_URL = "https://127.0.0.1:5000"


def get_demo_base_url():
    """Return the SimpleChat base URL for local demo tests."""
    return os.getenv("SIMPLECHAT_DEMO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def get_configured_storage_state_path():
    """Return the configured storage-state path before checking whether it exists."""
    return (
        os.getenv("SIMPLECHAT_DEMO_STORAGE_STATE")
        or os.getenv("SIMPLECHAT_UI_STORAGE_STATE")
        or os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE")
        or ""
    )


def is_storage_state_configured():
    """Return whether the caller intended to use an authenticated storage state."""
    return bool(get_configured_storage_state_path())


def get_storage_state_path():
    """Return an authenticated Playwright storage-state path when one is configured."""
    configured_path = get_configured_storage_state_path()
    if not configured_path:
        return ""

    storage_path = Path(configured_path)
    return str(storage_path) if storage_path.exists() else ""


def is_headless_mode():
    """Return whether demo browsers should run headless."""
    return os.getenv("SIMPLECHAT_DEMO_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}


def env_flag(name, default=False):
    """Return whether an environment flag is enabled."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes"}


def get_int_env(name, default):
    """Return an integer environment value with a safe fallback."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def get_slow_mo_ms():
    """Return Playwright slow motion delay for presenter-friendly demos."""
    return get_int_env("SIMPLECHAT_DEMO_SLOW_MO_MS", 0)


def get_login_timeout_ms():
    """Return how long headed demos wait for the presenter to complete login."""
    return int(os.getenv("SIMPLECHAT_DEMO_LOGIN_TIMEOUT_MS", "300000"))


def ensure_artifact_dir():
    """Create and return the demo artifact directory."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACT_DIR


def new_demo_context(playwright, viewport=None):
    """Create a local Chromium context for interactive SimpleChat demos."""
    launch_options = {"headless": is_headless_mode()}
    slow_mo_ms = get_slow_mo_ms()
    if slow_mo_ms > 0:
        launch_options["slow_mo"] = slow_mo_ms
    browser = playwright.chromium.launch(**launch_options)
    context_options = {
        "ignore_https_errors": True,
        "viewport": viewport or {"width": 1440, "height": 900},
    }
    storage_state = get_storage_state_path()
    if storage_state:
        context_options["storage_state"] = storage_state
    elif is_storage_state_configured():
        raise FileNotFoundError(
            f"Configured Playwright storage state was not found: {get_configured_storage_state_path()}"
        )
    context = browser.new_context(**context_options)
    return browser, context


def wait_for_authenticated_selector(page, selector, description):
    """Wait for an authenticated page marker, allowing manual login in headed mode."""
    login_timeout_ms = get_login_timeout_ms()
    try:
        page.locator(selector).wait_for(state="visible", timeout=10000)
        return
    except Exception as exc:
        if is_storage_state_configured():
            raise AssertionError(
                f"Expected authenticated selector '{selector}' for {description}, but it did not appear using "
                f"the configured storage state '{get_configured_storage_state_path()}'. Recapture the storage "
                "state or verify that it was captured against the same local URL."
            ) from exc
        if is_headless_mode():
            raise

    print("")
    print(f"Waiting for login before continuing {description}.")
    print("Use the opened browser to sign in to SimpleChat; the test will continue automatically.")
    page.locator(selector).wait_for(state="visible", timeout=login_timeout_ms)


def load_storage_state_cookies(storage_state_path, base_url):
    """Return cookie dictionaries from a Playwright storage-state file for requests.Session."""
    if not storage_state_path:
        return []

    with open(storage_state_path, "r", encoding="utf-8") as state_file:
        state = json.load(state_file)

    parsed_url = urlparse(base_url)
    host_name = parsed_url.hostname or ""
    cookies = []
    for cookie in state.get("cookies", []):
        domain = str(cookie.get("domain") or "").lstrip(".")
        if domain and host_name and not host_name.endswith(domain):
            continue
        cookies.append(cookie)
    return cookies


def wait_for_new_completed_assistant_response(
    page,
    previous_ai_message_count,
    timeout_ms,
    expected_text="",
    min_length=20,
):
    """Wait for a new completed assistant response and return its visible text."""
    page.wait_for_function(
        """
        ({ previousCount, expectedText, minLength }) => {
            const messages = Array.from(document.querySelectorAll('.ai-message .message-text'));
            if (messages.length <= previousCount) {
                return false;
            }
            const element = messages[messages.length - 1];
            const text = (element.textContent || '').trim();
            const normalizedText = text.toLowerCase();
            const normalizedExpectedText = String(expectedText || '').trim().toLowerCase();
            const messageElement = element.closest('.ai-message');
            return Boolean(
                text
                && !text.includes('Streaming...')
                && !text.includes('Reconnecting')
                && !normalizedText.startsWith('thinking')
                && !normalizedText.startsWith('checking content safety')
                && !normalizedText.startsWith('preparing')
                && !normalizedText.startsWith('processing')
                && !normalizedText.startsWith('connecting')
                && !normalizedText.startsWith('searching public workspace documents')
                && !normalizedText.startsWith('searching all workspace documents')
                && !normalizedText.startsWith('searching all workspaces')
                && !normalizedText.startsWith('searching workspace documents')
                && !normalizedText.startsWith('searching documents')
                && !normalizedText.startsWith('found ')
                && text.length >= minLength
                && (!normalizedExpectedText || normalizedText.includes(normalizedExpectedText))
                && messageElement
                && !messageElement.querySelector('.streaming-cursor, .spinner-border')
            );
        }
        """,
        arg={
            "previousCount": previous_ai_message_count,
            "expectedText": expected_text,
            "minLength": min_length,
        },
        timeout=timeout_ms,
    )

    assistant_text = (page.locator(".ai-message .message-text").last.text_content() or "").strip()
    if expected_text:
        assert expected_text.lower() in assistant_text.lower(), (
            f"Expected assistant response to contain '{expected_text}', got: {assistant_text[:500]}"
        )
    return assistant_text


def pause_for_presenter(page, env_name, default_ms, message):
    """Pause a headed demo so the presenter can narrate and click around."""
    pause_ms = get_int_env(env_name, default_ms)
    if pause_ms <= 0:
        return
    print(f"{message} Keeping browser open for {pause_ms} ms.")
    page.wait_for_timeout(pause_ms)