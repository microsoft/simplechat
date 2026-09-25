# test_orchestration_catalog_auto_execution.py
"""Exercise catalog-selected agent/action execution and Auto routing.

Version: 0.261.139
Implemented in: 0.261.126
Single orchestration contract updated in: 0.261.139

Uses production adapters, model routing, and dependency-plan validation with offline
provider responses and explicitly authorized candidate inventories.
"""

import importlib
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_execution_context import DelegationBudget, ExecutionIdentity
from functions_orchestration_model_routing import assign_step_models
from test_support.app_stubs import APP_ROOT, stubbed_config
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

IMPLEMENTED_IN = "0.261.126"
SINGLE_CONTRACT_UPDATED_IN = "0.261.139"


def fake_module(name, **values):
    module = type(sys)(name)
    module.__dict__.update(values)
    return module


def _capture(*args, **kwargs):
    return None


def _context(modules, *, agent_catalog=(), action_catalog=()):
    return modules.executor.RunContext(
        run_id="run-1", attempt_index=1,
        user_id="user1", conversation_id="conv1", user_message="Use the selected catalog item.",
        agent_catalog=list(agent_catalog), action_catalog=list(action_catalog),
        user_enable_agents=True,
        agent_execution_identity=ExecutionIdentity(user_id="user1", conversation_id="conv1"),
        delegation_budget=DelegationBudget(),
        capture_external_source_configuration=_capture,
        external_source_preflight=lambda **kwargs: None,
    )


@pytest.fixture(scope="module")
def modules():
    with stubbed_config(cognitive_services_scope="https://cognitiveservices.azure.com/.default"):
        return SimpleNamespace(
            adapters=importlib.import_module("functions_orchestration_adapters"),
            executor=importlib.import_module("functions_orchestration_executor"),
            schema=importlib.import_module("functions_orchestration_schema"),
        )


def test_version_includes_single_contract_update():
    assert_app_version_at_least(IMPLEMENTED_IN)
    assert_app_version_at_least(SINGLE_CONTRACT_UPDATED_IN)


def test_catalog_selected_action_step_executes_and_forwards_visual_flags(modules):
    action = {"action_ref": "global:global:sim", "id": "sim", "name": "sim", "display_name": "Simulation"}
    calls = []

    async def invoke_action(action_ref, task, context, **kwargs):
        calls.append((action_ref, task, kwargs))
        kwargs["invocation_capture"]("action", settings={}, source={"action_ref": action_ref}, selector=action_ref)
        return {"findings": "Action result", "artifacts": [], "invocations": [], "root_id": "root", "calls": 1, "charts": 0}

    stubs = {
        "functions_orchestration_actions": fake_module("functions_orchestration_actions", invoke_action=invoke_action),
        "semantic_kernel_plugins.plugin_invocation_logger": fake_module(
            "semantic_kernel_plugins.plugin_invocation_logger",
            sanitize_plugin_invocation_value=lambda value, max_string_length=20000: value,
        ),
        "functions_message_artifacts": fake_module(
            "functions_message_artifacts",
            build_agent_citation_tool_label=lambda plugin, function, *args: f"{plugin}.{function}",
            make_json_serializable=lambda value: value,
        ),
    }
    class Capture:
        def __call__(self, *args, **kwargs):
            return None

        def require_valid(self, *, captured=False):
            return None

    step = {
        "step_id": "action", "capability_id": "action_invoke",
        "arguments": {"action_ref": action["action_ref"], "task": "Gather rows.", "visuals": ["chart"]},
    }
    with patch.dict(sys.modules, stubs), patch.object(
        modules.adapters, "_external_invocation_capture", lambda *args, **kwargs: Capture(),
    ):
        result = modules.adapters.run_action_invoke(
            step, _context(modules, action_catalog=[action]), settings={}, user_id="user1",
            emit=None, cancel_requested=lambda: False,
        )
    assert result["status"] == "completed", result
    assert result["summary"] == "Used Simulation (1 function calls)."
    assert calls[0][0] == action["action_ref"]
    assert calls[0][2]["visual_request"]["chart"] is True


