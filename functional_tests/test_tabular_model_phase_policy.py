# test_tabular_model_phase_policy.py
"""Functional tests for deterministic tabular failures and bounded phase telemetry.

Version: 0.261.389
Implemented in: 0.261.388

Executes the production retry guard with a local service, not a string assertion
or a timed performance claim about an inaccessible Azure model.
"""

import ast
import asyncio
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from content_screening.contracts import ScreeningError
from functions_model_capabilities import ModelTokenBudgetError
from functions_model_endpoint_validation import ModelEndpointValidationError


@pytest.mark.parametrize("error", [
    ModelTokenBudgetError("model_tool_configuration_invalid", "Choose a supported reasoning setting."),
    ModelEndpointValidationError("Use a supported inference API."),
])
def test_invalid_model_configuration_does_not_repeat_three_analysis_attempts(error):
    source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_chats.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_tabular_sk_analysis")
    invocation = next(
        node for node in ast.walk(function) if isinstance(node, ast.Try) and node.finalbody
        and any(isinstance(child, ast.Name) and child.id == "synthesis_exception" for child in ast.walk(node))
        and any(isinstance(child, ast.Name) and child.id == "model_started_at" for child in ast.walk(node))
    )
    wrapper = ast.parse("async def invoke():\n    for attempt_number in range(1, 4):\n        pass\n").body[0]
    wrapper.body[0].body = [
        ast.parse("model_started_at = time.monotonic()").body[0], invocation,
    ]
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    create = AsyncMock(side_effect=error)
    logged = Mock()
    namespace = {
        "time": time, "logging": logging, "chat_history": None, "execution_settings": None,
        "kernel": None, "chat_service": SimpleNamespace(get_chat_message_contents=create),
        "guard_chat_service": lambda service: service, "token_usage_callback": None,
        "_publish_tabular_response_token_usage": Mock(), "log_event": logged,
        "ScreeningError": ScreeningError, "ModelTokenBudgetError": ModelTokenBudgetError,
        "ModelEndpointValidationError": ModelEndpointValidationError,
    }
    exec(compile(module, str(source), "exec"), namespace)
    with pytest.raises(type(error)):
        asyncio.run(namespace["invoke"]())
    assert create.await_count == 1
    assert logged.call_count == 1
    assert logged.call_args.kwargs["extra"]["phase"] == "model_call"
