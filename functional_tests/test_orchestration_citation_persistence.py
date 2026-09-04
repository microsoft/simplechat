#!/usr/bin/env python3
"""
Functional test for orchestration citation persistence.
Version: 0.261.087
Implemented in: 0.261.087

An orchestrated answer searched documents, found the right material, and cited it in its
prose -- and the Documents drawer still said "No documents used yet".

Two things were missing, and they are separate. The assistant message was written without
its `hybrid_citations`, so the reply had no citation chips. And the conversation's
`used_documents` list was never extended, which is what the Documents drawer actually
reads: an answer can cite a document perfectly and still show nothing there, because the
drawer works from the conversation rather than from the message.

Both are checked here at the source level, because the write path needs Cosmos and the
drawer needs a browser -- and a bug that only shows up in a live deployment is exactly the
kind this suite exists to catch earlier.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

ROUTE = 'route_backend_orchestration.py'


def _read(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return handle.read()


def _function(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _isolated(module, *names):
    """Execute named top-level functions from a module without importing it.

    Importing ``route_backend_orchestration`` pulls in ``config``, which builds a live
    Cosmos client and fails without credentials. These helpers are pure, so their real
    source is compiled and run here instead of being reimplemented -- the test exercises
    the shipping code rather than a copy of it that could drift.
    """
    tree = ast.parse(_read(module))
    wanted = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    missing = set(names) - {node.name for node in wanted}
    assert not missing, f"{module} no longer defines {sorted(missing)}"

    namespace = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), module, 'exec'), namespace)
    return namespace


def test_citations_are_split_into_document_and_web():
    """Document and web citations go to different fields, because they are read differently."""
    print("Testing the citation split...")
    try:
        route = _isolated(ROUTE, '_text', '_partition_citations')

        documents, web = route['_partition_citations']([
            {'document_id': 'doc1', 'file_name': 'Algebra.pdf', 'citation_id': 'c1'},
            {'url': 'https://example.test/a', 'source_type': 'web'},
            {'document_id': 'doc2', 'file_name': 'Handbook.pdf'},
            # An agent tool call: neither a document nor a page. Kept rather than
            # dropped, but kept out of document tracking where it has no place.
            {'tool_name': 'search', 'function_name': 'run'},
            'not a dict',
        ])

        assert [c['document_id'] for c in documents] == ['doc1', 'doc2'], (
            f"document citations were not separated: {documents}"
        )
        assert len(web) == 2, f"web and tool citations should survive: {web}"
        assert all('document_id' not in c for c in web), (
            "a citation with no document must never reach document tracking, where "
            "build_used_documents would skip it silently"
        )

        print("  ok  document and web citations are separated")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_assistant_message_carries_its_citations():
    """The saved message must carry hybrid_citations, not just prose that mentions sources."""
    print("Testing that the assistant message carries citations...")
    try:
        source = _read(ROUTE)

        save = _function(source, '_save_message')
        assert save is not None, '_save_message must exist'
        parameters = {arg.arg for arg in save.args.args}
        assert 'extra' in parameters, (
            "_save_message needs a channel for the top-level citation fields; nesting them "
            "in metadata would put them where no existing reader looks"
        )

        body = ast.dump(ast.parse(source))
        for field in ('hybrid_citations', 'web_search_citations'):
            assert field in body, f"the run must persist {field} on the assistant message"

        # And the terminal frame carries them too, so a client that never reloads still
        # renders the sources.
        events = _read('functions_orchestration_events.py')
        done = _function(events, 'build_run_done_event')
        assert done is not None
        done_parameters = {arg.arg for arg in done.args.args}
        assert 'web_citations' in done_parameters, (
            'the done event must carry web citations separately from document ones'
        )

        print("  ok  citations are persisted and streamed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cited_documents_reach_the_conversation():
    """The Documents drawer reads the conversation, so the run must write to it."""
    print("Testing that cited documents are recorded on the conversation...")
    try:
        source = _read(ROUTE)

        recorder = _function(source, '_record_cited_documents')
        assert recorder is not None, (
            '_record_cited_documents must exist: citing a document on the message is not '
            'enough to make it appear in the Documents drawer'
        )

        body = ast.dump(recorder)
        assert 'merge_cited_documents_into_conversation' in body, (
            'the conversation used-document list is what the drawer reads, and '
            'merge_cited_documents_into_conversation is what extends it'
        )
        assert 'upsert_item' in body, 'the merged conversation has to be written back'
        assert 'user_id' in body, (
            'ownership must be checked before writing to a conversation'
        )

        # It is actually called when a run finishes, not merely defined.
        calls = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, 'id', None) == '_record_cited_documents'
        ]
        assert calls, '_record_cited_documents is defined but never called'

        print("  ok  cited documents are merged into the conversation")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_search_citations_have_what_tracking_needs():
    """A search citation must carry the fields used-document tracking reads."""
    print("Testing the shape of a document search citation...")
    try:
        # Checked at the source level rather than by calling the builder. The adapters
        # module reaches Cosmos through its imports, so importing it here would need
        # credentials -- and a test that only runs where Azure does is a test that stops
        # running.
        source = _read('functions_orchestration_adapters.py')
        builder = _function(source, '_citations_from_search_results')
        assert builder is not None, '_citations_from_search_results must exist'

        body = ast.dump(builder)
        # build_used_documents skips any citation with no document_id, so an answer would
        # cite its sources in prose and show nothing in the drawer.
        for field in ('document_id', 'citation_id', 'file_name', 'page_number'):
            assert f"'{field}'" in body or f'"{field}"' in body, (
                f"a search citation must carry {field}; the conversation's used-document "
                f"tracking reads it"
            )

        print("  ok  search citations carry what document tracking needs")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.261.087")

    tests = [
        test_citations_are_split_into_document_and_web,
        test_assistant_message_carries_its_citations,
        test_cited_documents_reach_the_conversation,
        test_search_citations_have_what_tracking_needs,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
