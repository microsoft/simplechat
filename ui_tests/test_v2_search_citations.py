# test_v2_search_citations.py
"""Search-grounded V2 answers open the exact passage before and after reload.

Version: 0.261.365
Implemented in: 0.261.365

The backend payload comes from real Search/Compose adapters and retained storage.
Bundled V2 components use local synthetic API transport; no live conversation or
external qualification harness is modified.
"""

import json
from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.playwright_connection import connect_options


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
sys.path.insert(0, str(ROOT / 'functional_tests'))

# Shared backend fixtures load after the standalone application/test import paths.
from test_orchestration_dependency_runtime import binding, compose, execute, source_input  # noqa: E402
from test_orchestration_search_citations import HITS, runtime, search_content, search_step  # noqa: E402


__all__ = ['connect_options', 'runtime', 'search_content']
pytestmark = pytest.mark.ui


@pytest.mark.parametrize('output', ['evidence', 'prepared'])
@pytest.mark.parametrize('enhanced', [False, True])
def test_search_answer_citations_open_exact_passages_and_survive_reload(page, search_content, output, enhanced):
    harness_build.ensure_bundle()
    answer = (
        'Allow 10 business days for review. (Source: Policy.md, Page: 2) [#document-1_2]\n\n'
        'Rowan owns the review. (Source: Policy.md, Page: 7) [#document-1_7]'
    )
    case = search_content.make([
        search_step(), compose('answer', inputs={'passages': source_input('search', output)}),
    ], [answer], binding('answer'))
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    payload = json.loads(case.model.calls[0][0][-1]['content'])
    supplied = payload['inputs']['passages']['document_citations']
    assert [item['citation_id'] for item in supplied] == [hit['id'] for hit in HITS]
    assert all(item['citation'] in result['message'] for item in supplied[:2])
    assert [item['citation_id'] for item in result['citations']] == [hit['id'] for hit in HITS]
    message = {
        'id': 'saved-search-reply', 'role': 'assistant', 'conversation_id': 'citation-conversation',
        'content': result['message'], 'hybrid_citations': result['citations'], 'augmented': True,
    }
    requests, errors, metadata_requests = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    passages = {hit['id']: hit for hit in HITS[:2]}

    def respond(route):
        data = json.loads(route.request.post_data or '{}')
        requests.append(data)
        hit = passages[data['citation_id']]
        assert data['document_id'] == hit['document_id']
        assert data['page_number'] == str(hit['page_number'])
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'cited_text': hit['chunk_text'], 'file_name': hit['file_name'],
            'page_number': hit['page_number'],
        }))

    def metadata(route):
        metadata_requests.append(route.request.url)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'document_id': 'document-1', 'file_name': 'Policy.md', 'enhanced_citations': True,
        }))

    page.route('**/api/**', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{}',
    ))
    page.route('**/api/get_citation', respond)
    page.route('**/api/enhanced_citations/document_metadata?*', metadata)
    with harness_build.start_static_server() as origin:
        response = page.goto(f'{origin}/{harness_build.HARNESS_HTML_REL}')
        assert response is not None and response.ok
        for reload in (False, True):
            if reload:
                page.reload()
            page.wait_for_function('() => Boolean(window.OrchHarness)')
            page.evaluate('''({message, enhanced}) => {
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({data: {
                    features: {enable_enhanced_citations: enhanced}, settings: {},
                    catalogs: {models: [], agents: [], prompts: []},
                    user: {id: 'owner', display_name: 'Tester'}, scope: {},
                }});
                H.stores.chat.useChatStore.setState({
                    activeConversationId: 'citation-conversation', activeConversationKind: 'personal',
                    messages: [message], streaming: false, loadingMessages: false,
                    metadataLoading: false, metadataError: null,
                });
                H.mount('mount-a', 'MessageList');
            }''', {'message': message, 'enhanced': enhanced})
            assistant = page.locator('#message-saved-search-reply')
            for hit in passages.values():
                chip = assistant.get_by_title(f"{hit['file_name']} — Page {hit['page_number']}", exact=True)
                expect(chip).to_be_visible()
                chip.click()
                dialog = page.get_by_role('dialog', name='Citation', exact=True)
                expect(dialog.get_by_text(hit['chunk_text'], exact=True)).to_be_visible()
                other_passages = [item for item in passages.values() if item['id'] != hit['id']]
                for other in other_passages:
                    expect(dialog.get_by_text(other['chunk_text'], exact=True)).to_have_count(0)
                dialog.get_by_role('button', name='Close citation', exact=True).click()
            expect(page.get_by_role('dialog', name='Citation', exact=True)).to_have_count(0)
    assert [item['citation_id'] for item in requests] == list(passages) * 2
    assert len(metadata_requests) == (4 if enhanced else 0)
    assert len(search_content.calls) == len(case.model.calls) == 1
    assert errors == []
