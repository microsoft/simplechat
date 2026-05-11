# test_agent_template_gallery_actions_escaping.py
"""
UI test for agent template gallery actions escaping.
Version: 0.241.020
Implemented in: 0.241.020

This test ensures malicious actions_to_load values render as inert text in the
agent template gallery instead of becoming executable DOM.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')
SKIP_RESPONSE_CODES = {401, 403, 404}


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type='application/json',
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_agent_template_gallery_escapes_actions_to_load(playwright):
    """Validate gallery action labels keep attacker-controlled values inert."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()

    first_action = '<img src=x onerror="window.__agentTemplateActionXss = true">Action'
    second_action = '<svg onload="window.__agentTemplateActionSvgXss = true"></svg>Action'

    page.route(
        '**/api/user/settings*',
        lambda route: _fulfill_json(route, {'settings': {}, 'selected_agent': None}),
    )
    page.route(
        '**/api/get_conversations*',
        lambda route: _fulfill_json(route, {'conversations': []}),
    )
    page.route(
        '**/api/agent-templates',
        lambda route: _fulfill_json(
            route,
            {
                'templates': [
                    {
                        'id': 'template-1',
                        'title': 'Escaping Template',
                        'display_name': 'Escaping Template',
                        'description': 'Regression coverage for gallery action rendering.',
                        'helper_text': 'Regression coverage for gallery action rendering.',
                        'instructions': 'Do not execute action labels.',
                        'actions_to_load': [first_action, second_action],
                        'tags': [],
                    }
                ]
            },
        ),
    )

    try:
        response = page.goto(f'{BASE_URL}/chats', wait_until='domcontentloaded')
        assert response is not None, 'Expected a navigation response when loading /chats.'

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f'/chats returned HTTP {response.status} in this environment.')

        assert response.ok, f'Expected /chats to load successfully, got HTTP {response.status}.'

        page.evaluate(
            """async ({ firstAction, secondAction }) => {
                window.__agentTemplateActionXss = false;
                window.__agentTemplateActionSvgXss = false;
                window.appSettings = {
                    ...(window.appSettings || {}),
                    enable_agent_template_gallery: true,
                };

                const existing = document.getElementById('agent-template-gallery-test');
                if (existing) {
                    existing.remove();
                }

                const wrapper = document.createElement('div');
                wrapper.id = 'agent-template-gallery-test';
                wrapper.innerHTML = `
                    <div class="agent-template-gallery" data-accordion-id="galleryTestAccordion" data-show-copy="false" data-show-create="false">
                        <div class="agent-template-gallery-loading py-4 text-center"></div>
                        <div class="alert alert-warning d-none agent-template-gallery-empty" role="status"></div>
                        <div class="alert alert-info d-none agent-template-gallery-disabled" role="alert"></div>
                        <div class="alert alert-danger d-none agent-template-gallery-error" role="alert">
                            <div class="agent-template-gallery-error-text"></div>
                        </div>
                        <div class="accordion d-none" id="galleryTestAccordion"></div>
                    </div>
                `;
                document.body.appendChild(wrapper);

                await import(`/static/js/agent_templates_gallery.js?test=${Date.now()}`);
            }""",
            {'firstAction': first_action, 'secondAction': second_action},
        )

        expect(page.locator('#agent-template-gallery-test .accordion-item')).to_have_count(1)
        expect(page.locator('#agent-template-gallery-test')).to_contain_text('Recommended actions:')
        expect(page.locator('#agent-template-gallery-test')).to_contain_text(first_action)
        expect(page.locator('#agent-template-gallery-test')).to_contain_text(second_action)
        expect(page.locator("#agent-template-gallery-test img[src='x']")).to_have_count(0)
        expect(page.locator('#agent-template-gallery-test svg')).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                image: !!window.__agentTemplateActionXss,
                svg: !!window.__agentTemplateActionSvgXss,
            })"""
        )
        assert flags == {'image': False, 'svg': False}
    finally:
        context.close()
        browser.close()