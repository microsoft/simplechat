# test_agent_delegation_scoped_action_save.py
"""
Functional test for saving Call agent actions after scope binding.
Version: 0.261.217
Implemented in: 0.261.217

Every save binds the action to its collection with bind_action_origin, which adds the
server-owned scope and scope_id fields, and only then validates the Call agent manifest.
The manifest allowlist must accept those bound fields, or no personal, group, or global
Call agent action can be saved, while still rejecting any other extra field.
"""

import importlib.util

import pytest

from test_support.agent_delegation import APP_ROOT, delegation_environment, manifest, reference


@pytest.fixture
def environment():
    with delegation_environment() as value:
        yield value


def load_action_manifest():
    spec = importlib.util.spec_from_file_location(
        "_tested_scoped_functions_action_manifest", APP_ROOT / "functions_action_manifest.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("scope_type,scope_id", [
    ("global", "global"),
    ("personal", "actor"),
    ("group", "group-1"),
])
def test_scope_bound_call_agent_action_passes_manifest_validation(environment, scope_type, scope_id):
    helper, _ = environment
    target = reference("target-id", scope_type, scope_id)
    bound = load_action_manifest().bind_action_origin(manifest(target), scope_type, scope_id)
    assert bound["scope_id"] == scope_id

    result = helper.validate_agent_action_manifest(bound)

    assert result["additionalFields"]["target_agent"] == target
    assert result["scope_id"] == scope_id
    assert result["endpoint"] == "internal://agent"
    assert result["auth"] == {"type": "user"}


@pytest.mark.parametrize("field,value", [
    ("api_key", "private-key"),
    ("base_url", "https://override.invalid"),
])
def test_scope_binding_does_not_admit_other_fields(environment, field, value):
    helper, _ = environment
    bound = load_action_manifest().bind_action_origin(manifest(**{field: value}), "global", "global")
    with pytest.raises(ValueError):
        helper.validate_agent_action_manifest(bound)
