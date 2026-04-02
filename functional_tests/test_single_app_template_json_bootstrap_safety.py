#!/usr/bin/env python3
# test_single_app_template_json_bootstrap_safety.py
"""
Functional test for single_app template JSON bootstrap safety.
Version: 0.240.020
Implemented in: 0.240.020

This test ensures the workspace and admin templates emit bootstrapped JSON as
direct JavaScript literals rather than wrapping Jinja JSON output in
JSON.parse string literals that can break when payload values contain control
characters or quotes.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"

TEMPLATE_CASES = {
    "workspace.html": {
        "path": REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html",
        "safe": [
            "window.workspaceModelEndpoints = {{ personal_model_endpoints|default([], true)|tojson|safe }};",
            "window.globalModelEndpoints = {{ global_model_endpoints|default([], true)|tojson|safe }};",
            "window.classification_categories = {{ settings.document_classification_categories|default([], true)|tojson(indent=None)|safe }};",
        ],
        "unsafe": [
            "window.workspaceModelEndpoints = JSON.parse('{{ personal_model_endpoints|default([])|tojson|safe }}' || '[]');",
            "window.globalModelEndpoints = JSON.parse('{{ global_model_endpoints|default([])|tojson|safe }}' || '[]');",
            "window.classification_categories = JSON.parse('{{ settings.document_classification_categories|tojson(indent=None)|safe }}' || '[]');",
        ],
    },
    "group_workspaces.html": {
        "path": REPO_ROOT / "application" / "single_app" / "templates" / "group_workspaces.html",
        "safe": [
            "window.workspaceModelEndpoints = {{ group_model_endpoints|default([], true)|tojson|safe }};",
            "window.globalModelEndpoints = {{ global_model_endpoints|default([], true)|tojson|safe }};",
            "window.classification_categories = {{ settings.document_classification_categories|default([], true)|tojson(indent=None)|safe }};",
        ],
        "unsafe": [
            "window.workspaceModelEndpoints = JSON.parse('{{ group_model_endpoints|default([])|tojson|safe }}' || '[]');",
            "window.globalModelEndpoints = JSON.parse('{{ global_model_endpoints|default([])|tojson|safe }}' || '[]');",
            "window.classification_categories = JSON.parse('{{ settings.document_classification_categories|tojson(indent=None)|safe }}' || '[]');",
        ],
    },
    "public_workspaces.html": {
        "path": REPO_ROOT / "application" / "single_app" / "templates" / "public_workspaces.html",
        "safe": [
            "window.classification_categories = {{ settings.document_classification_categories|default([], true)|tojson(indent=None)|safe }};",
        ],
        "unsafe": [
            "window.classification_categories = JSON.parse('{{ settings.document_classification_categories|tojson(indent=None)|safe }}' || '[]');",
        ],
    },
    "admin_settings.html": {
        "path": REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html",
        "safe": [
            "window.gptSelected = {{ settings.gpt_model.selected|default([], true)|tojson|safe }};",
            "window.gptAll      = {{ settings.gpt_model.all|default([], true)|tojson|safe }};",
            "window.embeddingSelected = {{ settings.embedding_model.selected|default([], true)|tojson|safe }};",
            "window.embeddingAll      = {{ settings.embedding_model.all|default([], true)|tojson|safe }};",
            "window.imageSelected = {{ settings.image_gen_model.selected|default([], true)|tojson|safe }};",
            "window.imageAll      = {{ settings.image_gen_model.all|default([], true)|tojson|safe }};",
            "window.modelEndpoints = {{ settings.model_endpoints|default([], true)|tojson|safe }};",
            "window.defaultModelSelection = {{ settings.default_model_selection|default({}, true)|tojson|safe }};",
            "window.multiEndpointMigrationNotice = {{ settings.multi_endpoint_migration_notice|default({}, true)|tojson|safe }};",
            "window.classificationCategories = {{ settings.document_classification_categories|default([], true)|tojson(indent=None)|safe }};",
            "window.externalLinks = {{ settings.external_links|default([], true)|tojson(indent=None)|safe }};",
        ],
        "unsafe": [
            "window.gptSelected = JSON.parse('{{ settings.gpt_model.selected|tojson()|safe }}' || '[]');",
            "window.gptAll      = JSON.parse('{{ settings.gpt_model.all|tojson()|safe }}' || '[]');",
            "window.embeddingSelected = JSON.parse('{{ settings.embedding_model.selected|tojson()|safe }}' || '[]');",
            "window.embeddingAll      = JSON.parse('{{ settings.embedding_model.all|tojson()|safe }}' || '[]');",
            "window.imageSelected = JSON.parse('{{ settings.image_gen_model.selected|tojson()|safe }}' || '[]');",
            "window.imageAll      = JSON.parse('{{ settings.image_gen_model.all|tojson()|safe }}' || '[]');",
            "window.modelEndpoints = JSON.parse('{{ settings.model_endpoints|tojson()|safe }}' || '[]');",
            "window.defaultModelSelection = JSON.parse('{{ settings.default_model_selection|tojson()|safe }}' || '{}');",
            "window.multiEndpointMigrationNotice = JSON.parse('{{ settings.multi_endpoint_migration_notice|tojson()|safe }}' || '{}');",
            "let categoriesStr = '{{ settings.document_classification_categories|tojson(indent=None)|safe }}';",
            "window.classificationCategories = JSON.parse(categoriesStr);",
            "let externalLinksStr = '{{ settings.external_links|tojson(indent=None)|safe }}';",
            "window.externalLinks = JSON.parse(externalLinksStr);",
        ],
    },
}


def test_single_app_templates_bootstrap_json_with_direct_literals():
    """Verify single_app templates bootstrap JSON with direct Jinja literals."""
    config_content = CONFIG_FILE.read_text(encoding="utf-8")

    assert 'VERSION = "0.240.020"' in config_content, "Expected config.py version 0.240.020"

    failures = []
    for template_name, case in TEMPLATE_CASES.items():
        content = case["path"].read_text(encoding="utf-8")

        missing_safe = [snippet for snippet in case["safe"] if snippet not in content]
        if missing_safe:
            failures.append(f"{template_name} missing safe snippets: {missing_safe}")

        present_unsafe = [snippet for snippet in case["unsafe"] if snippet in content]
        if present_unsafe:
            failures.append(f"{template_name} still contains unsafe snippets: {present_unsafe}")

    assert not failures, " ; ".join(failures)


if __name__ == "__main__":
    test_single_app_templates_bootstrap_json_with_direct_literals()
    print("✅ single_app template JSON bootstrap safety verified.")