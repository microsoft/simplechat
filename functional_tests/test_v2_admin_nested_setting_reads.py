#!/usr/bin/env python3
# test_v2_admin_nested_setting_reads.py
"""
Functional test for V2 admin reads of settings saved at a nested path.
Version: 0.261.274
Implemented in: 0.261.260
Section status may take arguments after the field index, such as runtime flags: 0.261.274

The V2 Admin Settings page keys unsaved edits by each field's flat key, but a few
settings are saved inside a nested object. The Web Search Foundry connection is the
one that broke: it is saved inside ``web_search_agent``, so once it had been saved,
"Test web search" read ``web_search_foundry_endpoint`` as a top-level key, found
nothing, and the server answered "Foundry Project Endpoint is required" with the
endpoint plainly on screen. The same blind spot hid the fields gated on the saved
authentication type, left the section reading as incomplete, and dropped the warning
shown before a saved client secret is cleared.

This test saves a Foundry connection through the real normalizer, masks it the way
the settings GET does, runs the real TypeScript readers against the real field schema
through ``test_v2_admin_nested_setting_reads.mjs``, and hands the resulting
connection-test payload to the real server-side Web Search test. A copy of any of
those would prove nothing about the code that ships.
"""

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PAGE_TSX = REPO_ROOT / "application" / "v2_ui" / "src" / "pages" / "AdminSettingsPage.tsx"
COMPANION = Path(__file__).resolve().with_suffix(".mjs")

SECTION_ID = "web-search-section"
MINIMUM_NODE = (22, 6)

ENDPOINT = "https://contoso-foundry.services.ai.azure.com/api/projects/web-search"
EDITED_ENDPOINT = "https://fabrikam-foundry.services.ai.azure.com/api/projects/web-search"
API_VERSION = "v1"
AGENT_ID = "asst_nestedReadCheck"
TENANT_ID = "00000000-0000-0000-0000-000000000001"
CLIENT_ID = "00000000-0000-0000-0000-000000000002"
CLIENT_SECRET = "nested-read-check-secret"

MANAGED_IDENTITY = {
    "web_search_foundry_endpoint": ENDPOINT,
    "web_search_foundry_api_version": API_VERSION,
    "web_search_foundry_agent_id": AGENT_ID,
    "web_search_foundry_auth_type": "managed_identity",
    "web_search_foundry_managed_identity_type": "system_assigned",
}

SERVICE_PRINCIPAL = {
    "web_search_foundry_endpoint": ENDPOINT,
    "web_search_foundry_api_version": API_VERSION,
    "web_search_foundry_agent_id": AGENT_ID,
    "web_search_foundry_auth_type": "service_principal",
    "web_search_foundry_tenant_id": TENANT_ID,
    "web_search_foundry_client_id": CLIENT_ID,
    "web_search_foundry_client_secret": CLIENT_SECRET,
    "web_search_foundry_cloud": "",
}

SERVICE_PRINCIPAL_KEYS = (
    "web_search_foundry_tenant_id",
    "web_search_foundry_client_id",
    "web_search_foundry_client_secret",
    "web_search_foundry_cloud",
)

_MISSING = object()
_READER_RESULTS = {}

fields_module = import_app_module("admin_settings_fields")
secret_utils = import_app_module("admin_settings_secret_utils")


def save_connection(updates):
    """A settings document holding a Foundry connection as the V2 save stores it."""
    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        updates, {}
    )
    assert not errors, f"The Foundry connection did not normalize: {errors}"
    return {"enable_web_search": True, "web_search_consent_accepted": True, **normalized}


def as_sent_to_browser(document):
    """Mask stored secrets the way the settings GET does before the page sees them."""
    return secret_utils.redact_admin_settings_secrets_for_api(document)


def secret_storage_path():
    """Where the Web Search client secret is stored, as the schema declares it."""
    for field in fields_module.get_admin_settings_fields()[SECTION_ID]:
        if field.get("key") == "web_search_foundry_client_secret":
            return field["paths"][0]
    raise AssertionError("The Web Search client secret field is not declared.")


