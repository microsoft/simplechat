#!/usr/bin/env python3
# test_v2_admin_secret_fields.py
"""
Functional test for the credentials the AI Models sections store.
Version: 0.261.083
Implemented in: 0.261.083

The embedding and image-generation routes each hold an API key and an APIM subscription
key. Declaring them at all meant answering two questions a plain text field gets wrong in
opposite directions:

  - The read must not hand a working credential to the browser. ``GET
    /api/v2/admin/settings`` returns the settings document largely unsanitized by design,
    because sanitization strips the endpoints an administrator is there to manage, so
    credentials need withholding separately from that.
  - The write must not clear a credential nobody touched. The V2 surface saves a section
    at a time, so an untouched key still travels with whatever else was edited. If the
    placeholder standing in for a stored secret were written back verbatim, saving an API
    version would replace a working key with the literal string, and the damage would
    surface at the next call to the service rather than at save time.

Both are answered by the mechanism ``admin_settings_secret_utils.py`` already provides
for the server-rendered form, rather than by anything specific to these four keys. These
checks pin that they are registered with it, and that the round trip holds.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
ROUTES_FILE = APP_DIR / "route_backend_v2.py"
SECRET_UTILS_FILE = APP_DIR / "admin_settings_secret_utils.py"

fields_module = import_app_module("admin_settings_fields")

# The credentials the AI Models sections own. Named explicitly rather than matched on the
# word "key", because several non-secret settings contain it -- among them
# ``model_endpoint_identity_header_name``.
EXPECTED_SECRET_KEYS = {
    "azure_openai_embedding_key",
    "azure_apim_embedding_subscription_key",
    "azure_openai_image_gen_key",
    "azure_apim_image_gen_subscription_key",
}


def load_secret_utils():
    """Import ``admin_settings_secret_utils`` directly.

    It depends on nothing but ``copy``, so unlike ``functions_settings`` -- which reaches
    config.py and a live Cosmos client, and is stubbed out for these tests -- it can be
    loaded and exercised as the real module rather than lifted out of source.
    """
    spec = importlib.util.spec_from_file_location(
        "admin_settings_secret_utils", SECRET_UTILS_FILE
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


secret_utils = load_secret_utils()


def declared_fields_by_key():
    return {
        field["key"]: field
        for _section_id, field in fields_module.iter_fields()
        if field.get("key")
    }


def apply_patch(submitted, stored):
    """Port of ``v2_admin_patch_settings``' write path for the keys under test.

    The order is the point. The schema normalizes first, then the route resolves any
    placeholder against the stored document. Resolving first would mean the resolver's
    own reading of the empty string -- which it treats as a deliberate clear -- reached
    the schema, which cannot tell that apart from a field nobody filled in.
    """
    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        submitted, stored
    )
    if errors:
        return None, errors

    secret_keys = set(secret_utils.get_admin_settings_api_secret_fields())
    secret_keys |= fields_module.get_secret_field_keys()
    for key in secret_keys & set(normalized):
        normalized[key] = secret_utils.resolve_admin_settings_secret_value(
            key, normalized[key], stored
        )
    return {**stored, **normalized}, {}


def test_credentials_are_declared_as_secrets():
    """A credential declared as text renders into a readable input."""
    print("Testing that credential fields declare the secret type...")

    assert_app_version_at_least("0.261.083")

    by_key = declared_fields_by_key()

    problems = []
    for key in sorted(EXPECTED_SECRET_KEYS):
        field = by_key.get(key)
        if field is None:
            problems.append(f"{key}: not declared at all")
            continue
        if field.get("type") != "secret":
            problems.append(f"{key}: declared as {field.get('type')!r}, expected 'secret'")

    assert not problems, (
        "These credentials are not declared as secrets, so the V2 admin surface would "
        "render them in plain text:\n  " + "\n  ".join(problems)
    )

    # Declaring the type is also what puts them in the route's resolution set, so this
    # is not merely cosmetic.
    missing = EXPECTED_SECRET_KEYS - fields_module.get_secret_field_keys()
    assert not missing, (
        "These keys are not returned by get_secret_field_keys(), so the settings PATCH "
        f"would not resolve a placeholder for them: {', '.join(sorted(missing))}"
    )

    print(f"  All {len(EXPECTED_SECRET_KEYS)} credential field(s) declare 'secret'.")
    return True


def test_the_api_withholds_stored_credentials():
    """The read must not hand a working key to the browser."""
    print("\nTesting that the settings API redacts these credentials...")

    marker = secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE

    stored = {
        "azure_openai_embedding_key": "sk-live-embedding",
        "azure_openai_image_gen_key": "sk-live-image",
        "azure_apim_embedding_subscription_key": "",
        "azure_openai_embedding_endpoint": "https://example.openai.azure.com",
    }
    redacted = secret_utils.redact_admin_settings_secrets_for_api(stored)

    for key in ("azure_openai_embedding_key", "azure_openai_image_gen_key"):
        assert redacted[key] == marker, f"{key} was not redacted: {redacted[key]!r}"

    serialized = repr(redacted)
    for secret in ("sk-live-embedding", "sk-live-image"):
        assert secret not in serialized, f"{secret} survived redaction"

    # A key that is not set stays empty rather than gaining a marker, or the control
    # would claim a credential exists where none does.
    assert redacted["azure_apim_embedding_subscription_key"] == "", redacted

    # Non-secret configuration is exactly what an administrator is here to manage.
    assert redacted["azure_openai_embedding_endpoint"] == stored["azure_openai_embedding_endpoint"]

    # Redaction must not mutate the document the application goes on using.
    assert stored["azure_openai_embedding_key"] == "sk-live-embedding", stored

    # And every key under test has to be covered by the list the route actually uses.
    covered = set(secret_utils.get_admin_settings_api_secret_fields())
    missing = EXPECTED_SECRET_KEYS - covered
    assert not missing, (
        "These credentials are not in the API secret field list, so the read would "
        f"return them in the clear: {', '.join(sorted(missing))}"
    )

    print("  Stored credentials are replaced with the shared redaction marker.")
    return True


def test_the_v2_read_and_write_use_the_shared_mechanism():
    """A second, parallel secret mechanism would drift from the form's."""
    print("\nTesting that the V2 routes reuse the shared helpers...")

    source = ROUTES_FILE.read_text(encoding="utf-8")

    for fragment, why in (
        (
            "redact_admin_settings_secrets_for_api(settings)",
            "the settings read redacts before responding",
        ),
        (
            "resolve_admin_settings_secret_value",
            "the settings write resolves a returned placeholder",
        ),
        (
            "get_secret_field_keys()",
            "the resolution set includes every key the schema declares as secret",
        ),
    ):
        assert fragment in source, f"route_backend_v2.py no longer ensures that {why}"

    print("  Both routes use the shared mechanism.")
    return True


