# test_workflow_assist_cosmos_response_contract.py
"""
Functional regressions for the Ask AI workflow base reader's Cosmos response contract.
Version: 0.261.330
Implemented in: 0.261.330

The real installed SDK reads through the shared offline HTTP transport fixture.
These tests cover editor projection, metadata removal, partition isolation and
invalid identifiers without contacting Azure or replacing the storage owner.
"""

from copy import deepcopy
from pathlib import Path
import sys

from azure.cosmos._cosmos_responses import CosmosDict
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Standalone execution establishes repository paths before importing real modules.
import functions_workflow_assist_runtime as runtime  # noqa: E402
from functions_workflow_alert_safety import WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE  # noqa: E402
from functions_workflow_definitions import workflow_definition_revision  # noqa: E402
from test_m365_cosmos_sdk_contract import cosmos_factory  # noqa: E402, F401


@pytest.mark.parametrize("definition_version", [1, 2, 3])
def test_workflow_base_projects_real_sdk_point_response(cosmos_factory, definition_version):
    http, container = cosmos_factory("user_id")
    diagnostic = "Alert condition could not be evaluated: SENTINEL provider detail"
    stored = http.seed({
        "id": "workflow", "user_id": "owner", "name": "Document review",
        "definition_version": definition_version, "definition_revision": "stale",
        "tasks": [{"id": "review", "name": "Review", "prompt": "Review documents."}],
        "schedule": {"kind": "calendar", "frequency": "weekdays", "time_of_day": "07:00"},
        "alert_decision": {
            "matched_rules": [{"condition_type": "model_evaluation", "reason": diagnostic}],
            "message": diagnostic,
        },
    })
    point = container.read_item(item="workflow", partition_key="owner")
    before = deepcopy(http.records)

    loaded = runtime.read_workflow_base(container, "owner", "workflow")

    assert isinstance(point, CosmosDict)
    assert type(point) is not dict
    assert type(loaded) is dict
    assert loaded["id"] == "workflow"
    assert loaded["user_id"] == "owner"
    assert loaded["definition_version"] == definition_version
    assert loaded["tasks"] == stored["tasks"]
    assert type(loaded["tasks"][0]) is dict
    assert loaded["schedule"] == stored["schedule"]
    assert not any(key.startswith("_") for key in loaded)
    expected_revision = workflow_definition_revision(stored)
    assert loaded["definition_revision"] == expected_revision
    assert loaded["definition_revision"] != "stale"
    assert loaded["alert_decision"]["message"] == WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
    assert loaded["alert_decision"]["matched_rules"][0]["reason"] == WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
    assert http.records == before
    assert point["alert_decision"]["message"] == diagnostic
    assert all(method == "GET" for method, _path, _headers in http.calls)
    item_reads = [headers for method, path, headers in http.calls if path.endswith("/docs/workflow")]
    assert len(item_reads) == 2
    assert all(headers["x-ms-documentdb-partitionkey"] == '["owner"]' for headers in item_reads)


@pytest.mark.parametrize("user_id, workflow_id", [("someone-else", "workflow"), ("owner", "missing")])
def test_workflow_base_missing_or_foreign_item_uses_real_sdk_404(cosmos_factory, user_id, workflow_id):
    http, container = cosmos_factory("user_id")
    http.seed({"id": "workflow", "user_id": "owner", "name": "Private workflow"})
    before = deepcopy(http.records)

    loaded = runtime.read_workflow_base(container, user_id, workflow_id)

    assert loaded is None
    assert http.records == before
    item_reads = [(path, headers) for method, path, headers in http.calls if "/docs/" in path]
    assert len(item_reads) == 1
    path, headers = item_reads[0]
    assert path.endswith(f"/docs/{workflow_id}")
    assert headers["x-ms-documentdb-partitionkey"] == f'["{user_id}"]'


@pytest.mark.parametrize("character", ["/", "\\", "?", "#"])
def test_workflow_base_invalid_id_never_calls_sdk(cosmos_factory, character):
    http, container = cosmos_factory("user_id")
    before = list(http.calls)

    loaded = runtime.read_workflow_base(container, "owner", f"workflow{character}other")

    assert loaded is None
    assert http.calls == before


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve())]))
