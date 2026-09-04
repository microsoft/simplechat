#!/usr/bin/env python3
# test_v2_admin_settings_secret_handling.py
"""
Functional test for credential handling on the V2 Admin Settings endpoint.
Version: 0.261.059
Implemented in: 0.261.059

The server-rendered admin form runs every settings document through
``redact_admin_settings_secrets_for_form`` before rendering, so a stored key
reaches the browser as ``***REDACTED***`` and the submitted placeholder is
resolved back to the stored value on save.

``/api/v2/admin/settings`` returned ``get_settings()`` untouched, so the V2
surface delivered every stored key, connection string and client secret to the
browser in plain text -- readable in the network tab by anyone who could open
the page, and cached by anything sitting in front of it. V1 did not do this, so
it was a regression introduced by the newer interface rather than a shared
limitation.

These checks pin both halves of the fix:

reading
    The GET response carries the placeholder, never the stored credential.

writing
    Submitting the placeholder back is a no-op, and a save that consists only of
    untouched credentials succeeds instead of being rejected as empty. Getting
    this wrong replaces every credential in the settings document with the
    literal string "***REDACTED***" the first time an administrator saves an
    unrelated toggle.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTE_SOURCE = APP_ROOT / "route_backend_v2.py"

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates
REDACTED = fields_module.SECRET_REDACTED_VALUE


def read_route_source():
    assert ROUTE_SOURCE.is_file(), f"Missing {ROUTE_SOURCE}"
    return ROUTE_SOURCE.read_text(encoding="utf-8")


def test_get_does_not_return_the_raw_settings_document():
    """Returning get_settings() untouched hands every credential to the browser."""
    print("Testing that the settings GET redacts before responding...")

    assert_app_version_at_least("0.261.059")

    source = read_route_source()

    get_handler = re.search(
        r"def v2_admin_get_settings\(.*?\n(?=\s{4}@bp\.route)",
        source,
        re.DOTALL,
    )
    assert get_handler, "Could not locate v2_admin_get_settings in route_backend_v2.py"
    body = get_handler.group(0)

    assert '"settings": settings,' not in body, (
        "v2_admin_get_settings returns the settings document unredacted. Every "
        "stored API key, connection string and client secret would be delivered "
        "to the browser in plain text."
    )
    assert "_redact_admin_settings_for_v2(settings)" in body, (
        "The settings GET should pass the document through "
        "_redact_admin_settings_for_v2 before responding."
    )

    print("  The GET response is redacted.")
    return True


def test_redaction_covers_both_the_form_list_and_the_schema():
    """A credential protected in one interface but not the other is still leaked."""
    print("\nTesting the redaction helper's coverage...")

    source = read_route_source()

    helper = re.search(
        r"def _redact_admin_settings_for_v2\(.*?\n(?=\s{4}@bp\.route)",
        source,
        re.DOTALL,
    )
    assert helper, "Could not locate _redact_admin_settings_for_v2"
    body = helper.group(0)

    assert "redact_admin_settings_secrets_for_form" in body, (
        "The helper should reuse the server-rendered form's redaction list, which "
        "is what covers the nested Foundry client secret."
    )
    assert "get_secret_storage_paths()" in body, (
        "The helper should also redact anything the V2 schema declares as a "
        "secret, so a newly declared credential is protected without a second "
        "edit to the route. Storage paths rather than field keys, because a "
        "credential is not always stored under the name of its control."
    )

    print("  Both the form list and the schema list are applied.")
    return True


def test_patch_echo_is_redacted():
    """The PATCH response is merged into the browser's copy of the document."""
    print("\nTesting that the PATCH response redacts what it echoes...")

    source = read_route_source()

    assert '"settings": normalized,' not in source, (
        "The settings PATCH echoes normalized values straight back. A credential "
        "that was just saved would be returned in plain text."
    )
    assert '"settings": _redact_admin_settings_for_v2(normalized),' in source, (
        "The PATCH response should redact the values it echoes."
    )

    print("  The PATCH echo is redacted.")
    return True


