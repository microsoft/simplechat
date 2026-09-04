#!/usr/bin/env python3
# test_v2_admin_secret_fields.py
"""
Functional test for the Admin Settings ``password`` field type.
Version: 0.261.082
Implemented in: 0.261.082

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

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
SETTINGS_FILE = APP_DIR / "functions_settings.py"
ROUTES_FILE = APP_DIR / "route_backend_v2.py"

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


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _lift(path, function_names, constant_names=(), namespace=None):
    """Exec named module-level functions and constants out of a source file.

    ``functions_settings`` builds Azure clients at import time and the shared test stub
    replaces the whole module, and ``route_backend_v2`` imports it transitively, so
    neither can be imported here. The secret helpers are pure, so lifting their source
    runs the real implementation rather than a copy of it.
    """
    tree = _parse(path)
    selected = []
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in function_names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & set(constant_names):
                selected.append(node)
                found |= targets & set(constant_names)

    missing = (set(function_names) | set(constant_names)) - found
    assert not missing, (
        f"These names were not found in {path.name}, so this test cannot exercise the "
        f"real behaviour: {', '.join(sorted(missing))}"
    )

    scope = namespace if namespace is not None else {}
    scope.setdefault("copy", __import__("copy"))
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), scope)
    return scope


def load_secret_helpers():
    """Return the real redaction and resolution helpers from both modules."""
    scope = _lift(
        SETTINGS_FILE,
        function_names=(
            "is_admin_settings_redacted_secret",
            "_get_nested_setting_value",
            "_set_nested_setting_value",
            "resolve_admin_settings_secret_value",
            "redact_admin_settings_secrets_for_form",
        ),
        constant_names=(
            "ADMIN_SETTINGS_SECRET_REDACTED_VALUE",
            "ADMIN_SETTINGS_FORM_SECRET_FIELDS",
            "ADMIN_SETTINGS_NESTED_SECRET_FIELDS",
        ),
    )
    # The route helper closes over the two names above, so it is exec'd into the same
    # namespace rather than a fresh one.
    return _lift(ROUTES_FILE, function_names=("_resolve_redacted_secrets",), namespace=scope)


HELPERS = load_secret_helpers()


def declared_fields_by_key():
    return {
        field["key"]: field
        for _section_id, field in fields_module.iter_fields()
        if field.get("key")
    }


def test_password_is_a_known_field_type():
    """Without the type registered, a declared secret would render as nothing."""
    print("Testing that 'password' is a declared field type...")

    assert_app_version_at_least("0.261.082")

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


def test_the_api_redacts_stored_secrets():
    """The V2 read must not hand a working credential to the browser."""
    print("\nTesting that the settings API redacts secrets...")

    redact = HELPERS["redact_admin_settings_secrets_for_form"]
    marker = HELPERS["ADMIN_SETTINGS_SECRET_REDACTED_VALUE"]

    stored = {
        "azure_openai_embedding_key": "sk-live-embedding",
        "azure_openai_image_gen_key": "sk-live-image",
        "azure_apim_embedding_subscription_key": "",
        "azure_openai_embedding_endpoint": "https://example.openai.azure.com",
    }
    redacted = redact(stored)

    for key in ("azure_openai_embedding_key", "azure_openai_image_gen_key"):
        assert redacted[key] == marker, f"{key} was not redacted: {redacted[key]!r}"

    serialized = repr(redacted)
    for secret in ("sk-live-embedding", "sk-live-image"):
        assert secret not in serialized, f"{secret} survived redaction"

    # A key that is not set must stay empty rather than gaining a marker, or the UI
    # would claim a credential exists where none does.
    assert redacted["azure_apim_embedding_subscription_key"] == "", redacted

    # Non-secret configuration is exactly what an administrator is here to manage.
    assert redacted["azure_openai_embedding_endpoint"] == stored["azure_openai_embedding_endpoint"]

    # And redaction must not mutate the document the application goes on using.
    assert stored["azure_openai_embedding_key"] == "sk-live-embedding", stored

    print("  Stored credentials are replaced with the shared redaction marker.")
    return True


def test_the_v2_routes_use_the_shared_secret_mechanism():
    """A second, parallel secret mechanism would drift from the classic form's."""
    print("\nTesting that the V2 routes reuse the shared helpers...")

    source = ROUTES_FILE.read_text(encoding="utf-8")

    for fragment, why in (
        (
            'redact_admin_settings_secrets_for_form(settings)',
            "the settings read redacts before responding",
        ),
        (
            "_resolve_redacted_secrets(updates, current_settings)",
            "the settings write resolves a returned marker",
        ),
        (
            "ADMIN_SETTINGS_FORM_SECRET_FIELDS",
            "the field list is the shared one, not a second copy",
        ),
        (
            "resolve_admin_settings_secret_value",
            "resolution reuses the classic form's helper",
        ),
    ):
        assert fragment in source, f"route_backend_v2.py no longer ensures that {why}"

    # The four keys this PR declares must be covered by that shared list rather than
    # relying on the schema alone, so a key is redacted whether or not it is declared.
    covered = set(HELPERS["ADMIN_SETTINGS_FORM_SECRET_FIELDS"])
    missing = EXPECTED_SECRET_KEYS - covered
    assert not missing, (
        "These credentials are not in ADMIN_SETTINGS_FORM_SECRET_FIELDS, so the read "
        f"would return them in the clear: {', '.join(sorted(missing))}"
    )

    print(f"  Both routes use the shared mechanism; all {len(EXPECTED_SECRET_KEYS)} keys covered.")
    return True


