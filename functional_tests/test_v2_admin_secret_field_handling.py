#!/usr/bin/env python3
# test_v2_admin_secret_field_handling.py
"""
Functional test for masking and restoring secrets on the V2 admin settings API.
Version: 0.261.059
Implemented in: 0.261.059

Admin Settings is the one surface that edits credentials, so it cannot use
``sanitize_settings_for_user``, which removes those keys entirely. The
server-rendered form solved this years ago with a round trip: the stored value
goes out as ``***REDACTED***``, and a submitted value still equal to that
sentinel resolves back to the stored value on the way in.

The V2 admin API did neither. ``GET /api/v2/admin/settings`` returned
``get_settings()`` unchanged, so every stored API key and storage connection
string was sent to the admin browser in cleartext. Enhanced Citations is the
first section to put those credentials on the V2 page, which is what made the
gap actionable.

The round trip is also the part of this that fails destructively. If the sentinel
is not resolved, saving an untouched Enhanced Citations section overwrites a
working connection string with the literal string ``***REDACTED***`` and storage
stops working. These checks cover the three cases that matter -- untouched,
replaced, cleared -- plus the mask itself and the re-mask on the way back out.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTE_MODULE = APP_ROOT / "route_backend_v2.py"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SECRET_FIELD = V2_SRC / "components" / "admin" / "SecretField.tsx"
PAGE_MODULE = V2_SRC / "pages" / "AdminSettingsPage.tsx"

secret_utils = import_app_module("admin_settings_secret_utils")
fields_module = import_app_module("admin_settings_fields")

SENTINEL = secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE
REAL_SECRET = "DefaultEndpointsProtocol=https;AccountKey=super-secret-value=="


def test_the_mask_hides_configured_secrets_only():
    """An unset secret must stay empty so "not configured" stays distinguishable."""
    print("Testing the secret mask...")

    assert_app_version_at_least("0.261.059")

    settings = {
        "office_docs_storage_account_url": REAL_SECRET,
        "office_docs_storage_account_blob_endpoint": "",
        "app_title": "Simple Chat",
    }

    masked = secret_utils.redact_admin_settings_secrets_for_form(settings)

    assert masked["office_docs_storage_account_url"] == SENTINEL, (
        "A configured secret was not masked, so the credential would be sent to "
        f"the browser: {masked['office_docs_storage_account_url']!r}"
    )
    assert masked["office_docs_storage_account_blob_endpoint"] == "", (
        "An unset secret was masked, which would show 'saved and hidden' for a "
        "credential that was never configured."
    )
    assert masked["app_title"] == "Simple Chat", "A non-secret value was altered."
    assert settings["office_docs_storage_account_url"] == REAL_SECRET, (
        "Masking mutated the caller's settings document."
    )

    print(f"  {len(secret_utils.ADMIN_SETTINGS_FORM_SECRET_FIELDS)} secret field(s) declared; masking is value-dependent.")
    return True


def test_every_declared_secret_field_is_a_known_secret():
    """A secret control over an unmasked key would show the real value."""
    print("\nTesting declared secret fields against the mask list...")

    declared_secrets = sorted(
        field["key"]
        for _section_id, field in fields_module.iter_fields()
        if field.get("type") == "secret" and field.get("key")
    )
    assert declared_secrets, "No secret fields are declared; the extraction likely broke."

    unmasked = [
        key
        for key in declared_secrets
        if key not in secret_utils.ADMIN_SETTINGS_FORM_SECRET_FIELDS
    ]

    assert not unmasked, (
        "These fields are declared as secrets but are not in "
        "ADMIN_SETTINGS_FORM_SECRET_FIELDS, so the GET would send the real value "
        "to a control that promises it is hidden:\n  " + "\n  ".join(unmasked)
    )

    print(f"  All {len(declared_secrets)} declared secret(s) are masked on read.")
    return True


def test_an_untouched_secret_keeps_its_stored_value():
    """The destructive case: saving the mask would overwrite the credential."""
    print("\nTesting that an untouched secret survives a save...")

    current = {"office_docs_storage_account_url": REAL_SECRET}

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"office_docs_storage_account_url": SENTINEL}, current
    )

    assert not errors, f"Unexpected validation errors: {errors}"
    assert normalized["office_docs_storage_account_url"] == REAL_SECRET, (
        "Submitting the mask did not resolve back to the stored secret. Saving an "
        "untouched Enhanced Citations section would replace a working connection "
        f"string with {normalized['office_docs_storage_account_url']!r}."
    )

    print("  The sentinel resolves back to the stored secret.")
    return True


def test_a_new_secret_replaces_the_stored_value():
    """Replacing a credential is the normal case and must not be swallowed."""
    print("\nTesting that a new secret replaces the stored value...")

    current = {"office_docs_storage_account_url": REAL_SECRET}
    replacement = "DefaultEndpointsProtocol=https;AccountKey=rotated-value=="

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"office_docs_storage_account_url": replacement}, current
    )

    assert not errors, f"Unexpected validation errors: {errors}"
    assert normalized["office_docs_storage_account_url"] == replacement, (
        "A submitted secret did not replace the stored value: "
        f"{normalized['office_docs_storage_account_url']!r}"
    )

    print("  A submitted secret replaces the stored value.")
    return True


def test_an_empty_secret_clears_the_stored_value():
    """Clearing must be possible, or a secret could only ever be replaced."""
    print("\nTesting that an empty secret clears the stored value...")

    current = {"office_docs_storage_account_url": REAL_SECRET}

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"office_docs_storage_account_url": ""}, current
    )

    assert not errors, f"Unexpected validation errors: {errors}"
    assert normalized["office_docs_storage_account_url"] == "", (
        "An empty submission did not clear the secret, so a credential could be "
        f"replaced but never removed: {normalized['office_docs_storage_account_url']!r}"
    )

    print("  An empty submission clears the stored secret.")
    return True


def test_the_settings_endpoints_mask_before_responding():
    """Both the read and the echo must mask, or the round trip leaks anyway."""
    print("\nTesting that the V2 settings endpoints mask their responses...")

    assert ROUTE_MODULE.is_file(), f"Missing the V2 route module: {ROUTE_MODULE}"
    source = ROUTE_MODULE.read_text(encoding="utf-8")

    # The GET must not hand the raw document straight to jsonify.
    assert re.search(
        r"safe_settings\s*=\s*redact_admin_settings_secrets_for_form\(settings\)", source
    ), (
        "GET /api/v2/admin/settings no longer masks its response. Returning "
        "get_settings() unchanged sends every stored API key and connection "
        "string to the admin browser."
    )

    # Model endpoint credentials are nested inside a list, so the key-based mask
    # cannot reach them and they need stripping separately.
    assert re.search(
        r'safe_settings\["model_endpoints"\]\s*=\s*sanitize_model_endpoints_for_frontend',
        source,
    ), (
        "GET /api/v2/admin/settings no longer strips model endpoint credentials. "
        "Each entry in model_endpoints carries auth.api_key and auth.client_secret, "
        "which the key-based mask does not reach."
    )

    # The PATCH echoes what it saved, and a secret field resolves the mask back
    # to the real credential before saving, so the echo has to be re-masked.
    assert re.search(
        r'"settings":\s*redact_admin_settings_secrets_for_form\(normalized\)', source
    ), (
        "PATCH /api/v2/admin/settings no longer masks its echoed settings. A "
        "resolved secret would be returned to the browser, defeating the mask on "
        "the GET."
    )

    print("  Both endpoints mask before responding.")
    return True


def test_model_endpoints_cannot_be_written_through_the_patch():
    """The browser only ever holds a stripped copy; saving it would erase the keys."""
    print("\nTesting that model_endpoints is refused by the settings PATCH...")

    stored = [{"id": "one", "auth": {"api_key": REAL_SECRET}}]
    sanitized = [{"id": "one", "auth": {}, "has_api_key": True}]

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"model_endpoints": sanitized}, {"model_endpoints": stored}
    )

    assert "model_endpoints" in errors, (
        "The settings PATCH accepted model_endpoints. The admin surface is served a "
        "copy with every api_key and client_secret stripped, so writing it back "
        "would erase the credentials of every configured endpoint."
    )
    assert "model_endpoints" not in normalized, (
        "model_endpoints was rejected but still made it into the normalized update."
    )

    print("  model_endpoints is refused with an explanation.")
    return True


def test_storage_account_keys_are_masked():
    """These sign SAS tokens for citation access and must not reach a browser."""
    print("\nTesting that storage account keys are masked...")

    storage_keys = ("office_docs_key", "video_files_key", "audio_files_key")

    missing = [
        key
        for key in storage_keys
        if key not in secret_utils.ADMIN_SETTINGS_FORM_SECRET_FIELDS
    ]
    assert not missing, (
        "These storage account keys are not masked, so they are sent to the admin "
        "browser in cleartext. office_docs_key is used directly as account_key= to "
        "sign citation SAS tokens:\n  " + "\n  ".join(missing)
    )

    masked = secret_utils.redact_admin_settings_secrets_for_form(
        {key: REAL_SECRET for key in storage_keys}
    )
    still_visible = [key for key in storage_keys if masked[key] != SENTINEL]
    assert not still_visible, f"Not masked in practice: {still_visible}"

    print(f"  All {len(storage_keys)} storage account key(s) are masked.")
    return True


def test_nested_secrets_are_masked_too():
    """The web search client secret lives inside a nested object, not at the top."""
    print("\nTesting nested secret masking...")

    settings = {
        "web_search_agent": {
            "other_settings": {"azure_ai_foundry": {"client_secret": REAL_SECRET}}
        }
    }

    masked = secret_utils.redact_admin_settings_secrets_for_form(settings)
    nested = masked["web_search_agent"]["other_settings"]["azure_ai_foundry"]

    assert nested["client_secret"] == SENTINEL, (
        f"A nested secret was not masked: {nested['client_secret']!r}"
    )
    assert (
        settings["web_search_agent"]["other_settings"]["azure_ai_foundry"][
            "client_secret"
        ]
        == REAL_SECRET
    ), "Masking mutated the caller's nested settings."

    print("  Nested secrets are masked on a deep copy.")
    return True


def test_the_control_distinguishes_untouched_from_pending_delete():
    """An empty box must not mean both "hidden" and "about to be deleted"."""
    print("\nTesting the secret control's pending-delete state...")

    assert SECRET_FIELD.is_file(), f"Missing the secret control: {SECRET_FIELD}"
    source = SECRET_FIELD.read_text(encoding="utf-8")

    required = (
        (
            "reads the stored value, not just the draft",
            "storedValue",
        ),
        (
            "detects a pending removal",
            "willBeRemoved",
        ),
        (
            "warns before a save removes a credential",
            "will be removed when you save",
        ),
        (
            "offers a way back to the untouched state",
            "onChange(REDACTED_SECRET)",
        ),
    )

    missing = [description for description, fragment in required if fragment not in source]

    assert not missing, (
        "The secret control can no longer tell an untouched credential from one that "
        "is about to be deleted. Erasing a typed value leaves an empty box identical "
        "to the untouched state, and the next save silently destroys a working "
        "credential:\n  " + "\n  ".join(missing)
    )

    # The page must supply the stored value, or the control cannot make the call.
    page = PAGE_MODULE.read_text(encoding="utf-8")
    assert re.search(r"storedValue=\{field\.key \? settings\[field\.key\]", page), (
        "AdminSettingsPage no longer passes the stored value to SecretField, so the "
        "control cannot tell a configured credential from an unconfigured one."
    )

    print("  Untouched, replacing and pending-delete are distinguishable.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_mask_hides_configured_secrets_only,
        test_every_declared_secret_field_is_a_known_secret,
        test_an_untouched_secret_keeps_its_stored_value,
        test_a_new_secret_replaces_the_stored_value,
        test_an_empty_secret_clears_the_stored_value,
        test_the_settings_endpoints_mask_before_responding,
        test_model_endpoints_cannot_be_written_through_the_patch,
        test_storage_account_keys_are_masked,
        test_nested_secrets_are_masked_too,
        test_the_control_distinguishes_untouched_from_pending_delete,
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
