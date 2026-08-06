#!/usr/bin/env python3
# test_ai_notice.py
"""
Functional test for the configurable chat AI notice.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures AI notice settings, message-version hashes, and persisted
dismissal records behave consistently across every supported display policy.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_ai_notice import (  # noqa: E402
    AI_NOTICE_MAX_MESSAGE_LENGTH,
    AI_NOTICE_USER_SETTINGS_KEY,
    build_ai_notice_dismissal_record,
    get_ai_notice_config,
    is_ai_notice_dismissed,
    normalize_ai_notice_frequency,
    normalize_ai_notice_message,
)


def test_frequency_and_message_normalization():
    """Validate aliases, safe defaults, line endings, and length limits."""
    assert normalize_ai_notice_frequency("always") == "non_dismissible"
    assert normalize_ai_notice_frequency("per-session") == "every_session"
    assert normalize_ai_notice_frequency("once-per-day") == "daily"
    assert normalize_ai_notice_frequency("just-once") == "once"
    assert normalize_ai_notice_frequency("unexpected") == "non_dismissible"
    assert normalize_ai_notice_message("  Line one\r\nLine two  ") == "Line one\nLine two"
    assert len(normalize_ai_notice_message("x" * 1200)) == AI_NOTICE_MAX_MESSAGE_LENGTH


def test_notice_config_and_version_hash():
    """Validate enablement and dismissal invalidation when content changes."""
    disabled = get_ai_notice_config(
        {
            "enable_ai_notice": True,
            "ai_notice_message": "",
            "ai_notice_frequency": "once",
        }
    )
    first = get_ai_notice_config(
        {
            "enable_ai_notice": True,
            "ai_notice_message": "Review AI-generated responses.",
            "ai_notice_frequency": "once",
        }
    )
    changed_message = get_ai_notice_config(
        {
            "enable_ai_notice": True,
            "ai_notice_message": "Verify AI-generated responses.",
            "ai_notice_frequency": "once",
        }
    )
    changed_frequency = get_ai_notice_config(
        {
            "enable_ai_notice": True,
            "ai_notice_message": "Review AI-generated responses.",
            "ai_notice_frequency": "daily",
        }
    )

    assert disabled["enabled"] is False
    assert first["enabled"] is True
    assert first["hash"] != changed_message["hash"]
    assert first["hash"] != changed_frequency["hash"]


def test_dismissal_record_validation_and_matching():
    """Validate server timestamps and daily/once dismissal semantics."""
    current_time = datetime(2026, 7, 30, 18, 30, tzinfo=timezone.utc)
    once_config = get_ai_notice_config(
        {
            "enable_ai_notice": True,
            "ai_notice_message": "Review AI-generated responses.",
            "ai_notice_frequency": "once",
        }
    )
    record = build_ai_notice_dismissal_record(
        {"hash": once_config["hash"], "frequency": "once"},
        dismissed_at=current_time,
    )
    user_settings = {AI_NOTICE_USER_SETTINGS_KEY: record}

    assert record["dismissed_date"] == "2026-07-30"
    assert is_ai_notice_dismissed(once_config, user_settings, current_time=current_time)

    daily_config = get_ai_notice_config(
        {
            "enable_ai_notice": True,
            "ai_notice_message": "Review AI-generated responses.",
            "ai_notice_frequency": "daily",
        }
    )
    daily_record = build_ai_notice_dismissal_record(
        {"hash": daily_config["hash"], "frequency": "daily"},
        dismissed_at=current_time,
    )
    daily_settings = {AI_NOTICE_USER_SETTINGS_KEY: daily_record}
    assert is_ai_notice_dismissed(daily_config, daily_settings, current_time=current_time)
    assert not is_ai_notice_dismissed(
        daily_config,
        daily_settings,
        current_time=datetime(2026, 7, 31, 0, 1, tzinfo=timezone.utc),
    )

    for frequency in ("non_dismissible", "every_session"):
        config = get_ai_notice_config(
            {
                "enable_ai_notice": True,
                "ai_notice_message": "Review AI-generated responses.",
                "ai_notice_frequency": frequency,
            }
        )
        assert not is_ai_notice_dismissed(config, user_settings, current_time=current_time)


def test_invalid_dismissal_records_are_rejected():
    """Validate persisted records cannot use arbitrary hashes or policies."""
    invalid_records = [
        None,
        {"hash": "not-a-hash", "frequency": "daily"},
        {"hash": "a" * 64, "frequency": "every_session"},
        {"hash": "a" * 64, "frequency": "non_dismissible"},
    ]
    for invalid_record in invalid_records:
        try:
            build_ai_notice_dismissal_record(invalid_record)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid record to be rejected: {invalid_record}")


if __name__ == "__main__":
    os.environ.setdefault("DISABLE_FLASK_INSTRUMENTATION", "1")
    tests = [
        test_frequency_and_message_normalization,
        test_notice_config_and_version_hash,
        test_dismissal_record_validation_and_matching,
        test_invalid_dismissal_records_are_rejected,
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
