#!/usr/bin/env python3
# test_v2_admin_help_settings_normalization.py
"""
Functional test for how the V2 settings PATCH validates the Help group.
Version: 0.261.260
Implemented in: 0.261.260

The server-rendered Support Menu form quietly repairs bad input: a malformed
recipient is cleared and Send Feedback is switched off, and Send Feedback is also
switched off whenever it has no recipient. V2 does neither silently.

- A malformed recipient is refused with a field error, so what was typed stays
  on screen beside the reason.
- Send Feedback on with no recipient saves, with a warning, and the Support
  section reads "Needs configuration"; users simply do not see Send Feedback
  until a recipient exists, which is how the end-user menu already behaves.
- The per-announcement visibility map is a component field, which the type-driven
  path refuses, so it has its own validation. It merges over the stored map, so a
  partial payload can never re-share an announcement that was hidden.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


fields_module = import_app_module("admin_settings_fields")
support_menu_config = import_app_module("support_menu_config")
normalize = fields_module.normalize_admin_settings_updates

RECIPIENT = "support_feedback_recipient_email"
VISIBILITY = "support_latest_features_visibility"


def test_malformed_recipients_are_refused():
    """A typo is caught where it is typed, not in a user's draft."""
    print("Testing recipient validation...")

    assert_app_version_at_least("0.261.260")

    for value in (
        "support",
        "support@",
        "@contoso.com",
        "help desk@contoso.com",
        "a@contoso.com, b@contoso.com",
        "a@contoso.com;b@contoso.com",
        "Support <support@contoso.com>",
        "a@b@contoso.com",
        f"{'x' * 250}@contoso.com",
    ):
        normalized, errors, _warnings = normalize({RECIPIENT: value}, {})
        assert RECIPIENT in errors, f"{value!r} should be refused"
        assert RECIPIENT not in normalized, f"{value!r} must not be saved"

    print("  Malformed recipients are refused with a field error.")
    return True


def test_valid_and_blank_recipients_save():
    """A plain address is trimmed; a blank value is how the destination is left unset."""
    print("\nTesting accepted recipients...")

    normalized, errors, _warnings = normalize({RECIPIENT: "  help@contoso.com  "}, {})
    assert not errors, errors
    assert normalized[RECIPIENT] == "help@contoso.com"

    normalized, errors, _warnings = normalize({RECIPIENT: "service-desk@internal"}, {})
    assert not errors, "A single-label domain is accepted, as the end-user route accepts it."

    normalized, errors, _warnings = normalize({RECIPIENT: ""}, {})
    assert not errors, errors
    assert normalized[RECIPIENT] == ""

    print("  Plain and blank recipients save.")
    return True


def test_send_feedback_without_a_recipient_saves_with_a_warning():
    """Turning the menu on must not silently switch Send Feedback off."""
    print("\nTesting the missing-recipient warning...")

    stored = {
        "enable_support_menu": False,
        "enable_support_send_feedback": True,
        RECIPIENT: "",
    }

    normalized, errors, warnings = normalize({"enable_support_menu": True}, stored)
    assert not errors, errors
    assert normalized == {"enable_support_menu": True}, (
        "Saving the menu switch must not change Send Feedback the way the classic form does."
    )
    assert RECIPIENT in warnings, "The administrator should be told users will not see Send Feedback."

    _normalized, _errors, warnings = normalize(
        {"enable_support_menu": True, RECIPIENT: "help@contoso.com"}, stored
    )
    assert RECIPIENT not in warnings

    _normalized, _errors, warnings = normalize(
        {"enable_support_menu": True, "enable_support_send_feedback": False}, stored
    )
    assert RECIPIENT not in warnings, "Send Feedback off needs no recipient."

    _normalized, _errors, warnings = normalize({"enable_support_send_feedback": True}, stored)
    assert RECIPIENT not in warnings, "With the menu off, Send Feedback is not offered to anyone."

    _normalized, _errors, warnings = normalize(
        {"app_title": "Contoso Chat"}, {**stored, "enable_support_menu": True}
    )
    assert RECIPIENT not in warnings, "An unrelated save should not repeat the note."

    print("  Send Feedback without a recipient saves and is explained.")
    return True


def test_menu_name_falls_back_and_is_bounded():
    """A blank menu name reads as Support, as the classic save makes it."""
    print("\nTesting the menu name...")

    normalized, errors, _warnings = normalize({"support_menu_name": "   "}, {})
    assert not errors, errors
    assert normalized["support_menu_name"] == "Support"

    normalized, _errors, _warnings = normalize({"support_menu_name": "  Help Desk  "}, {})
    assert normalized["support_menu_name"] == "Help Desk"

    normalized, _errors, _warnings = normalize({"support_menu_name": "x" * 200}, {})
    assert len(normalized["support_menu_name"]) == fields_module.SUPPORT_MENU_NAME_MAX_LENGTH

    print("  The menu name falls back and is bounded.")
    return True


def test_visibility_map_merges_over_stored_choices():
    """A partial payload must never re-share an announcement that was hidden."""
    print("\nTesting the visibility map merge...")

    catalogue = support_menu_config.get_support_latest_feature_catalog()
    first, second = catalogue[0]["id"], catalogue[1]["id"]
    stored = {VISIBILITY: {first: False}}

    normalized, errors, _warnings = normalize({VISIBILITY: {second: "false", "retired_feature": True}}, stored)
    assert not errors, errors
    visibility = normalized[VISIBILITY]

    assert visibility[first] is False, "The stored hidden choice was lost."
    assert visibility[second] is False, "The submitted string 'false' should hide the announcement."
    assert "retired_feature" not in visibility, "Ids the catalogue no longer has are dropped."
    assert set(visibility) == set(support_menu_config.get_default_support_latest_features_visibility()), (
        "The saved map should name every announcement, as the classic save does."
    )
    assert visibility["deployment"] is False and visibility["redis_key_vault"] is False, (
        "Untouched announcements keep their catalogue defaults."
    )

    print("  Submitted choices merge over the stored ones.")
    return True


def test_visibility_map_must_be_an_object():
    """Anything but a map is refused rather than resetting every choice."""
    print("\nTesting visibility map validation...")

    for value in (["release_250_ai_access"], "all", None, 7):
        normalized, errors, _warnings = normalize({VISIBILITY: value}, {})
        assert VISIBILITY in errors, f"{value!r} should be refused"
        assert VISIBILITY not in normalized

    print("  Malformed visibility payloads are refused.")
    return True


def test_help_components_cannot_be_written():
    """Send Feedback and the publication notice are not settings."""
    print("\nTesting that the Help utilities save nothing...")

    for component in (
        "send-feedback-overview",
        "send-feedback-bug-report",
        "send-feedback-feature-request",
        "support-latest-features-publication",
    ):
        declared = [
            field
            for _section_id, field in fields_module.iter_fields()
            if field.get("component") == component
        ]
        assert len(declared) == 1, f"{component} should be declared exactly once"
        assert not declared[0].get("key"), f"{component} must not claim a settings key"

    print("  The utility components own no settings keys.")
    return True


if __name__ == "__main__":
    tests = [
        test_malformed_recipients_are_refused,
        test_valid_and_blank_recipients_save,
        test_send_feedback_without_a_recipient_saves_with_a_warning,
        test_menu_name_falls_back_and_is_bounded,
        test_visibility_map_merges_over_stored_choices,
        test_visibility_map_must_be_an_object,
        test_help_components_cannot_be_written,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
