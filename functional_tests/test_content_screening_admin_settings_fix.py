# test_content_screening_admin_settings_fix.py
"""
Functional regressions for discoverable and persistent screening administration.
Version: 0.261.107
Implemented in: 0.261.107

Executes the actual V2 settings handler with isolated storage boundaries. Failed
writes cannot report success, and Content Safety is not a screening prerequisite.
"""

import ast
from copy import deepcopy
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Reuse the repository's isolated schema loader without starting Azure clients.
from test_support.app_stubs import import_app_module
from content_screening.contracts import (
    ScreeningError,
    ScreeningPolicyRequiredError,
    ScreeningCitationsRequiredError,
)
from content_screening.policies import default_policy
from content_screening.service import validate_screening_configuration


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
fields = import_app_module("admin_settings_fields")
nav = import_app_module("admin_settings_nav")


def patch_handler(settings, *, write_succeeds=True, validation_error=None):
    tree = ast.parse((APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "v2_admin_patch_settings"
    )
    function.decorator_list = []
    writes = Mock(return_value=write_succeeds)
    validator = Mock(side_effect=validation_error)
    namespace = {
        "request": request, "jsonify": jsonify, "logging": logging,
        "ScreeningError": ScreeningError,
        "get_settings": Mock(side_effect=lambda **kwargs: deepcopy(settings)),
        "normalize_admin_settings_updates": fields.normalize_admin_settings_updates,
        "get_admin_settings_api_secret_fields": lambda: set(),
        "get_secret_field_keys": lambda: set(),
        "_seed_connections_on_first_enable": Mock(),
        "validate_content_screening_settings": validator,
        "update_settings": writes,
        "_refresh_branding_static_files": Mock(),
        "_redact_admin_settings_for_v2": deepcopy,
        "log_event": Mock(),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(APP_ROOT / "route_backend_v2.py"), "exec"), namespace)
    return namespace


def invoke(namespace, updates):
    app = Flask(__name__)
    with app.test_request_context("/api/v2/admin/settings", method="PATCH", json={"settings": updates}):
        response, status = namespace["v2_admin_patch_settings"]()
        return response.get_json(), status


def test_screening_has_its_own_visible_admin_section_and_editor():
    security = next(group for group in nav.ADMIN_NAV if group["id"] == "security")
    screening_tab = next(tab for tab in security["tabs"] if tab["id"] == "content-screening")
    assert screening_tab["label"] == "Content Screening"
    assert screening_tab["sections"][0]["id"] == "content-screening-section"
    schema = fields.ADMIN_SETTINGS_FIELDS["content-screening-section"]
    toggle = next(field for field in schema if field.get("key") == "enable_content_screening")
    assert "depends_on" not in toggle
    assert toggle["requires"]["key"] == "enable_enhanced_citations"
    assert toggle["role"] == "capability"
    assert any(field.get("component") == "content-screening-policy" for field in schema)
    assert all(field.get("key") != "enable_content_screening" for field in fields.ADMIN_SETTINGS_FIELDS["content-safety-section"])


def test_classic_admin_loads_the_dedicated_screening_pane():
    template = (APP_ROOT / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    assert '{% include "admin/_panes/content-screening.html" %}' in template
    pane = (APP_ROOT / "templates" / "admin" / "_panes" / "content-screening.html").read_text(encoding="utf-8")
    assert 'id="enable_content_screening"' in pane
    assert 'data-content-screening-policy' in pane


def test_acr_context_includes_ui_source_but_not_local_dependencies_or_secrets():
    rules = (APP_ROOT.parents[1] / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!application/v2_ui/" in rules
    assert "!application/v2_ui/**" in rules
    assert rules.index("application/v2_ui/node_modules/") > rules.index("!application/v2_ui/**")
    assert "**/.env" in rules and "application/single_app/static/v2/" in rules


def test_failed_settings_write_never_echoes_a_successful_switch_value():
    current = {"enable_content_screening": False, "enable_enhanced_citations": True, "enable_content_safety": True}
    namespace = patch_handler(current, write_succeeds=False)
    payload, status = invoke(namespace, {"enable_content_screening": True})
    assert status == 503
    assert payload["success"] is False
    assert "settings" not in payload and "updated_keys" not in payload
    namespace["_refresh_branding_static_files"].assert_not_called()
    assert current["enable_content_screening"] is False


def test_policy_rejection_is_visible_at_the_screening_switch():
    namespace = patch_handler(
        {"enable_content_screening": False, "enable_enhanced_citations": True},
        validation_error=ScreeningPolicyRequiredError(),
    )
    payload, status = invoke(namespace, {"enable_content_screening": True})
    assert status == 400
    assert payload["error_code"] == "screening_policy_required"
    assert "enabled policy" in payload["field_errors"]["enable_content_screening"]
    namespace["update_settings"].assert_not_called()


def test_screening_save_succeeds_when_content_safety_is_disabled():
    namespace = patch_handler({
        "enable_content_screening": False, "enable_enhanced_citations": True,
        "enable_content_safety": False,
    })
    payload, status = invoke(namespace, {"enable_content_screening": True})
    assert status == 200
    assert payload["settings"] == {"enable_content_screening": True}
    namespace["update_settings"].assert_called_once_with({"enable_content_screening": True})
    assert any(call.kwargs.get("use_cosmos") is True for call in namespace["get_settings"].call_args_list)


def test_service_distinguishes_missing_citations_from_missing_policy():
    settings = {"enable_content_screening": True, "enable_enhanced_citations": False, "enable_content_safety": True}
    try:
        validate_screening_configuration(settings, repository=SimpleNamespace(get_policy=lambda *_args: None))
    except ScreeningCitationsRequiredError as error:
        assert "Content Safety" in error.public_message
    else:
        raise AssertionError("Screening must require Enhanced Citations, not Content Safety.")
    settings["enable_enhanced_citations"] = True
    try:
        validate_screening_configuration(settings, repository=SimpleNamespace(get_policy=lambda *_args: None))
    except ScreeningPolicyRequiredError as error:
        assert error.status_code == 400
    else:
        raise AssertionError("An enabled policy must be saved first.")
    policy = default_policy()
    policy.update({"enabled": True, "rules": [{
        "id": "example", "name": "Restricted values", "type": "literal",
        "enabled": True, "severity": "high", "category": "sensitive", "values": ["private"],
    }]})
    settings["enable_content_safety"] = False
    validate_screening_configuration(settings, repository=SimpleNamespace(get_policy=lambda *_args: {"policy": policy}))