def test_untouched_credentials_are_never_written():
    """This is the destructive case: writing the placeholder loses the key."""
    print("\nTesting that an untouched credential is dropped from the update...")

    # A declared secret is needed to exercise the real path. Knowledge declares
    # several; until then, register one temporarily so this check is meaningful
    # from the moment the vocabulary exists rather than only after Phase 4.
    section = "__secret_handling_probe__"
    fields_module.ADMIN_SETTINGS_FIELDS[section] = [
        {"key": "probe_secret_key", "type": "secret", "label": "Probe secret"}
    ]
    try:
        current = {"probe_secret_key": "the-real-key"}

        untouched, errors, _ = normalize({"probe_secret_key": REDACTED}, current)
        assert not errors, errors
        assert "probe_secret_key" not in untouched, (
            "The placeholder was carried into the update. Saving any unrelated "
            "toggle would overwrite the stored credential with "
            f"{REDACTED!r}, which cannot be recovered without a backup."
        )

        # A save that touches a toggle alongside an untouched credential must
        # still apply the toggle.
        mixed, errors, _ = normalize(
            {"probe_secret_key": REDACTED, "enable_something": True}, current
        )
        assert not errors, errors
        assert mixed == {"enable_something": True}, mixed

        # A genuine edit still lands.
        changed, errors, _ = normalize({"probe_secret_key": "a-new-key"}, current)
        assert not errors, errors
        assert changed["probe_secret_key"] == "a-new-key", changed

        # Deliberately clearing a credential is a real edit, not "unchanged".
        cleared, errors, _ = normalize({"probe_secret_key": ""}, current)
        assert not errors, errors
        assert cleared["probe_secret_key"] == "", cleared
    finally:
        del fields_module.ADMIN_SETTINGS_FIELDS[section]

    print("  Untouched credentials are dropped; real edits and clears still save.")
    return True


def test_a_no_op_save_is_not_rejected_as_empty():
    """Submitting only untouched credentials normalizes to nothing."""
    print("\nTesting the empty-after-normalization path...")

    source = read_route_source()

    assert 'if not normalized:\n                return jsonify({"error": "No settings supplied"}), 400' not in source, (
        "A payload of nothing but untouched credentials normalizes to an empty "
        "update. Returning 400 there would show the administrator a save error "
        "for a save that had nothing to do."
    )
    assert '"updated_keys": [],' in source, (
        "The empty-after-normalization case should succeed with no updated keys."
    )

    print("  A no-op save succeeds rather than erroring.")
    return True


def test_declared_secrets_are_known_to_the_form_redaction_list():
    """A schema secret absent from the V1 list is still exposed by the old page."""
    print("\nTesting declared secrets against the server-rendered redaction list...")

    settings_source = (APP_ROOT / "functions_settings.py").read_text(encoding="utf-8")
    form_list = re.search(
        r"ADMIN_SETTINGS_FORM_SECRET_FIELDS = \((.*?)\)", settings_source, re.DOTALL
    )
    assert form_list, "Could not read ADMIN_SETTINGS_FORM_SECRET_FIELDS"
    protected = set(re.findall(r'"([^"]+)"', form_list.group(1)))

    nested_list = re.search(
        r"ADMIN_SETTINGS_NESTED_SECRET_FIELDS = \((.*?)\)", settings_source, re.DOTALL
    )
    assert nested_list, "Could not read ADMIN_SETTINGS_NESTED_SECRET_FIELDS"
    protected |= set(re.findall(r'"([^"]+)"', nested_list.group(1)))

    # Compared by storage path, not by field key. A field is named after its
    # control, and the Web Search client secret is stored inside
    # web_search_agent rather than under the form input's name.
    missing = sorted(fields_module.get_secret_storage_paths() - protected)

    assert not missing, (
        "These credentials are declared as secrets in admin_settings_fields.py "
        "but are not in the server-rendered form's redaction list, so the "
        "classic admin page would still render them in plain text. Add them to "
        "ADMIN_SETTINGS_FORM_SECRET_FIELDS (or "
        "ADMIN_SETTINGS_NESTED_SECRET_FIELDS for a dotted path) in "
        "functions_settings.py:\n  " + "\n  ".join(missing)
    )

    print(
        f"  All {len(fields_module.get_secret_storage_paths())} declared secret(s) "
        "are covered by both interfaces."
    )
    return True


if __name__ == "__main__":
    tests = [
        test_get_does_not_return_the_raw_settings_document,
        test_redaction_covers_both_the_form_list_and_the_schema,
        test_patch_echo_is_redacted,
        test_untouched_credentials_are_never_written,
        test_a_no_op_save_is_not_rejected_as_empty,
        test_declared_secrets_are_known_to_the_form_redaction_list,
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
