# test_admin_storage_container_repair_routes.py
"""Real-module admin repair, authentication, saved settings and partial failures.

Version: 0.261.396
Implemented in: 0.261.396

Fresh normal/optimized processes retain real routes and security decorators.
External services are blocked by the shared offline bootstrap.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch
from azure.core.exceptions import HttpResponseError
from flask import Blueprint, Flask

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "application" / "single_app"))
sys.path.insert(0, str(root / "functional_tests"))
from test_support.offline_bootstrap import offline_app_imports

def check(condition, message):
    if not condition:
        raise AssertionError(message)

class Storage:
    def __init__(self):
        self.containers = {"user-documents", "group-documents"}
        self.denied = set()
        self.creates = []
        self.checks = []
        self.closed = 0
    def get_container_client(self, name):
        owner = self
        class Container:
            def create_container(self, **kwargs):
                owner.creates.append(name)
                check(kwargs["public_access"] is None, "Container must be private")
                if name in owner.denied:
                    error = HttpResponseError("PRIVATE provider diagnostics")
                    error.error_code, error.status_code = "AuthorizationFailure", 403
                    raise error
                if name in owner.containers:
                    error = HttpResponseError("PRIVATE existing storage")
                    error.error_code, error.status_code = "ContainerAlreadyExists", 409
                    raise error
                owner.containers.add(name)
            def exists(self, **kwargs):
                owner.checks.append(name)
                return name in owner.containers
        return Container()
    def close(self):
        self.closed += 1

with offline_app_imports(), ExitStack() as stack:
    import route_backend_settings as routes
    from blob_container_readiness import APPLICATION_BLOB_CONTAINERS
    storage = Storage()
    saved = {"office_docs_authentication_type": "key", "office_docs_storage_account_url": "PRIVATE saved secret"}
    builder = Mock(return_value=storage)
    stack.enter_context(patch.object(routes, "get_settings", return_value=saved))
    stack.enter_context(patch.object(routes, "build_enhanced_citations_blob_service_client", builder))
    stack.enter_context(patch.object(routes, "log_event"))
    app = Flask("storage-repair", root_path=str(root / "application" / "single_app"))
    app.config.update(SECRET_KEY="offline-only", TESTING=True)
    blueprint = Blueprint("repair", __name__)
    routes.register_route_backend_settings(blueprint)
    app.register_blueprint(blueprint)
    client = app.test_client()
    url = "/api/admin/settings/storage/repair-containers"
    response = client.post(url, json={})
    check(response.status_code == 401, "Anonymous caller reached repair")
    with client.session_transaction() as session:
        session["user"] = {"oid": "user", "roles": ["User"]}
    response = client.post(url, json={})
    check(response.status_code == 403, "Non-admin caller reached repair")
    check(builder.call_count == 0 and not storage.creates, "Unauthorized request touched storage")
    with client.session_transaction() as session:
        session["user"] = {"oid": "admin", "roles": ["Admin"]}
    for body in ({"container_name": "arbitrary"}, {"blob_endpoint": "https://untrusted.invalid"}, [], None):
        response = client.post(url, json=body)
        check(response.status_code == 400, "Configuration override or malformed body was accepted")
    check(builder.call_count == 0, "Invalid request touched storage")
    response = client.post(url, json={})
    body = response.get_json()
    check(response.status_code == 200 and body["success"], str(body))
    check(set(storage.creates) == set(APPLICATION_BLOB_CONTAINERS), "Fixed inventory drifted")
    check(sum(row["status"] == "created" for row in body["containers"]) == 3, "Missing containers were not created")
    check(sum(row["status"] == "already_exists" for row in body["containers"]) == 2, "Existing containers were not preserved")
    check(builder.call_args.args == (saved,), "Repair did not use saved configuration")
    check(not storage.checks and storage.closed == 1, "Repair probed containers or leaked its client")
    response = client.post(url, json={})
    check(all(row["status"] == "already_exists" for row in response.get_json()["containers"]), "Repair was not idempotent")
    storage.containers.remove("personal-chat")
    storage.denied.add("personal-chat")
    response = client.post(url, json={})
    body = response.get_json()
    check(response.status_code == 503 and body["success"] is False, "Partial repair claimed success")
    check(len(body["containers"]) == 5, "Partial repair lost per-container outcomes")
    check("PRIVATE" not in json.dumps(body), "Provider or configuration data leaked")
    storage.denied.clear()
    response = client.post(url, json={})
    check(response.status_code == 200, "Explicit repair inherited a failed automatic cooldown")
    before = len(storage.creates)
    response = client.post("/api/admin/settings/test_connection", json={
        "test_type": "enhanced_citations_storage", "authentication_type": "key", "connection_string": "PRIVATE draft"
    })
    check(response.status_code == 200 and len(storage.creates) == before, "Read-only connection test created containers")
    check(len(storage.checks) == 5, "Connection test did not inspect the existing inventory")
    builder.side_effect = ValueError("PRIVATE invalid settings")
    response = client.post(url, json={})
    check(response.status_code == 400 and "PRIVATE" not in response.get_data(as_text=True), "Invalid settings leaked")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_real_admin_repair_contract(optimized):
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", PROBE, str(ROOT)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
