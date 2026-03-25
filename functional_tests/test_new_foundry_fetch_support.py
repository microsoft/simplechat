# test_new_foundry_fetch_support.py
#!/usr/bin/env python3
"""
Functional test for new Foundry fetch support.
Version: 0.239.154
Implemented in: 0.239.154

This test ensures that the backend exposes a new_foundry fetch path and that
the agent modal can fetch and apply New Foundry application metadata.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_new_foundry_fetch_support_present():
    """Validate New Foundry fetch plumbing across backend and modal files."""
    print("🔍 Testing New Foundry fetch support...")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    models_path = os.path.join(repo_root, "application", "single_app", "route_backend_models.py")
    modal_js_path = os.path.join(repo_root, "application", "single_app", "static", "js", "agent_modal_stepper.js")
    modal_html_path = os.path.join(repo_root, "application", "single_app", "templates", "_agent_modal.html")

    models_content = read_file_text(models_path)
    modal_js_content = read_file_text(modal_js_path)
    modal_html_content = read_file_text(modal_html_path)

    required_snippets = [
        "from azure.ai.projects import AIProjectClient",
        "def list_new_foundry_agents_from_project",
        'if provider == "new_foundry":',
        'agents = list_new_foundry_agents_from_project(endpoint_cfg)',
        "foundryFetchBtnLabel.textContent = isNewFoundry ? 'Fetch Applications' : 'Fetch Agents';",
        "return normalizedProvider === this.getCurrentFoundryProvider();",
        "applicationIdInput.value = selected.application_id || selected.id || '';",
        'id="agent-foundry-fetch-btn-label"',
        'id="agent-foundry-select-label"',
    ]

    combined = "\n".join([models_content, modal_js_content, modal_html_content])
    missing = [snippet for snippet in required_snippets if snippet not in combined]
    if missing:
        raise AssertionError(f"Missing expected New Foundry fetch snippets: {', '.join(missing)}")

    print("✅ New Foundry fetch support verified.")


if __name__ == "__main__":
    success = True
    try:
        test_new_foundry_fetch_support_present()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)