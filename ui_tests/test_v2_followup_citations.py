# test_v2_followup_citations.py
"""Formatting-only follow-up citations open their original passages after reload.

Version: 0.261.370
Implemented in: 0.261.370

The payload is produced by real offline planning, execution and publication.
The browser uses the bundled V2 UI and synthetic API transport, not a live chat.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.playwright_connection import connect_options


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
sys.path.insert(0, str(ROOT / 'functional_tests'))

__all__ = ['connect_options']


@pytest.fixture(scope='module')
def published_followup(tmp_path_factory):
    """Finish offline bootstrap before Playwright starts its event loop/network."""
    output = tmp_path_factory.mktemp('followup-citations') / 'payload.json'
    script = r'''
import json
from pathlib import Path
import sys
import pytest

class Capture:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        Path(sys.argv[1]).write_text(json.dumps({
            "message": item.funcargs["followup_message"], "hits": item.module.HITS,
        }), encoding="utf-8")
        yield

raise SystemExit(pytest.main([
    "-q", "-p", "no:cacheprovider", "-p", "test_support.cosmos_network_guard",
    r"functional_tests\test_orchestration_followup_citation_provenance.py"
    "::test_chained_followup_keeps_original_lineage_without_another_search",
], plugins=[Capture()]))
'''
    environment = {
        **os.environ, 'PYTHONPATH': os.pathsep.join((
            str(ROOT / 'application' / 'single_app'), str(ROOT / 'functional_tests'),
        )),
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    completed = subprocess.run(
        [sys.executable, '-c', script, str(output)], cwd=ROOT, env=environment,
        text=True, capture_output=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(output.read_text(encoding='utf-8'))


@pytest.mark.ui
@pytest.mark.parametrize('enhanced', [False, True])
def test_formatted_answer_citations_survive_publication_and_browser_reload(published_followup, page, enhanced):
    harness_build.ensure_bundle()
    followup_message, hits = published_followup['message'], published_followup['hits']
    requests, errors = [], []
    passages = {hit['id']: hit for hit in hits}
    page.on('pageerror', lambda error: errors.append(str(error)))

    def citation(route):
        data = json.loads(route.request.post_data or '{}')
        requests.append(data)
        hit = passages[data['citation_id']]
        assert data['document_id'] == hit['document_id']
        assert data['page_number'] == str(hit['page_number'])
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'cited_text': hit['chunk_text'], 'file_name': hit['file_name'], 'page_number': hit['page_number'],
        }))

    def metadata(route):
        identifier = parse_qs(urlparse(route.request.url).query)['doc_id'][0]
        hit = next(hit for hit in hits if hit['document_id'] == identifier)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'document_id': identifier, 'file_name': hit['file_name'], 'enhanced_citations': True,
        }))

    page.route('**/api/**', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{}',
    ))
    page.route('**/api/get_citation', citation)
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
                    activeConversationId: 'conversation-1', activeConversationKind: 'personal',
                    messages: [message], streaming: false, loadingMessages: false,
                    metadataLoading: false, metadataError: null,
                });
                H.mount('mount-a', 'MessageList');
            }''', {'message': followup_message, 'enhanced': enhanced})
            answer = page.locator(f"#message-{followup_message['id']}")
            expect(answer.get_by_role('cell', name='USD 125,000', exact=False)).to_be_visible()
            expect(answer.get_by_role('cell', name='USD 150,000', exact=False)).to_be_visible()
            for hit in hits:
                answer.get_by_title(f"{hit['file_name']} — Page {hit['page_number']}", exact=True).click()
                dialog = page.get_by_role('dialog', name='Citation', exact=True)
                expect(dialog.get_by_text(hit['chunk_text'], exact=True)).to_be_visible()
                for other in hits:
                    if other['id'] != hit['id']:
                        expect(dialog.get_by_text(other['chunk_text'], exact=True)).to_have_count(0)
                dialog.get_by_role('button', name='Close citation', exact=True).click()
    assert [item['citation_id'] for item in requests] == list(passages) * 2
    assert errors == []
