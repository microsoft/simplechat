# test_m365_file_runtime.py
"""
Functional regressions for persisted Microsoft 365 request budgets.
Version: 0.261.035
Implemented in: 0.261.030

Loads the real resolver with scoped owner/I/O dependencies. Conditional-write
conflicts never reset budgets, switch identities, or return an implicit None.
"""

import importlib.util
import json
from pathlib import Path
import sys
import types
from unittest.mock import Mock

from azure.cosmos.exceptions import CosmosHttpResponseError
from flask import Flask, g
import pytest
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

# Standalone tests initialize the source path before repository imports.
from functions_m365_execution import M365ExecutionContext
from functions_m365_transport import M365ProviderError
from functions_model_capabilities import ModelTokenBudget
from test_support.m365 import CosmosContainer


@pytest.fixture
def runtime(monkeypatch):
    jobs = CosmosContainer("user_id")
    create_budget = Mock(return_value="budget-run")
    memory = Mock(return_value=(object(), object()))
    seams = {
        "config": {"cosmos_m365_execution_runs_container": jobs},
        "conversation_memory_runtime": {"resolve_m365_memory": memory},
        "functions_m365_retrieval": {
            "configure_m365_retrieval": Mock(), "create_m365_request_budget": create_budget,
        },
        "functions_m365_agent_continuation": {"configure_m365_agent_continuation": Mock()},
        "functions_m365_analysis_runtime": {"analyze_m365_memory": Mock()},
        "functions_m365_workflow_checkpoints": {"configure_m365_workflow_checkpoints": Mock()},
    }
    for name, values in seams.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("test_file_runtime", APP / "functions_m365_file_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = M365ExecutionContext(
        "owner", "owner", "tenant", conversation_id="conversation", request_id="request",
    )
    app = Flask(__name__)
    with app.test_request_context():
        yield types.SimpleNamespace(
            module=module, jobs=jobs, context=context, create_budget=create_budget, memory=memory,
        )


def seed_request(runtime, **changes):
    return runtime.jobs.create_item(body={
        "id": "request", "user_id": "owner", "actor_user_id": "owner",
        "conversation_id": "conversation", "memory_budget_initializing": True,
        **changes,
    })


def test_new_request_reuses_one_budget_and_never_resets_its_counters(runtime):
    first = runtime.module.resolve_m365_budget_run(runtime.context)
    second = runtime.module.resolve_m365_budget_run(runtime.context)
    saved = runtime.jobs.read_item("request", "owner")
    assert first == second == "budget-run"
    assert saved["memory_budget_run_id"] == first
    assert g.m365_has_pending_record is True
    runtime.create_budget.assert_called_once()
    runtime.memory.assert_called_once_with(runtime.context)


@pytest.mark.parametrize("conflicts", [1, 3])
def test_conditional_conflicts_retry_the_same_budget_with_fresh_etags(runtime, monkeypatch, conflicts):
    seed_request(runtime)
    replace = runtime.jobs.replace_item
    attempts = []

    def racing_replace(item, body, **kwargs):
        attempts.append(body["memory_budget_run_id"])
        if len(attempts) <= conflicts:
            current = runtime.jobs.read_item(item, body["user_id"])
            runtime.jobs.upsert_item({**current, "other_worker_progress": len(attempts)})
            raise CosmosHttpResponseError(status_code=412)
        return replace(item, body, **kwargs)

    monkeypatch.setattr(runtime.jobs, "replace_item", racing_replace)
    result = runtime.module.resolve_m365_budget_run(runtime.context)
    saved = runtime.jobs.read_item("request", "owner")
    assert result == "budget-run"
    assert attempts == ["budget-run"] * (conflicts + 1)
    assert saved["other_worker_progress"] == conflicts
    assert "memory_budget_initializing" not in saved
    runtime.create_budget.assert_called_once()


def test_final_conflict_exhaustion_is_an_error_not_an_empty_budget(runtime, monkeypatch):
    seed_request(runtime)
    conflict = Mock(side_effect=CosmosHttpResponseError(status_code=412))
    monkeypatch.setattr(runtime.jobs, "replace_item", conflict)
    with pytest.raises(CosmosHttpResponseError) as raised:
        runtime.module.resolve_m365_budget_run(runtime.context)
    saved = runtime.jobs.read_item("request", "owner")
    assert raised.value.status_code == 412
    assert conflict.call_count == 4
    assert "memory_budget_run_id" not in saved
    assert "m365_has_pending_record" not in g
    runtime.create_budget.assert_called_once()


