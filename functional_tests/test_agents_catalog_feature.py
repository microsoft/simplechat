#!/usr/bin/env python3
"""
Functional test for the Agents catalog page and agent icon/tag metadata.
Version: 0.242.066
Implemented in: 0.242.061; updated in 0.242.064; 0.242.065; 0.242.066

This test ensures the global Agents page, shared catalog APIs, safe agent
metadata, and chat handoff contract are present and regression-resistant.
"""

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


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
    sanitize_agent_payload = importlib.import_module("functions_agent_payload").sanitize_agent_payload

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
    assert_contains(app_route, "def build_agents_page_config", "agents page presentation config")
    assert_contains(app_route, "agents_page_config=build_agents_page_config(public_settings)", "agents page config template handoff")
    assert_contains(app_route, "HEX_COLOR_PATTERN", "agents page hero color validation")
    assert_contains(backend_route, "@bpa.route('/api/agents/catalog'", "catalog API route")
    assert_contains(backend_route, "@bpa.route('/api/agents/popular'", "popular API route")
    assert_contains(backend_route, "usage_window = str(request.args.get('usage_window')", "popular API usage-window query")
    assert_contains(app_py, "register_route_frontend_agents(app)", "Agents route registration")
    assert_contains(sidebar, "url_for('agents')", "main sidebar Agents link")
    assert_contains(short_sidebar, "url_for('agents')", "chat sidebar Agents link")
    assert_contains(sidebar, "sidebar_settings = settings if settings is defined else app_settings", "main sidebar settings fallback")
    assert_contains(short_sidebar, "sidebar_settings = settings if settings is defined else app_settings", "chat sidebar settings fallback")
    assert_not_contains(sidebar, "{% if settings.enable_semantic_kernel %}", "undefined settings semantic-kernel gate")
    assert_not_contains(short_sidebar, "{% if settings.enable_semantic_kernel %}", "undefined settings semantic-kernel gate")


def test_agents_catalog_browser_rendering_uses_safe_dom_patterns():
    script = read_repo_file("application/single_app/static/js/agents_catalog.js")
    styles = read_repo_file("application/single_app/static/css/agents-catalog.css")
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
    assert_contains(template, "id=\"agents-catalog-search-form\"", "hero search form")
    assert_contains(template, "Search for agents, skills, or workflows", "hero search placeholder")
    assert_contains(template, "agents-search-button", "hero search button")
    assert_contains(template, "agents_page_config.title", "custom hero title binding")
    assert_contains(template, "agents_page_config.subtitle", "custom hero subtitle binding")
    assert_contains(template, "agents_page_config.hero_primary_color", "custom hero primary color binding")
    assert_contains(template, "agents_page_config.disclaimer_markdown", "custom markdown disclaimer payload")
    assert_contains(template, "id=\"agents-new-agent-link\"", "contextual new agent link")
    assert_not_contains(template, "id=\"agents-count-label\"", "visible shown and available counts")
    assert_not_contains(template, "id=\"agents-results-count\"", "hidden results count")
    assert_contains(template, "id=\"agents-popular-window-toggle\"", "popular usage-window toggle")
    assert_contains(template, "data-agent-usage-window=\"all_time\"", "all-time popular toggle")
    assert_contains(template, "data-agent-usage-window=\"30_days\"", "last-30-days popular toggle")
    assert_contains(template, "id=\"item-view-modal\"", "shared details modal")
    assert_not_contains(template, "id=\"agentCatalogDetailsModal\"", "legacy catalog details modal")
    assert_contains(script, "TAB_LABELS.search", "search results title")
    assert_contains(script, "syncTabsForSearch", "search tab selection handler")
    assert_contains(script, "popularUsageWindow = 'all_time'", "default all-time popular ranking")
    assert_contains(script, "syncPopularWindowToggle", "popular usage-window toggle sync")
    assert_contains(script, "usage_count_all_time", "all-time usage count field")
    assert_contains(script, "usage_count_30_days", "last-30-days usage count field")
    assert_contains(script, "attachOpenDetailsInteraction", "card click details interaction")
    assert_contains(script, "createDetailsButton", "details icon control")
    assert_contains(script, "agent-info-icon-btn", "icon-only details control")
    assert_contains(script, "agent-card-media-row", "rank and icon alignment row")
    assert_not_contains(script, "document.createTextNode('Details')", "full details button label")
    assert_contains(styles, ".agent-row:hover", "list row hover highlight")
    assert_contains(styles, "transform: translateY(-2px)", "workspace-style hover lift")
    assert_contains(styles, ".agents-popular-window-toggle", "popular usage-window toggle styles")
    assert_contains(styles, ".agent-info-icon-btn", "icon-only details control styles")
    assert_contains(styles, ".agent-card-media-row .agent-rank", "card rank alignment styles")
    assert_contains(script, "openViewModal", "shared modal details helper")
    assert_contains(script, "scope_label: getScopeLabel(agent)", "catalog scope label handoff")
    assert_not_contains(script, "agentCatalogDetails", "legacy modal element references")
    assert_not_contains(script, "No tags", "empty tag placeholder")
    assert_not_contains(script, "runs", "implementation-flavored usage label")
    assert_contains(template, "id=\"agents-card-view\"", "card view container")
    assert_contains(template, "id=\"agents-list-view\"", "list view container")
    assert_contains(script, "DOMPurify.sanitize(marked.parse(markdownText))", "safe markdown disclaimer rendering")
    assert_contains(script, "new DOMParser().parseFromString", "sanitized disclaimer DOM parsing")


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


