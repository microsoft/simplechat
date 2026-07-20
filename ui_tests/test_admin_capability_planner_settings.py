# test_admin_capability_planner_settings.py
"""Azure Playwright UI tests for governed capability planner settings.

Version: 0.250.077
Implemented in: 0.250.072; dependent model selectors added in 0.250.077

This test verifies that administrators can select off, shadow, or assist mode
and choose a valid global endpoint/model pair without layout overflow.
"""

import os

import pytest


def test_capability_planner_control_source_contract():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_path = os.path.join(
        repo_root,
        'application',
        'single_app',
        'templates',
        'admin_settings.html',
    )
    script_path = os.path.join(
        repo_root,
        'application',
        'single_app',
        'static',
        'js',
        'admin',
        'admin_settings.js',
    )
    endpoint_script_path = os.path.join(
        repo_root,
        'application',
        'single_app',
        'static',
        'js',
        'admin',
        'admin_model_endpoints.js',
    )
    with open(template_path, encoding='utf-8') as template_file:
        template_source = template_file.read()
    with open(script_path, encoding='utf-8') as script_file:
        script_source = script_file.read()
    with open(endpoint_script_path, encoding='utf-8') as endpoint_script_file:
        endpoint_script_source = endpoint_script_file.read()

    planner_section = template_source.split(
        'id="chat-capability-planner-section"',
        1,
    )[1].split('<!-- Embeddings Configuration Section -->', 1)[0]
    assert 'Use Assist for normal operation.' in planner_section
    assert 'Shadow is evaluation-only' in planner_section
    assert planner_section.count('data-bs-toggle="tooltip"') >= 11
    assert 'id="chat_capability_planner_timeout_ms"' in planner_section
    assert 'min="1000" max="20000"' in planner_section
    assert 'id="chat_capability_planner_max_completion_tokens"' in planner_section
    assert 'min="64" max="1200"' in planner_section
    assert 'id="chat_capability_planner_max_candidate_plans"' in planner_section
    assert 'range(1, 7)' in planner_section
    assert 'id="chat_capability_planner_max_capabilities_per_plan"' in planner_section
    assert 'min="1" max="8"' in planner_section
    assert '<select class="form-select" id="chat_capability_planner_model_endpoint_id"' in planner_section
    assert '<select class="form-select" id="chat_capability_planner_model_id"' in planner_section
    assert '<input type="text" class="form-control" id="chat_capability_planner_model_endpoint_id"' not in planner_section
    assert '<input type="text" class="form-control" id="chat_capability_planner_model_id"' not in planner_section
    assert 'setupCapabilityPlannerControls();' in script_source
    assert 'modeTitle.textContent = description.title;' in script_source
    assert 'modeText.textContent = description.text;' in script_source
    assert 'valueOutput.textContent' in script_source
    assert 'endpointSelect.replaceChildren(' in script_source
    assert 'modelSelect.replaceChildren(' in script_source
    assert 'endpoint.models' in script_source
    assert "document.addEventListener('model-endpoints-changed'" in script_source
    assert 'endpointSelect?.value ?? savedEndpointId' in script_source
    assert 'modelSelect?.value ?? savedModelId' in script_source
    assert 'setGlobalEndpoints(window.modelEndpoints, savedEndpointId, savedModelId);' in (
        script_source
    )
    assert 'const plannerEndpoints = (modelEndpoints || []).map(endpoint => ({' in (
        endpoint_script_source
    )
    assert 'detail: { endpoints: plannerEndpoints }' in endpoint_script_source
    assert 'detail: { endpoints: modelEndpoints }' not in endpoint_script_source


def _admin_settings_url():
    url = os.getenv('SIMPLECHAT_PLAYWRIGHT_ADMIN_SETTINGS_URL', '').strip()
    if not url:
        pytest.skip(
            'Set SIMPLECHAT_PLAYWRIGHT_ADMIN_SETTINGS_URL to run planner settings UI tests.'
        )
    return url