def test_conflict_cannot_switch_to_another_request_budget(runtime, monkeypatch):
    seed_request(runtime)

    def conflicting_budget(item, body, **kwargs):
        current = runtime.jobs.read_item(item, body["user_id"])
        runtime.jobs.upsert_item({**current, "memory_budget_run_id": "different-budget"})
        raise CosmosHttpResponseError(status_code=412)

    monkeypatch.setattr(runtime.jobs, "replace_item", conflicting_budget)
    with pytest.raises(M365ProviderError) as raised:
        runtime.module.resolve_m365_budget_run(runtime.context)
    assert raised.value.code == "request_memory_mismatch"
    assert "m365_has_pending_record" not in g
    runtime.create_budget.assert_called_once()


@pytest.mark.parametrize("field", ["conversation_id", "actor_user_id"])
def test_mismatched_request_identity_is_rejected_before_creating_a_budget(runtime, field):
    seed_request(runtime, **{field: "other", "memory_budget_run_id": "unrelated-budget"})
    with pytest.raises(M365ProviderError) as raised:
        runtime.module.resolve_m365_budget_run(runtime.context)
    assert raised.value.code == "request_memory_mismatch"
    runtime.create_budget.assert_not_called()
    runtime.memory.assert_not_called()


@pytest.mark.parametrize("status", [403, 429, 500])
def test_non_conflict_storage_failures_are_surfaced_without_retry(runtime, monkeypatch, status):
    seed_request(runtime)
    failure = Mock(side_effect=CosmosHttpResponseError(status_code=status))
    monkeypatch.setattr(runtime.jobs, "replace_item", failure)
    with pytest.raises(CosmosHttpResponseError) as raised:
        runtime.module.resolve_m365_budget_run(runtime.context)
    assert raised.value.status_code == status
    assert failure.call_count == 1
    assert "m365_has_pending_record" not in g


def test_model_room_counts_dict_messages_instructions_and_tool_schemas(runtime):
    budget = ModelTokenBudget(
        context_window=20000, input_limit=18000, output_limit=5000,
        request_output_limit=1000, output_accounting="total_generation",
    )
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "search", "description": "x" * 1000}}]
    token = runtime.module.configure_m365_model_context(
        budget, messages, instructions="Use sources", tool_schemas=tools,
    )
    try:
        room = runtime.module.resolve_m365_model_room(runtime.context)
    finally:
        runtime.module.reset_m365_model_context(token)
    expected_bytes = len(json.dumps(messages[0]).encode()) + 256 + len("Use sources") + len(json.dumps(tools).encode()) + 4096
    assert room == 18000 - expected_bytes
    assert runtime.module._model_context.get() is None


def test_serialized_tool_arguments_are_included_even_without_visible_content(runtime):
    message = ChatMessageContent(role=AuthorRole.ASSISTANT, items=[
        FunctionCallContent(id="call", name="search", arguments=json.dumps({"query": "x" * 3000})),
    ])
    budget = ModelTokenBudget(context_window=20000, request_output_limit=1000, output_accounting="total_generation")
    token = runtime.module.configure_m365_model_context(budget, [message])
    try:
        room = runtime.module.resolve_m365_model_room(runtime.context)
    finally:
        runtime.module.reset_m365_model_context(token)
    assert room < 20000 - 1000 - 4096 - 3000


@pytest.mark.parametrize("message", [
    {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid/image"}}]},
    {"role": "user", "items": [{"content_type": "audio", "uri": "https://example.invalid/audio"}]},
])
def test_remote_media_is_not_budgeted_as_short_url_text(runtime, message):
    budget = ModelTokenBudget(context_window=20000, output_limit=1000, output_accounting="total_generation")
    token = runtime.module.configure_m365_model_context(budget, [message])
    try:
        with pytest.raises(M365ProviderError) as error:
            runtime.module.resolve_m365_model_room(runtime.context)
    finally:
        runtime.module.reset_m365_model_context(token)
    assert error.value.code == "model_input_estimate_unavailable"


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
