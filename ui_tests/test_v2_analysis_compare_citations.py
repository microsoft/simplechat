# test_v2_analysis_compare_citations.py
"""V2 uses its ordinary citation viewer for Analyze and Compare source references.

Version: 0.261.356
Implemented in: 0.261.356

Real bundled components render shared-pipeline citation markers, open their source
passages, and rehydrate the same saved payload after a browser reload. HTTP data is
synthetic and local; the live app and external FED harness are not used.
"""

import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'application' / 'single_app'))

from functions_document_citations import build_document_citation  # noqa: E402

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('operation', ['Analyze', 'Compare'])
def test_analysis_compare_citations_open_original_passages_and_survive_reload(page, operation):
    harness_build.ensure_bundle()
    ids = ['policy-original'] if operation == 'Analyze' else ['policy-original', 'policy-revised']
    sources = [build_document_citation(
        {'document_id': identifier, 'file_name': f'{identifier}.md', 'scope': 'personal', 'scope_id': 'owner'},
        {'chunk_id': f'{identifier}_2', 'page_number': 2, 'chunk_sequence': 2},
    ) for identifier in ids]
    message = {
        'id': 'saved-analysis-reply', 'role': 'assistant', 'conversation_id': 'citation-conversation',
        'content': f'{operation} findings. ' + ' '.join(item['citation'] for item in sources),
        'hybrid_citations': sources, 'augmented': True,
    }
    requests = []
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def respond(route):
        data = json.loads(route.request.post_data or '{}')
        requests.append(data)
        identifier = data['citation_id'].rsplit('_', 1)[0]
        assert identifier in ids
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'cited_text': f'Original retained passage from {identifier}.',
            'file_name': f'{identifier}.md', 'page_number': 2,
        }))

    page.route('**/api/**', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{}',
    ))
    page.route('**/api/get_citation', respond)
    with harness_build.start_static_server() as origin:
        response = page.goto(f'{origin}/{harness_build.HARNESS_HTML_REL}')
        assert response is not None and response.ok
        for reload in (False, True):
            if reload:
                page.reload()
            page.wait_for_function('() => Boolean(window.OrchHarness)')
            page.evaluate('''(message) => {
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({data: {
                    features: {enable_enhanced_citations: false}, settings: {},
                    catalogs: {models: [], agents: [], prompts: []},
                    user: {id: 'owner', display_name: 'Tester'}, scope: {},
                }});
                H.stores.chat.useChatStore.setState({
                    activeConversationId: 'citation-conversation', activeConversationKind: 'personal',
                    messages: [message], streaming: false, loadingMessages: false,
                    metadataLoading: false, metadataError: null,
                });
                H.mount('mount-a', 'MessageList');
            }''', message)
            for identifier in ids:
                chip = page.get_by_title(f'{identifier}.md — Page 2', exact=True)
                expect(chip).to_be_visible()
                chip.click()
                dialog = page.get_by_role('dialog', name='Citation', exact=True)
                expect(dialog.get_by_text(f'Original retained passage from {identifier}.', exact=True)).to_be_visible()
                dialog.get_by_role('button', name='Close citation', exact=True).click()
            expect(page.get_by_role('dialog', name='Citation', exact=True)).to_have_count(0)
    assert len(requests) == len(ids) * 2
    assert all(item['page_number'] == '2' for item in requests)
    assert {item['document_id'] for item in requests} == set(ids)
    assert errors == []
