#!/usr/bin/env python3
# test_voice_assisted_authoring.py
"""
Functional test for voice-assisted form authoring.
Version: 0.241.177
Implemented in: 0.241.177

This test ensures speech-to-text controls and model-backed agent instruction
drafting are wired across agent, workspace, group, and public workspace forms
without requiring live microphone, Azure Speech, or Azure OpenAI services.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_voice_assisted_authoring_contract():
    """Verify voice controls, draft endpoint, and version tracking are wired."""
    config_text = read_text("application/single_app/config.py")
    base_template = read_text("application/single_app/templates/base.html")
    agent_modal = read_text("application/single_app/templates/_agent_modal.html")
    agent_stepper = read_text("application/single_app/static/js/agent_modal_stepper.js")
    voice_helper = read_text("application/single_app/static/js/form-voice-input.js")
    agent_routes = read_text("application/single_app/route_backend_agents.py")
    manage_group_js = read_text("application/single_app/static/js/group/manage_group.js")
    manage_public_js = read_text("application/single_app/static/js/public/manage_public_workspace.js")

    assert 'VERSION = "0.241.177"' in config_text

    assert "js/form-voice-input.js" in base_template
    assert "app_settings.enable_speech_to_text_input" in base_template
    assert "session.get('user')" in base_template

    assert "const DEFAULT_TRANSCRIPTION_ENDPOINT = '/api/speech/transcribe-chat';" in voice_helper
    assert "function normalizeTagName" in voice_helper
    assert "function normalizeCommaList" in voice_helper
    assert "window.SimpleChatVoiceInput" in voice_helper
    for field_id in [
        "agent-display-name",
        "agent-description",
        "agent-instruction-brief",
        "groupName",
        "groupDescription",
        "editGroupName",
        "editGroupDescription",
        "publicWorkspaceName",
        "publicWorkspaceDescription",
        "editWorkspaceName",
        "editWorkspaceDescription",
        "doc-title",
        "doc-abstract",
        "doc-keywords",
        "public-doc-title",
        "public-doc-abstract",
        "public-doc-keywords",
        "new-tag-name",
        "group-new-tag-name",
        "public-new-tag-name",
    ]:
        assert field_id in voice_helper, f"Expected default voice wiring for {field_id}."

    assert 'id="agent-instruction-brief"' in agent_modal
    assert 'id="agent-draft-instructions-btn"' in agent_modal
    assert "initializeVoiceControls()" in agent_stepper
    assert "SimpleChatVoiceInput.enhanceFieldById('agent-instructions'" in agent_stepper
    assert "async draftInstructions()" in agent_stepper
    assert "fetch('/api/agents/draft-instructions'" in agent_stepper
    assert "this.setInstructionsValue(result.instructions || '')" in agent_stepper

    assert "@bpa.route('/api/agents/draft-instructions', methods=['POST'])" in agent_routes
    assert "@swagger_route(" in agent_routes
    assert "@login_required" in agent_routes
    assert "@user_required" in agent_routes
    assert "require_active_group(" in agent_routes
    assert "Group agents are disabled." in agent_routes
    assert "Personal agents are disabled." in agent_routes
    assert "Admin role is required to draft global agent instructions." in agent_routes
    assert "_build_agent_instruction_messages" in agent_routes
    assert "Return only the finished instructions in Markdown." in agent_routes
    assert "client.chat.completions.create" in agent_routes
    assert "max_completion_tokens" in agent_routes

    assert "window.SimpleChatVoiceInput?.refreshButtons?.();" in manage_group_js
    assert "window.SimpleChatVoiceInput?.refreshButtons?.();" in manage_public_js

    print("Voice-assisted authoring wiring verified.")


if __name__ == "__main__":
    test_voice_assisted_authoring_contract()