def test_action_step_refuses_items_absent_from_the_authorized_catalog(modules):
    step = {
        "step_id": "action", "capability_id": "action_invoke",
        "arguments": {"action_ref": "global:global:missing", "task": "Gather rows."},
    }
    result = modules.adapters.run_action_invoke(
        step, _context(modules, action_catalog=[]), settings={}, user_id="user1",
        emit=None, cancel_requested=lambda: False,
    )
    assert result["status"] == "failed"
    assert result["failure"]["code"] == "step_failed"


def test_catalog_selected_agent_step_executes_with_the_server_identity(modules):
    agent = {
        "id": "agent1", "name": "RecoveryAgent", "display_name": "Recovery agent",
        "catalog_key": "global:global:agent1",
    }
    calls = []

    async def invoke_scoped_agent(agent_cfg, task, **kwargs):
        calls.append((deepcopy(agent_cfg), task, kwargs))
        kwargs["invocation_capture"]("agent", settings={}, source={"agent_id": agent_cfg["id"]}, selector=agent_cfg["catalog_key"])
        return {"response": "Agent result", "citations": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}

    stubs = {
        "functions_agent_scope": fake_module("functions_agent_scope", is_selected_agent_scope_enabled=lambda settings, agent_cfg: True),
        "functions_agent_delegation": fake_module(
            "functions_agent_delegation",
            agent_reference=lambda agent_cfg, user_id: {"scope_type": "global", "scope_id": "global", "id": agent_cfg["id"]},
        ),
        "agent_delegation_runtime": fake_module(
            "agent_delegation_runtime", invoke_scoped_agent=invoke_scoped_agent,
            delegation_citations=lambda budget: [],
        ),
        "semantic_kernel_plugins.plugin_invocation_logger": fake_module(
            "semantic_kernel_plugins.plugin_invocation_logger",
            get_plugin_logger=lambda: SimpleNamespace(invocations=lambda: []),
        ),
    }
    class Capture:
        def __call__(self, *args, **kwargs):
            return None

        def require_valid(self, *, captured=False):
            return None

    step = {
        "step_id": "agent", "capability_id": "agent_invoke",
        "arguments": {"agent_name": "RecoveryAgent", "task": "Gather B", "visuals": ["diagram"]},
    }
    with patch.dict(sys.modules, stubs), patch.object(
        modules.adapters, "_external_invocation_capture", lambda *args, **kwargs: Capture(),
    ):
        result = modules.adapters.run_agent_invoke(
            step, _context(modules, agent_catalog=[agent]), settings={"enable_semantic_kernel": True},
            user_id="user1", emit=None, cancel_requested=lambda: False,
        )
    assert result["status"] == "completed", result
    assert result["summary"] == "Agent result"
    assert calls and calls[0][2]["identity"].user_id == "user1"
    assert "Visual output for this request" in calls[0][1]


def test_auto_routed_catalog_plan_ends_in_compose_final_response():
    candidates = [{
        "key": "routed-answer", "label": "routed-answer",
        "selection": {"model_deployment": "routed-answer", "model_provider": "aoai"},
        "profile": {
            "id": "profile-routed", "revision": "rev-1", "archived": False,
            "tasks": {"general": "strong"}, "preferences": {"priority": "standard", "favorite": False},
        },
        "capabilities": {"processesText": True, "generatesText": True},
        "effective_revision": "rev-1",
    }]
    plan = {
        "planner_contract_version": 2,
        "model_routing": "auto",
        "steps": [
            {"step_id": "agent", "capability_id": "agent_invoke", "arguments": {"agent_name": "RecoveryAgent", "task": "Gather B"}},
            compose_step("answer", inputs={
                "agent_notes": {"binding": input_binding("agent", "prepared"), "allow_partial": True},
            }),
        ],
        "final_response": input_binding("answer"),
    }
    assign_step_models(plan, candidates)
    assert plan["steps"][-1]["model_binding"]["selection"]["model_deployment"] == "routed-answer"
    assert plan["final_response"]["step_id"] == "answer"
    assert [step["capability_id"] for step in plan["steps"]] == ["agent_invoke", "compose"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
