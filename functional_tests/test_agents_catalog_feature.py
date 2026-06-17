#!/usr/bin/env python3
"""
Functional test for the Agents catalog page and agent icon/tag metadata.
Version: 0.241.227
Implemented in: 0.241.218

This test ensures the global Agents page, shared catalog APIs, safe agent
metadata, and chat handoff contract are present and regression-resistant.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))


def read_repo_file(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(text, expected, label):
    if expected not in text:
        raise AssertionError(f"Missing expected {label}: {expected}")


def assert_not_contains(text, unexpected, label):
    if unexpected in text:
        raise AssertionError(f"Unexpected {label}: {unexpected}")


def test_agent_payload_tags_and_icon_normalization():
    from functions_agent_payload import sanitize_agent_payload

    sanitized = sanitize_agent_payload({
        "id": "agent-1",
        "name": "catalog_agent",
        "display_name": "Catalog Agent",
        "description": "Test agent",
        "instructions": "Help the user.",
        "actions_to_load": [],
        "other_settings": {},
        "max_completion_tokens": -1,
        "agent_type": "local",
        "tags": "Finance, Planning, finance",
        "icon": {"kind": "bootstrap", "value": "bi-stars"},
    })

    assert sanitized["tags"] == ["Finance", "Planning"]
    assert sanitized["icon"] == {"kind": "bootstrap", "value": "bi-stars"}


def test_agent_schema_exposes_catalog_metadata():
    schema = read_repo_file("application/single_app/static/json/schemas/agent.schema.json")
    assert_contains(schema, '"tags"', "agent tags schema")
    assert_contains(schema, '"icon"', "agent icon schema")
    assert_contains(schema, '"IconPayload"', "icon payload schema definition")


def test_agents_catalog_routes_and_navigation():
    app_route = read_repo_file("application/single_app/route_frontend_agents.py")
    backend_route = read_repo_file("application/single_app/route_backend_agents.py")
    app_py = read_repo_file("application/single_app/app.py")
    sidebar = read_repo_file("application/single_app/templates/_sidebar_nav.html")
    short_sidebar = read_repo_file("application/single_app/templates/_sidebar_short_nav.html")

    assert_contains(app_route, "@app.route('/agents'", "Agents page route")
    assert_contains(app_route, "@swagger_route(security=get_auth_security())", "Agents route swagger security")
    assert_contains(app_route, "@login_required", "Agents route login guard")
    assert_contains(app_route, "@user_required", "Agents route user guard")
    assert_contains(app_route, "@enabled_required('enable_semantic_kernel')", "Agents enabled gate")
    assert_contains(backend_route, "@bpa.route('/api/agents/catalog'", "catalog API route")
    assert_contains(backend_route, "@bpa.route('/api/agents/popular'", "popular API route")
    assert_contains(app_py, "register_route_frontend_agents(app)", "Agents route registration")
    assert_contains(sidebar, "url_for('agents')", "main sidebar Agents link")
    assert_contains(short_sidebar, "url_for('agents')", "chat sidebar Agents link")
    assert_contains(sidebar, "sidebar_settings = settings if settings is defined else app_settings", "main sidebar settings fallback")
    assert_contains(short_sidebar, "sidebar_settings = settings if settings is defined else app_settings", "chat sidebar settings fallback")
    assert_not_contains(sidebar, "{% if settings.enable_semantic_kernel %}", "undefined settings semantic-kernel gate")
    assert_not_contains(short_sidebar, "{% if settings.enable_semantic_kernel %}", "undefined settings semantic-kernel gate")


def test_agents_catalog_browser_rendering_uses_safe_dom_patterns():
    script = read_repo_file("application/single_app/static/js/agents_catalog.js")
    template = read_repo_file("application/single_app/templates/agents.html")

    assert_contains(script, "fetch('/api/agents/catalog?include_usage=true')", "catalog fetch")
    assert_contains(script, "textContent", "safe text rendering")
    assert_contains(script, "document.createElement", "DOM node rendering")
    assert_not_contains(script, "innerHTML", "dynamic HTML sink")
    assert_not_contains(script, "onclick", "inline event handler")
    assert_contains(template, "data-agent-tab=\"popular\"", "popular tab")
    assert_contains(template, "data-agent-tab=\"search\"", "hidden search results tab")
    assert_contains(template, "data-agent-tab=\"personal\"", "personal tab")
    assert_contains(template, "data-agent-tab=\"group\"", "group tab")
    assert_contains(template, "data-agent-tab=\"enterprise\"", "enterprise tab")
    assert_contains(template, "id=\"agents-new-agent-link\"", "contextual new agent link")
    assert_contains(template, "id=\"item-view-modal\"", "shared details modal")
    assert_not_contains(template, "id=\"agentCatalogDetailsModal\"", "legacy catalog details modal")
    assert_contains(script, "TAB_LABELS.search", "search results title")
    assert_contains(script, "syncTabsForSearch", "search tab selection handler")
    assert_contains(script, "attachOpenDetailsInteraction", "card click details interaction")
    assert_contains(script, "createInfoIconButton", "compact info icon details control")
    assert_contains(script, "openViewModal", "shared modal details helper")
    assert_contains(script, "scope_label: getScopeLabel(agent)", "catalog scope label handoff")
    assert_not_contains(script, "'Details'", "full Details button label")
    assert_not_contains(script, "agentCatalogDetails", "legacy modal element references")
    assert_not_contains(script, "No tags", "empty tag placeholder")
    assert_not_contains(script, "runs", "implementation-flavored usage label")
    assert_contains(template, "id=\"agents-card-view\"", "card view container")
    assert_contains(template, "id=\"agents-list-view\"", "list view container")


def test_agents_catalog_workspace_creation_links():
    template = read_repo_file("application/single_app/templates/agents.html")
    script = read_repo_file("application/single_app/static/js/agents_catalog.js")
    workspace_init = read_repo_file("application/single_app/static/js/workspace/workspace-init.js")
    group_workspace_template = read_repo_file("application/single_app/templates/group_workspaces.html")

    assert_contains(template, "data-allow-personal-create", "personal create permission flag")
    assert_contains(template, "data-allow-group-create", "group create permission flag")
    assert_contains(script, "/workspace?tab=agents&new_agent=1", "personal new agent link")
    assert_contains(script, "/group_workspaces?tab=group-agents", "group agent tab link")
    assert_contains(workspace_init, "params.get('tab') !== 'agents'", "workspace agents tab query gate")
    assert_contains(workspace_init, "document.getElementById('create-agent-btn')?.click();", "personal new agent modal launch")
    assert_contains(group_workspace_template, "navigationParams.get(\"tab\") === \"group-agents\"", "group agents tab query gate")


def test_chat_agent_metadata_and_avatar_handoff():
    chat_agents = read_repo_file("application/single_app/static/js/chat/chat-agents.js")
    chat_messages = read_repo_file("application/single_app/static/js/chat/chat-messages.js")
    chat_streaming = read_repo_file("application/single_app/static/js/chat/chat-streaming.js")
    backend_chat = read_repo_file("application/single_app/route_backend_chats.py")
    selected_agent_route = read_repo_file("application/single_app/route_backend_agents.py")
    frontend_chat_route = read_repo_file("application/single_app/route_frontend_chats.py")

    assert_contains(chat_agents, "option.dataset.agentIcon", "agent option icon metadata")
    assert_contains(chat_agents, "option.dataset.agentTags", "agent option tag metadata")
    assert_contains(frontend_chat_route, "chat_agent_options = build_accessible_agent_catalog", "chat preloads catalog icons")
    assert_contains(chat_messages, "createAssistantAvatarHtml", "agent avatar rendering helper")
    assert_contains(chat_messages, "fullMessageObject?.agent_icon", "assistant agent icon source")
    assert_contains(chat_messages, "fallbackAgentInfo: messageData.agent_info || null", "streaming selected agent icon fallback handoff")
    assert_contains(chat_streaming, "function applyFallbackAgentIcon", "streaming selected agent icon fallback")
    assert_contains(chat_streaming, "normalizeFallbackAgentIcon", "streaming fallback icon validation")
    assert_contains(backend_chat, "'agent_icon': agent_icon", "non-streaming agent icon persistence")
    assert_contains(backend_chat, "'agent_icon': agent_icon_used if use_agent_streaming else None", "streaming agent icon persistence")
    assert_contains(selected_agent_route, "\"icon\": matched_agent.get('icon') or {}", "selected agent icon setting")
    assert_contains(selected_agent_route, "\"tags\": matched_agent.get('tags') or []", "selected agent tag setting")


def test_agent_modal_icon_picker_and_upload_contract():
    modal_template = read_repo_file("application/single_app/templates/_agent_modal.html")
    agents_common = read_repo_file("application/single_app/static/js/agents_common.js")
    agent_stepper = read_repo_file("application/single_app/static/js/agent_modal_stepper.js")
    view_utils = read_repo_file("application/single_app/static/js/workspace/view-utils.js")

    assert_contains(modal_template, "id=\"agent-icon-type-bootstrap\"", "Bootstrap icon mode")
    assert_contains(modal_template, "id=\"agent-icon-type-image\"", "image icon mode")
    assert_contains(modal_template, "id=\"agent-icon-picker-search\"", "searchable icon picker")
    assert_contains(modal_template, "id=\"agent-icon-image-file\"", "agent icon image upload")
    assert_contains(agents_common, "fetch('/static/css/bootstrap-icons.css')", "local Bootstrap icon catalog")
    assert_contains(agents_common, "resizeIconFileToDataUrl", "client-side image resize")
    assert_contains(agents_common, "export function getAgentIconPayload", "modal icon payload extraction export")
    assert_contains(agents_common, "setAgentIconPayload", "modal icon payload hydration")
    assert_contains(agent_stepper, "icon: agentsCommon.getAgentIconPayload(document)", "stepper icon save payload")
    assert_contains(agent_stepper, "document.getElementById('agent-tags')", "stepper tags save payload")
    assert_contains(view_utils, "data-agent-view-icon", "details modal icon placeholder")
    assert_contains(view_utils, "hydrateAgentViewIcons", "details modal icon hydration")
    assert_contains(view_utils, "data-agent-card-icon", "workspace card icon placeholder")
    assert_contains(view_utils, "normalizeAgentIconPayload", "workspace details icon validation")
    assert_contains(modal_template, "id=\"summary-agent-icon\"", "summary page icon placeholder")
    assert_contains(agent_stepper, "renderAgentSummaryIcon", "summary page icon renderer")
    assert_contains(agent_stepper, "agentsCommon.getAgentIconPayload(document)", "summary uses current icon selection")


def test_model_icon_contract():
    settings = read_repo_file("application/single_app/functions_settings.py")
    admin_models = read_repo_file("application/single_app/static/js/admin/admin_model_endpoints.js")
    workspace_models = read_repo_file("application/single_app/static/js/workspace/workspace_model_endpoints.js")
    chat_model_selector = read_repo_file("application/single_app/static/js/chat/chat-model-selector.js")

    assert_contains(settings, "normalize_icon_payload(model_copy.get(\"icon\")", "model icon normalization")
    assert_contains(admin_models, "data-icon-class-for", "admin model icon field")
    assert_contains(workspace_models, "data-icon-class-for", "workspace model icon field")
    assert_contains(chat_model_selector, "option.dataset.modelIcon", "chat model icon dataset")
    assert_contains(chat_model_selector, "renderModelOptionContent", "chat model icon renderer")


def test_agents_catalog_resolves_model_and_action_labels():
    catalog_helper = read_repo_file("application/single_app/functions_agent_catalog.py")
    view_utils = read_repo_file("application/single_app/static/js/workspace/view-utils.js")

    assert_contains(catalog_helper, "_build_model_label_map", "catalog model label map")
    assert_contains(catalog_helper, "_build_action_label_map", "catalog action label map")
    assert_contains(catalog_helper, "\"instructions\"", "instructions in catalog response")
    assert_contains(catalog_helper, "\"action_labels\"", "resolved action labels in catalog response")
    assert_contains(view_utils, "agent.action_labels", "details use resolved action labels")
    assert_contains(view_utils, "agent.model_label", "details use resolved model label")
    assert_contains(view_utils, "marked.parse(rawInstructions)", "details render instructions markdown")


def run_tests():
    tests = [
        test_agent_payload_tags_and_icon_normalization,
        test_agent_schema_exposes_catalog_metadata,
        test_agents_catalog_routes_and_navigation,
        test_agents_catalog_browser_rendering_uses_safe_dom_patterns,
        test_agents_catalog_workspace_creation_links,
        test_chat_agent_metadata_and_avatar_handoff,
        test_agent_modal_icon_picker_and_upload_contract,
        test_model_icon_contract,
        test_agents_catalog_resolves_model_and_action_labels,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
