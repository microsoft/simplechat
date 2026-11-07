# test_model_endpoint_capacity_save_validation.py
"""
Functional tests for safe capacity validation at existing endpoint save routes.
Version: 0.261.126
Implemented in: 0.261.035
Catalog association round trips implemented in: 0.261.126

Fresh normal/optimized processes import the real application, settings normalizer,
and route modules with external bootstrap I/O blocked. The registered route bodies
are called in Flask request contexts; the separate route policy suite verifies
their unchanged authorization decorators. Invalid overrides must fail before
secret/settings writes, and unrelated failures must not become validation errors.
Real editor read APIs and template bootstrap expressions must retain all seven
budget metadata fields and explicit nulls without exposing auth credentials.
Catalog profile associations must survive those same save/reopen paths without
persisting temporary effective-profile metadata.
"""

from contextlib import ExitStack
import copy
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
TEST_ROOT = ROOT / "functional_tests"
BUDGET_FIELDS = (
    "contextWindow", "inputTokenLimit", "outputTokenLimit", "catalogModelId",
    "modelVersion", "tokenLimitProvider", "outputTokenAccounting",
)


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _endpoint():
    return {
        "id": "budget-endpoint",
        "name": "Capacity validation fixture",
        "provider": "aoai",
        "enabled": True,
        "connection": {"endpoint": "https://budget.invalid"},
        "auth": {"type": "api_key", "api_key": "test-secret-must-not-be-returned"},
        "models": [{
            "id": "budget-model",
            "deploymentName": "deployment-alias",
            "enabled": True,
            "responseLength": 512,
        }],
    }


