# test_v2_admin_settings_secret_redaction.py
#!/usr/bin/env python3
"""
Functional test that the V2 admin settings endpoint never ships a stored secret.
Version: 0.261.122
Implemented in: 0.261.063

``GET /api/v2/admin/settings`` returns the settings document so an administrator can
edit it. Admin settings are deliberately not passed through
``sanitize_settings_for_user`` -- that strips endpoint and integration configuration,
which is what the page exists to manage. Secrets are a different question, and the
endpoint originally returned them as stored, so simply opening Admin Settings put every
API key in the document into the page payload.

The server-rendered form solved this years ago with a placeholder: secrets are swapped
for ``***REDACTED***`` before rendering and swapped back on save. The V2 endpoint now
does the same, against a wider list, because it returns the whole document rather than
the subset a template happens to draw. ``office_docs_key`` is the clearest example --
an Azure Storage account key used to sign SAS URLs, which the form list does not cover
because the form submits it back verbatim rather than through ``admin_secret``.

Three properties have to hold together, and breaking any one of them either leaks a
credential or destroys one:

  1. The GET redacts, using the API list rather than the form list.
  2. The PATCH resolves the placeholder back to the stored value, for every key the GET
     redacted -- not just the ones the field schema declares.
  3. The PATCH response re-redacts, so a freshly saved secret is not echoed back.

This reads the route source rather than exercising the endpoint, because importing it
requires a live Cosmos client.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_ROUTE = APP_ROOT / "route_backend_v2.py"
SETTINGS_MODULE = APP_ROOT / "admin_settings_secret_utils.py"

# Credentials that must not reach the browser. The first two are declared by the field
# schema; the rest are storage account keys that no admin template renders as a secret,
# which is exactly why an endpoint returning the whole document has to cover them.
MUST_BE_REDACTED = (
    "content_safety_key",
    "azure_apim_content_safety_subscription_key",
    "office_docs_key",
    "video_files_key",
    "audio_files_key",
    "azure_openai_gpt_key",
    "azure_ai_search_key",
    "redis_key",
)

TUPLE_RE = r"{name}\s*=\s*\((?P<body>.*?)\)"

fields_module = import_app_module("admin_settings_fields")
secret_utils = import_app_module("admin_settings_secret_utils")


def read_secret_field_tuple(name):
    """Return the string entries of a secret-field tuple in the shared helper."""
    source = SETTINGS_MODULE.read_text(encoding="utf-8")
    match = re.search(TUPLE_RE.format(name=name), source, re.DOTALL)
    assert match, f"Could not find {name} in admin_settings_secret_utils.py"
    return set(re.findall(r'"([a-z0-9_.]+)"', match.group("body")))


def test_api_secret_list_covers_every_known_credential():
    """A key missing from the list is a key the endpoint returns as stored."""
    print("Testing the API secret field list...")

    assert_app_version_at_least("0.261.063")

    covered = read_secret_field_tuple("ADMIN_SETTINGS_FORM_SECRET_FIELDS") | (
        read_secret_field_tuple("ADMIN_SETTINGS_API_ONLY_SECRET_FIELDS")
    )
    missing = sorted(key for key in MUST_BE_REDACTED if key not in covered)

    assert not missing, (
        "These credentials are not covered by the redaction lists, so "
        "/api/v2/admin/settings would return them as stored:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(MUST_BE_REDACTED)} checked credential(s) are covered.")
    return True


def test_form_list_is_left_alone():
    """Read-only storage keys stay masked without introducing writable form controls."""
    print("\nTesting read-only storage credentials on both settings surfaces...")
    api_only = read_secret_field_tuple("ADMIN_SETTINGS_API_ONLY_SECRET_FIELDS")
    stored = {key: f"fixture-secret-{key}" for key in api_only}
    for redact in (
        secret_utils.redact_admin_settings_secrets_for_form,
        secret_utils.redact_admin_settings_secrets_for_api,
    ):
        masked = redact(stored)
        assert all(masked[key] == secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE for key in api_only)
        assert all(stored[key] == f"fixture-secret-{key}" for key in api_only)

    panes = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (APP_ROOT / "templates" / "admin" / "_panes").glob("*.html")
    )
    admin_route = (APP_ROOT / "route_frontend_admin_settings.py").read_text(encoding="utf-8")
    route_tree = ast.parse(admin_route)
    for key in api_only:
        assert not re.search(rf"""\bname\s*=\s*['"]{re.escape(key)}['"]""", panes), key
        getters = [
            node for node in ast.walk(route_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "form_data"
            and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == key
        ]
        assert len(getters) == 1, key
        expression = compile(ast.Expression(getters[0]), str(APP_ROOT / "route_frontend_admin_settings.py"), "eval")
        assert eval(expression, {"form_data": {}, "settings": stored}) == stored[key]

    print(f"  {len(api_only)} read-only key(s) are masked and not posted by the form.")
    return True


def test_route_redacts_resolves_and_reredacts():
    """All three steps have to be present; any one missing leaks or destroys a secret."""
    print("\nTesting the V2 settings route wiring...")

    source = V2_ROUTE.read_text(encoding="utf-8")

    required = (
        (
            "the GET redacts with the API list",
            "redact_admin_settings_secrets_for_api(settings)",
        ),
        (
            "the PATCH resolves every redacted key, not only declared ones",
            "set(get_admin_settings_api_secret_fields()) | get_secret_field_keys()",
        ),
        (
            "the PATCH resolves the placeholder against the stored document",
            "resolve_admin_settings_secret_value(",
        ),
        (
            "the PATCH response re-redacts before echoing",
            "ADMIN_SETTINGS_SECRET_REDACTED_VALUE",
        ),
    )

    missing = [description for description, fragment in required if fragment not in source]

    assert not missing, (
        "The V2 admin settings route no longer handles secrets safely:\n  "
        + "\n  ".join(missing)
    )

    assert '"settings": settings,' not in source, (
        "The V2 admin settings GET returns the raw settings document again, which "
        "ships every stored credential to the browser."
    )

    print(f"  All {len(required)} secret-handling step(s) are wired up.")
    return True


def test_schema_secrets_are_declared_as_secret_type():
    """A credential declared as text renders in a plain input and round-trips as one."""
    print("\nTesting that schema-declared credentials use the secret type...")

    form_fields = read_secret_field_tuple("ADMIN_SETTINGS_FORM_SECRET_FIELDS")
    api_only = read_secret_field_tuple("ADMIN_SETTINGS_API_ONLY_SECRET_FIELDS")
    nested = read_secret_field_tuple("ADMIN_SETTINGS_NESTED_SECRET_FIELDS")
    declared = fields_module.get_secret_storage_paths()

    # A field key can differ from its credential's nested storage location.
    unredacted = sorted(declared - form_fields - api_only - nested)

    assert not unredacted, (
        "These fields are declared with the 'secret' type but are not redacted by the "
        "endpoint, so the control would receive the real value:\n  "
        + "\n  ".join(unredacted)
    )

    print(f"  All {len(declared)} declared secret(s) are redacted by the endpoint.")
    return True


if __name__ == "__main__":
    tests = [
        test_api_secret_list_covers_every_known_credential,
        test_form_list_is_left_alone,
        test_route_redacts_resolves_and_reredacts,
        test_schema_secrets_are_declared_as_secret_type,
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
