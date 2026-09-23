# test_group_agent_drafting.py
"""
Functional tests for the group_id branch of POST /api/agents/draft-instructions.
Version: 0.261.138
Implemented in: 0.261.138

M4C §8 B3. When the drafting request names a group, that group authorizes the
draft (membership plus agent availability) and the account's active group is
never consulted: ``require_active_group`` must not be called. Failures return
stable, non-sensitive messages rather than the raw exception text, so the wording
cannot leak group internals or drift with the underlying helpers. The legacy
branch (no ``group_id``) is unchanged and still resolves the active group.

The route function is exec'd in isolation over stubbed collaborators, so no Flask
app, Cosmos, Key Vault or model backend is required and no network is touched.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROUTES_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_agents.py"


def _load_draft_function(namespace):
    """Compile only ``draft_agent_instructions`` into the supplied namespace."""
    source = AGENT_ROUTES_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(AGENT_ROUTES_FILE))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "draft_agent_instructions"
    )
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, str(AGENT_ROUTES_FILE), "exec"), namespace)
    return namespace["draft_agent_instructions"]


def _fake_model_client(instructions="Drafted instructions."):
    message = SimpleNamespace(content=instructions)
    choice = SimpleNamespace(message=message)
    completions = SimpleNamespace(create=lambda **_kwargs: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class _Result:
    """Normalize the route's ``(payload, status)`` or bare-payload returns."""

    def __init__(self, returned):
        if isinstance(returned, tuple):
            self.payload, self.status = returned[0], returned[1]
        else:
            self.payload, self.status = returned, 200


def run_draft(
    body,
    *,
    settings,
    assert_group_role,
    require_active_group,
    group_agents_available=lambda user_id, settings: (True, None),
    roles=("User",),
    instructions="Drafted instructions.",
):
    namespace = {
        "get_settings": lambda: settings,
        "request": SimpleNamespace(get_json=lambda silent=False: body),
        "get_current_user_id": lambda: "caller",
        "session": {"user": {"roles": list(roles)}},
        "jsonify": lambda payload: payload,
        "assert_group_role": assert_group_role,
        "require_active_group": require_active_group,
        "group_agents_available": group_agents_available,
        "_resolve_agent_instruction_model": lambda settings: "gpt-model",
        "_create_agent_instruction_client": lambda settings: _fake_model_client(instructions),
        "_build_agent_instruction_messages": lambda *a, **k: [{"role": "user", "content": "x"}],
        "_build_agent_instruction_api_params": lambda model, messages: {"model": model, "messages": messages},
        "log_event": Mock(),
        "logging": __import__("logging"),
    }
    draft = _load_draft_function(namespace)
    return _Result(draft())


AVAILABLE_SETTINGS = {"allow_group_agents": True, "allow_user_agents": True}


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


def test_named_group_authorizes_the_draft_and_never_touches_the_active_group():
    require_active_group = Mock()
    assert_group_role = Mock()
    result = run_draft(
        {"agent_scope": "group", "group_id": "group-b", "brief": "Help staff."},
        settings=AVAILABLE_SETTINGS,
        assert_group_role=assert_group_role,
        require_active_group=require_active_group,
    )
    assert result.status == 200 and result.payload["success"] is True
    assert result.payload["instructions"] == "Drafted instructions."
    # The named group is the sole authorizer; the active group is never resolved.
    assert_group_role.assert_called_once()
    assert assert_group_role.call_args.args[1] == "group-b"
    require_active_group.assert_not_called()


def test_non_member_of_named_group_is_403_with_stable_message():
    result = run_draft(
        {"agent_scope": "group", "group_id": "group-b", "brief": "Help."},
        settings=AVAILABLE_SETTINGS,
        assert_group_role=Mock(side_effect=PermissionError("You are not an Owner of raw-group-name.")),
        require_active_group=Mock(),
    )
    assert result.status == 403
    assert result.payload == {"error": "You do not have access to the selected group."}


def test_unknown_named_group_is_404_with_stable_message():
    result = run_draft(
        {"agent_scope": "group", "group_id": "ghost", "brief": "Help."},
        settings=AVAILABLE_SETTINGS,
        assert_group_role=Mock(side_effect=LookupError("Group ghost not found in cosmos partition xyz.")),
        require_active_group=Mock(),
    )
    assert result.status == 404
    assert result.payload == {"error": "The selected group was not found."}


def test_named_group_unavailable_is_403_with_the_reason_and_no_active_group():
    require_active_group = Mock()
    result = run_draft(
        {"agent_scope": "group", "group_id": "group-b", "brief": "Help."},
        settings=AVAILABLE_SETTINGS,
        assert_group_role=Mock(),
        require_active_group=require_active_group,
        group_agents_available=lambda user_id, settings: (False, "Group agents are not enabled."),
    )
    assert result.status == 403
    assert result.payload == {"error": "Group agents are not enabled."}
    require_active_group.assert_not_called()


def test_allow_group_agents_off_is_403_before_any_group_resolution():
    require_active_group = Mock()
    assert_group_role = Mock()
    result = run_draft(
        {"agent_scope": "group", "group_id": "group-b", "brief": "Help."},
        settings={"allow_group_agents": False},
        assert_group_role=assert_group_role,
        require_active_group=require_active_group,
    )
    assert result.status == 403
    assert result.payload == {"error": "Group agents are disabled."}
    assert_group_role.assert_not_called()
    require_active_group.assert_not_called()


def test_without_group_id_the_legacy_active_group_path_is_unchanged():
    require_active_group = Mock()
    assert_group_role = Mock()
    result = run_draft(
        {"agent_scope": "group", "brief": "Help."},
        settings=AVAILABLE_SETTINGS,
        assert_group_role=assert_group_role,
        require_active_group=require_active_group,
    )
    assert result.status == 200 and result.payload["success"] is True
    # Legacy behaviour: the active group is resolved and the named-group helper is
    # never used.
    require_active_group.assert_called_once()
    assert_group_role.assert_not_called()


def test_legacy_active_group_failure_keeps_the_raw_message():
    result = run_draft(
        {"agent_scope": "group", "brief": "Help."},
        settings=AVAILABLE_SETTINGS,
        assert_group_role=Mock(),
        require_active_group=Mock(side_effect=PermissionError("You are not a member of the active group.")),
    )
    assert result.status == 403
    # The legacy branch is untouched: it still surfaces the helper's own text.
    assert result.payload == {"error": "You are not a member of the active group."}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