def _run_offline_probe():
    # Real application imports must occur inside the external-I/O bootstrap seam.
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as offline:
        import app
        from flask import Blueprint, Flask, session
        from functions_model_capabilities import ModelTokenBudgetError
        import functions_settings as settings_module
        import route_backend_models as models
        import route_frontend_admin_settings as admin
        _require(not offline.network_attempts, "Application imports attempted network access.")

        web = Flask("endpoint-budget-validation")
        web.secret_key = "offline-route-test"
        web.config["VERSION"] = app.app.config["VERSION"]
        models_blueprint = Blueprint("backend_models", __name__)
        models.register_route_backend_models(models_blueprint)
        web.register_blueprint(models_blueprint)
        admin_blueprint = Blueprint("frontend_admin_settings", __name__)
        admin.register_route_frontend_admin_settings(admin_blueprint)
        web.register_blueprint(admin_blueprint)
        handlers = {
            "user": inspect.unwrap(web.view_functions["backend_models.save_user_model_endpoints"]),
            "group": inspect.unwrap(web.view_functions["backend_models.save_group_model_endpoints"]),
            "admin": inspect.unwrap(web.view_functions["frontend_admin_settings.admin_settings"]),
        }
        defaults = settings_module.get_settings(use_cosmos=True)
        _require(not offline.network_attempts, "Offline settings read attempted network access.")
        defaults.update({"_etag": "budget-revision", "model_endpoints": []})
        initial_defaults = copy.deepcopy(defaults)
        forbidden_write = Mock(side_effect=AssertionError("Invalid capacity reached persistence."))
        role_guard = Mock()
        model_logs = Mock()
        admin_logs = Mock()
        provider_validation = Mock()
        invalid_cases = (
            ("contextWindow", True, "contextWindow must be a positive whole number of tokens."),
            ("inputTokenLimit", "private-invalid-capacity", "inputTokenLimit must be a positive whole number of tokens."),
            ("outputTokenLimit", "9007199254740992", "outputTokenLimit must be a positive whole number of tokens."),
            ("catalogModelId", False, "catalogModelId must be text."),
            ("modelVersion", 20260801, "modelVersion must be text."),
            ("tokenLimitProvider", "private-invalid-provider", "Select a supported token-limit provider."),
            ("outputTokenAccounting", "private-invalid-accounting", "Select a supported output-token accounting mode."),
        )

        def request_context(scope, endpoint):
            if scope == "admin":
                return web.test_request_context("/admin/settings", method="POST", data={
                    "admin_settings_etag": "budget-revision",
                    "model_endpoints_json": json.dumps([endpoint]),
                })
            return web.test_request_context(
                f"/api/{scope}/model-endpoints", method="POST", json={"endpoints": [endpoint]},
            )

        replacements = (
            patch.object(models, "get_current_user_id", return_value="budget-user"),
            patch.object(models, "get_user_settings", return_value={"settings": {"personal_model_endpoints": []}}),
            patch.object(models, "get_group_model_endpoints", return_value=[]),
            patch.object(models, "get_settings", side_effect=lambda: copy.deepcopy(defaults)),
            patch.object(models, "ensure_governance_access"),
            patch.object(models, "require_active_group", return_value="budget-group"),
            patch.object(models, "assert_group_role", role_guard),
            patch.object(models, "validate_custom_model_endpoints", provider_validation),
            patch.object(models, "keyvault_model_endpoint_save_helper", forbidden_write),
            patch.object(models, "keyvault_model_endpoint_cleanup_helper", forbidden_write),
            patch.object(models, "keyvault_model_endpoint_delete_helper", forbidden_write),
            patch.object(models, "update_user_settings", forbidden_write),
            patch.object(models, "update_group_model_endpoints", forbidden_write),
            patch.object(models, "log_event", model_logs),
            patch.object(admin, "get_settings", side_effect=lambda: copy.deepcopy(defaults)),
            patch.object(admin, "get_current_user_id", return_value="budget-admin"),
            # Browser availability probing is external I/O; UI tests run separately.
            patch.object(admin, "get_source_review_runtime_capabilities", return_value={
                "js_rendering_available": False,
                "playwright_available": False,
                "chromium_launch_available": False,
                "message": "Browser availability is not probed by endpoint save tests.",
            }),
            patch.object(admin, "update_settings", forbidden_write),
            patch.object(admin, "keyvault_model_endpoint_save_helper", forbidden_write),
            patch.object(admin, "keyvault_model_endpoint_cleanup_helper", forbidden_write),
            patch.object(admin, "keyvault_model_endpoint_delete_helper", forbidden_write),
            patch.object(admin, "validate_custom_model_endpoints", provider_validation),
            patch.object(admin, "log_event", admin_logs),
        )
        with ExitStack() as patch_stack:
            for replacement in replacements:
                patch_stack.enter_context(replacement)
            for scope, handler in handlers.items():
                for level in ("endpoint", "model"):
                    for field, invalid, expected_message in invalid_cases:
                        endpoint = _endpoint()
                        record = endpoint if level == "endpoint" else endpoint["models"][0]
                        record[field] = invalid
                        original = copy.deepcopy(endpoint)
                        with request_context(scope, endpoint):
                            response = web.make_response(handler())
                            _require(not offline.network_attempts, f"Network access during {scope} {level} {field} validation.")
                            if scope == "admin":
                                flashes = list(session.get("_flashes", []))
                                _require(response.status_code == 302, "Admin invalid capacity did not return to the settings form.")
                                _require(response.location.endswith("/admin/settings"), "Admin validation redirected elsewhere.")
                                _require(("danger", expected_message) in flashes, "Admin form did not show the safe field message.")
                                visible = json.dumps(flashes)
                            else:
                                payload = response.get_json()
                                _require(response.status_code == 400, "Invalid capacity was not an HTTP 400.")
                                _require(payload == {
                                    "error": expected_message,
                                    "error_code": "model_context_invalid",
                                }, "Invalid capacity did not use the typed safe error payload.")
                                visible = response.get_data(as_text=True)
                            _require("private-invalid" not in visible, "Invalid submitted metadata was reflected to the client.")
                            _require("test-secret-must-not-be-returned" not in visible, "Endpoint secret leaked in validation.")
                        _require(endpoint == original, "Route validation mutated the submitted record.")

                public_error = ModelTokenBudgetError("model_context_invalid", "Review the verified model capacity.")
                public_error.args = ("private-internal-capacity-diagnostic",)
                route_module = admin if scope == "admin" else models
                with patch.object(route_module, "merge_model_endpoints_with_existing", side_effect=public_error):
                    with request_context(scope, _endpoint()):
                        response = web.make_response(handler())
                        if scope == "admin":
                            flashes = list(session.get("_flashes", []))
                            _require(("danger", public_error.public_message) in flashes, "Admin validation ignored the typed public message.")
                            visible = json.dumps(flashes)
                        else:
                            payload = response.get_json()
                            _require(payload == {
                                "error": public_error.public_message,
                                "error_code": public_error.code,
                            }, "The API ignored the typed public validation message.")
                            visible = response.get_data(as_text=True)
                        _require("private-internal-capacity-diagnostic" not in visible, "Raw exception text escaped into validation output.")

                for unrelated in (ValueError("private implementation detail"), RuntimeError("private provider detail")):
                    route_module = admin if scope == "admin" else models
                    with patch.object(route_module, "merge_model_endpoints_with_existing", side_effect=unrelated):
                        with request_context(scope, _endpoint()):
                            try:
                                handler()
                            except type(unrelated) as error:
                                _require(error is unrelated, "The route replaced an unrelated failure.")
                            else:
                                raise AssertionError("An unrelated failure was swallowed as a configuration error.")

            _require(not forbidden_write.called, "Invalid validation performed a write.")
            _require(not provider_validation.called, "Invalid budgets reached later provider validation.")
            _require(defaults == initial_defaults, "Invalid budgets mutated stored application settings.")
            _require(role_guard.call_args.kwargs == {"allowed_roles": ("Owner", "Admin")}, "Group edit authorization changed.")
            _require(model_logs.called and admin_logs.called, "Rejected configuration was not logged.")

            for scope in ("user", "group"):
                endpoint = _endpoint()
                endpoint.update({
                    "contextWindow": "8192",
                    "inputTokenLimit": "7000",
                    "outputTokenLimit": None,
                    "tokenLimitProvider": "custom",
                    "outputTokenAccounting": "total_generation",
                })
                endpoint["models"][0].update({
                    "catalogModelId": "gpt-5.6-terra",
                    "modelVersion": "2026-07-09",
                    "outputTokenLimit": "4096",
                })
                saved = Mock()
                with (
                    patch.object(models, "keyvault_model_endpoint_save_helper", side_effect=lambda record, *args, **kwargs: copy.deepcopy(record)),
                    patch.object(models, "keyvault_model_endpoint_cleanup_helper"),
                    patch.object(models, "update_user_settings", saved),
                    patch.object(models, "update_group_model_endpoints", saved),
                    request_context(scope, endpoint),
                ):
                    response = web.make_response(handlers[scope]())
                    _require(not offline.network_attempts, f"Network access during valid {scope} save.")
                    payload = response.get_json()
                    _require(response.status_code == 200 and payload.get("success") is True, "Valid capacity stopped saving.")
                    result = payload["endpoints"][0]
                    _require(result["contextWindow"] == 8192 and result["inputTokenLimit"] == 7000, "Valid endpoint limits were not normalized.")
                    _require(result["outputTokenLimit"] is None, "Null endpoint inheritance was not retained.")
                    _require(result["outputTokenAccounting"] == "total_generation", "Custom output accounting was lost.")
                    _require(result["models"][0]["outputTokenLimit"] == 4096, "Valid model limit was not normalized.")
                    _require(result["models"][0]["responseLength"] == 512, "Capacity changed Response Length.")
                    _require(result["models"][0]["modelVersion"] == "2026-07-09", "Saved model version was lost.")
                    _require("api_key" not in result["auth"], "Save response returned credentials.")
                    _require(saved.call_count == 1, "Valid scoped save did not persist exactly once.")

        _check_editor_projection_round_trips(web, defaults, settings_module, models, admin, offline)