def test_agents_page_admin_customization_settings():
    settings_defaults = read_repo_file("application/single_app/functions_settings.py")
    admin_route = read_repo_file("application/single_app/route_frontend_admin_settings.py")
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")

    for field_name in [
        "agents_page_title",
        "agents_page_subtitle",
        "agents_page_hero_color_mode",
        "agents_page_hero_primary_color",
        "agents_page_hero_secondary_color",
        "agents_page_disclaimer_markdown",
        "agents_page_show_instructions_in_details",
        "agents_page_promoted_popular_agents",
        "agents_page_promoted_popular_order",
        "agents_page_promoted_popular_tag_enabled",
        "agents_page_promoted_popular_tag_label",
    ]:
        assert_contains(settings_defaults, field_name, f"default {field_name}")
        assert_contains(admin_route, field_name, f"admin save {field_name}")
        assert_contains(admin_template, field_name, f"admin control {field_name}")

    assert_contains(admin_route, "normalize_agents_page_color", "admin hero color validation")
    assert_contains(admin_route, "normalize_agents_page_color_mode", "admin color mode validation")
    assert_contains(admin_route, "normalize_agents_page_promoted_popular_agents", "promoted popular agent validation")
    assert_contains(settings_defaults, "normalize_agents_page_promoted_popular_settings", "promoted popular settings migration")
    assert_contains(admin_template, "Agents Page Customization", "admin customization section title")
    assert_contains(admin_template, "Markdown supported", "admin disclaimer markdown helper")
    assert_contains(admin_template, "Show agent instructions in Agents page details", "admin instruction visibility toggle")
    assert_contains(admin_template, "Promoted Popular Agents", "admin promoted popular agents section")
    assert_contains(admin_template, "agents_page_promoted_popular_agents_json", "promoted popular hidden JSON field")


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
    catalog_route = read_repo_file("application/single_app/route_backend_agents.py")
    catalog_template = read_repo_file("application/single_app/templates/agents.html")
    catalog_script = read_repo_file("application/single_app/static/js/agents_catalog.js")
    view_utils = read_repo_file("application/single_app/static/js/workspace/view-utils.js")

    assert_contains(catalog_helper, "_build_model_label_map", "catalog model label map")
    assert_contains(catalog_helper, "_build_action_label_map", "catalog action label map")
    assert_contains(catalog_helper, "\"instructions\"", "instructions in catalog response")
    assert_contains(catalog_helper, "\"action_labels\"", "resolved action labels in catalog response")
    assert_contains(catalog_helper, "usage_count_all_time", "all-time usage count serialization")
    assert_contains(catalog_helper, "usage_count_30_days", "last-30-days usage count serialization")
    assert_contains(catalog_helper, "usage_window", "popular usage-window ranking")
    assert_contains(catalog_helper, "apply_agent_popular_promotions", "popular promotion catalog annotation")
    assert_contains(catalog_helper, "is_promoted_popular", "popular promotion response flag")
    assert_contains(catalog_route, "apply_agent_popular_promotions(catalog, settings=settings)", "popular promotion route application")
    assert_contains(catalog_route, "_redact_catalog_agent_instructions", "catalog instruction redaction helper")
    assert_contains(catalog_route, "agents_page_show_instructions_in_details", "catalog instruction visibility setting")
    assert_contains(catalog_template, "data-show-instructions-in-details", "catalog instruction visibility flag")
    assert_contains(catalog_script, "showInstructions: shouldShowInstructionsInDetails()", "catalog modal instruction visibility option")
    assert_contains(catalog_script, "isPromotedPopularForWindow", "client promoted popular window filtering")
    assert_contains(catalog_script, "promoted_popular_tag_label", "client promoted popular badge label")
    assert_contains(catalog_script, "getPromotedPopularOrder", "client promoted popular placement")
    assert_contains(view_utils, "callbacks.showInstructions !== false", "shared modal defaults to showing instructions")
    assert_contains(view_utils, "agent.action_labels", "details use resolved action labels")
    assert_contains(view_utils, "agent.model_label", "details use resolved model label")
    assert_contains(view_utils, "Times Used All Time", "details all-time usage label")
    assert_contains(view_utils, "Times Used Last 30 Days", "details recent usage label")
    assert_contains(view_utils, "marked.parse(rawInstructions)", "details render instructions markdown")


