#!/usr/bin/env python3
# test_v2_admin_settings_normalization.py
"""
Functional test for Admin Settings PATCH normalization.
Version: 0.261.039
Implemented in: 0.261.039

The V2 admin surface saves settings one section at a time through a JSON PATCH,
so the server-rendered form's inline validation no longer runs. These checks pin
the replacement: values are coerced and bounded, unsafe values are refused with a
message the UI can show, and keys belonging to groups that have not been
described yet still save unchanged.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates


def test_numeric_values_are_clamped_to_declared_bounds():
    """An out-of-range logo scale would render an unusable home page."""
    print("Testing numeric clamping...")

    assert_app_version_at_least("0.261.039")

    high, errors, _ = normalize({"landing_page_logo_scale_percent": 9000})
    assert not errors, errors
    assert high["landing_page_logo_scale_percent"] == 500, high

    low, errors, _ = normalize({"landing_page_logo_scale_percent": -20})
    assert not errors, errors
    assert low["landing_page_logo_scale_percent"] == 50, low

    # The browser sends range inputs as strings.
    coerced, errors, _ = normalize({"landing_page_logo_scale_percent": "250"})
    assert not errors, errors
    assert coerced["landing_page_logo_scale_percent"] == 250, coerced

    rejected, errors, _ = normalize({"landing_page_logo_scale_percent": "large"})
    assert "landing_page_logo_scale_percent" in errors, errors

    print("  Numeric values clamp to bounds and reject non-numbers.")
    return True


def test_colours_must_be_hex():
    """A non-hex banner colour would break the classification banner style."""
    print("\nTesting colour validation...")

    valid, errors, _ = normalize({"classification_banner_color": "#ABCDEF"})
    assert not errors, errors
    assert valid["classification_banner_color"] == "#abcdef", valid

    for candidate in ("red", "#fff", "#12345g", "", "javascript:x"):
        _, errors, _ = normalize({"classification_banner_color": candidate})
        assert "classification_banner_color" in errors, f"{candidate!r} was accepted"

    print("  Only six-digit hex colours are accepted.")
    return True


def test_external_links_reject_unsafe_urls():
    """Links render into an anchor href, so the scheme has to be constrained."""
    print("\nTesting external link validation...")

    accepted, errors, _ = normalize(
        {
            "external_links": [
                {"label": "  Docs  ", "url": " https://docs.test/guide "},
                {"label": "Home", "url": "/welcome"},
            ]
        }
    )
    assert not errors, errors
    assert accepted["external_links"] == [
        {"label": "Docs", "url": "https://docs.test/guide"},
        {"label": "Home", "url": "/welcome"},
    ], accepted

    unsafe_cases = [
        [{"label": "x", "url": "javascript:alert(1)"}],
        [{"label": "x", "url": "data:text/html,<script>alert(1)</script>"}],
        [{"label": "x", "url": "//evil.test"}],
        [{"label": "", "url": "https://ok.test"}],
        [{"label": "x", "url": ""}],
        [{"label": "x"}],
        "not-a-list",
        ["not-an-object"],
    ]
    for case in unsafe_cases:
        _, errors, _ = normalize({"external_links": case})
        assert "external_links" in errors, f"{case!r} was accepted"

    print("  Unsafe and malformed link lists are refused.")
    return True


def test_checkbox_sets_are_ordered_and_bounded():
    """The apply-to array must be stable and non-empty while the feature is on."""
    print("\nTesting checkbox set handling...")

    # Declared option order wins, so the stored array does not depend on the
    # order the browser happened to send.
    ordered, errors, _ = normalize(
        {"user_agreement_apply_to": ["chat", "personal"]},
        {"enable_user_agreement": True},
    )
    assert not errors, errors
    assert ordered["user_agreement_apply_to"] == ["personal", "chat"], ordered

    _, errors, _ = normalize(
        {"user_agreement_apply_to": []}, {"enable_user_agreement": True}
    )
    assert "user_agreement_apply_to" in errors, errors

    # With the capability off the constraint does not apply, so an administrator
    # can turn the feature off without first fixing its selection.
    _, errors, _ = normalize(
        {"user_agreement_apply_to": []}, {"enable_user_agreement": False}
    )
    assert not errors, errors

    _, errors, _ = normalize(
        {"user_agreement_apply_to": ["personal", "made_up"]},
        {"enable_user_agreement": True},
    )
    assert "user_agreement_apply_to" in errors, errors

    print("  Selections are ordered, validated and bounded by the capability toggle.")
    return True


def test_selects_reject_unknown_values_but_reuse_shared_aliases():
    """Frequency fields must accept the same aliases the V1 form accepts."""
    print("\nTesting select handling...")

    _, errors, _ = normalize({"landing_page_alignment": "sideways"})
    assert "landing_page_alignment" in errors, errors

    valid, errors, _ = normalize({"landing_page_alignment": "center"})
    assert not errors and valid["landing_page_alignment"] == "center"

    # Delegated to the shared normalizers, so aliases resolve identically in both
    # admin interfaces rather than being rejected in one of them.
    aliased, errors, _ = normalize({"ai_notice_frequency": "ALWAYS"})
    assert not errors and aliased["ai_notice_frequency"] == "non_dismissible", aliased

    aliased, errors, _ = normalize({"terms_of_use_frequency": "per-session"})
    assert not errors and aliased["terms_of_use_frequency"] == "every_session", aliased

    print("  Unknown values are refused and shared aliases still resolve.")
    return True


def test_redirect_url_refuses_unsafe_targets():
    """Silently rewriting an administrator's redirect would hide the rejection."""
    print("\nTesting cancel redirect validation...")

    for safe in ("/", "/goodbye", "https://sso.test/logout"):
        result, errors, _ = normalize({"terms_of_use_decline_redirect_url": safe})
        assert not errors, f"{safe!r} was refused: {errors}"
        assert result["terms_of_use_decline_redirect_url"] == safe

    for unsafe in (
        "javascript:alert(1)",
        "//evil.test",
        "http://plain.test",
        "https://user:pass@evil.test",
        "\\\\evil.test",
    ):
        _, errors, _ = normalize({"terms_of_use_decline_redirect_url": unsafe})
        assert "terms_of_use_decline_redirect_url" in errors, f"{unsafe!r} was accepted"

    print("  Unsafe redirect targets are refused rather than silently rewritten.")
    return True


