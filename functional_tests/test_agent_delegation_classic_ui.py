#!/usr/bin/env python3
# test_agent_delegation_classic_ui.py
"""
Functional test for the classic "Call agent" action modal and Actions step wiring.
Version: 0.261.093
Implemented in: 0.261.093

This test statically verifies the classic UI contract for agent delegation actions
without invoking a browser or any Azure/network dependency:

- `_plugin_modal.html` renders a dedicated Call agent configuration section (search,
  loading/error/empty/unavailable states, and a selected-target summary), with no
  endpoint, credential, identity, or test-connection controls for this type.
- `plugin_modal_stepper.js` treats `agent` as a first-class, structured action type
  that always normalizes to the fixed `internal://agent` endpoint and `{"type":
  "user"}` auth, stores only `additionalFields.target_agent`, fetches its target
  catalogue from the shared `/api/plugins/agent-targets` endpoint, and never renders
  the generic Step 4 additional-fields editor for it.
- `agent_modal_stepper.js` enriches Call agent actions shown in the agent Actions
  step with a resolved target label and blocks attaching an action that would
  delegate back to the agent currently being edited.
- The frontend's `agent`/`internal://agent` constants agree with the backend
  contract already defined in `functions_agent_delegation.py`.

Refs microsoft/simplechat agent delegation actions plan.
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

APP_DIR = os.path.join(REPO_ROOT, "application", "single_app")
MODAL_TEMPLATE = os.path.join(APP_DIR, "templates", "_plugin_modal.html")
PLUGIN_STEPPER_JS = os.path.join(APP_DIR, "static", "js", "plugin_modal_stepper.js")
AGENT_STEPPER_JS = os.path.join(APP_DIR, "static", "js", "agent_modal_stepper.js")
GROUP_AGENTS_JS = os.path.join(APP_DIR, "static", "js", "workspace", "group_agents.js")
DELEGATION_MODULE = os.path.join(APP_DIR, "functions_agent_delegation.py")

REQUIRED_TEMPLATE_ELEMENT_IDS = [
    "agent-config-section",
    "agent-target-search",
    "agent-target-loading",
    "agent-target-error",
    "agent-target-empty",
    "agent-target-unavailable",
    "agent-target-list",
    "agent-target-selected-summary",
    "agent-target-selected-name",
    "agent-target-selected-description",
    "agent-target-selected-type-badge",
    "agent-target-selected-scope-badge",
    "agent-target-change-btn",
    "summary-agent-section",
    "summary-agent-target-name",
    "summary-agent-target-type",
    "summary-agent-target-scope",
]


def _read(file_path):
    with open(file_path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_modal_renders_call_agent_section_without_endpoint_or_credential_controls():
    """Verify the modal markup exposes the Call agent panel and hides unrelated controls."""
    print("Testing Call agent modal markup...")

    try:
        assert_app_version_at_least(
            "0.261.093",
            reason="The classic Call agent configuration panel was added in 0.261.093.",
        )

        template_source = _read(MODAL_TEMPLATE)

        for element_id in REQUIRED_TEMPLATE_ELEMENT_IDS:
            assert f'id="{element_id}"' in template_source, f"Missing modal element: {element_id}"

        section_match = re.search(
            r'<div id="agent-config-section" class="d-none">(.*?)\n          </div>\n\n          <div id="mcp-config-section"',
            template_source,
            re.DOTALL,
        )
        assert section_match, "Could not isolate the agent-config-section markup block."
        section_body = section_match.group(1)

        assert "test-connection" not in section_body.lower(), (
            "Call agent configuration must not render a test-connection control."
        )
        assert "type=\"password\"" not in section_body, (
            "Call agent configuration must not render a credential input."
        )
        assert "identity" not in section_body.lower(), (
            "Call agent configuration must not expose a reusable identity control."
        )
        assert 'placeholder="https' not in section_body, (
            "Call agent configuration must not expose a free-form endpoint field."
        )

        print(f"Verified {len(REQUIRED_TEMPLATE_ELEMENT_IDS)} Call agent modal elements.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_stepper_treats_agent_as_a_structured_internal_type():
    """Verify plugin_modal_stepper.js normalizes the agent type and skips generic Step 4 fields."""
    print("Testing plugin_modal_stepper.js agent type wiring...")

    try:
        stepper_source = _read(PLUGIN_STEPPER_JS)

        assert "const AGENT_PLUGIN_TYPE = 'agent';" in stepper_source, (
            "The stepper must declare the agent plugin type constant."
        )
        assert "const AGENT_DEFAULT_ENDPOINT = 'internal://agent';" in stepper_source, (
            "The stepper must declare the fixed internal agent endpoint constant."
        )
        assert "isAgentType(type = this.selectedType)" in stepper_source, (
            "The stepper must expose an isAgentType predicate."
        )

        structured_match = re.search(
            r"isStructuredConfigType\(type = this\.selectedType\) \{\s*return ([^;]+);",
            stepper_source,
        )
        assert structured_match, "isStructuredConfigType was not found."
        assert "this.isAgentType(type)" in structured_match.group(1), (
            "agent must be a structured config type so Step 4 does not render a duplicate JSON editor."
        )

        assert "agent: document.getElementById('agent-config-section')" in stepper_source, (
            "The agent section must be registered in showConfigSectionForType."
        )
        assert "this.renderAgentConfiguration();" in stepper_source, (
            "Selecting the agent type must render the target picker."
        )

        # getEndpointValue / getAuthTypeValue must never expose a user-editable value.
        endpoint_match = re.search(r"getEndpointValue\(\) \{(.*?)\n  \}", stepper_source, re.DOTALL)
        assert endpoint_match, "getEndpointValue was not found."
        assert "return AGENT_DEFAULT_ENDPOINT;" in endpoint_match.group(1), (
            "getEndpointValue must return the fixed internal agent endpoint for the agent type."
        )

        auth_match = re.search(r"getAuthTypeValue\(\) \{(.*?)\n  \}", stepper_source, re.DOTALL)
        assert auth_match, "getAuthTypeValue was not found."
        assert "this.isAgentType()" in auth_match.group(1), (
            "getAuthTypeValue must special-case the agent type instead of exposing generic auth controls."
        )

        # getFormData must persist only target_agent and must throw without a selection.
        form_data_match = re.search(r"getFormData\(\) \{(.*?)\n    return formData;", stepper_source, re.DOTALL)
        assert form_data_match, "getFormData was not found."
        form_data_body = form_data_match.group(1)
        assert "additionalFields.target_agent = this.getSelectedAgentTargetPayload();" in form_data_body, (
            "getFormData must store the selected target under additionalFields.target_agent."
        )

        payload_match = re.search(
            r"getSelectedAgentTargetPayload\(\) \{(.*?)\n  \}",
            stepper_source,
            re.DOTALL,
        )
        assert payload_match, "getSelectedAgentTargetPayload was not found."
        payload_body = payload_match.group(1)
        assert "throw new Error" in payload_body, (
            "Saving without a selected target must raise a validation error rather than saving an empty reference."
        )
        assert set(re.findall(r"scope_type|scope_id|id", payload_body)) >= {"id", "scope_type", "scope_id"}, (
            "The saved target reference must include id, scope_type, and scope_id."
        )

        # The target catalogue must be fetched from the shared, scope-aware endpoint.
        assert "/api/plugins/agent-targets?" in stepper_source, (
            "The stepper must fetch the shared agent-targets catalogue endpoint."
        )
        assert "new URLSearchParams({ scope: this.getAgentTargetScope() })" in stepper_source, (
            "The stepper must build the agent-targets query string with URLSearchParams."
        )

        # An unresolved existing binding must not be silently cleared.
        selection_state_match = re.search(
            r"applyAgentTargetSelectionState\(\) \{(.*?)\n  \}",
            stepper_source,
            re.DOTALL,
        )
        assert selection_state_match, "applyAgentTargetSelectionState was not found."
        assert "agent-target-unavailable" in selection_state_match.group(1), (
            "An unresolved target reference must surface the unavailable banner instead of disappearing."
        )

        print("Verified plugin_modal_stepper.js agent type wiring.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_agent_modal_enriches_and_blocks_self_delegation():
    """Verify agent_modal_stepper.js labels Call agent actions and blocks self-attachment."""
    print("Testing agent_modal_stepper.js Call agent attachment wiring...")

    try:
        agent_stepper_source = _read(AGENT_STEPPER_JS)

        assert "const AGENT_DELEGATION_ACTION_TYPE = 'agent';" in agent_stepper_source, (
            "The agent modal must declare the Call agent action type constant."
        )
        assert "isSelfDelegationAction(action)" in agent_stepper_source, (
            "The agent modal must expose a self-delegation guard for the Actions step."
        )
        assert "enrichAgentDelegationLabels" in agent_stepper_source, (
            "The agent modal must resolve friendly target labels for Call agent actions."
        )
        assert "/api/plugins/agent-targets?" in agent_stepper_source, (
            "The agent modal must reuse the shared agent-targets catalogue endpoint."
        )

        card_match = re.search(r"createActionCard\(action\) \{(.*?)\n  \}\n\n  toggleActionSelection", agent_stepper_source, re.DOTALL)
        assert card_match, "createActionCard was not found."
        card_body = card_match.group(1)
        assert "isSelfDelegationAction(action)" in card_body, (
            "createActionCard must check for self-delegation before rendering the card."
        )
        assert "if (isSelfDelegation) {" in card_body, (
            "createActionCard must branch on the self-delegation flag before toggling selection."
        )
        assert "agent-delegation-target-label" in card_body, (
            "createActionCard must render a dedicated element for the resolved target label."
        )

        # Never rely on the frontend alone: comment/documentation must acknowledge the
        # runtime remains authoritative, matching the shared plan contract.
        assert "runtime is the" in agent_stepper_source or "runtime remains the authoritative" in agent_stepper_source, (
            "The self-delegation guard must be documented as a UX aid, not the authoritative guard."
        )

        print("Verified agent_modal_stepper.js Call agent attachment wiring.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_group_agents_override_enriches_agent_delegation_labels():
    """Verify the group agent Actions-step override still resolves Call agent target labels.

    group_agents.js replaces AgentModalStepper.loadAvailableActions with a group-scoped
    fetch against /api/group/plugins. That override must call the shared enrichment
    helper too, or every Call agent action shown for a group agent would be stuck on
    the initial "Target: resolving..." placeholder.
    """
    print("Testing group_agents.js Call agent label enrichment wiring...")

    try:
        group_agents_source = _read(GROUP_AGENTS_JS)

        override_match = re.search(
            r"stepper\.loadAvailableActions = async function loadGroupActions\(\) \{(.*?)\n  \};",
            group_agents_source,
            re.DOTALL,
        )
        assert override_match, "loadGroupActions override was not found in group_agents.js."
        assert "/api/group/plugins" in override_match.group(1), (
            "The group Actions step override must fetch the group-scoped actions endpoint."
        )
        assert "this.enrichAgentDelegationLabels(normalized)" in override_match.group(1), (
            "The group Actions step override must resolve Call agent target labels, "
            "matching AgentModalStepper.loadAvailableActions."
        )

        print("Verified group_agents.js resolves Call agent target labels.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_frontend_constants_match_backend_delegation_contract():
    """Verify the classic UI's fixed strings agree with functions_agent_delegation.py."""
    print("Testing classic UI vs backend delegation contract...")

    try:
        stepper_source = _read(PLUGIN_STEPPER_JS)
        backend_source = _read(DELEGATION_MODULE)

        backend_type_match = re.search(r'AGENT_PLUGIN_TYPE = "([^"]+)"', backend_source)
        backend_endpoint_match = re.search(r'AGENT_DEFAULT_ENDPOINT = "([^"]+)"', backend_source)
        assert backend_type_match and backend_endpoint_match, (
            "functions_agent_delegation.py must define AGENT_PLUGIN_TYPE and AGENT_DEFAULT_ENDPOINT."
        )

        assert f"const AGENT_PLUGIN_TYPE = '{backend_type_match.group(1)}';" in stepper_source, (
            "plugin_modal_stepper.js AGENT_PLUGIN_TYPE must match the backend contract."
        )
        assert f"const AGENT_DEFAULT_ENDPOINT = '{backend_endpoint_match.group(1)}';" in stepper_source, (
            "plugin_modal_stepper.js AGENT_DEFAULT_ENDPOINT must match the backend contract."
        )

        assert 'AGENT_TYPES = frozenset({"local", "aifoundry", "new_foundry", "foundry_workflow"})' in backend_source, (
            "The backend callable agent_type set changed; the classic label map must be reviewed to match."
        )
        for agent_type in ("local", "aifoundry", "new_foundry", "foundry_workflow"):
            assert f"{agent_type}:" in stepper_source, (
                f"AGENT_TYPE_LABELS must provide a classic label for backend agent_type '{agent_type}'."
            )

        print("Verified classic UI constants match the backend delegation contract.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_modal_renders_call_agent_section_without_endpoint_or_credential_controls,
        test_stepper_treats_agent_as_a_structured_internal_type,
        test_agent_modal_enriches_and_blocks_self_delegation,
        test_group_agents_override_enriches_agent_delegation_labels,
        test_frontend_constants_match_backend_delegation_contract,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