def _check_editor_projection_round_trips(web, defaults, settings_module, models, admin, offline):
    # Called only inside the real-module, external-I/O bootstrap context above.
    from flask import Blueprint
    import functions_governance as governance
    import functions_workspace_sections as workspace_sections
    import route_frontend_group_workspaces as group_workspace
    import route_frontend_workspace as workspace

    endpoint_budget = {
        "contextWindow": 8192,
        "inputTokenLimit": None,
        "outputTokenLimit": 2048,
        "catalogModelId": "gpt-5.6-terra",
        "modelVersion": "2026-07-09",
        "tokenLimitProvider": "azure",
        "outputTokenAccounting": "total_generation",
    }
    model_budget = {
        "contextWindow": None,
        "inputTokenLimit": 6000,
        "outputTokenLimit": None,
        "catalogModelId": "gpt-5.6-terra",
        "modelVersion": None,
        "tokenLimitProvider": None,
        "outputTokenAccounting": "visible_only",
    }
    credentials = {
        field: f"private-projection-{field}"
        for field in ("api_key", "client_secret", "bearer_token", "access_token", "refresh_token")
    }
    endpoint = _endpoint()
    endpoint.update(endpoint_budget)
    endpoint["models"][0].update(model_budget)
    endpoint["models"][0]["catalogProfileId"] = "gpt-5-nano"
    endpoint["auth"].update(credentials)
    canonical, _ = settings_module.normalize_model_endpoints([endpoint])
    stores = {scope: copy.deepcopy(canonical) for scope in ("user", "group", "global")}
    for module, name in (
        (workspace, "frontend_workspace"),
        (group_workspace, "frontend_group_workspaces"),
    ):
        blueprint = Blueprint(name, __name__)
        getattr(module, f"register_route_{name}")(blueprint)
        web.register_blueprint(blueprint)

    def snapshot():
        return {
            **copy.deepcopy(defaults),
            "model_endpoints": copy.deepcopy(stores["global"]),
            "azure_openai_gpt_key": "private-projection-app-key",
            "enable_multi_model_endpoints": True,
            "last_update_check_time": "2099-01-01T00:00:00+00:00",
            "latest_version_available": web.config["VERSION"],
            "update_available": False,
        }

    def user_settings(_user_id):
        return {"settings": {"personal_model_endpoints": copy.deepcopy(stores["user"])}}

    def save_user(_user_id, changes):
        stores["user"] = copy.deepcopy(changes["personal_model_endpoints"])

    def save_group(_group_id, endpoints):
        stores["group"] = copy.deepcopy(endpoints)

    def verify(records, expected_endpoint, expected_model):
        _require(len(records) == 1, "The endpoint projection changed the visible record set.")
        for record, expected in (
            (records[0], expected_endpoint),
            (records[0]["models"][0], expected_model),
        ):
            projected = {field: record[field] for field in BUDGET_FIELDS}
            _require(projected == expected, "Capacity/identity/accounting metadata was filtered or changed.")
        serialized = json.dumps(records)
        _require(not any(secret in serialized for secret in credentials.values()), "An editor projection exposed an auth credential.")
        _require(records[0]["has_api_key"] is True, "Stored API-key presence was lost.")
        _require(records[0]["has_client_secret"] is True, "Stored client-secret presence was lost.")
        _require(records[0]["models"][0]["responseLength"] == 512, "Metadata projection changed Response Length.")
        _require(records[0]["models"][0]["catalogProfileId"] == "gpt-5-nano", "The catalog association was lost.")
        _require(
            not {"_catalog_profile", "_catalog_effective_revision"} & records[0]["models"][0].keys(),
            "Temporary routing metadata leaked into the editor projection.",
        )

    captured = {}

    def capture_template(template_name, **kwargs):
        captured.clear()
        captured.update({"template": template_name, "context": kwargs})
        return "Endpoint projection fixture"

    def template_projection(variable):
        source = (APP_ROOT / "templates" / captured["template"]).read_text(encoding="utf-8")
        assignment = re.search(rf"window\.{variable}\s*=\s*[^\n]+;", source)
        _require(assignment is not None, "The real template no longer exposes the expected endpoint bootstrap.")
        rendered = Environment(autoescape=True).from_string(assignment.group()).render(**captured["context"])
        return json.loads(rendered.split("=", 1)[1].strip().removesuffix(";"))

    with ExitStack() as patches:
        replacements = [
            patch.object(governance, "is_governance_access_allowed", return_value=True),
            patch.object(models, "get_current_user_id", return_value="budget-user"),
            patch.object(models, "get_user_settings", side_effect=user_settings),
            patch.object(models, "get_group_model_endpoints", side_effect=lambda _group_id: copy.deepcopy(stores["group"])),
            patch.object(models, "get_settings", side_effect=snapshot),
            patch.object(models, "ensure_governance_access"),
            patch.object(models, "require_active_group", return_value="budget-group"),
            patch.object(models, "assert_group_role"),
            patch.object(models, "keyvault_model_endpoint_save_helper", side_effect=lambda record, *args, **kwargs: copy.deepcopy(record)),
            patch.object(models, "keyvault_model_endpoint_cleanup_helper"),
            patch.object(models, "update_user_settings", side_effect=save_user),
            patch.object(models, "update_group_model_endpoints", side_effect=save_group),
            patch.object(models, "log_event"),
            patch.object(admin, "get_settings", side_effect=snapshot),
            patch.object(admin, "get_current_user_id", return_value="budget-admin"),
            patch.object(admin, "get_user_settings", side_effect=user_settings),
            patch.object(admin, "get_audio_runtime_capabilities", return_value={}),
            patch.object(admin, "get_source_review_runtime_capabilities", return_value={"js_rendering_available": False}),
            patch.object(admin, "get_enhanced_citations_storage_status", return_value={}),
            patch.object(admin, "update_settings", side_effect=AssertionError("Projection unexpectedly wrote settings.")),
            patch.object(admin, "render_template", side_effect=capture_template),
            patch.object(workspace, "get_user_groups", return_value=[]),
            patch.object(workspace, "get_user_visible_public_workspace_docs", return_value=[]),
            patch.object(group_workspace, "require_active_group", return_value="budget-group"),
            patch.object(group_workspace, "get_group_model_endpoints", side_effect=lambda _group_id: copy.deepcopy(stores["group"])),
        ]
        for module in (workspace_sections, group_workspace):
            replacements.extend((
                patch.object(module, "is_governance_access_allowed", return_value=True),
                patch.object(module, "is_action_scope_access_allowed", return_value=True),
            ))
        for module in (workspace, group_workspace):
            replacements.extend((
                patch.object(module, "get_current_user_id", return_value="budget-user"),
                patch.object(module, "get_current_user_info", return_value={"email": "budget@example.invalid"}),
                patch.object(module, "get_settings", side_effect=snapshot),
                patch.object(module, "get_user_settings", side_effect=user_settings),
                patch.object(module, "render_template", side_effect=capture_template),
            ))
        for replacement in replacements:
            patches.enter_context(replacement)

        for clear in (False, True):
            expected_endpoint = {field: None for field in BUDGET_FIELDS} if clear else endpoint_budget
            expected_model = {field: None for field in BUDGET_FIELDS} if clear else model_budget
            if clear:
                for scope in ("user", "group", "global"):
                    incoming = settings_module.sanitize_model_endpoints_for_frontend(stores[scope])
                    incoming[0].update(expected_endpoint)
                    incoming[0]["models"][0].update(expected_model)
                    incoming[0]["models"][0].update({
                        "_catalog_profile": {"id": "must-not-persist"},
                        "_catalog_effective_revision": "must-not-persist",
                    })
                    incoming[0]["inputTokenLimit"] = " \t "
                    incoming[0]["models"][0]["outputTokenLimit"] = " \t "
                    if scope == "global":
                        merged = settings_module.merge_model_endpoints_with_existing(incoming, stores[scope])
                        stores[scope], _ = settings_module.normalize_model_endpoints(merged)
                    else:
                        handler = inspect.unwrap(web.view_functions[f"backend_models.save_{scope}_model_endpoints"])
                        with web.test_request_context(
                            f"/api/{scope}/model-endpoints", method="POST", json={"endpoints": incoming},
                        ):
                            response = web.make_response(handler())
                            payload = response.get_json()
                        _require(response.status_code == 200, "A cleared override could not be saved.")
                        verify(payload["endpoints"], expected_endpoint, expected_model)
                    _require(
                        all(stores[scope][0]["auth"].get(field) == value for field, value in credentials.items()),
                        "Clearing capacity changed stored credentials.",
                    )
                    _require(
                        not {"_catalog_profile", "_catalog_effective_revision"} & stores[scope][0]["models"][0].keys(),
                        "Temporary effective-profile metadata was persisted.",
                    )

            public = settings_module.sanitize_settings_for_user({
                **snapshot(),
                "personal_model_endpoints": copy.deepcopy(stores["user"]),
            })
            verify(public["model_endpoints"], expected_endpoint, expected_model)
            verify(public["personal_model_endpoints"], expected_endpoint, expected_model)
            _require("private-projection-app-key" not in json.dumps(public), "General frontend settings exposed an application credential.")
            for scope, endpoint_name in (
                ("user", "get_user_model_endpoints"),
                ("group", "get_group_model_endpoints_route"),
            ):
                handler = inspect.unwrap(web.view_functions[f"backend_models.{endpoint_name}"])
                with web.test_request_context(f"/api/{scope}/model-endpoints"):
                    response = web.make_response(handler())
                    payload = response.get_json()
                _require(response.status_code == 200, "The endpoint editor read API failed.")
                verify(payload["endpoints"], expected_endpoint, expected_model)

            for endpoint_name, path, variables in (
                ("frontend_admin_settings.admin_settings", "/admin/settings", ("modelEndpoints",)),
                ("frontend_workspace.workspace", "/workspace", ("workspaceModelEndpoints", "globalModelEndpoints")),
                ("frontend_group_workspaces.group_workspaces", "/group_workspaces", ("workspaceModelEndpoints", "globalModelEndpoints")),
            ):
                handler = inspect.unwrap(web.view_functions[endpoint_name])
                with web.test_request_context(path):
                    response = web.make_response(handler())
                _require(response.status_code == 200, "The endpoint editor frontend projection failed.")
                for variable in variables:
                    projection = template_projection(variable)
                    verify(projection, expected_endpoint, expected_model)
            _require(not offline.network_attempts, "Endpoint metadata projection attempted network access.")


@pytest.mark.parametrize("optimized", (False, True))
def test_capacity_save_routes_fail_safely_before_persistence(optimized):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(APP_ROOT), str(TEST_ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend((str(Path(__file__).resolve()), "--offline-probe"))
    result = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    _require(result.returncode == 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--offline-probe" in sys.argv:
        _run_offline_probe()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
