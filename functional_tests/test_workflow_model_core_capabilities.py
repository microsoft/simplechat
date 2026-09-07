# test_workflow_model_core_capabilities.py
"""
Functional test for Direct Model workflow core capabilities.
Version: 0.250.172
Implemented in: 0.250.063
Enhanced in: 0.250.064; updated in 0.250.172

This test ensures new Direct Model workflows bind their saved model selection
to a Semantic Kernel service and pass the kernel to auto-invoked core tools.
"""

import ast
import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory


ROOT = Path(__file__).resolve().parents[1]
RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"


class FakeKernel:
    """Minimal kernel double that captures the selected chat service."""

    def __init__(self):
        self.services = []

    def add_service(self, service):
        self.services.append(service)


class FakeChatService:
    """Minimal asynchronous chat service double for the workflow adapter."""

    def __init__(self):
        self.call = None

    async def get_chat_message_contents(self, chat_history, settings, **kwargs):
        self.call = {
            "chat_history": chat_history,
            "settings": settings,
            "kwargs": kwargs,
        }
        return [SimpleNamespace(content="Core capability result")]


class FakePluginLogger:
    """Captures conversation-scoped plugin logging interactions."""

    def __init__(self):
        self.cleared_conversations = []
        self.deregistered_keys = []

    def clear_invocations_for_conversation(self, user_id, conversation_id):
        self.cleared_conversations.append((user_id, conversation_id))

    def deregister_callbacks(self, callback_key):
        self.deregistered_keys.append(callback_key)


def load_model_core_helpers():
    """Load the isolated model-core helpers with deterministic dependencies."""
    parsed = ast.parse(RUNNER_FILE.read_text(encoding="utf-8"), filename=str(RUNNER_FILE))
    helper_names = {
        "_workflow_model_chat_capabilities_enabled",
        "_build_workflow_model_context",
        "_resolve_workflow_conversation_context",
        "_workflow_model_core_execution_context",
        "_execute_model_workflow_with_core_capabilities",
        "_execute_model_workflow",
    }
    helper_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    assert len(helper_nodes) == len(helper_names), "Expected all Direct Model core capability helpers."

    kernel = FakeKernel()
    chat_service = FakeChatService()
    plugin_logger = FakePluginLogger()
    loaded_core_plugin_settings = []
    semantic_service_requests = []
    fake_g = SimpleNamespace(conversation_id="previous-conversation")

    @contextmanager
    def ensure_execution_context(_user_id):
        yield

    namespace = {
        "asyncio": asyncio,
        "ChatHistory": ChatHistory,
        "FunctionChoiceBehavior": FunctionChoiceBehavior,
        "Kernel": lambda: kernel,
        "PromptExecutionSettings": PromptExecutionSettings,
        "_add_workflow_activity_thought": lambda *args, **kwargs: None,
        "_build_agent_citations_from_invocations": lambda user_id, conversation_id: [
            {"user_id": user_id, "conversation_id": conversation_id}
        ],
        "_build_workflow_chat_messages": lambda prompt, **kwargs: [
            {"role": "user", "content": prompt}
        ],
        "_collect_agent_alert_targets": lambda user_id, conversation_id: [
            {"user_id": user_id, "conversation_id": conversation_id}
        ],
        "_ensure_execution_context": ensure_execution_context,
        "_execute_cancelable_workflow_step": lambda workflow, run_id, operation: operation(),
        "_execute_raw_model_workflow": lambda *args, **kwargs: {"reply": "legacy"},
        "_extract_message_text": lambda message_content: str(message_content or ""),
        "_get_workflow_group_id": lambda workflow: str(workflow.get("group_id") or ""),
        "_raise_if_workflow_run_cancelled": lambda workflow, run_id: None,
        "_resolve_model_workflow_client": lambda workflow, settings: (
            object(),
            "workflow-deployment",
            "aoai",
        ),
        "build_semantic_kernel_chat_service_for_model": lambda deployment_name, settings, **kwargs: (
            semantic_service_requests.append({
                "deployment_name": deployment_name,
                "settings": settings,
                **kwargs,
            }) or chat_service,
            "azure_openai",
        ),
        "contextmanager": contextmanager,
        "g": fake_g,
        "get_max_auto_invoke_attempts": lambda settings: int(settings["max_auto_invoke_attempts"]),
        "get_plugin_logger": lambda: plugin_logger,
        "get_workflow_kernel_settings": lambda settings: {"max_auto_invoke_attempts": 7},
        "load_core_plugins_only": lambda selected_kernel, settings: loaded_core_plugin_settings.append(
            (selected_kernel, settings)
        ),
        "register_plugin_invocation_thought_callback": lambda *args, **kwargs: "callback-key",
    }
    module = ast.Module(body=helper_nodes, type_ignores=[])
    exec(compile(module, str(RUNNER_FILE), "exec"), namespace)
    return namespace, kernel, chat_service, plugin_logger, loaded_core_plugin_settings, semantic_service_requests, fake_g


