#!/usr/bin/env python3
"""
Functional test for the V2 chat notices (web search notice and AI notice).

Version: 0.261.028
Implemented in: 0.261.028

The server-rendered chat page renders two administrator-configured notices around the
composer, and the V2 React interface rendered neither. This test pins the parts of that
parity that are easy to lose again:

- the bootstrap payload resolves both notices server-side, reusing the same helpers the
  classic page uses rather than recomputing the AI notice hash or the dismissal window in
  the browser;
- the web search notice still requires all three settings keys, including
  ``web_search_consent_accepted``, which is not an ``enable_*`` key and therefore never
  reaches the feature flags the composer branches on;
- the composer renders both notices and no longer substitutes a hardcoded disclaimer of its
  own, which would have contradicted an administrator who turned the notice off;
- all four AI notice frequencies are handled, and ``non_dismissible`` has no dismiss
  control;
- the session storage keys still match the ones the classic interface writes, so a
  dismissal is not undone by switching interfaces in the same tab.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN_VERSION = "0.261.028"

# Quoted from the classic client so a rename on either side is caught here.
LEGACY_WEB_SEARCH_SESSION_KEY = "webSearchNoticeDismissed"
LEGACY_AI_NOTICE_SESSION_PREFIX = "simplechat.aiNoticeDismissal"

AI_NOTICE_FREQUENCIES = ("non_dismissible", "every_session", "daily", "once")


def _read(path):
    return path.read_text(encoding="utf-8")


def test_bootstrap_resolves_both_notices_with_the_shared_helpers():
    """The bootstrap payload carries a notices block built from functions_ai_notice."""
    print("Testing the bootstrap notices block...")

    route = _read(APP_DIR / "route_backend_v2.py")

    assert "def _build_notices(" in route, (
        "route_backend_v2.py must build the notices block; the SPA cannot read the Jinja "
        "context the classic chat page uses"
    )
    assert '"notices": _build_notices(' in route, (
        "The bootstrap payload must include a notices field, or the V2 composer has "
        "nothing to render"
    )

    # The hash and the dismissal window must come from the same code the classic page runs.
    assert "from functions_ai_notice import" in route, (
        "The notices block must reuse functions_ai_notice rather than reimplementing it"
    )
    assert "get_ai_notice_config(public_settings)" in route, (
        "The AI notice config must come from get_ai_notice_config"
    )
    assert "is_ai_notice_dismissed(ai_notice, user_settings_dict)" in route, (
        "Whether the caller has dismissed the notice must be decided by "
        "is_ai_notice_dismissed, not recomputed"
    )

    # Recomputing the version hash in the route (or the browser) would let the two
    # interfaces disagree about whether an edited notice should reappear.
    assert "sha256" not in route and "compute_ai_notice_hash" not in route, (
        "route_backend_v2.py must not compute the AI notice hash itself; "
        "get_ai_notice_config already provides it"
    )

    # Sanitized settings only. The notice text is safe, but the rule is the rule.
    assert "_build_notices(public_settings" in route, (
        "The notices block must be built from sanitize_settings_for_user() output"
    )

    print("Bootstrap notices block test passed!")
    return True


def test_web_search_notice_requires_all_three_settings():
    """Consent is part of the condition, and is not an enable_ flag."""
    print("Testing the web search notice condition...")

    route = _read(APP_DIR / "route_backend_v2.py")
    builder = route.split("def _build_notices(")[1].split("\ndef ")[0]

    for key in (
        "enable_web_search",
        "web_search_consent_accepted",
        "enable_web_search_user_notice",
    ):
        assert f'"{key}"' in builder, (
            f"The web search notice must require {key}, matching the condition in chats.html"
        )

    # _build_feature_flags only forwards boolean keys starting with enable_, so consent
    # never reaches `features`. That is exactly why this lives on the server.
    assert not re.search(
        r"features\[.web_search_consent_accepted", route
    ), "web_search_consent_accepted is not an enable_ key and is not a feature flag"

    settings_source = _read(APP_DIR / "functions_settings.py")
    assert "WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT" in settings_source, (
        "The default notice text must be a shared constant so V1 and V2 cannot fall back "
        "to different wording"
    )
    assert "WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT" in route, (
        "The bootstrap builder must reuse the shared default notice text"
    )
    assert (
        "'web_search_user_notice_text': WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT"
        in settings_source
    ), "The settings default must be the shared constant rather than a repeated literal"

    print("Web search notice condition test passed!")
    return True


def test_the_client_types_the_notices_payload():
    """The SPA declares the shape it reads, including the server-decided dismissal."""
    print("Testing the client notice types...")

    types_source = _read(V2_SRC / "lib" / "types.ts")

    assert "export interface AiNoticeConfig" in types_source
    assert "export interface WebSearchNoticeConfig" in types_source
    assert "notices: {" in types_source, (
        "BootstrapPayload must declare the notices field"
    )

    for frequency in AI_NOTICE_FREQUENCIES:
        assert f"'{frequency}'" in types_source, (
            f"AiNoticeFrequency must include {frequency}, which the server may send"
        )

    assert "dismissed: boolean" in types_source, (
        "The AI notice's dismissed state is decided by the server and must be read, not "
        "recomputed in the browser"
    )

    print("Client notice type test passed!")
    return True


def test_the_ai_notice_handles_every_frequency():
    """Each frequency is stored where it belongs, and non_dismissible has no control."""
    print("Testing AI notice dismissal handling...")

    notice = _read(V2_SRC / "components" / "chat" / "AiNotice.tsx")

    assert "notice.frequency !== 'non_dismissible'" in notice, (
        "A non_dismissible notice must not render a dismiss button"
    )
    assert "notice.frequency === 'every_session'" in notice, (
        "every_session must be dismissed into session storage, not sent to the server"
    )
    assert "dismissAiNotice(notice.hash, notice.frequency)" in notice, (
        "daily and once must be persisted server-side, since they outlive the tab"
    )

    # The server already answered this for daily/once; ignoring it would re-show a notice
    # the user dismissed yesterday.
    assert "notice.dismissed" in notice, (
        "The component must honour the server-decided dismissed flag"
    )

    # Hiding before the write lands would claim a dismissal that never happened.
    try_block = re.search(r"try \{(.*?)\} catch", notice, re.DOTALL)
    assert try_block, "The server-side dismissal must be guarded by try/catch"
    assert try_block.group(1).index("await dismissAiNotice") < try_block.group(1).index(
        "setDismissed(true)"
    ), "The notice must only hide after the dismissal write succeeds"
    assert "pushToast('error'" in notice, (
        "A failed dismissal must be reported; otherwise the button looks dead"
    )

    # An unconfigured notice renders nothing at all, matching the classic interface.
    assert "!notice?.enabled" in notice and "!notice.message" in notice, (
        "Nothing must render when the administrator has not configured a notice"
    )

    # normalize_ai_notice_message keeps the administrator's line breaks, and the classic
    # notice renders them with white-space: pre-line.
    assert "whitespace-pre-line" in notice, (
        "The notice must preserve the line breaks an administrator typed"
    )
    app_css = _read(APP_DIR / "static" / "css" / "chats.css")
    assert "white-space: pre-line" in app_css.split(".ai-notice-message")[1].split("}")[0], (
        "The classic notice no longer preserves line breaks; the V2 notice mirrors it"
    )

    print("AI notice dismissal test passed!")
    return True


def test_session_keys_match_the_classic_interface():
    """A dismissal follows the person, not the interface they were looking at."""
    print("Testing session storage key agreement...")

    notices = _read(V2_SRC / "lib" / "notices.ts")
    classic_input_actions = _read(APP_DIR / "static" / "js" / "chat" / "chat-input-actions.js")
    classic_ai_notice = _read(APP_DIR / "static" / "js" / "chat" / "chat-ai-notice.js")

    assert f'"{LEGACY_WEB_SEARCH_SESSION_KEY}"' in classic_input_actions, (
        "The classic web search notice key changed; update the V2 client to match"
    )
    assert f"'{LEGACY_AI_NOTICE_SESSION_PREFIX}'" in classic_ai_notice, (
        "The classic AI notice key changed; update the V2 client to match"
    )

    assert f"'{LEGACY_WEB_SEARCH_SESSION_KEY}'" in notices, (
        "V2 must reuse the classic web search dismissal key so switching interfaces in "
        "one tab does not resurrect a dismissed notice"
    )
    assert f"'{LEGACY_AI_NOTICE_SESSION_PREFIX}'" in notices, (
        "V2 must reuse the classic AI notice dismissal key"
    )

    # Keyed by hash on both sides, so editing the notice re-shows it.
    assert "${AI_NOTICE_SESSION_KEY_PREFIX}.${noticeHash}" in notices, (
        "The AI notice session key must be scoped by the notice hash"
    )

    # sessionStorage throws rather than returning null in some privacy modes.
    assert "DOMException" in notices, (
        "Session storage access must tolerate privacy modes that throw"
    )

    print("Session key agreement test passed!")
    return True


def test_the_composer_renders_both_notices_and_no_hardcoded_disclaimer():
    """V2 defers to the administrator instead of inventing its own disclaimer."""
    print("Testing composer wiring...")

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")

    assert "<WebSearchNotice active={options.webSearch} />" in composer, (
        "The web search notice must be tied to the Web toggle, matching the classic client"
    )
    assert "<AiNotice />" in composer, "The AI notice must render below the composer"

    assert "AI responses can be inaccurate" not in composer, (
        "The hardcoded disclaimer must be gone: an organisation that disabled the AI "
        "notice did so deliberately, and the classic interface honours that"
    )

    web_search_notice = _read(V2_SRC / "components" / "chat" / "WebSearchNotice.tsx")
    assert "!active" in web_search_notice, (
        "The web search notice must only appear while web search is armed"
    )

    # Rendered as a React child, which escapes it. dangerouslySetInnerHTML on
    # administrator-entered text would be an injection route.
    for source in (composer, web_search_notice, _read(V2_SRC / "components" / "chat" / "AiNotice.tsx")):
        assert "dangerouslySetInnerHTML" not in source, (
            "Notice text is administrator-entered and must be escaped by React"
        )

    print("Composer wiring test passed!")
    return True


def test_the_dismissal_key_is_accepted_by_the_settings_route():
    """An unlisted key is dropped silently, so the write has to be whitelisted."""
    print("Testing the dismissal settings key...")

    users = _read(APP_DIR / "route_backend_users.py")
    assert "'aiNoticeDismissal'" in users, (
        "aiNoticeDismissal must be in allowed_keys or the POST succeeds and discards it"
    )
    assert "build_ai_notice_dismissal_record(" in users, (
        "The route must rewrite the posted value into a server-timestamped record"
    )

    client_settings = _read(V2_SRC / "lib" / "userSettings.ts")
    writable = client_settings.split("WRITABLE_USER_SETTING_KEYS")[1].split("]")[0]
    assert "'aiNoticeDismissal'" in writable, (
        "The V2 client declares every settings key it writes, so the whitelist test covers it"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "export const dismissAiNotice" in endpoints, (
        "The dismissal must have its own endpoint helper"
    )
    assert "aiNoticeDismissal: { hash, frequency }" in endpoints, (
        "The dismissal payload must carry the hash and frequency the route validates"
    )

    print("Dismissal settings key test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that carried this work."""
    print("Testing application version...")
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_bootstrap_resolves_both_notices_with_the_shared_helpers,
        test_web_search_notice_requires_all_three_settings,
        test_the_client_types_the_notices_payload,
        test_the_ai_notice_handles_every_frequency,
        test_session_keys_match_the_classic_interface,
        test_the_composer_renders_both_notices_and_no_hardcoded_disclaimer,
        test_the_dismissal_key_is_accepted_by_the_settings_route,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
