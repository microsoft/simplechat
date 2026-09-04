#!/usr/bin/env python3
# test_v2_admin_secret_fields.py
"""
Functional test for the Admin Settings ``password`` field type.
Version: 0.261.075
Implemented in: 0.261.075

Before this type existed, a secret declared in the field schema would have been drawn by
the generic text control: a live Azure OpenAI key in a plain ``<input type="text">``,
readable over a shoulder and offered to every password manager and form-restore cache on
the machine.

The type also carries a write rule that cannot be expressed by the control alone. The V2
surface saves a section at a time, so a secret field that is left alone still travels
with whatever else was edited. If an empty box meant "empty string", saving an API
version would clear a working credential, and the damage would only appear the next time
the service was called.

So the server treats an empty secret as "nothing was typed" and drops the key from the
update entirely, while ``None`` -- which the control sends only from an explicit remove
-- clears it. These checks pin both halves, and that the sections carrying credentials
declare them as secrets rather than as text.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


fields_module = import_app_module("admin_settings_fields")

# Every settings key in the schema that carries a credential. Named explicitly rather
# than matched on the word "key", because ``model_endpoint_identity_header_name`` and
# several other keys contain it without being secret.
EXPECTED_SECRET_KEYS = {
    "azure_openai_embedding_key",
    "azure_apim_embedding_subscription_key",
    "azure_openai_image_gen_key",
    "azure_apim_image_gen_subscription_key",
}


def declared_fields_by_key():
    return {
        field["key"]: field
        for _section_id, field in fields_module.iter_fields()
        if field.get("key")
    }


def test_password_is_a_known_field_type():
    """Without the type registered, a declared secret would render as nothing."""
    print("Testing that 'password' is a declared field type...")

    assert_app_version_at_least("0.261.075")

    assert "password" in fields_module.FIELD_TYPES, (
        "'password' is not in FIELD_TYPES, so the schema test would reject any field "
        "declaring it and the renderer would draw nothing."
    )

    # A secret still has to be savable. Putting it in NON_PATCHABLE_TYPES would make the
    # settings PATCH refuse every credential in the AI Models group.
    assert "password" not in fields_module.NON_PATCHABLE_TYPES, (
        "'password' must stay patchable; it has no endpoint of its own."
    )

    print("  'password' is a known, patchable field type.")
    return True


def test_credentials_are_declared_as_secrets():
    """A credential declared as text renders into a readable input."""
    print("\nTesting that credential fields declare the password type...")

    by_key = declared_fields_by_key()

    problems = []
    for key in sorted(EXPECTED_SECRET_KEYS):
        field = by_key.get(key)
        if field is None:
            problems.append(f"{key}: not declared at all")
            continue
        if field.get("type") != "password":
            problems.append(f"{key}: declared as {field.get('type')!r}, expected 'password'")

    assert not problems, (
        "These credentials are not declared as secrets, so the V2 admin surface would "
        "render them in plain text:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(EXPECTED_SECRET_KEYS)} credential field(s) declare 'password'.")
    return True


def test_an_empty_secret_keeps_what_is_stored():
    """Saving a neighbouring field must not wipe a credential nobody touched."""
    print("\nTesting the empty-means-unchanged rule...")

    current = {"azure_openai_embedding_key": "stored-secret"}

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {
            "azure_openai_embedding_key": "",
            "azure_openai_embedding_api_version": "2024-05-01-preview",
        },
        current,
    )

    assert not errors, errors
    assert "azure_openai_embedding_key" not in normalized, (
        "An empty secret reached update_settings, which would overwrite the stored "
        f"credential with nothing: {normalized}"
    )
    assert normalized["azure_openai_embedding_api_version"] == "2024-05-01-preview", (
        "The rest of the update must still be applied."
    )

    # Whitespace alone is still nothing typed, which is what a stray paste produces.
    whitespace_only, _errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"azure_openai_embedding_key": "   \n"}, current
    )
    assert "azure_openai_embedding_key" not in whitespace_only, whitespace_only

    print("  An empty or whitespace-only secret is dropped from the update.")
    return True


def test_a_typed_secret_replaces_the_stored_one():
    """The ordinary case: a new credential is stored, trimmed."""
    print("\nTesting that a typed secret is stored...")

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"azure_apim_image_gen_subscription_key": "  new-secret\n"},
        {"azure_apim_image_gen_subscription_key": "old-secret"},
    )

    assert not errors, errors
    # A key pasted from a portal or terminal routinely carries a trailing newline, and a
    # credential that fails only because of an invisible character is undiagnosable.
    assert normalized["azure_apim_image_gen_subscription_key"] == "new-secret", normalized

    print("  A typed secret replaces the stored one and is trimmed.")
    return True


def test_null_clears_the_stored_secret():
    """Removal has to remain expressible, or a pasted mistake is permanent."""
    print("\nTesting the explicit clear...")

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"azure_openai_image_gen_key": None},
        {"azure_openai_image_gen_key": "stored-secret"},
    )

    assert not errors, errors
    assert "azure_openai_image_gen_key" in normalized, (
        "An explicit clear must reach update_settings, or the secret cannot be removed."
    )
    assert normalized["azure_openai_image_gen_key"] == "", normalized

    print("  None clears the stored secret.")
    return True


def test_the_renderer_implements_the_control():
    """A declared type with no branch renders an empty space where a field should be."""
    print("\nTesting the V2 password control...")

    repo_root = Path(__file__).resolve().parents[1]
    controls = (
        repo_root / "application" / "v2_ui" / "src" / "components" / "admin" / "fields.tsx"
    ).read_text(encoding="utf-8")

    assert "case 'password':" in controls, "fields.tsx has no branch for the password type"

    # The three properties that make it a secret control rather than a text box.
    for fragment, why in (
        ("type={revealed ? 'text' : 'password'}", "the input is masked by default"),
        ('autoComplete="new-password"', "the browser is told not to autofill a stored login"),
        ("onChange(null)", "removal sends the explicit clear the server reads"),
    ):
        assert fragment in controls, f"The password control no longer ensures that {why}"

    page = (
        repo_root / "application" / "v2_ui" / "src" / "pages" / "AdminSettingsPage.tsx"
    ).read_text(encoding="utf-8")

    assert "readSecretValue(field, draft)" in page, (
        "The page must read a password field from the draft alone. Reading it through "
        "readFieldValue would seed the control from the settings document, putting the "
        "stored credential into a form control."
    )

    print("  The control is masked, non-autofilling and write-only.")
    return True


if __name__ == "__main__":
    tests = [
        test_password_is_a_known_field_type,
        test_credentials_are_declared_as_secrets,
        test_an_empty_secret_keeps_what_is_stored,
        test_a_typed_secret_replaces_the_stored_one,
        test_null_clears_the_stored_secret,
        test_the_renderer_implements_the_control,
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
