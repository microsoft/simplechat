# test_chat_v1_page_bootstrap.py
"""Runtime regressions for the V1 chat page's initial model selection.

Version: 0.261.327
Implemented in: 0.261.327

Fresh normal/optimized interpreters import the real web app with external I/O
blocked. The selector, reasoning resolver, catalog builder, authentication
decorators, settings sanitizer, and templates are not replaced.
"""

import pytest

from test_orchestration_result_imports import run_probe


PROBE = r'''
from contextlib import ExitStack
from copy import deepcopy
import json
import re
import sys
from unittest.mock import Mock, patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports() as environment:
    import app as web
    import functions_settings as settings_owner
    import route_frontend_chats as route
    from functions_model_capabilities import resolve_model_reasoning_policy

    def option(deployment, model_name, **fields):
        return {
            "selection_key": deployment,
            "deployment_name": deployment,
            "model_name": model_name,
            "display_name": deployment,
            **fields,
        }

    if sys.argv[3] == "selection":
        check(
            route.resolve_model_reasoning_policy is resolve_model_reasoning_policy,
            "V1 must explicitly bind the real reasoning resolver.",
        )
        legacy = [
            option("z-production", "gpt-4o"),
            option("a-production", "gpt-5.6-luna"),
        ]
        apim = [option("z-apim", "z-apim"), option("a-apim", "a-apim")]
        scoped = [
            option("personal", "gpt-4o", scope_type="personal", model_id="personal-id"),
            option(
                "z-global", "gpt-4o", scope_type="global", model_id="global-id",
                selection_key="global::endpoint:global-id",
            ),
            option(
                "a-global", "gpt-5.6-luna", scope_type="global", model_id="reasoning-id",
                selection_key="global::endpoint:reasoning-id",
            ),
        ]
        cases = [
            (legacy, {}, "z-production", "unsupported"),
            (legacy, {"preferred_model_deployment": "a-production"}, "a-production", "supported"),
            (apim, {}, "z-apim", "unknown"),
            (scoped, {}, "a-global", "supported"),
            (scoped, {"preferred_model_id": "global-id"}, "z-global", "unsupported"),
            (scoped, {"preferred_model_id": "global::endpoint:global-id"}, "z-global", "unsupported"),
            (scoped, {"preferred_model_deployment": "personal"}, "personal", "unsupported"),
            (scoped, {"preferred_model_id": "deleted", "preferred_model_deployment": "deleted"},
             "a-global", "supported"),
        ]
        for options, preferences, deployment, status in cases:
            before = deepcopy(options)
            selected = route._build_initial_chat_model_selection(
                chat_model_options=options, **preferences,
            )
            check(selected["option_value"] == deployment, "Initial model ordering/preference changed.")
            check(selected["model_name"] == next(
                item["model_name"] for item in options if item["deployment_name"] == deployment
            ), "Deployment alias replaced the canonical model identity.")
            check(selected["reasoning_capabilities"]["status"] == status, "Reasoning status changed.")
            expected_policy = resolve_model_reasoning_policy(selected["model_name"])
            check(selected["reasoning_capabilities"] == expected_policy, "Reasoning policy shape changed.")
            serialized = json.dumps(selected)
            restored = json.loads(serialized)
            check(restored == selected, "Initial selection is not JSON serializable.")
            check(options == before, "Initial selection mutated the catalog.")

        for options in (None, [], [None, "invalid"]):
            selected = route._build_initial_chat_model_selection(chat_model_options=options)
            check(selected is None, "Empty/invalid catalogs should not invent a model.")
    else:
        defaults = settings_owner.get_settings()
        defaults.update({
            "enable_user_workspace": False,
            "enable_group_workspaces": False,
            "enable_public_workspaces": False,
            "enable_semantic_kernel": False,
            "enable_user_agreement": False,
            "enable_idle_timeout": False,
            "allow_user_custom_endpoints": False,
            "allow_group_custom_endpoints": False,
            "azure_openai_gpt_key": "private-bootstrap-test-key",
        })
        legacy_models = [
            {"deploymentName": "z-production", "modelName": "gpt-4o"},
            {"deploymentName": "a-production", "modelName": "gpt-5.6-luna"},
        ]
        endpoint = {
            "id": "test-endpoint", "provider": "aoai", "enabled": True,
            "auth": {"type": "api_key", "api_key": "private-endpoint-test-key"},
            "connection": {"endpoint": "https://private-bootstrap.example.test", "api_version": "2024-10-21"},
            "models": [
                {
                    "id": "ordinary-id", "modelName": "gpt-4o",
                    "deploymentName": "ordinary-alias", "displayName": "Zulu ordinary",
                    "enabled": True,
                },
                {
                    "id": "reasoning-id", "modelName": "gpt-5.6-luna",
                    "deploymentName": "reasoning-alias", "displayName": "Alpha reasoning",
                    "enabled": True,
                },
            ],
        }
        cases = [
            ("legacy", {
                "enable_multi_model_endpoints": False, "enable_gpt_apim": False,
                "gpt_model": {"selected": legacy_models},
            }, {}, "z-production", "unsupported"),
            ("apim", {
                "enable_multi_model_endpoints": False, "enable_gpt_apim": True,
                "azure_apim_gpt_deployment": "z-apim, a-apim",
            }, {}, "z-apim", "unknown"),
            ("multi", {
                "enable_multi_model_endpoints": True, "enable_gpt_apim": False,
                "model_endpoints": [endpoint],
            }, {"preferredModelId": "reasoning-id"}, "reasoning-alias", "supported"),
            ("empty", {
                "enable_multi_model_endpoints": False, "enable_gpt_apim": False,
                "gpt_model": {"selected": []},
            }, {}, None, None),
        ]
        web.app.config.update(TESTING=True)
        for name, changes, preferences, deployment, status in cases:
            settings = {**deepcopy(defaults), **deepcopy(changes)}
            user_document = {
                "id": "bootstrap-user", "display_name": "Bootstrap User",
                "settings": {"profileImage": None, **preferences},
            }
            read_cache = Mock(return_value=None)
            write_cache = Mock()
            with ExitStack() as patches:
                patches.enter_context(patch.object(web, "get_request_settings", return_value=settings))
                patches.enter_context(patch.object(route, "get_settings", return_value=settings))
                patches.enter_context(patch.object(route, "get_user_settings", return_value=user_document))
                patches.enter_context(patch.object(settings_owner, "get_user_settings", return_value=user_document))
                patches.enter_context(patch.object(settings_owner, "get_user_ui_settings", return_value=user_document))
                patches.enter_context(patch.object(route, "get_cached_chat_bootstrap_payload", read_cache))
                patches.enter_context(patch.object(route, "set_cached_chat_bootstrap_payload", write_cache))
                client = web.app.test_client()
                with client.session_transaction() as user_session:
                    user_session["user"] = {
                        "oid": "bootstrap-user", "roles": ["User"], "name": "Bootstrap User",
                        "preferred_username": "bootstrap@example.test",
                    }

                for warm in (False, True):
                    with patch.object(route, "_build_chat_model_catalog", wraps=route._build_chat_model_catalog) as build:
                        response = client.get("/chats")
                    check(response.status_code == 200, name + ": /chats did not render successfully.")
                    check(build.call_count == (0 if warm else 1), name + ": wrong warm/cold catalog path.")
                    body = response.get_data(as_text=True)
                    check('id="chatbox"' in body and 'id="user-input"' in body, "V1 composer missing.")
                    match = re.search(r"window.initialChatModelSelection = (.*?);", body)
                    check(match is not None, "Initial selection bootstrap is missing.")
                    initial = json.loads(match.group(1))
                    if deployment is None:
                        check(initial == {}, "Empty catalog invented an initial model.")
                        check("Select a Model" in body, "Empty-catalog placeholder missing.")
                    else:
                        check(initial["option_value"] == deployment, name + ": selected deployment changed.")
                        check(initial["reasoning_capabilities"]["status"] == status, name + ": policy changed.")
                        check('value="' + deployment + '"' in body, "Selected model option missing.")
                    check("private-bootstrap-test-key" not in body, "Raw settings reached the browser.")
                    check("private-endpoint-test-key" not in body, "Endpoint credentials reached the browser.")
                    check("private-bootstrap.example.test" not in body, "Private endpoint reached the browser.")
                    if not warm:
                        check(write_cache.call_count == 1, "Cold bootstrap did not produce a cache payload.")
                        read_cache.return_value = deepcopy(write_cache.call_args.args[1])

                anonymous = web.app.test_client()
                response = anonymous.get("/chats")
                check(response.status_code == 302, "Anonymous V1 access no longer redirects to login.")
                with anonymous.session_transaction() as user_session:
                    user_session["user"] = {"oid": "bootstrap-user", "roles": []}
                response = anonymous.get("/chats")
                check(response.status_code == 403, "V1 no longer requires the User/Admin role.")
        check(not environment.network_attempts, "Page bootstrap attempted external I/O.")
print("PASS: V1 " + sys.argv[3] + " bootstrap")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("scenario", ["selection", "page"])
def test_v1_chat_bootstrap_real_runtime(scenario, optimized):
    """Exercise V1 startup without supplying the resolver through a test stub."""
    run_probe(PROBE, (scenario,), optimized)