def test_the_save_reload_save_round_trip_preserves_the_key():
    """The case that actually breaks: save, reload, save again without retyping."""
    print("\nTesting the save/reload/save round trip...")

    redact = HELPERS["redact_admin_settings_secrets_for_form"]
    resolve_updates = HELPERS["_resolve_redacted_secrets"]
    marker = HELPERS["ADMIN_SETTINGS_SECRET_REDACTED_VALUE"]

    # 1. A key is stored.
    stored = {
        "azure_openai_embedding_key": "sk-original",
        "azure_openai_embedding_api_version": "2024-05-01-preview",
    }

    # 2. The page reloads. This is what the browser now holds.
    from_api = redact(stored)
    assert from_api["azure_openai_embedding_key"] == marker

    # 3. The administrator edits only the API version, and the client returns the whole
    #    section -- including the redacted marker it was given.
    submitted = {
        "azure_openai_embedding_api_version": "2025-01-01-preview",
        "azure_openai_embedding_key": from_api["azure_openai_embedding_key"],
    }

    resolved = resolve_updates(submitted, stored)
    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        resolved, stored
    )
    assert not errors, errors

    merged = {**stored, **normalized}
    assert merged["azure_openai_embedding_key"] == "sk-original", (
        "The round trip overwrote the stored key with "
        f"{merged['azure_openai_embedding_key']!r}. The marker must never be stored, and "
        "an untouched key must survive a save of the field next to it."
    )
    assert merged["azure_openai_embedding_api_version"] == "2025-01-01-preview", merged

    # 4. The same round trip, but the client sends the untouched field as blank rather
    #    than echoing the marker -- which is what the V2 password control actually does.
    blank_submitted = {
        "azure_openai_embedding_api_version": "2025-06-01-preview",
        "azure_openai_embedding_key": "",
    }
    resolved = resolve_updates(blank_submitted, stored)
    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        resolved, stored
    )
    assert not errors, errors
    merged = {**stored, **normalized}
    assert merged["azure_openai_embedding_key"] == "sk-original", merged

    print("  A key survives a reload and a save of the field beside it.")
    return True


def test_an_explicit_clear_survives_the_resolution_pass():
    """The clear must not be swallowed by the marker-resolution step in front of it."""
    print("\nTesting that the clear survives resolution...")

    resolve_updates = HELPERS["_resolve_redacted_secrets"]
    stored = {"azure_openai_image_gen_key": "sk-original"}

    # `resolve_admin_settings_secret_value` coerces its input with `str(value or '')`,
    # so passing None straight through it would turn an explicit clear into "keep".
    # The pass therefore has to rewrite the marker only.
    resolved = resolve_updates({"azure_openai_image_gen_key": None}, stored)
    assert resolved["azure_openai_image_gen_key"] is None, (
        "The resolution pass turned an explicit clear into "
        f"{resolved['azure_openai_image_gen_key']!r}, so a key could never be removed."
    )

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        resolved, stored
    )
    assert not errors, errors
    merged = {**stored, **normalized}
    assert merged["azure_openai_image_gen_key"] == "", merged

    # A real replacement must also pass through untouched.
    resolved = resolve_updates({"azure_openai_image_gen_key": "sk-replacement"}, stored)
    assert resolved["azure_openai_image_gen_key"] == "sk-replacement", resolved

    print("  None still clears, and a typed replacement is untouched.")
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
        test_the_api_redacts_stored_secrets,
        test_the_v2_routes_use_the_shared_secret_mechanism,
        test_an_empty_secret_keeps_what_is_stored,
        test_a_typed_secret_replaces_the_stored_one,
        test_null_clears_the_stored_secret,
        test_the_save_reload_save_round_trip_preserves_the_key,
        test_an_explicit_clear_survives_the_resolution_pass,
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
