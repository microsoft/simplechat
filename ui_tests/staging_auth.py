# staging_auth.py
"""Pinned, CI-identity-only onboarding for staging browser tests.

Version: 0.261.402
Implemented in: 0.261.401
"""

import hashlib
import json
import re
from urllib.parse import urlsplit


def _origin(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise AssertionError("Terms onboarding requires a valid HTTP(S) origin without credentials.")
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), port


def prepare_staging_browser(context, base_url):
    """Keep the ordinary tutorial preference scoped to this test browser/origin."""
    _origin(base_url)
    encoded_url = json.dumps(base_url)
    context.add_init_script(
        "(() => {"
        f"const origin = new URL({encoded_url}).origin;"
        "if (window.location.origin === origin) {"
        "window.localStorage.setItem('chatTutorialDismissed', 'dismissed');"
        "}"
        "})();"
    )


def complete_staging_terms_onboarding(page, base_url, *, access_token="", terms_sha256=""):
    """Accept only explicitly pinned content in an authenticated CI session."""
    current = urlsplit(page.url)
    if current.path != "/terms-of-use":
        return False

    target_origin = _origin(base_url)
    if _origin(page.url) != target_origin:
        raise AssertionError("Terms onboarding must remain on the configured staging origin.")
    if not access_token:
        raise AssertionError("Automatic terms onboarding is limited to the dedicated CI bearer identity.")

    expected_hash = terms_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise AssertionError("The CI identity needs a reviewed SIMPLECHAT_UI_TERMS_SHA256 before onboarding.")

    message = page.locator(".terms-message")
    message.wait_for(state="visible", timeout=30000)
    # Keep the canonicalization identical to the Node smoke helper.
    text = re.sub(r"[ \t\r\n\f\v]+", " ", message.inner_text()).strip(" ")
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        raise AssertionError("Staging terms changed; review and pin their content before CI accepts them.")
    active_content_count = message.locator("a,script,iframe,form").count()
    if active_content_count:
        raise AssertionError("Terms with links or active content require manual review.")

    page.get_by_role("button", name="Accept and continue", exact=True).click()
    page.wait_for_url(lambda value: urlsplit(value).path != "/terms-of-use", timeout=30000)
    if _origin(page.url) != target_origin:
        raise AssertionError("Terms onboarding returned outside the configured staging origin.")
    return True