def test_text_is_bounded_and_falls_back_when_empty():
    """Menu names have a fallback; free text is trimmed to its declared maximum."""
    print("\nTesting text handling...")

    fallback, errors, _ = normalize({"custom_pages_menu_name": "   "})
    assert not errors and fallback["custom_pages_menu_name"] == "Custom Pages", fallback

    fallback, errors, _ = normalize({"external_links_menu_name": ""})
    assert not errors and fallback["external_links_menu_name"] == "External Links"

    truncated, errors, _ = normalize({"terms_of_use_title": "T" * 400})
    assert not errors, errors
    assert len(truncated["terms_of_use_title"]) == 160, len(truncated["terms_of_use_title"])

    # An empty title falls back rather than leaving an unlabelled dialog.
    titled, errors, _ = normalize({"terms_of_use_title": ""})
    assert not errors and titled["terms_of_use_title"] == "Terms of Use", titled

    print("  Text is trimmed, bounded and falls back where declared.")
    return True


def test_word_limit_warns_without_blocking():
    """The V1 form warns and saves, so blocking here would strand existing text."""
    print("\nTesting the agreement word limit...")

    long_text = "word " * 250
    saved, errors, warnings = normalize({"user_agreement_text": long_text})
    assert not errors, errors
    assert "user_agreement_text" in warnings, warnings
    assert saved["user_agreement_text"].startswith("word"), saved

    _, _, warnings = normalize({"user_agreement_text": "short agreement"})
    assert not warnings, warnings

    print("  Over-long agreements warn but still save.")
    return True


def test_enabling_custom_pages_requires_acknowledgement():
    """Custom Pages is not fully live until restart, so enabling must be acknowledged."""
    print("\nTesting the Custom Pages restart acknowledgement...")

    _, errors, _ = normalize({"enable_custom_pages": True}, {"enable_custom_pages": False})
    assert "enable_custom_pages" in errors, errors

    acknowledged, errors, _ = normalize(
        {"enable_custom_pages": True, "custom_pages_restart_acknowledged": True},
        {"enable_custom_pages": False},
    )
    assert not errors, errors
    # The acknowledgement gates the change; it is not itself a stored setting.
    assert acknowledged == {"enable_custom_pages": True}, acknowledged

    # Disabling, and saving while already enabled, need no acknowledgement.
    _, errors, _ = normalize({"enable_custom_pages": False}, {"enable_custom_pages": True})
    assert not errors, errors
    _, errors, _ = normalize({"enable_custom_pages": True}, {"enable_custom_pages": True})
    assert not errors, errors

    print("  Enabling requires acknowledgement; the flag is never persisted.")
    return True


def test_uploads_cannot_be_set_through_the_settings_patch():
    """Branding blobs have their own endpoint that converts and versions them."""
    print("\nTesting the upload guard...")

    for key in ("custom_logo_base64", "custom_logo_dark_base64", "custom_favicon_base64"):
        _, errors, _ = normalize({key: "AAAA"})
        assert key in errors, f"{key} was accepted through PATCH"

    print("  Image payloads are refused by the settings PATCH.")
    return True


def test_undeclared_keys_pass_through_unchanged():
    """Groups that have not been described yet must keep saving."""
    print("\nTesting passthrough for undescribed settings...")

    payload = {
        "enable_some_future_capability": True,
        "some_endpoint_url": "https://api.test",
        "some_threshold": 7,
    }
    result, errors, warnings = normalize(dict(payload))
    assert not errors and not warnings, (errors, warnings)
    assert result == payload, result

    print("  Undeclared keys are forwarded untouched.")
    return True


def test_switches_coerce_form_shaped_truthiness():
    """Switch values arrive as JSON booleans and, from some clients, as strings."""
    print("\nTesting switch coercion...")

    for raw, expected in (
        (True, True),
        (False, False),
        ("on", True),
        ("true", True),
        ("", False),
        ("false", False),
        (None, False),
    ):
        result, errors, _ = normalize({"enable_dark_mode_default": raw})
        assert not errors, errors
        assert result["enable_dark_mode_default"] is expected, (raw, result)

    print("  Switch values coerce to real booleans.")
    return True


if __name__ == "__main__":
    tests = [
        test_numeric_values_are_clamped_to_declared_bounds,
        test_colours_must_be_hex,
        test_external_links_reject_unsafe_urls,
        test_checkbox_sets_are_ordered_and_bounded,
        test_selects_reject_unknown_values_but_reuse_shared_aliases,
        test_redirect_url_refuses_unsafe_targets,
        test_text_is_bounded_and_falls_back_when_empty,
        test_word_limit_warns_without_blocking,
        test_enabling_custom_pages_requires_acknowledgement,
        test_uploads_cannot_be_set_through_the_settings_patch,
        test_undeclared_keys_pass_through_unchanged,
        test_switches_coerce_form_shaped_truthiness,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
