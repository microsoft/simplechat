#!/usr/bin/env python3
# test_tabular_attachment_followup.py
"""
Functional test for tabular attachment follow-up.
Version: 0.241.144
Implemented in: 0.241.144

This test ensures the tabular mini-agent can use document search for
attachment-backed rows, retries when attachment references were not followed,
and strengthens the final handoff so attachment excerpts are not ignored.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / 'application' / 'single_app' / 'config.py'
CHAT_ROUTE_FILE = ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
EXPECTED_VERSION = '0.241.144'


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def read_current_version() -> str:
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError('Expected config.py to define VERSION')


def test_tabular_attachment_followup_wires_document_search() -> None:
    print('Testing tabular attachment follow-up document-search wiring...')

    current_version = read_current_version()
    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert current_version == EXPECTED_VERSION, (
        f'Expected config.py version {EXPECTED_VERSION} for the tabular attachment follow-up fix.'
    )
    assert 'from semantic_kernel_plugins.document_search_plugin import DocumentSearchPlugin' in chat_route_content, (
        'Expected run_tabular_sk_analysis to import DocumentSearchPlugin for attachment follow-up.'
    )
    assert 'kernel.add_plugin(document_search_plugin, plugin_name="document_search")' in chat_route_content, (
        'Expected the tabular mini-agent kernel to register the document_search plugin.'
    )
    assert 'def get_tabular_attachment_search_function_names():' in chat_route_content, (
        'Expected route_backend_chats.py to expose the document-search functions allowed during tabular analysis.'
    )
    assert "'search_documents'" in chat_route_content, (
        'Expected tabular attachment follow-up to allow search_documents.'
    )
    assert "'retrieve_document_chunks'" in chat_route_content, (
        'Expected tabular attachment follow-up to allow retrieve_document_chunks.'
    )
    assert "'summarize_document'" in chat_route_content, (
        'Expected tabular attachment follow-up to allow summarize_document.'
    )

    print('Document-search wiring checks passed')


def test_tabular_attachment_followup_retry_and_handoff_guidance() -> None:
    print('Testing tabular attachment follow-up retry and handoff guidance...')

    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert 'def question_requests_attachment_backed_row_follow_up(' in chat_route_content, (
        'Expected route_backend_chats.py to detect when the user wants attachment-backed row substance.'
    )
    assert 'def tabular_invocations_include_attachment_candidates(' in chat_route_content, (
        'Expected route_backend_chats.py to detect attachment references in successful tabular rows.'
    )
    assert 'did not retrieve the referenced document text' in chat_route_content, (
        'Expected tabular analysis retries to trigger when rows reference attachments but document search was skipped.'
    )
    assert 'If returned rows reference attachments, PDFs, DOCX files, letters, or other external documents' in chat_route_content, (
        'Expected the tabular analysis system prompt to instruct attachment follow-up through document search.'
    )
    assert 'Do not say the attachment was not searched or that attachment text is unavailable' in chat_route_content, (
        'Expected the outer-model handoff to forbid ignoring resolved attachment excerpts.'
    )

    print('Retry and handoff guidance checks passed')


def run_tests() -> bool:
    tests = [
        test_tabular_attachment_followup_wires_document_search,
        test_tabular_attachment_followup_retry_and_handoff_guidance,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    return success


if __name__ == '__main__':
    raise SystemExit(0 if run_tests() else 1)
