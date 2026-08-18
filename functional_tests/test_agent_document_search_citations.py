#!/usr/bin/env python3
# test_agent_document_search_citations.py
"""
Functional test for agent document-search citations.
Version: 0.250.219
Implemented in: 0.250.219

This test ensures that documents an agent retrieves through DocumentSearchPlugin
produce the same document citation shape as the route-level hybrid search, so they
appear as message sources, feed the sources-vs-cited-reference tracking, and can be
promoted into the conversation's used documents when the response cites them.

Related issue: microsoft/simplechat#1239
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')

if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from test_support.versioning import assert_app_version_at_least

import functions_agent_document_citations as agent_document_citations
from functions_citation_tracking import build_cited_source_subsets

IMPLEMENTED_VERSION = '0.250.219'


def read_source(*relative_parts):
    file_path = os.path.join(REPO_ROOT, *relative_parts)
    with open(file_path, 'r', encoding='utf-8') as source_file:
        return source_file.read()


def build_search_agent_citation(results):
    return {
        'plugin_name': 'DocumentSearchPlugin',
        'function_name': 'search_documents',
        'function_result': {'query': 'policy', 'scope': 'all', 'results': results},
        'success': True,
    }


def test_version_is_at_least_implementation_version():
    """The fix must be present in at least the version it shipped in."""
    print('🔍 Validating application version...')
    try:
        app_version = assert_app_version_at_least(
            IMPLEMENTED_VERSION,
            reason='Agent document-search citations were added in this version.',
        )
        print(f'✅ config.py VERSION {app_version} is at or above {IMPLEMENTED_VERSION}')
        return True
    except Exception as e:
        print(f'❌ Version check failed: {e}')
        return False


def test_search_results_become_document_citations():
    """search_documents results must map to the route-level document citation shape."""
    print('🔍 Validating search_documents citation derivation...')
    try:
        agent_citation = build_search_agent_citation([
            {
                'id': 'doc-1_3',
                'document_id': 'doc-1',
                'file_name': 'Policy.pdf',
                'page_number': 3,
                'chunk_id': 'chunk-3',
                'chunk_sequence': 3,
                'score': 2.5,
                'version': 4,
                'document_classification': 'internal',
                'group_id': 'group-9',
            },
        ])

        citations = agent_document_citations.build_document_citations_from_agent_citations(
            [agent_citation]
        )
        if len(citations) != 1:
            print(f'❌ Expected 1 derived citation, found {len(citations)}')
            return False

        citation = citations[0]
        required_fields = {
            'file_name': 'Policy.pdf',
            'document_id': 'doc-1',
            'citation_id': 'doc-1_3',
            'page_number': 3,
            'location_label': 'Page',
            'location_value': '3',
            'chunk_id': 'chunk-3',
            'chunk_sequence': 3,
            'score': 2.5,
            'version': 4,
            'classification': 'internal',
            'group_id': 'group-9',
        }
        for field_name, expected_value in required_fields.items():
            if citation.get(field_name) != expected_value:
                print(
                    f'❌ Citation field {field_name} was {citation.get(field_name)!r}, '
                    f'expected {expected_value!r}'
                )
                return False

        if citation.get('source') != agent_document_citations.AGENT_DOCUMENT_CITATION_SOURCE:
            print('❌ Derived citation is missing agent document-search provenance')
            return False

        print('✅ search_documents results produce document citations')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_chunk_and_summary_functions_produce_citations():
    """retrieve_document_chunks and summarize_document must also produce citations."""
    print('🔍 Validating chunk and summary citation derivation...')
    try:
        chunk_citations = agent_document_citations.build_document_citations_from_agent_citations([
            {
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'retrieve_document_chunks',
                'function_result': {
                    'document': {'id': 'doc-2', 'file_name': 'Guide.pdf'},
                    'chunks': [
                        {'id': 'doc-2_5', 'document_id': 'doc-2', 'page_number': 5, 'chunk_id': 'chunk-5'},
                        {'id': 'doc-2_6', 'document_id': 'doc-2', 'page_number': 6, 'chunk_id': 'chunk-6'},
                    ],
                },
                'success': True,
            },
        ])
        if len(chunk_citations) != 2:
            print(f'❌ Expected 2 chunk citations, found {len(chunk_citations)}')
            return False
        if chunk_citations[0].get('citation_id') != 'doc-2_5':
            print('❌ Chunk citation id was not taken from the indexed chunk id')
            return False

        summary_citations = agent_document_citations.build_document_citations_from_agent_citations([
            {
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'summarize_document',
                'function_result': {
                    'document': {'id': 'doc-3', 'file_name': 'Spec.docx'},
                    'citation_chunk': {
                        'id': 'doc-3_4',
                        'document_id': 'doc-3',
                        'file_name': 'Spec.docx',
                        'page_number': 4,
                        'chunk_id': 'chunk-4',
                    },
                    'summary': 'A summary.',
                },
                'success': True,
            },
        ])
        if len(summary_citations) != 1:
            print(f'❌ Expected 1 summary citation, found {len(summary_citations)}')
            return False
        if summary_citations[0].get('document_id') != 'doc-3':
            print('❌ Summary citation did not carry the summarized document id')
            return False
        if summary_citations[0].get('citation_id') != 'doc-3_4':
            print('❌ Summary citation did not use the real source chunk id')
            return False

        print('✅ Chunk retrieval and summarization produce document citations')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_zero_indexed_and_missing_locators_are_not_faked():
    """Zero sequences must survive and summaries must never invent a chunk locator."""
    print('🔍 Validating locator handling...')
    try:
        # Video chunks are keyed by second and legitimately start at zero.
        video_citations = agent_document_citations.build_document_citations_from_agent_citations([
            build_search_agent_citation([
                {
                    'id': 'video-1_0',
                    'document_id': 'video-1',
                    'file_name': 'Briefing.mp4',
                    'chunk_sequence': 0,
                },
            ]),
        ])
        if len(video_citations) != 1:
            print(f'❌ Expected 1 video citation, found {len(video_citations)}')
            return False
        if video_citations[0].get('page_number') != 0:
            print(
                '❌ A valid chunk sequence of 0 was replaced with '
                f'{video_citations[0].get("page_number")!r}'
            )
            return False
        if video_citations[0].get('citation_id') != 'video-1_0':
            print('❌ Video citation id was not preserved')
            return False
        if video_citations[0].get('location_value') != '0':
            print(
                '❌ A zero location was displayed as '
                f'{video_citations[0].get("location_value")!r} instead of "0"'
            )
            return False

        # The emitted marker must point at the same location the id encodes, otherwise
        # the rendered inline link cannot resolve.
        zero_payload = agent_document_citations.annotate_document_search_payload(
            {
                'results': [{
                    'id': 'video-1_0',
                    'document_id': 'video-1',
                    'file_name': 'Briefing.mp4',
                    'chunk_sequence': 0,
                }],
            },
            'search_documents',
        )
        zero_marker = zero_payload['results'][0].get('citation')
        if zero_marker != '(Source: Briefing.mp4, Page: 0) [#video-1_0]':
            print(f'❌ Unexpected zero-location citation marker: {zero_marker!r}')
            return False

        # Without a reported source chunk the summary must not synthesize "<id>_1".
        summary_citations = agent_document_citations.build_document_citations_from_agent_citations([
            {
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'summarize_document',
                'function_result': {
                    'document': {'id': 'doc-9', 'file_name': 'Legacy.pdf'},
                    'summary': 'A summary.',
                },
                'success': True,
            },
        ])
        if len(summary_citations) != 1:
            print(f'❌ Expected 1 summary citation, found {len(summary_citations)}')
            return False
        if summary_citations[0].get('citation_id') == 'doc-9_1':
            print('❌ Summary citation synthesized a chunk locator that may not exist')
            return False
        if summary_citations[0].get('citation_id') != 'doc-9':
            print(
                '❌ Summary fallback citation id should be the document id, found '
                f'{summary_citations[0].get("citation_id")!r}'
            )
            return False

        print('✅ Zero sequences survive and summaries do not invent locators')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_plugin_invocations_are_supported_for_cancelled_streams():
    """Raw invocations must also produce citations for cancelled or errored streams."""
    print('🔍 Validating plugin invocation derivation...')
    try:
        class StubInvocation:
            def __init__(self):
                self.plugin_name = 'DocumentSearchPlugin'
                self.function_name = 'search_documents'
                self.success = True
                self.result = {
                    'results': [{
                        'id': 'doc-7_2',
                        'document_id': 'doc-7',
                        'file_name': 'Draft.pdf',
                        'page_number': 2,
                        'chunk_id': 'chunk-2',
                    }],
                }

        invocation = StubInvocation()

        # A cancelled stream has invocations but an empty agent citation list.
        hybrid_citations = []
        added_count = agent_document_citations.apply_agent_document_citations(
            hybrid_citations,
            [],
            plugin_invocations=[invocation],
        )
        if added_count != 1 or len(hybrid_citations) != 1:
            print(f'❌ Expected 1 citation from raw invocations, found {added_count}')
            return False
        if hybrid_citations[0].get('citation_id') != 'doc-7_2':
            print('❌ Invocation-derived citation carried the wrong id')
            return False

        # Passing both sources must not double count the same chunk.
        both_sources = []
        agent_document_citations.apply_agent_document_citations(
            both_sources,
            [build_search_agent_citation([{
                'id': 'doc-7_2',
                'document_id': 'doc-7',
                'file_name': 'Draft.pdf',
                'page_number': 2,
                'chunk_id': 'chunk-2',
            }])],
            plugin_invocations=[invocation],
        )
        if len(both_sources) != 1:
            print(f'❌ Expected dedupe across both sources, found {len(both_sources)}')
            return False

        print('✅ Raw invocations are supported and deduplicated')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_non_document_and_failed_invocations_are_ignored():
    """Only successful document-search invocations may produce document citations."""
    print('🔍 Validating invocation filtering...')
    try:
        ignored_citations = agent_document_citations.build_document_citations_from_agent_citations([
            {
                'plugin_name': 'SmartHttpPlugin',
                'function_name': 'search_documents',
                'function_result': {'results': [{'id': 'x_1', 'document_id': 'x', 'file_name': 'a.pdf'}]},
                'success': True,
            },
            {
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'search_documents',
                'function_result': {'results': [{'id': 'y_1', 'document_id': 'y', 'file_name': 'b.pdf'}]},
                'success': False,
            },
            {
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'search_documents',
                'function_result': {'error': 'Access denied'},
                'success': True,
            },
        ])
        if ignored_citations:
            print(f'❌ Expected no derived citations, found {len(ignored_citations)}')
            return False

        print('✅ Unrelated, failed, and errored invocations are ignored')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_merge_deduplicates_without_truncating():
    """Merging must dedupe against route citations and never cap the source list."""
    print('🔍 Validating merge behavior...')
    try:
        existing_citations = [{
            'file_name': 'Policy.pdf',
            'document_id': 'doc-1',
            'citation_id': 'doc-1_3',
            'page_number': 3,
            'chunk_id': 'chunk-3',
        }]

        large_result_set = [
            {
                'id': f'doc-1_{index}',
                'document_id': 'doc-1',
                'file_name': 'Policy.pdf',
                'page_number': index,
                'chunk_id': f'chunk-{index}',
            }
            for index in range(1, 501)
        ]
        added_count = agent_document_citations.apply_agent_document_citations(
            existing_citations,
            [build_search_agent_citation(large_result_set)],
        )

        if added_count != 499:
            print(f'❌ Expected 499 added citations, found {added_count}')
            return False
        if len(existing_citations) != 500:
            print(f'❌ Expected 500 total source citations, found {len(existing_citations)}')
            return False

        citation_ids = [citation.get('citation_id') for citation in existing_citations]
        if len(citation_ids) != len(set(citation_ids)):
            print('❌ Merged citations contain duplicates')
            return False

        route_citation = next(
            citation for citation in existing_citations
            if citation.get('citation_id') == 'doc-1_3'
        )
        if route_citation.get('source') == agent_document_citations.AGENT_DOCUMENT_CITATION_SOURCE:
            print('❌ Existing route-level citation was overwritten by the agent-derived copy')
            return False

        print('✅ Merge dedupes, preserves route citations, and does not truncate')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_inline_markers_promote_documents_into_cited_references():
    """Payload citation markers must be matched by the citation tracker."""
    print('🔍 Validating inline citation markers...')
    try:
        payload = agent_document_citations.annotate_document_search_payload(
            {
                'results': [
                    {
                        'id': 'doc-1_3',
                        'document_id': 'doc-1',
                        'file_name': 'Policy.pdf',
                        'page_number': 3,
                        'chunk_id': 'chunk-3',
                    },
                    {
                        'id': 'doc-2_7',
                        'document_id': 'doc-2',
                        'file_name': 'Other.pdf',
                        'page_number': 7,
                        'chunk_id': 'chunk-7',
                    },
                ],
            },
            'search_documents',
        )

        marker = payload['results'][0].get('citation')
        if marker != '(Source: Policy.pdf, Page: 3) [#doc-1_3]':
            print(f'❌ Unexpected citation marker: {marker!r}')
            return False
        if not payload.get('citation_instructions'):
            print('❌ Annotated payload is missing citation instructions')
            return False

        hybrid_citations = []
        agent_document_citations.apply_agent_document_citations(
            hybrid_citations,
            [{
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'search_documents',
                'function_result': payload,
                'success': True,
            }],
        )
        if len(hybrid_citations) != 2:
            print(f'❌ Expected 2 source citations, found {len(hybrid_citations)}')
            return False

        citation_tracking = build_cited_source_subsets(
            f'Double dipping is prohibited {marker}',
            hybrid_citations=hybrid_citations,
            web_search_citations=[],
        )
        cited_citations = citation_tracking.get('cited_hybrid_citations') or []
        if len(cited_citations) != 1:
            print(f'❌ Expected 1 cited reference, found {len(cited_citations)}')
            return False
        if cited_citations[0].get('document_id') != 'doc-1':
            print('❌ The wrong document was promoted into cited references')
            return False

        print('✅ Markers promote agent-discovered documents into cited references')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_sheet_and_json_payload_handling():
    """Tabular sheets and JSON-string payloads must be handled."""
    print('🔍 Validating tabular and JSON payload handling...')
    try:
        sheet_payload = agent_document_citations.annotate_document_search_payload(
            {
                'results': [{
                    'id': 'doc-4_1',
                    'document_id': 'doc-4',
                    'file_name': 'Budget.xlsx',
                    'sheet_name': 'Q1',
                    'page_number': 1,
                }],
            },
            'search_documents',
        )
        sheet_marker = sheet_payload['results'][0].get('citation')
        if sheet_marker != '(Source: Budget.xlsx, Sheet: Q1) [#doc-4_1]':
            print(f'❌ Unexpected tabular citation marker: {sheet_marker!r}')
            return False

        json_citations = agent_document_citations.build_document_citations_from_agent_citations([
            {
                'plugin_name': 'DocumentSearchPlugin',
                'function_name': 'search_documents',
                'function_result': (
                    '{"results": [{"id": "doc-5_2", "document_id": "doc-5", '
                    '"file_name": "Notes.pdf", "page_number": 2}]}'
                ),
                'success': True,
            },
        ])
        if len(json_citations) != 1 or json_citations[0].get('citation_id') != 'doc-5_2':
            print('❌ JSON-string plugin results were not parsed into citations')
            return False

        print('✅ Tabular sheets and JSON-string payloads are handled')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_chat_and_workflow_paths_apply_the_helper():
    """Every assistant-message path must merge agent document citations."""
    print('🔍 Validating chat and workflow wiring...')
    try:
        chat_source = read_source('application', 'single_app', 'route_backend_chats.py')
        workflow_source = read_source('application', 'single_app', 'functions_workflow_runner.py')
        plugin_source = read_source(
            'application', 'single_app', 'semantic_kernel_plugins', 'document_search_plugin.py'
        )

        chat_call_count = chat_source.count('apply_agent_document_citations(')
        if chat_call_count < 5:
            print(
                '❌ Expected apply_agent_document_citations in the document action, '
                f'non-streaming, and all three streaming branches, found {chat_call_count} calls'
            )
            return False
        if 'from functions_agent_document_citations import apply_agent_document_citations' not in chat_source:
            print('❌ route_backend_chats.py does not import the shared helper')
            return False

        if 'apply_agent_document_citations(' not in workflow_source:
            print('❌ functions_workflow_runner.py does not merge agent document citations')
            return False

        annotate_count = plugin_source.count('annotate_document_search_payload(')
        if annotate_count < 3:
            print(
                '❌ Expected the document search plugin to annotate all three functions, '
                f'found {annotate_count} call sites'
            )
            return False

        # Cancelled and errored streams must supply raw invocations, because streaming
        # invocations only reach the agent citation list after a stream completes.
        invocation_call_count = chat_source.count(
            'plugin_invocations=_get_current_message_plugin_invocations('
        )
        if invocation_call_count < 4:
            print(
                '❌ Expected all four agent chat paths to pass raw plugin invocations, '
                f'found {invocation_call_count}'
            )
            return False

        print('✅ Chat, workflow, and plugin wiring are in place')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def collect_direct_call_lines(function_node, call_names):
    """Return line numbers of calls made directly in a function, skipping nested defs."""
    call_lines = {call_name: [] for call_name in call_names}
    nested_function_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nested_function_types):
                continue
            if isinstance(child, ast.Call):
                called = child.func
                called_name = getattr(called, 'id', None) or getattr(called, 'attr', None)
                if called_name in call_lines:
                    call_lines[called_name].append(child.lineno)
            visit(child)

    for statement in function_node.body:
        if isinstance(statement, nested_function_types):
            continue
        visit(statement)

    return call_lines


NESTED_FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

BLOCK_FIELDS = ('body', 'orelse', 'finalbody', 'handlers')


def collect_statement_own_calls(statement, call_names):
    """Return (line, name) for calls in a statement, excluding its nested blocks."""
    own_calls = []
    nested_block_nodes = set()

    for field_name in BLOCK_FIELDS:
        for child in getattr(statement, field_name, None) or []:
            nested_block_nodes.add(id(child))

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, NESTED_FUNCTION_TYPES) or id(child) in nested_block_nodes:
                continue
            if isinstance(child, ast.Call):
                called = child.func
                called_name = getattr(called, 'id', None) or getattr(called, 'attr', None)
                if called_name in call_names:
                    own_calls.append((child.lineno, called_name))
            visit(child)

    visit(statement)
    return sorted(own_calls)


def get_statement_blocks(statement):
    """Return the nested statement blocks a compound statement introduces."""
    blocks = []
    for field_name in BLOCK_FIELDS:
        block = getattr(statement, field_name, None)
        if not block:
            continue
        for entry in block:
            if isinstance(entry, ast.ExceptHandler):
                blocks.append(entry.body)
            else:
                blocks.append(block)
                break
    return blocks


def find_unmerged_snapshot(statements, merge_name, snapshot_names, merge_seen=False):
    """Return the first snapshot line reachable without a preceding merge on that path.

    Merges inside a branch do not leak to sibling branches or to code after the branch,
    so a merge moved into one finalization branch cannot vouch for another.
    """
    for statement in statements:
        if isinstance(statement, NESTED_FUNCTION_TYPES):
            continue

        for line, called_name in collect_statement_own_calls(
            statement,
            [merge_name] + snapshot_names,
        ):
            if called_name == merge_name:
                merge_seen = True
            elif not merge_seen:
                return line

        for block in get_statement_blocks(statement):
            unmerged_line = find_unmerged_snapshot(
                block,
                merge_name,
                snapshot_names,
                merge_seen=merge_seen,
            )
            if unmerged_line is not None:
                return unmerged_line

    return None


def test_merge_runs_before_tracking_and_persistence():
    """The merge must precede cited-subset tracking and persistence on every branch."""
    print('🔍 Validating merge ordering...')
    try:
        merge_name = 'apply_agent_document_citations'
        tracking_name = 'build_cited_source_subsets'
        persistence_names = [
            'persist_agent_citation_artifacts',
            '_persist_agent_citation_artifacts',
        ]
        snapshot_names = [tracking_name] + persistence_names

        module_targets = [
            ('route_backend_chats.py', ['application', 'single_app', 'route_backend_chats.py']),
            (
                'functions_workflow_runner.py',
                ['application', 'single_app', 'functions_workflow_runner.py'],
            ),
        ]

        for module_label, module_parts in module_targets:
            module_ast = ast.parse(read_source(*module_parts))
            verified_function_count = 0

            for node in ast.walk(module_ast):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                call_lines = collect_direct_call_lines(node, [merge_name] + snapshot_names)
                if not call_lines.get(tracking_name):
                    # Functions that only mirror an already-tracked assistant document
                    # copy its citations and must not re-merge.
                    continue

                unmerged_line = find_unmerged_snapshot(node.body, merge_name, snapshot_names)
                if unmerged_line is not None:
                    print(
                        f'❌ {module_label}:{node.lineno} function {node.name!r} snapshots '
                        f'citations at line {unmerged_line} without a merge on that branch'
                    )
                    return False

                verified_function_count += 1

            if verified_function_count == 0:
                print(f'❌ No cited-subset functions were found in {module_label}')
                return False

            print(f'   {module_label}: {verified_function_count} function(s) verified')

        print('✅ Merges run before cited-subset tracking and persistence on every branch')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_large_source_lists_collapse_in_the_ui():
    """The sources panel must collapse large source lists instead of capping data."""
    print('🔍 Validating source list rendering...')
    try:
        messages_source = read_source(
            'application', 'single_app', 'static', 'js', 'chat', 'chat-messages.js'
        )
        citations_source = read_source(
            'application', 'single_app', 'static', 'js', 'chat', 'chat-citations.js'
        )

        required_message_snippets = [
            'const DOCUMENT_CITATION_VISIBLE_LIMIT',
            'function buildDocumentCitationGroupHtml(',
            'citation-overflow-group d-none',
            'citation-overflow-toggle',
        ]
        for snippet in required_message_snippets:
            if snippet not in messages_source:
                print(f'❌ chat-messages.js is missing {snippet!r}')
                return False

        if 'button.citation-overflow-toggle' not in citations_source:
            print('❌ chat-citations.js does not handle the source overflow toggle')
            return False
        if 'function toggleCitationOverflowGroup(' not in citations_source:
            print('❌ chat-citations.js is missing the overflow toggle handler')
            return False

        print('✅ Large source lists collapse behind a show-more control')
        return True
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_version_is_at_least_implementation_version,
        test_search_results_become_document_citations,
        test_chunk_and_summary_functions_produce_citations,
        test_zero_indexed_and_missing_locators_are_not_faked,
        test_plugin_invocations_are_supported_for_cancelled_streams,
        test_non_document_and_failed_invocations_are_ignored,
        test_merge_deduplicates_without_truncating,
        test_inline_markers_promote_documents_into_cited_references,
        test_sheet_and_json_payload_handling,
        test_chat_and_workflow_paths_apply_the_helper,
        test_merge_runs_before_tracking_and_persistence,
        test_large_source_lists_collapse_in_the_ui,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