def test_agents_catalog_omits_instructions_when_admin_disabled():
    backend_route = read_repo_file("application/single_app/route_backend_agents.py")
    catalog_script = read_repo_file("application/single_app/static/js/agents_catalog.js")
    view_utils = read_repo_file("application/single_app/static/js/workspace/view-utils.js")

    assert_contains(
        backend_route,
        "agent_copy.pop('instructions', None)",
        "catalog response instruction removal",
    )
    assert_contains(
        backend_route,
        "if not settings.get('agents_page_show_instructions_in_details', True):",
        "admin-disabled instruction redaction gate",
    )
    assert_contains(
        backend_route,
        "popular_agents = _redact_catalog_agent_instructions(popular_agents)",
        "popular catalog instruction redaction",
    )
    assert_contains(
        catalog_script,
        "directory?.dataset.showInstructionsInDetails !== 'false'",
        "Agents tab defaults instructions visible unless disabled",
    )
    assert_contains(view_utils, "const instructionsHtml = showInstructions ?", "conditional instructions section")


def test_agent_catalog_usage_windows_rank_independently():
    def normalize_promoted_agents(value):
        normalized_agents = []
        seen_keys = set()
        for candidate in value if isinstance(value, list) else []:
            if not isinstance(candidate, dict):
                continue
            catalog_key = str(candidate.get("catalog_key") or "").strip()
            if not catalog_key or catalog_key in seen_keys:
                continue
            seen_keys.add(catalog_key)
            normalized_agents.append({
                "catalog_key": catalog_key,
                "display_name": str(candidate.get("display_name") or "").strip(),
                "scope_label": str(candidate.get("scope_label") or "").strip(),
                "scope_type": str(candidate.get("scope_type") or "").strip(),
                "window": str(candidate.get("window") or "both").strip() or "both",
            })
        return normalized_agents

    def normalize_promotion_order(value):
        return value if value in {"before", "after", "mixed"} else "before"

    def normalize_promotion_window(value):
        return value if value in {"all_time", "30_days", "both"} else "both"

    def normalize_promotion_tag_label(value):
        return str(value or "Promoted").strip()[:40] or "Promoted"

    stub_modules = {
        "config": {"cosmos_activity_logs_container": SimpleNamespace(query_items=lambda **kwargs: [])},
        "functions_appinsights": {"log_event": lambda *args, **kwargs: None},
        "functions_assigned_knowledge": {"get_agent_assigned_knowledge": lambda *args, **kwargs: {}},
        "functions_global_actions": {"get_global_actions": lambda *args, **kwargs: []},
        "functions_global_agents": {"get_global_agents": lambda *args, **kwargs: []},
        "functions_group": {"get_group_model_endpoints": lambda *args, **kwargs: [], "get_user_groups": lambda *args, **kwargs: []},
        "functions_group_actions": {"get_group_actions": lambda *args, **kwargs: []},
        "functions_group_agents": {"get_group_agents": lambda *args, **kwargs: []},
        "functions_governance": {
            "filter_actions_by_action_type_access": lambda _user_id, actions, _feature_key, _scope: actions or [],
            "filter_governed_global_actions_for_user": lambda _user_id, actions: actions or [],
        },
        "functions_keyvault": {"SecretReturnType": SimpleNamespace(NAME="name")},
        "functions_personal_actions": {
            "get_governed_personal_actions": lambda *args, **kwargs: [],
            "get_personal_actions": lambda *args, **kwargs: [],
        },
        "functions_personal_agents": {"ensure_migration_complete": lambda *args, **kwargs: None, "get_personal_agents": lambda *args, **kwargs: []},
        "functions_settings": {
            "get_settings": lambda *args, **kwargs: {},
            "get_user_settings": lambda *args, **kwargs: {"settings": {}},
            "normalize_agents_page_promoted_popular_agents": normalize_promoted_agents,
            "normalize_agents_page_promoted_popular_order": normalize_promotion_order,
            "normalize_agents_page_promoted_popular_tag_enabled": lambda value: bool(value),
            "normalize_agents_page_promoted_popular_tag_label": normalize_promotion_tag_label,
            "normalize_agents_page_promoted_popular_window": normalize_promotion_window,
            "normalize_model_endpoints": lambda endpoints: (endpoints or [], []),
        },
    }
    original_modules = {name: sys.modules.get(name) for name in stub_modules}
    original_catalog_module = sys.modules.pop("functions_agent_catalog", None)
    for module_name, attributes in stub_modules.items():
        module = ModuleType(module_name)
        for attribute_name, value in attributes.items():
            setattr(module, attribute_name, value)
        sys.modules[module_name] = module

    catalog_module = importlib.import_module("functions_agent_catalog")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    records = [
        {"agent_catalog_key": "global:global:alpha", "timestamp": (now - timedelta(days=2)).isoformat()},
        {"agent_catalog_key": "global:global:alpha", "timestamp": (now - timedelta(days=45)).isoformat()},
        {"agent_catalog_key": "global:global:alpha", "timestamp": (now - timedelta(days=90)).isoformat()},
        {"agent_catalog_key": "global:global:beta", "timestamp": (now - timedelta(days=1)).isoformat()},
        {"agent_catalog_key": "global:global:beta", "timestamp": (now - timedelta(days=3)).isoformat()},
    ]

    class FakeActivityLogContainer:
        def query_items(self, query, parameters=None, enable_cross_partition_query=False):
            since = None
            for parameter in parameters or []:
                if parameter.get("name") == "@since":
                    since = datetime.fromisoformat(parameter.get("value"))

            if since is None:
                return list(records)

            return [record for record in records if datetime.fromisoformat(record["timestamp"]) >= since]

    catalog_module.cosmos_activity_logs_container = FakeActivityLogContainer()
    try:
        catalog = [
            {"catalog_key": "global:global:alpha", "display_name": "Alpha"},
            {"catalog_key": "global:global:beta", "display_name": "Beta"},
        ]
        catalog_module.apply_agent_usage_counts(catalog, days=30)

        alpha, beta = catalog
        assert alpha["usage_count_all_time"] == 3
        assert alpha["usage_count_30_days"] == 1
        assert beta["usage_count_all_time"] == 2
        assert beta["usage_count_30_days"] == 2

        all_time_names = [agent["display_name"] for agent in catalog_module.get_popular_agents(catalog, limit=2, usage_window="all_time")]
        recent_names = [agent["display_name"] for agent in catalog_module.get_popular_agents(catalog, limit=2, usage_window="30_days")]
        assert all_time_names == ["Alpha", "Beta"]
        assert recent_names == ["Beta", "Alpha"]

        promoted_catalog = [
            {"catalog_key": "global:global:seed", "display_name": "Seed", "usage_count_all_time": 0, "usage_count_30_days": 0},
            {"catalog_key": "global:global:alpha", "display_name": "Alpha", "usage_count_all_time": 3, "usage_count_30_days": 1},
            {"catalog_key": "global:global:beta", "display_name": "Beta", "usage_count_all_time": 2, "usage_count_30_days": 2},
        ]
        catalog_module.apply_agent_popular_promotions(
            promoted_catalog,
            settings={
                "agents_page_promoted_popular_agents": [
                    {"catalog_key": "global:global:seed", "display_name": "Seed", "window": "all_time"},
                    {"catalog_key": "group:missing:hidden", "display_name": "Hidden", "window": "both"},
                ],
                "agents_page_promoted_popular_order": "before",
                "agents_page_promoted_popular_tag_enabled": True,
                "agents_page_promoted_popular_tag_label": "Featured",
            },
        )

        seed_agent = promoted_catalog[0]
        assert seed_agent["is_promoted_popular"] is True
        assert seed_agent["promoted_popular_window"] == "all_time"
        assert seed_agent["promoted_popular_tag_label"] == "Featured"
        all_time_promoted_names = [
            agent["display_name"]
            for agent in catalog_module.get_popular_agents(promoted_catalog, limit=2, usage_window="all_time")
        ]
        recent_promoted_names = [
            agent["display_name"]
            for agent in catalog_module.get_popular_agents(promoted_catalog, limit=2, usage_window="30_days")
        ]
        assert all_time_promoted_names == ["Seed", "Alpha", "Beta"]
        assert recent_promoted_names == ["Beta", "Alpha"]
    finally:
        sys.modules.pop("functions_agent_catalog", None)
        if original_catalog_module is not None:
            sys.modules["functions_agent_catalog"] = original_catalog_module
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def run_tests():
    tests = [
        test_agent_payload_tags_and_icon_normalization,
        test_agent_schema_exposes_catalog_metadata,
        test_agents_catalog_routes_and_navigation,
        test_agents_catalog_browser_rendering_uses_safe_dom_patterns,
        test_agents_catalog_workspace_creation_links,
        test_agents_page_admin_customization_settings,
        test_chat_agent_metadata_and_avatar_handoff,
        test_agent_modal_icon_picker_and_upload_contract,
        test_model_icon_contract,
        test_agents_catalog_resolves_model_and_action_labels,
        test_agents_catalog_omits_instructions_when_admin_disabled,
        test_agent_catalog_usage_windows_rank_independently,
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
