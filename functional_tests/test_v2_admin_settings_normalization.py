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


def test_dependency_conditions_compare_by_declared_type():
    """A string condition compared for truthiness would match every non-empty choice."""
    print("Testing depends_on comparison semantics...")

    assert_app_version_at_least("0.261.083")

    satisfied = fields_module._dependency_is_satisfied

    # Boolean dependencies keep working exactly as they did.
    assert satisfied({"key": "flag", "equals": True}, {"flag": True}) is True
    assert satisfied({"key": "flag", "equals": True}, {"flag": False}) is False
    assert satisfied({"key": "flag", "equals": False}, {"flag": False}) is True
    # Including the form-shaped truthiness a stored document may carry.
    assert satisfied({"key": "flag", "equals": True}, {"flag": "on"}) is True

    # An omitted ``equals`` still means True, which is the historical default.
    assert satisfied({"key": "flag"}, {"flag": True}) is True

    auth = {"key": "azure_openai_embedding_authentication_type", "equals": "key"}

    # Exact equality only. "managed_identity" is truthy, so a boolean comparison here
    # would show an API key field for a route that stores no key.
    assert satisfied(auth, {"azure_openai_embedding_authentication_type": "key"}) is True
    assert (
        satisfied(auth, {"azure_openai_embedding_authentication_type": "managed_identity"})
        is False
    )

    # A near miss must not match: no prefix, substring or case folding.
    for near_miss in ("keys", "ke", "KEY", "Key", " key", "key "):
        assert satisfied(auth, {"azure_openai_embedding_authentication_type": near_miss}) is False, (
            f"{near_miss!r} matched a condition on 'key'"
        )

    # A missing or null value must not match a string condition by accident.
    for absent in ({}, {"azure_openai_embedding_authentication_type": None}):
        assert satisfied(auth, absent) is False, absent

    print("  Boolean conditions unchanged; string conditions match on exact equality.")
    return True


def test_every_condition_must_hold_for_a_multi_gated_field():
    """A field inside two nested blocks is only visible while both are open."""
    print("Testing multi-condition visibility...")

    # The Azure OpenAI embedding key sits inside the direct-connection card and the
    # key-authentication card within it, so it declares both conditions. Judging only
    # one would leave a direct-connection credential on screen under APIM.
    field = fields_module.get_field_definition("azure_openai_embedding_key")
    conditions = list(fields_module.iter_field_dependencies(field))
    assert len(conditions) == 2, conditions

    holds = fields_module.field_dependencies_are_satisfied

    assert holds(field, {
        "enable_embedding_apim": False,
        "azure_openai_embedding_authentication_type": "key",
    }) is True

    # Either condition failing is enough to hide it.
    assert holds(field, {
        "enable_embedding_apim": True,
        "azure_openai_embedding_authentication_type": "key",
    }) is False
    assert holds(field, {
        "enable_embedding_apim": False,
        "azure_openai_embedding_authentication_type": "managed_identity",
    }) is False

    # Image generation adds a third: the capability toggle above the APIM switch.
    image_key = fields_module.get_field_definition("azure_openai_image_gen_key")
    assert len(list(fields_module.iter_field_dependencies(image_key))) == 3

    assert holds(image_key, {
        "enable_image_generation": False,
        "enable_image_gen_apim": False,
        "azure_openai_image_gen_authentication_type": "key",
    }) is False

    print("  Every declared condition has to hold before a field is shown.")
    return True


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


def test_assignment_lists_are_deduplicated_and_typed():
    """A download policy keyed on a blank or repeated id would grant the wrong set."""
    print("\nTesting assignment list handling...")

    assert_app_version_at_least("0.261.060")

    normalized, errors, _ = normalize(
        {
            "file_download_allowed_group_ids": [
                " 3f1a7c64-9b2e-4d58-8a11-6c0f2e5d4b73 ",
                "9d4b2e18-7a35-4c69-b0f2-1e8c5a6d3f40",
                "3f1a7c64-9b2e-4d58-8a11-6c0f2e5d4b73",
                "not-a-uuid",
                "",
                None,
            ]
        }
    )
    assert not errors, errors
    # The application's own normalizer requires canonical group UUIDs and silently
    # drops anything else, so V2 must too. Storing "not-a-uuid" here would grant a
    # download policy an id the server-rendered form would have discarded.
    assert normalized["file_download_allowed_group_ids"] == [
        "3f1a7c64-9b2e-4d58-8a11-6c0f2e5d4b73",
        "9d4b2e18-7a35-4c69-b0f2-1e8c5a6d3f40",
    ], normalized

    # Public workspace ids are not UUID-constrained; their normalizer only trims and
    # deduplicates, so imposing a UUID check would reject valid assignments.
    normalized, errors, _ = normalize(
        {
            "file_download_allowed_public_workspace_ids": [
                " ws-alpha ",
                "ws-beta",
                "ws-alpha",
                "",
            ]
        }
    )
    assert not errors, errors
    assert normalized["file_download_allowed_public_workspace_ids"] == [
        "ws-alpha",
        "ws-beta",
    ], normalized

    # V1 round-trips this through a hidden textarea and accepts a JSON string. V2
    # always sends a real array, and accepting a string here would mean two shapes
    # to keep in step for no gain.
    _, errors, _ = normalize({"file_download_allowed_public_workspace_ids": "ws-a,ws-b"})
    assert "file_download_allowed_public_workspace_ids" in errors, errors

    print("  Assignment lists match the normalizer the application already uses.")
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
        test_dependency_conditions_compare_by_declared_type,
        test_every_condition_must_hold_for_a_multi_gated_field,
        test_numeric_values_are_clamped_to_declared_bounds,
        test_colours_must_be_hex,
        test_external_links_reject_unsafe_urls,
        test_checkbox_sets_are_ordered_and_bounded,
        test_assignment_lists_are_deduplicated_and_typed,
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
