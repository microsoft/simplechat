# test_admin_agent_default_model_migration.py
#!/usr/bin/env python3
"""
Functional test for admin agent default-model migration workflow.
Version: 0.240.075
Implemented in: 0.240.073

This test ensures admin APIs and the AI Models admin page expose a preview and
selection-driven migration workflow for legacy agents and future default-model
rebinding scenarios.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_admin_agent_default_model_migration_wiring():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_path = os.path.join(
        repo_root, "application", "single_app", "route_backend_agents.py"
    )
    template_path = os.path.join(
        repo_root, "application", "single_app", "templates", "admin_settings.html"
    )
    js_path = os.path.join(
        repo_root, "application", "single_app", "static", "js", "admin", "admin_model_endpoints.js"
    )
    admin_settings_js_path = os.path.join(
        repo_root, "application", "single_app", "static", "js", "admin", "admin_settings.js"
    )
    payload_path = os.path.join(
        repo_root, "application", "single_app", "functions_agent_payload.py"
    )
    config_path = os.path.join(
        repo_root, "application", "single_app", "config.py"
    )

    backend_content = read_file_text(backend_path)
    template_content = read_file_text(template_path)
    js_content = read_file_text(js_path)
    admin_settings_js_content = read_file_text(admin_settings_js_path)
    payload_content = read_file_text(payload_path)
    config_content = read_file_text(config_path)

    assert "/api/admin/agents/default-model-migration/preview" in backend_content, (
        "Expected an admin preview endpoint for default-model migration."
    )
    assert "/api/admin/agents/default-model-migration/run" in backend_content, (
        "Expected an admin bulk migration endpoint for default-model migration."
    )
    assert "_build_default_model_agent_migration_preview" in backend_content, (
        "Expected route_backend_agents.py to build a reusable migration preview payload."
    )
    assert "save_personal_agent(scope_id, agent, actor_user_id=admin_user_id)" in backend_content, (
        "Expected personal-agent migration writes to preserve the admin actor ID."
    )
    assert "selected_agent_keys" in backend_content, (
        "Expected the migration run endpoint to accept an explicit set of selected agent keys."
    )
    assert "_clear_legacy_agent_connection_override" in backend_content, (
        "Expected explicit override migrations to clear legacy custom connection fields before rebinding."
    )
    assert "can_force_migrate" in backend_content, (
        "Expected preview records to distinguish manual-review agents that admins can explicitly override."
    )
    assert "can_agent_use_default_multi_endpoint_model" in payload_content, (
        "Expected shared agent payload helpers to identify inherited/default-connection agents."
    )
    assert "id=\"agent-default-model-migration-panel\"" in template_content, (
        "Expected admin settings to render the agent migration panel."
    )
    assert "id=\"agentDefaultModelMigrationModal\"" in template_content, (
        "Expected admin settings to render the migration review modal."
    )
    assert "id=\"agent-default-model-migration-search\"" in template_content, (
        "Expected admin settings to render a search input for large migration reviews."
    )
    assert "id=\"select-manual-agent-default-model-migration-btn\"" in template_content, (
        "Expected admin settings to expose a manual-review override selection control."
    )
    assert "id=\"preview-agent-default-model-migration-btn\"" in template_content, (
        "Expected admin settings to render the migration preview button."
    )
    assert "id=\"run-agent-default-model-migration-btn\"" in template_content, (
        "Expected admin settings to render the bulk migration button."
    )
    assert 'data-open-admin-tab="#ai-models"' in template_content, (
        "Expected the Agents tab to link admins back to AI Models for model-review workflows."
    )
    assert 'data-open-admin-tab="#agents"' in template_content, (
        "Expected the AI Models disabled-state guidance to link admins to Agents settings."
    )
    assert 'id="multi-endpoint-warning"' not in template_content, (
        "Expected admin settings to remove the obsolete multi-endpoint warning banner."
    )
    assert 'fetch("/api/admin/agents/default-model-migration/preview"' in js_content, (
        "Expected admin_model_endpoints.js to fetch the migration preview."
    )
    assert 'fetch("/api/admin/agents/default-model-migration/run"' in js_content, (
        "Expected admin_model_endpoints.js to invoke the bulk migration endpoint."
    )
    assert 'selected_agent_keys: Array.from(migrationSelectedKeys)' in js_content, (
        "Expected admin_model_endpoints.js to submit the explicitly selected agents for migration."
    )
    assert 'openMigrationReviewModal' in js_content, (
        "Expected admin_model_endpoints.js to open the review workflow in a modal."
    )
    assert 'select-manual-agent-default-model-migration-btn' in js_content, (
        "Expected admin_model_endpoints.js to support selecting manual-review override candidates."
    )
    assert 'window.multiEndpointMigrationNotice' not in js_content, (
        "Expected admin_model_endpoints.js to stop depending on obsolete migration notice state."
    )
    assert "window.isAdminSettingsFormModified" in js_content or "window.isAdminSettingsFormModified" in admin_settings_js_content, (
        "Expected admin settings JS to expose unsaved-form state for migration safeguards."
    )
    assert "openAdminSettingsTab" in admin_settings_js_content, (
        "Expected admin settings JS to expose a reusable tab navigation helper for cross-links."
    )
    assert 'VERSION = "0.240.075"' in config_content, (
        "Expected config.py version 0.240.075 after the workspace agent chat launch selection fix."
    )

    print("✅ Admin agent default-model migration wiring verified.")


def run_tests():
    tests = [test_admin_agent_default_model_migration_wiring]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)