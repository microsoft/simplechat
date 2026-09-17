# test_workflow_editor_options.py
"""
Functional tests for authorized, non-secret workflow editor choices.
Version: 0.261.108
Implemented in: 0.261.108
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Import after setting the worktree application path.
from functions_workflow_editor import build_workflow_editor_options


def options(**kwargs):
    return build_workflow_editor_options(
        scope_type="personal", scope_id="owner", can_manage=True, max_tasks=50, **kwargs,
    )


def test_secrets_and_internal_endpoints_never_leave_editor_projection():
    result = options(agents=[{
        "id": "agent", "name": "inventory", "instructions": "PRIVATE-INSTRUCTIONS",
        "key": "PRIVATE-SECRET", "other_settings": {"endpoint": "PRIVATE-ENDPOINT"},
    }], endpoints=[{
        "id": "endpoint", "name": "Models", "provider": "aoai",
        "auth": {"api_key": "PRIVATE-SECRET"}, "connection": {"endpoint": "PRIVATE-ENDPOINT"},
        "models": [{"id": "model", "modelName": "gpt-4.1", "enabled": True}],
    }])
    assert result["models"][0]["model_id"] == "model"
    assert result["agents"][0]["name"] == "inventory"
    assert "PRIVATE" not in json.dumps(result)


def test_disabled_and_nonchat_models_are_not_offered():
    result = options(agents=[], endpoints=[{
        "id": "endpoint", "models": [
            {"id": "disabled", "modelName": "gpt-4.1", "enabled": False},
            {"id": "image", "modelName": "gpt-image-1", "enabled_capabilities": ["image_generation"]},
            {"id": "chat", "modelName": "gpt-4.1"},
        ],
    }])
    assert [model["model_id"] for model in result["models"]] == ["chat"]


def test_scoped_endpoint_precedence_matches_runtime_resolution():
    result = options(agents=[], endpoints=[
        {"id": "same-id", "name": "Personal endpoint", "models": [{"id": "personal", "modelName": "gpt-4.1"}]},
        {"id": "same-id", "name": "Global endpoint", "models": [{"id": "global", "modelName": "gpt-4.1"}]},
    ])
    assert [model["model_id"] for model in result["models"]] == ["personal"]


def test_management_policy_and_definition_version_are_explicit():
    result = build_workflow_editor_options(
        scope_type="group", scope_id="group", can_manage=False, max_tasks=30, agents=[], endpoints=[],
    )
    assert result["can_manage"] is False
    assert result["scope"] == {"type": "group", "id": "group"}
    assert result["definition_version"] == 2
