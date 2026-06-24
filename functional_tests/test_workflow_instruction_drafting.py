# test_workflow_instruction_drafting.py
"""
Functional test for workflow instruction drafting.
Version: 0.250.028
Implemented in: 0.250.028

This test ensures workflow creation exposes a task brief, drafts workflow or task
instructions through a gated backend endpoint, and keeps the saved task_prompt
contract intact for existing workflow storage.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workflow_instruction_drafting_contract():
    """Validate workflow draft API and UI wiring."""
    config_content = read_text("application/single_app/config.py")
    route_content = read_text("application/single_app/route_backend_workflows.py")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    voice_js_content = read_text("application/single_app/static/js/form-voice-input.js")
    workspace_template_content = read_text("application/single_app/templates/workspace.html")
    group_workspace_template_content = read_text("application/single_app/templates/group_workspaces.html")
    action_modal_content = read_text("application/single_app/templates/_plugin_modal.html")

    assert 'VERSION = "0.250.028"' in config_content, (
        "Expected config.py to carry the workflow instruction drafting version."
    )
    assert "@app.route('/api/workflows/draft-instructions', methods=['POST'])" in route_content, (
        "Expected a shared workflow instruction drafting endpoint."
    )
    assert "@swagger_route(security=get_auth_security())" in route_content, (
        "Expected the workflow draft endpoint to use Swagger auth metadata."
    )
    assert "_assert_personal_workflow_draft_access(settings)" in route_content, (
        "Expected personal workflow drafting to honor workflow app-role gating."
    )
    assert "_resolve_active_group_for_workflow_management(user_id)" in route_content, (
        "Expected group workflow drafting to honor group workflow management roles."
    )
    assert "_build_workflow_instruction_messages" in route_content, (
        "Expected workflow-specific draft prompt construction."
    )
    assert "workflow or task instructions" in route_content, (
        "Expected the draft prompt to use workflow/task instructions language."
    )

    for template_content in (workspace_template_content, group_workspace_template_content):
        assert 'id="workflow-task-brief"' in template_content, (
            "Expected workflow modals to expose a task brief field."
        )
        assert 'id="workflow-draft-instructions-btn"' in template_content, (
            "Expected workflow modals to expose a Draft Workflow Instructions button."
        )
        assert 'Workflow or Task Instructions' in template_content, (
            "Expected workflow modals to rename Task Prompt for users."
        )
        assert 'id="workflow-task-prompt"' in template_content, (
            "Expected workflow modals to preserve the task_prompt field id for storage compatibility."
        )

    assert "draftWorkflowInstructions" in workflow_js_content, (
        "Expected workflow JavaScript to implement the draft button flow."
    )
    assert "workflow_scope" in workflow_js_content, (
        "Expected the workflow draft request to include personal/group scope."
    )
    assert "existing_instructions" in workflow_js_content, (
        "Expected the workflow draft request to improve existing saved instructions when present."
    )
    assert "task_prompt: normalizeText(workflowTaskPromptInput?.value)" in workflow_js_content, (
        "Expected saved workflows to keep using the task_prompt payload key."
    )

    assert "workflow-task-brief" in voice_js_content, (
        "Expected voice input to support the workflow task brief."
    )
    assert "workflow-task-prompt" in voice_js_content, (
        "Expected voice input to support workflow or task instructions."
    )
    assert "plugin-display-name" in voice_js_content, (
        "Expected voice input to support action display names."
    )
    assert "plugin-name" in voice_js_content, (
        "Expected voice input to support action names."
    )
    assert "plugin-description" in voice_js_content, (
        "Expected voice input to support action descriptions."
    )

    assert 'id="plugin-name" name="plugin_name"' in action_modal_content, (
        "Expected the shared action modal to expose the generated action name for voice editing."
    )
    assert 'type="hidden" id="plugin-name"' not in action_modal_content, (
        "Expected action name to be visible instead of hidden so voice input can target it."
    )
