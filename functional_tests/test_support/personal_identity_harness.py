# personal_identity_harness.py
"""
Isolated real personal identity APIs over the existing Cosmos/Key Vault harness.
Version: 0.261.315
Implemented in: 0.261.315
"""

import importlib.util
import sys
from types import SimpleNamespace

import pytest
from flask import Blueprint

from test_support.agent_delegation import module_stub
from test_support.group_identity_harness import APP_ROOT, IdentityContainer


@pytest.fixture
def personal_environment(environment, monkeypatch):
    env = environment
    env.settings["enable_user_workspace"] = True
    env.state.personal_actions = []
    container = IdentityContainer("user_id")
    monkeypatch.setattr(env.identities, "cosmos_personal_workspace_identities_container", container)
    monkeypatch.setattr(
        sys.modules["functions_file_sync"], "is_file_sync_enabled_for_user",
        lambda *args, **kwargs: env.state.file_sync_enabled, raising=False,
    )
    monkeypatch.setattr(
        sys.modules["functions_settings"], "is_user_workflows_enabled_for_user",
        lambda *args, **kwargs: False, raising=False,
    )
    monkeypatch.setitem(sys.modules, "functions_governance", module_stub(
        "functions_governance",
        is_action_scope_access_allowed=lambda *args: True,
        is_governance_access_allowed=lambda *args: True,
    ))
    monkeypatch.setitem(sys.modules, "functions_personal_actions", module_stub(
        "functions_personal_actions", get_personal_actions=lambda user_id: env.state.personal_actions,
    ))

    def load_real(name):
        spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    load_real("functions_workspace_sections")
    access = load_real("functions_personal_identity_access")
    routes = load_real("route_backend_personal_identities_scoped")
    blueprint = Blueprint("backend_personal_identities_scoped", __name__)
    blueprint.before_request(sys.modules["functions_authentication"].user_required_blueprint())
    routes.register_route_backend_personal_identities_scoped(blueprint)
    env.app.register_blueprint(blueprint)
    return SimpleNamespace(
        **vars(env), personal_container=container, personal_access=access,
    )
