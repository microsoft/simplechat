#!/usr/bin/env python3
# test_terms_of_use.py
"""
Functional test for Terms of Use recurrence and persistence helpers.
Version: 0.250.056
Implemented in: 0.250.055

This test ensures Terms of Use hashes, redirect validation,
pre-auth session acceptance, and user-settings persistence behave consistently.
"""

import os
import sys
import types
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"


class FakeSession(dict):
    """Minimal Flask session stand-in for helper tests."""

    modified = False


fake_session = FakeSession()
_MISSING_MODULE = object()


def _install_helper_test_stubs():
    fake_flask = types.ModuleType("flask")
    fake_flask.session = fake_session
    fake_flask.has_request_context = lambda: True
    stubs = {"flask": fake_flask}

    fake_activity = types.ModuleType("functions_activity_logging")
    fake_activity.log_terms_of_use_accepted = lambda **payload: None
    fake_activity.log_terms_of_use_declined = lambda **payload: None
    stubs["functions_activity_logging"] = fake_activity

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    stubs["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
    fake_settings.update_user_settings = lambda user_id, payload: True
    stubs["functions_settings"] = fake_settings

    originals = {}
    for name, module in stubs.items():
        originals[name] = sys.modules.get(name, _MISSING_MODULE)
        sys.modules[name] = module
    return originals


def _restore_helper_test_stubs(originals):
    for name, original_module in originals.items():
        if original_module is _MISSING_MODULE:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original_module


def _load_helper_module():
    originals = _install_helper_test_stubs()
    module_path = APP_DIR / "functions_terms_of_use.py"
    spec = importlib.util.spec_from_file_location("terms_of_use_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        _restore_helper_test_stubs(originals)
    return module


terms = _load_helper_module()


def _enabled_settings(frequency="once", message="Please accept these terms."):
    return {
        "enable_terms_of_use": True,
        "terms_of_use_title": "Rules of Behavior",
        "terms_of_use_message": message,
        "terms_of_use_frequency": frequency,
        "terms_of_use_decline_redirect_url": "/",
        "terms_of_use_accept_button_text": "Accept",
        "terms_of_use_decline_button_text": "Cancel",
    }


def test_hash_and_redirect_normalization():
    """Validate hash invalidation and redirect safety."""
    first_hash = terms.compute_terms_of_use_hash("Title", "Message", "once")
    second_hash = terms.compute_terms_of_use_hash("Title", "Changed", "once")

    assert first_hash != second_hash
    assert terms.normalize_terms_of_use_frequency("once-per-day") == "daily"
    assert terms.normalize_terms_of_use_redirect_url("/goodbye") == "/goodbye"
    assert terms.normalize_terms_of_use_redirect_url("https://contoso.example/terms") == "https://contoso.example/terms"
    assert terms.normalize_terms_of_use_redirect_url("//evil.example") == "/"
    assert terms.normalize_terms_of_use_redirect_url("javascript:alert(1)") == "/"
    assert terms.normalize_terms_of_use_return_path("/chats?x=1") == "/chats?x=1"
    assert terms.normalize_terms_of_use_return_path("https://evil.example") == "/"


def test_pre_auth_session_acceptance_unblocks_login_for_daily_mode():
    """Validate anonymous pre-auth acceptance prevents a daily-mode login loop."""
    settings = _enabled_settings(frequency="daily")

    fake_session.clear()
    assert not terms.has_terms_of_use_acceptance(settings)
    terms.mark_pre_auth_terms_of_use_acceptance(settings)
    assert terms.has_terms_of_use_acceptance(settings)
    assert terms.TERMS_OF_USE_PRE_AUTH_SESSION_KEY in fake_session


def test_once_acceptance_persists_to_user_settings_and_activity_log():
    """Validate once-per-version acceptance writes user settings and audit data."""
    settings = _enabled_settings(frequency="once")
    updates = []
    audits = []

    original_update_user_settings = terms.update_user_settings
    original_get_user_settings = terms.get_user_settings
    original_log_acceptance = terms.log_terms_of_use_accepted

    terms.update_user_settings = lambda user_id, payload: updates.append((user_id, payload)) or True
    terms.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
    terms.log_terms_of_use_accepted = lambda **payload: audits.append(payload)

    try:
        fake_session.clear()
        record = terms.record_terms_of_use_acceptance(
            user_id="user-123",
            settings=settings,
            source="post_auth",
        )
        assert record["frequency"] == "once"
        assert fake_session[terms.TERMS_OF_USE_SESSION_KEY]["hash"] == record["hash"]
    finally:
        terms.update_user_settings = original_update_user_settings
        terms.get_user_settings = original_get_user_settings
        terms.log_terms_of_use_accepted = original_log_acceptance

    assert updates[0][0] == "user-123"
    stored_record = updates[0][1][terms.TERMS_OF_USE_USER_SETTINGS_KEY]
    assert stored_record["hash"] == record["hash"]
    assert audits[0]["user_id"] == "user-123"
    assert audits[0]["frequency"] == "once"


def test_daily_user_settings_acceptance_requires_today():
    """Validate daily recurrence expires on the next UTC date."""
    settings = _enabled_settings(frequency="daily")
    config = terms.get_terms_of_use_config(settings)
    today_record = {
        "hash": config["hash"],
        "frequency": "daily",
        "accepted_date": terms._utc_now().strftime("%Y-%m-%d"),
    }
    stale_record = {
        "hash": config["hash"],
        "frequency": "daily",
        "accepted_date": "2000-01-01",
    }

    original_get_user_settings = terms.get_user_settings
    try:
        terms.get_user_settings = lambda user_id: {
            "id": user_id,
            "settings": {terms.TERMS_OF_USE_USER_SETTINGS_KEY: today_record},
        }
        assert terms.has_terms_of_use_acceptance(settings, user_id="user-123")

        terms.get_user_settings = lambda user_id: {
            "id": user_id,
            "settings": {terms.TERMS_OF_USE_USER_SETTINGS_KEY: stale_record},
        }
        assert not terms.has_terms_of_use_acceptance(settings, user_id="user-123")
    finally:
        terms.get_user_settings = original_get_user_settings


if __name__ == "__main__":
    os.environ.setdefault("DISABLE_FLASK_INSTRUMENTATION", "1")
    tests = [
        test_hash_and_redirect_normalization,
        test_pre_auth_session_acceptance_unblocks_login_for_daily_mode,
        test_once_acceptance_persists_to_user_settings_and_activity_log,
        test_daily_user_settings_acceptance_requires_today,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
