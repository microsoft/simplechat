#!/usr/bin/env python3
# test_agent_editor_hides_internal_ids.py
"""
Functional test for hiding internal identifiers in the shared agent editor.
Version: 0.261.275
Implemented in: 0.261.275

This test ensures that the shared v2 agent editor (personal, group and global agents)
does not render GUIDs or internal IDs: no stable ID in the header or identity section,
no endpoint/model IDs in Current selection, no action IDs in the action picker, and no
workspace or document IDs in the knowledge fields. It also checks that the header shows
the agent's own icon and that documents show their file name.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "application", "v2_ui", "src")


def read_source(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_header_shows_agent_icon_without_stable_id():
    """The editor header renders the agent icon and never the stable ID."""
    page = read_source("pages", "workspace", "AgentEditorPage.tsx")
    frame = read_source("components", "workspace", "WorkspaceEditorFrame.tsx")
    identity = read_source("components", "workspaceAgents", "AgentIdentityFields.tsx")
    assert "<AgentIcon icon={draft.icon}" in page
    assert "iconNode" in page and "iconNode" in frame
    assert "Stable ID" not in page
    assert "Stable ID" not in identity
    return True


def test_current_selection_uses_readable_names():
    """Current selection lists deployment, model, connection and provider names only."""
    model = read_source("components", "workspaceAgents", "AgentModelFields.tsx")
    for removed in ("Endpoint ID", ">Model ID<", "'Model ID'"):
        assert removed not in model, removed
    for label in ("'Deployment'", "'Model'", "'Connection'", "'Provider'"):
        assert label in model, label
    assert "PROVIDER_OPTIONS" in model
    assert "GUID_PATTERN" in model
    return True


def test_action_picker_hides_action_ids():
    """Action choices and unavailable references never render IDs."""
    picker = read_source("components", "workspaceAgents", "AgentActionPicker.tsx")
    assert "ID: {action.id}" not in picker
    assert "Unavailable action" in picker
    return True


def test_knowledge_fields_hide_ids_and_show_file_names():
    """Workspaces show a friendly type, documents show file names, and no IDs render."""
    knowledge = read_source("components", "workspaceAgents", "AgentKnowledgeFields.tsx")
    assert "{source.scope} · {source.id}" not in knowledge
    assert "{document.source_name} · {document.id}" not in knowledge
    assert "Unavailable document: {id}" not in knowledge
    assert "Saved source unavailable here: {key}" not in knowledge
    assert "${document.id}`.toLowerCase()" not in knowledge
    assert "sourceTypeLabel" in knowledge
    assert "document.file_name" in knowledge
    return True


def test_version_floor():
    assert_app_version_at_least("0.261.275")
    return True


if __name__ == "__main__":
    tests = [
        test_header_shows_agent_icon_without_stable_id,
        test_current_selection_uses_readable_names,
        test_action_picker_hides_action_ids,
        test_knowledge_fields_hide_ids_and_show_file_names,
        test_version_floor,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            results.append(test())
        except AssertionError as error:
            print(f"Failed: {test.__name__}: {error}")
            results.append(False)
    print(f"Results: {sum(bool(r) for r in results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
