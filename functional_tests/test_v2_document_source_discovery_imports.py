# test_v2_document_source_discovery_imports.py
"""Cold document-source discovery and route failures against real configuration.

Version: 0.261.400
Implemented in: 0.261.400

Only external storage I/O is replaced. Real config, discovery, authorization,
public payload projection and route registration execute with network blocked.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
PROBE = r'''
import importlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from flask import Blueprint, Flask
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    import config
    import functions_document_source_discovery as discovery
    import route_backend_v2 as routes
    from functions_authentication import user_required_blueprint

    config.cosmos_user_settings_container.upsert_item(body={
        "id": "reader", "settings": {
            "profileImage": None, "personal_model_endpoints": [],
            "showTutorialButtons": True, "desktopNotificationsEnabled": True,
        },
    })
    settings = {"enable_group_workspaces": True, "enable_public_workspaces": True}
    owners = {"personal": "reader", "group": "group-1", "public": "public-1"}
    containers = {
        "personal": config.cosmos_user_documents_container,
        "group": config.cosmos_group_documents_container,
        "public": config.cosmos_public_documents_container,
    }

    def metadata_query(kind, *, query, parameters, **kwargs):
        parameters = {parameter["name"]: parameter["value"] for parameter in parameters}
        if "JOIN s IN c.shared_group_ids" in query:
            return []
        if "GROUP BY" in query:
            if parameters.get("@owners") != [owners[kind]]:
                raise AssertionError("Discovery queried the wrong workspace owner.")
            return [{"owner": owners[kind], "count": 1}]
        if "DISTINCT VALUE t" in query:
            return ["policy"]
        if parameters.get("@owner") != owners[kind]:
            raise AssertionError("Document page lost its workspace predicate.")
        return [{"id": f"{kind}-document", "file_name": f"{kind}.pdf", "tags": ["policy"]}]

    app = Flask("document_source_discovery_imports")
    app.config.update(TESTING=True, SECRET_KEY="fixture-only-signing")
    bp = Blueprint("backend_v2", __name__)
    bp.before_request(user_required_blueprint())
    routes.register_route_backend_v2(bp)
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": "reader", "roles": ["User"]}

    with ExitStack() as stack:
        stack.enter_context(patch.object(config.cosmos_groups_container, "query_items", return_value=[
            {"id": "group-1", "name": "Policy group", "users": [{"userId": "reader"}]},
        ]))
        stack.enter_context(patch.object(config.cosmos_public_workspaces_container, "query_items", return_value=[
            {"id": "public-1", "name": "Policy library", "status": "active"},
        ]))
        for kind, container in containers.items():
            stack.enter_context(patch.object(
                container, "query_items",
                side_effect=lambda kind=kind, **kwargs: metadata_query(kind, **kwargs),
            ))
        stack.enter_context(patch.object(routes, "get_settings", return_value=settings))
        logs = stack.enter_context(patch.object(routes, "log_event"))

        response = client.get("/api/v2/document-sources?query=")
        payload = response.get_json()
        if response.status_code != 200:
            raise AssertionError(f"Initial directory failed: {response.status_code}, {payload}")
        if payload["source_total"] != 3 or payload["matching_workspace_count"] != 3:
            raise AssertionError("Directory lost authorized workspaces or document counts.")
        if [row["document"]["id"] for row in payload["documents"]] != [
            "personal-document", "group-document", "public-document",
        ]:
            raise AssertionError("Discovery did not read all three configured document containers.")

        page = discovery.discover_document_sources("reader", settings, page_size=1, source_offset=1)
        if page["documents"][0]["document"]["id"] != "group-document" or page["source_next"] != 2:
            raise AssertionError("Document pagination no longer crosses workspace boundaries.")
        for kind in containers:
            key = f"{kind}:{'' if kind == 'personal' else owners[kind]}"
            response = client.get("/api/v2/document-sources", query_string={"query": "policy", "workspace": key})
            page = response.get_json()
            if response.status_code != 200 or page["source_total"] != 1 or page["tags"] != ["policy"]:
                raise AssertionError("Scoped document/tag discovery failed.")
            if page["documents"][0]["document"]["id"] != f"{kind}-document":
                raise AssertionError("Workspace browsing read a different document container.")

        logs.reset_mock()
        with patch.object(config.cosmos_user_documents_container, "query_items",
                          side_effect=RuntimeError("PRIVATE_STORAGE_DIAGNOSTIC")):
            response = client.get("/api/v2/document-sources")
        if response.status_code != 503 or response.get_json() != {
            "error": "Could not load document sources. Please retry.",
        }:
            raise AssertionError("Storage failure was hidden or exposed private diagnostics.")
        logs.assert_called_once()
        if logs.call_args.kwargs.get("exceptionTraceback") is not True:
            raise AssertionError("Discovery failure did not request a server-side traceback.")
        if logs.call_args.kwargs["extra"] != {"error_type": "RuntimeError"}:
            raise AssertionError("Discovery failure lost its safe error-type dimension.")

    if environment.network_attempts:
        raise AssertionError("Discovery attempted external I/O.")
print("PASS: real configured document discovery and safe route failure")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("config", "functions_document_source_discovery"),
    ("functions_document_source_discovery", "config"),
])
def test_real_config_discovery_and_route_failure(order, optimized):
    command = [sys.executable, "-B"] + (["-O"] if optimized else [])
    process = subprocess.run(
        command + ["-c", PROBE, str(APP), str(TESTS), *order],
        cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
    )
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS: real configured document discovery and safe route failure" in process.stdout
