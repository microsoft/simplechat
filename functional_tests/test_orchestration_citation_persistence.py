# test_orchestration_citation_persistence.py
"""
Functional test for orchestration citation persistence.
Version: 0.261.139
Implemented in: 0.261.087
Single orchestration contract updated in: 0.261.139

Action tool-citation channel coverage added in: 0.261.098

Gather / Reason / Render persists citations through ``HarnessExecution``. The assistant
message receives citation fields, the done frame streams the same split channels, and
``_touch_conversation`` merges cited documents into the conversation's used-document cache.
End-to-end fixture coverage lives in
``test_orchestration_harness_execution.py::test_selected_result_citations_reach_headless_message_cache_and_delivery``.
"""

import ast
import os
import sys
from copy import deepcopy

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

EXECUTION = 'functions_orchestration_execution.py'


def _read(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return handle.read()


def _function(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _isolated(module, *names):
    tree = ast.parse(_read(module))
    wanted = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    missing = set(names) - {node.name for node in wanted}
    assert not missing, f'{module} no longer defines {sorted(missing)}'
    namespace = {'deepcopy': deepcopy}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), module, 'exec'), namespace)
    return namespace


def test_citations_are_split_into_document_web_and_tool_channels():
    execution = _isolated(EXECUTION, '_partition_citations')
    documents, web, tools = execution['_partition_citations']([
        {'document_id': 'doc1', 'file_name': 'Algebra.pdf', 'citation_id': 'c1'},
        {'url': 'https://example.test/a', 'source_type': 'web'},
        {'document_id': 'doc2', 'file_name': 'Handbook.pdf'},
        {'tool_name': 'search', 'function_name': 'run'},
        'not a dict',
    ])
    assert [citation['document_id'] for citation in documents] == ['doc1', 'doc2']
    assert len(web) == 1 and web[0]['url'] == 'https://example.test/a'
    assert len(tools) == 1 and tools[0]['function_name'] == 'run'


def test_assistant_message_and_done_frame_carry_citation_channels():
    source = _read(EXECUTION)
    body = ast.dump(ast.parse(source))
    for field in ('hybrid_citations', 'web_search_citations', 'agent_citations', 'generated_artifacts'):
        assert field in body

    done = _function(_read('functions_orchestration_events.py'), 'build_run_done_event')
    assert done is not None
    done_parameters = {arg.arg for arg in done.args.args}
    assert {'web_citations', 'agent_citations'} <= done_parameters


def test_cited_documents_reach_the_conversation_cache():
    source = _read(EXECUTION)
    touch = _function(source, '_touch_conversation')
    assert touch is not None
    body = ast.dump(touch)
    assert 'merge_cited_documents_into_conversation' in body
    assert 'replace_item' in body and 'IfNotModified' in body
    assert 'invalidate_conversation_cache_for_item' in body

    finalize = _function(source, '_finalize')
    assert finalize is not None
    finalize_body = ast.dump(finalize)
    assert '_touch_conversation' in finalize_body
    assert 'documents' in finalize_body


def test_search_citations_have_what_tracking_needs():
    source = _read('functions_orchestration_adapters.py')
    builder = _function(source, '_citations_from_search_results')
    assert builder is not None
    body = ast.dump(builder)
    for field in ('document_id', 'citation_id', 'file_name', 'page_number', 'group_id', 'public_workspace_id'):
        assert f"'{field}'" in body or f'"{field}"' in body


def _run_script():
    assert_app_version_at_least('0.261.139')
    tests = [
        test_citations_are_split_into_document_web_and_tool_channels,
        test_assistant_message_and_done_frame_carry_citation_channels,
        test_cited_documents_reach_the_conversation_cache,
        test_search_citations_have_what_tracking_needs,
    ]
    passed = 0
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            passed += 1
            print('Test passed!')
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
    print(f"\nResults: {passed}/{len(tests)} tests passed")
    return passed == len(tests)


if __name__ == '__main__':
    sys.exit(0 if _run_script() else 1)
