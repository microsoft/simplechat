# test_workflow_history_source_access.py
"""
Functional tests for workflow history, preview, and activity source inheritance.
Version: 0.261.108
Implemented in: 0.261.108

History authorization follows real stored producer receipts and does not rely on
the workflow owner's old permissions or the visible UI's item limit.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_workflow_result_contract import SerializedSections, WORKFLOW, RUN_ID
from functions_analysis_access import AnalysisResultUnavailable, build_analysis_access
from functions_workflow_results import (
    authorize_workflow_run_read,
    build_workflow_task_result,
    load_workflow_task_input,
    persist_workflow_task_result,
    workflow_result_summary,
)


ROUTES = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_workflows.py"


def history():
    store = SerializedSections()
    state = {"allowed": True, "readers": []}

    def sources(ids, **kwargs):
        state["readers"].append(kwargs["user_id"])
        return [{
            "document_id": identifier, "scope": "group", "scope_id": "group-source",
            "authorization_status": "authorized" if state["allowed"] else "unresolved",
        } for identifier in ids]

    first = build_workflow_task_result({
        "reply": "Final source findings.",
        "analysis_access": build_analysis_access([{
            "document_id": "source", "scope_type": "group", "scope_id": "group-source",
        }]),
    }, workflow=WORKFLOW, run_id=RUN_ID, task={"id": "first"})
    first_manifest, first_ref = persist_workflow_task_result(
        first, workflow=WORKFLOW, run_id=RUN_ID, task_id="first", save_result=store.save,
    )
    _, receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, "first", first_ref, load_result=store.load, source_resolver=sources,
    )
    second = build_workflow_task_result(
        {"reply": "A derived explanation."}, workflow=WORKFLOW, run_id=RUN_ID, task={"id": "second"},
    )
    second["consumed_inputs"] = [receipt]
    second_manifest, second_ref = persist_workflow_task_result(
        second, workflow=WORKFLOW, run_id=RUN_ID, task_id="second", save_result=store.save,
    )
    items = [
        {"workflow_id": WORKFLOW["id"], "run_id": RUN_ID, "task_id": task_id, "item_type": "task",
         "workflow_result": workflow_result_summary(manifest, reference)}
        for task_id, manifest, reference in (
            ("first", first_manifest, first_ref), ("second", second_manifest, second_ref),
        )
    ]
    return store, state, sources, items


def test_history_rechecks_transitive_sources_as_the_current_reader():
    store, state, sources, items = history()
    authorize_workflow_run_read(
        WORKFLOW, RUN_ID, result_items=[items[1]], reader_user_id="current-reader",
        load_result=store.load, source_resolver=sources,
    )
    assert state["readers"][-1] == "current-reader"
    state["allowed"] = False
    with pytest.raises(AnalysisResultUnavailable):
        authorize_workflow_run_read(
            WORKFLOW, RUN_ID, result_items=[items[1]], reader_user_id="current-reader",
            load_result=store.load, source_resolver=sources,
        )


def test_history_authorization_does_not_stop_at_the_old_thousand_item_limit():
    store, state, sources, items = history()
    state["allowed"] = False
    pending = [{"item_type": "task", "workflow_result": {}} for _ in range(1000)]
    with pytest.raises(AnalysisResultUnavailable):
        authorize_workflow_run_read(
            WORKFLOW, RUN_ID, result_items=iter([*pending, items[1]]),
            reader_user_id="current-reader", load_result=store.load, source_resolver=sources,
        )


def test_definition_catalog_redacts_cached_text_without_hiding_editable_settings():
    store, state, sources, items = history()
    namespace = {
        "AnalysisResultUnavailable": AnalysisResultUnavailable,
        "authorize_workflow_run_read": lambda workflow, run_id, **kwargs: authorize_workflow_run_read(
            workflow, run_id, result_items=items, load_result=store.load, source_resolver=sources, **kwargs,
        ),
    }
    node = next(node for node in ast.parse(ROUTES.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == "_workflow_definition_response")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROUTES), "exec"), namespace)
    workflow = {
        **WORKFLOW, "last_run_id": RUN_ID, "name": "Still editable",
        "last_run_response_preview": "PRIVATE-DERIVED-OUTPUT", "last_run_error": "",
    }
    state["allowed"] = False
    response = namespace["_workflow_definition_response"](workflow, "current-reader")
    assert response["name"] == "Still editable"
    assert response["result_access"] == "source_unavailable"
    assert "PRIVATE-DERIVED-OUTPUT" not in str(response)
    workflow.pop("last_run_id")
    assert namespace["_workflow_definition_response"](workflow, "current-reader")["result_access"] == "legacy_preview_unbound"


@pytest.mark.parametrize("group", [False, True])
def test_activity_stream_stops_before_emitting_revoked_source_content(group):
    calls = []

    def snapshot(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise AnalysisResultUnavailable()
        return {"run": {"status": "running"}, "activities": [{"title": "Authorized first update"}]}

    name = "_stream_group_workflow_activity" if group else "_stream_workflow_activity"
    namespace = {
        "AnalysisResultUnavailable": AnalysisResultUnavailable, "json": json,
        "time": SimpleNamespace(sleep=lambda seconds: None),
        "_resolve_workflow_activity_context": snapshot,
        "_resolve_group_workflow_activity_context": snapshot,
    }
    node = next(node for node in ast.parse(ROUTES.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROUTES), "exec"), namespace)
    args = ("reader", "group") if group else ("reader",)
    frames = list(namespace[name](*args, run_id=RUN_ID))
    assert len(calls) == 2
    assert frames[-1].startswith("event: error")
    assert "source_access_denied" in frames[-1]
