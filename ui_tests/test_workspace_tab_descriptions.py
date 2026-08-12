# test_workspace_tab_descriptions.py
"""
UI contract test for workspace tab descriptions.
Version: 0.250.014
Implemented in: 0.250.014

This test ensures workspace tab and sidebar labels expose concise hover
descriptions without rendering persistent explanatory text into the layout.
"""

from pathlib import Path

import pytest


jinja2 = pytest.importorskip("jinja2")


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT_DIR / "application" / "single_app" / "templates"

HELP_TITLES_BY_TEMPLATE = {
    "workspace.html": [
        "Upload, search, organize, tag, and manage personal files used for grounded chat after processing and indexing.",
        "Configure external file sources that bring approved files into this workspace and run them through the document processing pipeline.",
        "Manage reusable authentication profiles for File Sync and Actions so credentials stay scoped and resolved server-side.",
        "Create, search, view, and reuse prompt templates for consistent chat instructions.",
        "Reusable, specialized AI assistants that combine instructions, approved knowledge, and optional actions. Actions are tasks an agent is allowed to perform.",
        "Configure governed tools that agents can call, such as APIs, databases, or other connected systems.",
        "Save repeatable personal tasks that run manually or on a schedule using a selected model or agent, with optional document actions and run history.",
        "Manage model endpoints available to personal agents and workflows alongside admin-managed global endpoints.",
    ],
    "group_workspaces.html": [
        "Manage shared group files with role-aware upload, metadata filters, tags, bulk actions, extraction changes, and chat grounding.",
        "Configure group-scoped file sources that bring approved files into this workspace and run them through the document processing pipeline.",
        "Manage reusable group authentication profiles for File Sync and Actions so credentials stay scoped and resolved server-side.",
        "Create and manage reusable prompts shared within the active group, with role-based editing.",
        "Create repeatable group tasks that run manually, on a schedule, or after File Sync changes using group agents, documents, or models.",
        "Reusable, specialized AI assistants that combine instructions, approved knowledge, and optional actions. Actions are tasks an agent is allowed to perform.",
        "Configure governed group tools that agents can call, such as APIs, databases, or other connected systems.",
        "Manage model endpoints available to group agents and workflows alongside admin-managed global endpoints.",
    ],
    "public_workspaces.html": [
        "Browse and manage public workspace files with metadata filters, tags, folder views, extraction changes, and chat grounding when permitted.",
        "Manage reusable prompts associated with this public workspace, with list and card views for quick review.",
    ],
    "manage_group.html": [
        "Edit group details, branding, logo, ownership, and member-level actions.",
        "Manage members, roles, pending requests, bulk imports, role changes, and removals.",
        "Review document, storage, token, member, and activity metrics across selectable time windows, with CSV export.",
        "Configure group-specific retention and file-download overrides when these controls are enabled.",
    ],
    "manage_public_workspace.html": [
        "Edit workspace details, branding, logo, ownership, and member-level actions.",
        "Manage members, roles, pending requests, bulk imports, role changes, and removals.",
        "Review document, storage, token, member, and activity metrics across selectable time windows, with CSV export.",
        "Manage reusable File Sync authentication profiles scoped to this public workspace.",
        "Configure public workspace file sources that bring approved files into this workspace and run them through the document processing pipeline.",
        "Configure public workspace retention and file-download overrides when these controls are enabled.",
    ],
    "_sidebar_nav.html": [
        "Open your personal workspace for private documents, prompts, agents, actions, workflows, endpoints, sync, and identities.",
        "Open group workspaces for shared documents, prompts, agents, actions, workflows, endpoints, sync, and identities.",
        "Open public workspaces for shared document collections and prompts available to authorized users.",
        "Reusable, specialized AI assistants that combine instructions, approved knowledge, and optional actions. Actions are tasks an agent is allowed to perform.",
    ],
}


def test_workspace_description_templates_parse() -> None:
    """Validate changed Jinja templates still parse."""
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=jinja2.select_autoescape(["html"]),
    )

    for template_name in HELP_TITLES_BY_TEMPLATE:
        source = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
        environment.parse(source)


def test_workspace_tabs_and_sidebar_use_hover_descriptions() -> None:
    """Validate workspace descriptions are present as hover text."""
    for template_name, descriptions in HELP_TITLES_BY_TEMPLATE.items():
        content = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")

        for description in descriptions:
            assert f'title="{description}"' in content, f"Missing hover description in {template_name}: {description}"