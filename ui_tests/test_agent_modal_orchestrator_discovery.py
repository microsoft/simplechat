# test_agent_modal_orchestrator_discovery.py
"""
UI test for governed orchestrator discovery settings in the agent modal.
Version: 0.250.067
Implemented in: 0.250.067

This test ensures discovery defaults off, safe descriptors are validated and
serialized, existing settings reopen correctly, and controls remain accessible.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


@pytest.mark.ui
@pytest.mark.parametrize(
    'viewport',
    [
        {'width': 1280, 'height': 900},
        {'width': 390, 'height': 844},
    ],
)
def test_agent_modal_governed_discovery_policy(viewport):
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            'Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.'
        )

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport=viewport,
            ignore_https_errors=True,
        )
        page = context.new_page()
        try:
            page.goto(f'{BASE_URL}/workspace', wait_until='domcontentloaded')
            expect(page.locator('#agentModal')).to_be_attached()
            page.wait_for_function(
                '() => window.agentModalStepper && '
                'typeof window.agentModalStepper.getAgentFormData === "function"'
            )
            page.evaluate(
                """
                () => {
                    window.agentModalStepper.showModal();
                }
                """
            )
            expect(page.locator('#agentModal.show')).to_be_visible()
            page.wait_for_timeout(200)
            page.evaluate('() => window.agentModalStepper.goToStep(6)')

            toggle = page.locator('#agent-discoverable-by-orchestrator')
            controls = page.locator('#agent-orchestrator-descriptor-controls')
            expect(toggle).to_be_visible()
            expect(toggle).not_to_be_checked()
            expect(toggle).to_have_attribute('aria-expanded', 'false')
            expect(controls).to_be_hidden()
            assert page.locator('#agent-orchestrator-capability-tags').is_disabled()

            toggle.focus()
            toggle.press('Space')
            expect(toggle).to_be_checked()
            expect(toggle).to_have_attribute('aria-expanded', 'true')
            expect(controls).to_be_visible()
            expect(page.locator('#agent-orchestrator-capability-tags')).to_be_enabled()

            page.locator('#agent-orchestrator-capability-tags').fill(
                ' Benefits, benefits, Policy Lookup! '
            )
            page.locator('#agent-orchestrator-evidence-types').fill('Policy Documents')
            page.locator('#agent-orchestrator-risk-class').select_option('internal_read')
            page.locator('#agent-orchestrator-data-sensitivity').select_option('internal')
            page.locator('#agent-orchestrator-latency-class').select_option('seconds')
            page.locator('#agent-orchestrator-cost-class').select_option('standard')
            page.locator('#agent-orchestrator-read-only').uncheck()

            assert page.evaluate(
                '() => window.agentModalStepper.validateCurrentStep()'
            ) is False
            expect(page.locator('#agent-modal-error')).to_contain_text(
                'read-only agents only'
            )

            page.locator('#agent-orchestrator-read-only').check()
            assert page.evaluate(
                '() => window.agentModalStepper.validateCurrentStep()'
            ) is True
            payload = page.evaluate(
                '() => window.agentModalStepper.getAgentFormData()'
            )
            assert payload['discoverable_by_orchestrator'] is True
            assert payload['orchestrator_descriptor'] == {
                'capability_tags': ['benefits', 'policy_lookup'],
                'evidence_types': ['policy_documents'],
                'read_only': True,
                'external_data': False,
                'risk_class': 'internal_read',
                'data_sensitivity': 'internal',
                'latency_class': 'seconds',
                'cost_class': 'standard',
            }

            layout = page.locator('#agent-orchestrator-discovery-fieldset').evaluate(
                """
                element => ({
                    overflows: element.scrollWidth > element.clientWidth,
                    right: element.getBoundingClientRect().right,
                    viewportWidth: window.innerWidth,
                })
                """
            )
            assert layout['overflows'] is False
            assert layout['right'] <= layout['viewportWidth'] + 1

            page.evaluate(
                "() => window.agentModalStepper.handleAgentTypeChange('new_foundry')"
            )
            expect(page.locator('#agent-orchestrator-discovery-fieldset')).to_be_hidden()
            foundry_payload = page.evaluate(
                '() => window.agentModalStepper.getAgentFormData()'
            )
            assert foundry_payload['discoverable_by_orchestrator'] is False
            assert foundry_payload['orchestrator_descriptor'] == {}
            page.evaluate(
                "() => window.agentModalStepper.handleAgentTypeChange('local')"
            )
            page.evaluate(
                """
                () => {
                    const actionCard = document.createElement('div');
                    actionCard.id = 'phase8b-selected-action';
                    actionCard.className = 'action-card border-primary';
                    actionCard.dataset.actionId = 'action-1';
                    actionCard.dataset.actionName = 'Action One';
                    document.getElementById('agent-step-4').appendChild(actionCard);
                }
                """
            )
            toggle.check()
            page.locator('#agent-orchestrator-capability-tags').fill('benefits')
            page.locator('#agent-orchestrator-evidence-types').fill('policy_documents')
            assert page.evaluate(
                '() => window.agentModalStepper.validateCurrentStep()'
            ) is False
            expect(page.locator('#agent-modal-error')).to_contain_text(
                'Remove attached actions'
            )
            page.locator('#phase8b-selected-action').evaluate('element => element.remove()')

            page.evaluate(
                """
                agent => {
                    window.agentModalStepper.showModal(agent);
                }
                """,
                {
                    'id': 'agent-1',
                    'name': 'benefits_research',
                    'display_name': 'Benefits Research',
                    'description': 'Benefits evidence.',
                    'instructions': 'Private canonical instructions.',
                    'actions_to_load': [],
                    'other_settings': {},
                    'max_completion_tokens': -1,
                    'agent_type': 'local',
                    'discoverable_by_orchestrator': True,
                    'orchestrator_descriptor': {
                        'capability_tags': ['benefits'],
                        'evidence_types': ['policy_documents'],
                        'read_only': True,
                        'external_data': True,
                        'risk_class': 'external_read',
                        'data_sensitivity': 'public',
                        'latency_class': 'minutes',
                        'cost_class': 'low',
                    },
                },
            )
            page.wait_for_timeout(200)
            page.evaluate('() => window.agentModalStepper.goToStep(6)')
            expect(toggle).to_be_checked()
            expect(controls).to_be_visible()
            expect(page.locator('#agent-orchestrator-capability-tags')).to_have_value('benefits')
            expect(page.locator('#agent-orchestrator-evidence-types')).to_have_value(
                'policy_documents'
            )
            expect(page.locator('#agent-orchestrator-external-data')).to_be_checked()
            expect(page.locator('#agent-orchestrator-risk-class')).to_have_value(
                'external_read'
            )
            expect(page.locator('#agent-orchestrator-data-sensitivity')).to_have_value(
                'public'
            )
            expect(page.locator('#agent-orchestrator-latency-class')).to_have_value(
                'minutes'
            )
            expect(page.locator('#agent-orchestrator-cost-class')).to_have_value('low')
        finally:
            context.close()
            browser.close()