def test_direct_model_workflow_binds_core_capabilities_to_saved_model() -> None:
    """Validate direct model core capability execution uses the selected model and kernel."""
    print("Testing Direct Model workflow core capability adapter...")
    (
        helpers,
        kernel,
        chat_service,
        plugin_logger,
        loaded_core_plugin_settings,
        semantic_service_requests,
        fake_g,
    ) = load_model_core_helpers()

    workflow = {
        "id": "workflow-1",
        "user_id": "user-1",
        "group_id": "group-1",
        "task_prompt": "Create a chart from the available tabular data.",
        "model_endpoint_id": "endpoint-1",
        "model_id": "model-1",
        "model_provider": "aoai",
        "chat_capabilities_enabled": True,
    }
    result = helpers["_execute_model_workflow"](
        workflow,
        {"enable_semantic_kernel": True},
        conversation_id="workflow-conversation-1",
        run_id="run-1",
    )

    assert result["reply"] == "Core capability result"
    assert result["core_capabilities_enabled"] is True
    assert result["agent_citations"] == [{"user_id": "user-1", "conversation_id": "workflow-conversation-1"}]
    assert kernel.services == [chat_service]
    assert loaded_core_plugin_settings == [(kernel, {"max_auto_invoke_attempts": 7})]
    assert semantic_service_requests[0]["deployment_name"] == "workflow-deployment"
    assert semantic_service_requests[0]["model_context"] == {
        "user_id": "user-1",
        "model_deployment": "workflow-deployment",
        "provider": "aoai",
        "endpoint_id": "endpoint-1",
        "model_id": "model-1",
        "active_group_ids": ["group-1"],
    }
    assert chat_service.call["kwargs"]["kernel"] is kernel
    assert chat_service.call["settings"].function_choice_behavior is not None
    assert plugin_logger.cleared_conversations == [("user-1", "workflow-conversation-1")]
    assert fake_g.conversation_id == "previous-conversation"
    assert not hasattr(fake_g, "workflow_id")

    print("PASS: Direct Model workflow uses core capabilities with its saved model")


def test_legacy_direct_model_workflow_retains_raw_completion() -> None:
    """Legacy workflows without the new flag must keep their existing direct path."""
    print("Testing Direct Model workflow legacy compatibility...")
    helpers, *_ = load_model_core_helpers()

    result = helpers["_execute_model_workflow"](
        {"user_id": "user-1", "chat_capabilities_enabled": False},
        {},
    )

    assert result == {"reply": "legacy"}
    print("PASS: legacy Direct Model workflow keeps raw completion")


def test_default_model_selection_context_retains_saved_endpoint() -> None:
    """Default app model selections must retain their saved endpoint identity."""
    print("Testing default model selection context...")
    helpers, *_ = load_model_core_helpers()

    model_context = helpers["_build_workflow_model_context"](
        {
            "user_id": "user-1",
            "model_binding_summary": {
                "mode": "default_selection",
                "endpoint_id": "default-endpoint-1",
                "model_id": "default-model-1",
                "provider": "aoai",
            },
        },
        "default-deployment",
        "aoai",
    )

    assert model_context["endpoint_id"] == "default-endpoint-1"
    assert model_context["model_id"] == "default-model-1"
    assert model_context["model_deployment"] == "default-deployment"
    print("PASS: default model selection context retains saved endpoint")


def run_tests() -> bool:
    tests = [
        test_direct_model_workflow_binds_core_capabilities_to_saved_model,
        test_legacy_direct_model_workflow_retains_raw_completion,
        test_default_model_selection_context_retains_saved_endpoint,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)