@pytest.mark.ui
@pytest.mark.parametrize(
    'viewport',
    [
        {'width': 1280, 'height': 900},
        {'width': 390, 'height': 844},
    ],
)
def test_capability_planner_settings_are_accessible_and_responsive(viewport):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
        storage_state = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
        if storage_state:
            context_kwargs['storage_state'] = storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(f"{_admin_settings_url().split('#', 1)[0]}#ai-models")

        panel = page.get_by_test_id('chat-capability-planner-settings')
        expect(panel).to_be_visible()
        expect(panel.get_by_role('radio', name='Off')).to_be_visible()
        expect(panel.get_by_role('radio', name='Shadow')).to_be_visible()
        expect(panel.get_by_role('radio', name='Assist')).to_be_visible()
        panel.get_by_role('radio', name='Assist').check()
        expect(panel.get_by_role('radio', name='Assist')).to_be_checked()
        expect(page.locator('#chat-capability-planner-mode-title')).to_have_text('Assist')
        expect(page.locator('#chat-capability-planner-mode-text')).to_contain_text(
            'shown for approval'
        )

        panel.get_by_role('radio', name='Shadow').check()
        expect(page.locator('#chat-capability-planner-mode-title')).to_have_text('Shadow')
        expect(page.locator('#chat-capability-planner-mode-text')).to_contain_text(
            'never shows its proposals'
        )
        panel.get_by_role('radio', name='Assist').check()

        page.evaluate(
            """
            () => document.dispatchEvent(new CustomEvent('model-endpoints-changed', {
                detail: {
                    endpoints: [
                        {
                            id: 'planner-endpoint',
                            name: 'Planner <Endpoint>',
                            provider: 'aoai',
                            enabled: true,
                            models: [
                                {
                                    id: 'planner-model',
                                    displayName: 'Planner <Model>',
                                    modelName: 'gpt-test',
                                    enabled: true,
                                },
                                {
                                    id: 'disabled-model',
                                    displayName: 'Disabled model',
                                    enabled: false,
                                },
                            ],
                        },
                        {
                            id: 'disabled-endpoint',
                            name: 'Disabled endpoint',
                            enabled: false,
                            models: [],
                        },
                    ],
                },
            }))
            """
        )
        model_source = panel.get_by_label('Planner model source')
        endpoint_select = panel.get_by_label('Global endpoint')
        model_select = panel.get_by_label('Global model')
        model_source.select_option('configured')
        expect(endpoint_select).to_be_enabled()
        expect(endpoint_select.locator('option')).to_have_count(2)
        endpoint_select.select_option('planner-endpoint')
        expect(model_select).to_be_enabled()
        expect(model_select.locator('option')).to_have_count(2)
        expect(model_select.locator('option').nth(1)).to_have_text(
            'Planner <Model> (gpt-test)'
        )
        expect(panel.locator('img')).to_have_count(0)
        model_select.select_option('planner-model')

        page.evaluate(
            """
            () => document.dispatchEvent(new CustomEvent('model-endpoints-changed', {
                detail: {
                    endpoints: [
                        {
                            id: 'planner-endpoint',
                            name: 'Renamed planner endpoint',
                            provider: 'aoai',
                            enabled: true,
                            models: [
                                {
                                    id: 'planner-model',
                                    displayName: 'Renamed planner model',
                                    modelName: 'gpt-test',
                                    enabled: true,
                                },
                            ],
                        },
                    ],
                },
            }))
            """
        )
        expect(endpoint_select).to_have_value('planner-endpoint')
        expect(model_select).to_have_value('planner-model')

        endpoint_select.select_option('')
        page.evaluate(
            """
            () => document.dispatchEvent(new CustomEvent('model-endpoints-changed', {
                detail: {
                    endpoints: [
                        {
                            id: 'planner-endpoint',
                            name: 'Renamed planner endpoint',
                            provider: 'aoai',
                            enabled: true,
                            models: [
                                {
                                    id: 'planner-model',
                                    displayName: 'Renamed planner model',
                                    modelName: 'gpt-test',
                                    enabled: true,
                                },
                            ],
                        },
                    ],
                },
            }))
            """
        )
        expect(endpoint_select).to_have_value('')
        expect(model_select).to_have_value('')

        timeout = panel.get_by_label('Planner timeout')
        timeout.fill('15000')
        expect(timeout).to_have_value('15000')
        expect(page.locator('#chat-capability-planner-timeout-value')).to_contain_text(
            '15s'
        )

        completion_budget = panel.get_by_label('Completion budget')
        completion_budget.fill('800')
        expect(completion_budget).to_have_value('800')
        expect(page.locator('#chat-capability-planner-token-value')).to_have_text(
            '800 tokens'
        )

        panel.get_by_label('Candidate plans').select_option('4')
        expect(panel.get_by_label('Candidate plans')).to_have_value('4')

        capabilities = panel.get_by_label('Capabilities per plan')
        capabilities.fill('6')
        expect(capabilities).to_have_value('6')
        expect(page.locator('#chat-capability-planner-capabilities-value')).to_have_text(
            '6 capabilities'
        )
        layout = panel.evaluate(
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

        context.close()
        browser.close()