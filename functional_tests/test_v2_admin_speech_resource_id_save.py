# test_v2_admin_speech_resource_id_save.py
"""
Regression coverage for V2 Speech Resource ID settings saves.
Version: 0.261.397
Implemented in: 0.261.397

Exercise the real normalizer and registered Flask routes in offline processes.
Built and pasted IDs must save with companion settings without relaxing other
component restrictions, authentication, redaction, or atomic failure handling.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
SPEECH_RESOURCE_ID = (
    "/subscriptions/12345678-1234-1234-1234-123456789abc"
    "/resourceGroups/rg-speech-test"
    "/providers/Microsoft.CognitiveServices/accounts/speech-test"
)


@pytest.mark.parametrize("padding", ["", " \r\n"])
def test_speech_resource_id_uses_text_normalization(padding):
    fields = import_app_module("admin_settings_fields")
    normalized, errors, warnings = fields.normalize_admin_settings_updates({
        "speech_service_resource_id": f"{padding}{SPEECH_RESOURCE_ID}{padding}",
        "speech_service_authentication_type": "managed_identity",
        "enable_text_to_speech": True,
    })

    assert not errors, errors
    assert not warnings, warnings
    assert normalized == {
        "speech_service_resource_id": SPEECH_RESOURCE_ID,
        "speech_service_authentication_type": "managed_identity",
        "enable_text_to_speech": True,
    }


@pytest.mark.parametrize("value", ["", None, "   "])
def test_speech_resource_id_can_still_be_cleared(value):
    fields = import_app_module("admin_settings_fields")
    normalized, errors, _warnings = fields.normalize_admin_settings_updates({
        "speech_service_resource_id": value,
        "speech_service_authentication_type": "key",
    })

    assert not errors, errors
    assert normalized["speech_service_resource_id"] == ""


PROBE = r'''
import copy
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))

from test_support.offline_bootstrap import offline_app_imports


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports(), ExitStack() as stack:
    import route_backend_v2 as v2
    from admin_settings_fields import get_field_definition

    stored = {
        "speech_service_authentication_type": "key",
        "speech_service_resource_id": "",
        "speech_service_key": "offline-speech-key",
        "enable_text_to_speech": False,
        "app_title": "Before save",
    }
    writes = []
    fail_write = False

    def save(changes):
        writes.append(copy.deepcopy(changes))
        if fail_write:
            return False
        stored.update(copy.deepcopy(changes))
        return True

    stack.enter_context(patch.object(v2, "get_settings", side_effect=lambda **kwargs: copy.deepcopy(stored)))
    stack.enter_context(patch.object(v2, "update_settings", side_effect=save))
    stack.enter_context(patch.object(v2, "_refresh_branding_static_files"))
    stack.enter_context(patch.object(v2, "ensure_m365_workflow_encryption_key", return_value={"status": "not_configured"}))
    # The settings GET also probes a separate browser runtime; keep that I/O offline.
    stack.enter_context(patch.object(v2, "get_source_review_runtime_capabilities", return_value={}))
    stack.enter_context(patch.object(v2, "log_event"))
    app = Flask("v2-speech-resource-id")
    app.config.update(TESTING=True, SECRET_KEY="offline-test-only")
    bp = Blueprint("speech_settings", __name__)
    v2.register_route_backend_v2_admin(bp)
    app.register_blueprint(bp)
    client = app.test_client()

    field = get_field_definition("speech_service_resource_id")
    builder_values = {
        "subscription": "12345678-1234-1234-1234-123456789abc",
        "resource_group": "rg-speech-test",
        "resource_name": "speech-test",
    }
    resource_id = field["builder_template"].format(**builder_values)
    draft = {
        "speech_service_resource_id": resource_id,
        "speech_service_authentication_type": "managed_identity",
        "speech_service_endpoint": " https://speech-test.cognitiveservices.azure.com/ ",
        "speech_service_location": " eastus ",
        "enable_text_to_speech": True,
        "app_title": "Speech settings saved together",
        **{key: builder_values[name] for name, key in field["builder_sources"].items()},
    }

    response = client.patch("/api/v2/admin/settings", json={"settings": draft})
    check(response.status_code == 401, "Anonymous settings write was allowed.")
    with client.session_transaction() as session:
        session["user"] = {"oid": "offline-user", "roles": ["User"]}
    response = client.patch("/api/v2/admin/settings", json={"settings": draft})
    check(response.status_code == 403, "Non-admin settings write was allowed.")
    check(not writes, "An unauthorized request reached persistence.")
    with client.session_transaction() as session:
        session["user"] = {"oid": "offline-admin", "roles": ["Admin"]}

    # Exercise both the builder's exact output and a whitespace-padded pasted ID.
    for candidate in (resource_id, f" \r\n{resource_id} \r\n"):
        response = client.patch("/api/v2/admin/settings", json={
            "settings": {**draft, "speech_service_resource_id": candidate},
        })
        body = response.get_json()
        check(response.status_code == 200 and body["success"], str(body))
        check(body["settings"]["speech_service_resource_id"] == resource_id, str(body))
        check(set(body["updated_keys"]) == set(draft), "A companion setting was dropped.")
        expected = {**draft, "speech_service_endpoint": draft["speech_service_endpoint"].strip(),
                    "speech_service_location": "eastus"}
        check(writes[-1] == expected, str(writes[-1]))
        check(all(stored[key] == value for key, value in expected.items()), "Save did not persist.")
        response = client.get("/api/v2/admin/settings")
        body = response.get_json()
        check(response.status_code == 200, str(body))
        check(body["settings"]["speech_service_resource_id"] == resource_id, "Reload lost the ID.")
        check(body["settings"]["speech_service_key"] == v2.SECRET_REDACTED_VALUE,
              "GET did not redact the Speech key.")

    snapshot = copy.deepcopy(stored)
    write_count = len(writes)
    rejected_changes = (
        {"embedding_model": {"selected": [], "all": []}},
        {"image_gen_model": {"selected": [], "all": []}},
        {v2.EMBEDDING_VECTOR_PROFILE_KEY: {}},
        {"speech_service_authentication_type": "invalid-auth"},
    )
    for changes in rejected_changes:
        response = client.patch("/api/v2/admin/settings", json={"settings": {
            **draft, "app_title": "Must remain unsaved", **changes,
        }})
        body = response.get_json()
        check(response.status_code == 400, str(body))
        check(set(changes) <= set(body["field_errors"]), str(body))
        check("settings" not in body and "updated_keys" not in body, "Failure echoed a saved draft.")
        check(len(writes) == write_count and stored == snapshot, "Rejected save partially persisted.")

    fail_write = True
    response = client.patch("/api/v2/admin/settings", json={"settings": {
        **draft, "app_title": "Persistence failure must remain unsaved",
    }})
    body = response.get_json()
    check(response.status_code == 503 and body["success"] is False, str(body))
    check(stored == snapshot, "Failed persistence mutated stored settings.")
    check("settings" not in body and "updated_keys" not in body, "Failed persistence looked successful.")
    fail_write = False

    # Clearing an optional stored ID when returning to key auth retains existing semantics.
    response = client.patch("/api/v2/admin/settings", json={"settings": {
        "speech_service_resource_id": "",
        "speech_service_authentication_type": "key",
        "speech_service_key": v2.SECRET_REDACTED_VALUE,
    }})
    body = response.get_json()
    check(response.status_code == 200, str(body))
    check(stored["speech_service_resource_id"] == "", "The resource ID could not be cleared.")
    check(stored["speech_service_key"] == "offline-speech-key", "An untouched key was overwritten.")
    check(body["settings"]["speech_service_key"] == v2.SECRET_REDACTED_VALUE,
          "PATCH did not redact the Speech key.")

print("Real V2 Speech settings routes: save, reload, restrictions, auth, redaction and failures passed.")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_registered_v2_speech_settings_routes(optimized):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        [*command, "-c", PROBE, str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert_app_version_at_least("0.261.397")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