def build_scenarios():
    saved_identity = as_sent_to_browser(save_connection(MANAGED_IDENTITY))
    return {
        "managed_identity": {"settings": saved_identity, "draft": {}},
        "service_principal": {
            "settings": as_sent_to_browser(save_connection(SERVICE_PRINCIPAL)),
            "draft": {},
        },
        "edited_endpoint": {
            "settings": saved_identity,
            "draft": {"web_search_foundry_endpoint": EDITED_ENDPOINT},
        },
        "not_configured": {
            "settings": {"enable_web_search": True, "web_search_consent_accepted": True},
            "draft": {},
        },
    }


def node_executable():
    """The Node binary when it can strip TypeScript types, otherwise None."""
    node = shutil.which("node")
    if not node:
        return None
    version = subprocess.run([node, "--version"], capture_output=True, text=True)
    try:
        installed = tuple(int(part) for part in version.stdout.strip().lstrip("v").split(".")[:2])
    except ValueError:
        return None
    return node if installed >= MINIMUM_NODE else None


def reader_results():
    """What the TypeScript readers produce for each scenario, or None to skip.

    Computed once and shared, because every check reads the same run.
    """
    if "results" in _READER_RESULTS:
        return _READER_RESULTS["results"]

    node = node_executable()
    if not node:
        print("  skip  Node 22.6 or newer is required to run the TypeScript readers")
        _READER_RESULTS["results"] = None
        return None

    request = {
        "section_id": SECTION_ID,
        "schema": fields_module.get_admin_settings_fields(),
        "status_rule": fields_module.get_admin_section_status().get(SECTION_ID),
        "scenarios": build_scenarios(),
    }
    with tempfile.TemporaryDirectory() as workdir:
        request_path = Path(workdir) / "scenarios.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(
            [node, str(COMPANION), str(request_path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("The TypeScript readers did not run.")

    _READER_RESULTS["results"] = json.loads(result.stdout)
    return _READER_RESULTS["results"]


def load_web_search_test_module():
    """Load functions_web_search_test.py with its runtime dependencies stubbed.

    The Foundry runtime and Semantic Kernel are replaced only for the duration of the
    import; the module keeps the stand-ins it bound, and nothing else sees them.
    """

    class FoundryAgentInvocationError(RuntimeError):
        pass

    class ChatMessageContent:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    foundry = types.ModuleType("foundry_agent_runtime")
    foundry.FoundryAgentInvocationError = FoundryAgentInvocationError
    foundry.execute_foundry_agent = lambda **kwargs: None

    appinsights = types.ModuleType("functions_appinsights")
    appinsights.log_event = lambda *args, **kwargs: None

    chat_message = types.ModuleType("semantic_kernel.contents.chat_message_content")
    chat_message.ChatMessageContent = ChatMessageContent

    stubs = {
        "foundry_agent_runtime": foundry,
        "functions_appinsights": appinsights,
        "semantic_kernel": types.ModuleType("semantic_kernel"),
        "semantic_kernel.contents": types.ModuleType("semantic_kernel.contents"),
        "semantic_kernel.contents.chat_message_content": chat_message,
    }
    originals = {name: sys.modules.get(name, _MISSING) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "functions_web_search_test_nested_reads",
            APP_ROOT / "functions_web_search_test.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def run_server_test(payload):
    """Run the server-side Web Search test with an agent that records its settings."""
    module = load_web_search_test_module()
    captured = {}

    def record_agent_call(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            message="Microsoft - https://www.microsoft.com",
            citations=[{"url": "https://www.microsoft.com"}],
            model="test-model",
        )

    response, status_code = module.run_web_search_connection_test(
        copy.deepcopy(payload),
        global_settings={},
        execute_agent=record_agent_call,
    )
    return response, status_code, captured


def test_a_saved_connection_lives_inside_web_search_agent():
    """The premise: the saved values are nested, so a top-level read finds nothing."""
    print("Testing where the V2 save stores the Foundry connection...")

    assert_app_version_at_least("0.261.260")

    stored = save_connection(MANAGED_IDENTITY)
    foundry = fields_module.read_nested_setting(
        stored, "web_search_agent.other_settings.azure_ai_foundry"
    )
    assert isinstance(foundry, dict), "The Foundry connection was not saved in web_search_agent."
    assert foundry.get("endpoint") == ENDPOINT
    assert foundry.get("agent_id") == AGENT_ID

    flat_keys = sorted(key for key in stored if key.startswith("web_search_foundry_"))
    assert not flat_keys, f"The connection was also saved under top-level keys: {flat_keys}"

    print("  The connection is saved inside web_search_agent and nowhere else.")
    return True


def test_the_connection_test_sends_the_saved_values():
    """A saved connection is tested with the values on screen, not with blanks."""
    print("\nTesting the connection-test payload for a saved managed identity...")

    results = reader_results()
    if results is None:
        return True

    managed = results["managed_identity"]
    foundry = managed["payload"]["foundry"]
    assert foundry["endpoint"] == ENDPOINT, f"Endpoint sent as {foundry['endpoint']!r}"
    assert foundry["api_version"] == API_VERSION
    assert foundry["agent_id"] == AGENT_ID
    assert foundry["authentication_type"] == "managed_identity"
    assert foundry["managed_identity_type"] == "system_assigned"
    assert "client_secret" not in foundry, (
        "A service principal credential was sent for a managed identity connection."
    )

    response, status_code, captured = run_server_test(managed["payload"])
    assert status_code == 200, f"The server rejected the saved connection: {response}"
    assert captured["foundry_settings"]["endpoint"] == ENDPOINT
    assert captured["foundry_settings"]["agent_id"] == AGENT_ID

    # What the button sent before the fix, and the answer the administrator saw.
    flat_response, flat_status, _captured = run_server_test(managed["flat_payload"])
    assert flat_status == 400, f"A blank connection was accepted: {flat_response}"
    for message in (
        "Foundry Project Endpoint is required.",
        "Foundry API Version is required.",
        "Foundry Agent ID is required.",
    ):
        assert message in flat_response["guidance"], flat_response

    print("  The saved endpoint, API version and agent ID reach the Foundry agent call.")
    return True


def test_a_saved_service_principal_is_tested_as_one():
    """Reading the saved auth type as blank would test a service principal as an identity."""
    print("\nTesting the connection-test payload for a saved service principal...")

    results = reader_results()
    if results is None:
        return True

    foundry = results["service_principal"]["payload"]["foundry"]
    assert foundry["authentication_type"] == "service_principal"
    assert foundry["tenant_id"] == TENANT_ID
    assert foundry["client_id"] == CLIENT_ID
    assert "managed_identity_type" not in foundry

    # The browser only holds the mask. The route swaps it for the stored secret, read
    # from the same nested path the field declares.
    assert foundry["client_secret"] == fields_module.SECRET_REDACTED_VALUE
    stored = save_connection(SERVICE_PRINCIPAL)
    resolved = secret_utils.resolve_admin_settings_secret_value(
        secret_storage_path(), foundry["client_secret"], stored
    )
    assert resolved == CLIENT_SECRET, "The masked client secret did not resolve."

    payload = copy.deepcopy(results["service_principal"]["payload"])
    payload["foundry"]["client_secret"] = resolved
    response, status_code, captured = run_server_test(payload)
    assert status_code == 200, f"The server rejected the saved connection: {response}"
    assert captured["foundry_settings"]["authentication_type"] == "service_principal"
    assert captured["foundry_settings"]["client_secret"] == CLIENT_SECRET

    print("  The saved service principal is tested with its own credentials.")
    return True


def test_fields_gated_on_the_saved_auth_type_are_shown():
    """A gate saved at a nested path still decides which fields are on screen."""
    print("\nTesting visibility of fields gated on the saved authentication type...")

    results = reader_results()
    if results is None:
        return True

    managed = results["managed_identity"]["visible"]
    assert managed["web_search_foundry_managed_identity_type"] is True, (
        "Managed Identity Type is hidden although Managed Identity is the saved choice."
    )
    for key in SERVICE_PRINCIPAL_KEYS:
        assert managed[key] is False, f"{key} is shown for a managed identity connection."

    principal = results["service_principal"]["visible"]
    for key in SERVICE_PRINCIPAL_KEYS:
        assert principal[key] is True, f"{key} is hidden although Service Principal is saved."
    assert principal["web_search_foundry_managed_identity_type"] is False
    # Only a custom cloud needs an authority, and the saved cloud is Azure Public.
    assert principal["web_search_foundry_authority"] is False

    print("  The fields for the saved authentication type are the ones shown.")
    return True


def test_a_saved_connection_reads_as_configured():
    """The section status reads the same saved values the controls show."""
    print("\nTesting the Web Search section status...")

    results = reader_results()
    if results is None:
        return True

    assert results["managed_identity"]["status"] == "ready"
    assert results["service_principal"]["status"] == "ready"
    assert results["not_configured"]["status"] == "incomplete"

    print("  A saved connection reads as configured; an empty one still does not.")
    return True


def test_a_saved_client_secret_is_recognized():
    """The secret field must know a credential is saved to warn before clearing it."""
    print("\nTesting the stored value behind the client secret field...")

    results = reader_results()
    if results is None:
        return True

    assert results["service_principal"]["stored_secret"] == fields_module.SECRET_REDACTED_VALUE
    assert results["managed_identity"]["stored_secret"] is None

    print("  The saved client secret is recognized at its nested path.")
    return True


def test_an_unsaved_edit_still_wins():
    """Testing before saving is the point, so an edit outranks the saved value."""
    print("\nTesting that an unsaved edit is what the connection test sends...")

    results = reader_results()
    if results is None:
        return True

    foundry = results["edited_endpoint"]["payload"]["foundry"]
    assert foundry["endpoint"] == EDITED_ENDPOINT
    assert foundry["agent_id"] == AGENT_ID, "The saved values should fill in the rest."

    print("  The edited endpoint is sent, with the saved values alongside it.")
    return True


def test_the_page_hands_the_field_index_to_every_reader():
    """The readers only find a nested value when the page passes them the index."""
    print("\nTesting that the page wires the field index through...")

    page = PAGE_TSX.read_text(encoding="utf-8")

    for component in ("SettingsSection", "ConnectionTest"):
        assert re.search(
            rf"<{component}\b[^>]*?fieldsByKey=\{{fieldsByKey\}}", page, re.DOTALL
        ), f"AdminSettingsPage should pass fieldsByKey to {component}."

    assert "storedValue={readStoredFieldValue(field, settings)}" in page, (
        "The secret field should be told what is saved at the field's storage path."
    )
    assert re.search(
        r"computeSectionStatus\(\s*section\.allFields,[^)]*fieldsByKey,[^)]*\)", page, re.DOTALL
    ), "The section status should be computed with the field index."

    print("  The connection test, section shell, status and secret field get the index.")
    return True


if __name__ == "__main__":
    tests = [
        test_a_saved_connection_lives_inside_web_search_agent,
        test_the_connection_test_sends_the_saved_values,
        test_a_saved_service_principal_is_tested_as_one,
        test_fields_gated_on_the_saved_auth_type_are_shown,
        test_a_saved_connection_reads_as_configured,
        test_a_saved_client_secret_is_recognized,
        test_an_unsaved_edit_still_wins,
        test_the_page_hands_the_field_index_to_every_reader,
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