def test_the_save_reload_save_round_trip_preserves_the_key():
    """The case that actually breaks: save, reload, save again without retyping."""
    print("\nTesting the save/reload/save round trip...")

    marker = secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE

    # 1. A key is stored.
    stored = {
        "azure_openai_embedding_key": "sk-original",
        "azure_openai_embedding_api_version": "2024-05-01-preview",
    }

    # 2. The page reloads. This is what the browser now holds.
    from_api = secret_utils.redact_admin_settings_secrets_for_api(stored)
    assert from_api["azure_openai_embedding_key"] == marker

    # 3. The administrator edits only the API version, and the client returns the whole
    #    section -- including the placeholder it was given.
    merged, errors = apply_patch(
        {
            "azure_openai_embedding_api_version": "2025-01-01-preview",
            "azure_openai_embedding_key": from_api["azure_openai_embedding_key"],
        },
        stored,
    )
    assert not errors, errors
    assert merged["azure_openai_embedding_key"] == "sk-original", (
        "The round trip overwrote the stored key with "
        f"{merged['azure_openai_embedding_key']!r}. The placeholder must never be "
        "stored, and an untouched key must survive a save of the field next to it."
    )
    assert merged["azure_openai_embedding_api_version"] == "2025-01-01-preview", merged

    # 4. The same round trip for an image key, which is a separate entry in the list.
    image_stored = {"azure_apim_image_gen_subscription_key": "sk-image-original"}
    image_from_api = secret_utils.redact_admin_settings_secrets_for_api(image_stored)
    merged, errors = apply_patch(
        {
            "azure_apim_image_gen_subscription_key":
                image_from_api["azure_apim_image_gen_subscription_key"]
        },
        image_stored,
    )
    assert not errors, errors
    assert merged["azure_apim_image_gen_subscription_key"] == "sk-image-original", merged

    print("  A key survives a reload and a save of the field beside it.")
    return True


def test_a_typed_secret_replaces_the_stored_one():
    """The ordinary case: a new credential is stored, trimmed."""
    print("\nTesting that a typed secret is stored...")

    merged, errors = apply_patch(
        {"azure_apim_image_gen_subscription_key": "  new-secret\n"},
        {"azure_apim_image_gen_subscription_key": "old-secret"},
    )

    assert not errors, errors
    # A key pasted from a portal or a terminal routinely carries a trailing newline, and
    # a credential that fails only because of an invisible character is undiagnosable.
    assert merged["azure_apim_image_gen_subscription_key"] == "new-secret", merged

    print("  A typed secret replaces the stored one and is trimmed.")
    return True


def test_removal_stays_possible():
    """Blank must stay distinguishable from the placeholder, or nothing can be deleted."""
    print("\nTesting that a credential can still be removed...")

    marker = secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE

    # This is the distinction the whole design rests on. If an empty submission were read
    # as the placeholder, "keep what is stored" would be the only reachable outcome and a
    # key pasted by mistake could never be taken back.
    assert not secret_utils.is_admin_settings_redacted_secret("")
    assert not secret_utils.is_admin_settings_redacted_secret(None)
    assert secret_utils.is_admin_settings_redacted_secret(marker)

    merged, errors = apply_patch(
        {"azure_openai_image_gen_key": ""},
        {"azure_openai_image_gen_key": "sk-original"},
    )
    assert not errors, errors
    assert merged["azure_openai_image_gen_key"] == "", merged

    print("  Blank clears; only the placeholder means keep.")
    return True


def test_the_secret_control_never_renders_a_stored_value():
    """A declared secret must not reach an ordinary text input."""
    print("\nTesting the V2 secret control...")

    controls = (
        REPO_ROOT / "application" / "v2_ui" / "src" / "components" / "admin" / "fields.tsx"
    ).read_text(encoding="utf-8")

    assert "case 'secret':" in controls, "fields.tsx has no branch for the secret type"
    assert "SECRET_PLACEHOLDER" in controls, (
        "The secret control no longer recognises the placeholder, so it cannot tell "
        "'a secret is stored' from 'no secret set'."
    )

    print("  The secret control recognises the placeholder rather than showing a value.")
    return True


if __name__ == "__main__":
    tests = [
        test_credentials_are_declared_as_secrets,
        test_the_api_withholds_stored_credentials,
        test_the_v2_read_and_write_use_the_shared_mechanism,
        test_the_save_reload_save_round_trip_preserves_the_key,
        test_a_typed_secret_replaces_the_stored_one,
        test_removal_stays_possible,
        test_the_secret_control_never_renders_a_stored_value,
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
