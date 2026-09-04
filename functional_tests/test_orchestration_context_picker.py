#!/usr/bin/env python3
"""
Functional test for the document context picker reaching orchestration.
Version: 0.261.091
Implemented in: 0.261.091

The composer's context picker lets a user name documents, tags and whole workspaces before
asking. Orchestration read the document ids and ignored everything else: a tag chip worked
in classic chat and silently did nothing in a plan, and a picked document reached the
planner as a bare uuid because the seeded-candidate path filled its name in as ''.

Both matter for different reasons. The tag is a correctness bug -- the run searched more
widely than the user asked. The name is a reviewability bug -- the approval card exists so
someone can confirm the planner picked the right document, and `8f14e45f-ceea-467a-...`
cannot support that.

The security-relevant assertion here is the last one: names come from the browser, and a
browser must not be able to widen what it can read by claiming a document is called
something. Labels are display; authorization is by id.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT, stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

ADAPTERS = 'functions_orchestration_adapters.py'
CONTEXT = 'functions_orchestration_context.py'
SEARCH = 'functions_search.py'

# A deployment with everything on, so a validation test fails on the thing it is testing
# rather than on a gate.
_PERMISSIVE = {
    'enable_chat_orchestration': True,
    'enable_user_workspace': True,
    'enable_group_workspaces': True,
    'enable_web_search': True,
}
_CAPABILITIES = [
    'document_search',
    'document_analyze',
    'document_compare',
    'tabular_analyze',
    'web_search',
    'respond',
]


def _read(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return handle.read()


def _tree(module):
    return ast.parse(_read(module))


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_picked_tags_reach_the_plan():
    """A tag chip must narrow a plan the way it narrows a chat message."""
    print("Testing that picked tags reach the seeds...")
    try:
        assert_app_version_at_least('0.261.091')

        with stubbed_app_imports():
            from functions_orchestration_context import resolve_seeds

            seeds = resolve_seeds({
                'selected_document_ids': ['doc1'],
                'tags': ['Contracts', 'Q3'],
                'document_filter_mode': 'union',
            })

            assert seeds['tags'] == ['Contracts', 'Q3'], (
                f"tags were dropped from the seeds: {seeds.get('tags')}. The composer sends "
                f"them on both the chat and the orchestration path; ignoring them here means "
                f"the run searches more widely than the user asked."
            )
            assert seeds['document_filter_mode'] == 'union', (
                'the filter mode was dropped; a picked document beside an unrelated tag '
                'intersects to nothing without it'
            )

            # Anything unrecognised must fall back to the server default rather than being
            # passed through to the query builder.
            assert resolve_seeds({'document_filter_mode': 'nonsense'})['document_filter_mode'] == ''
            assert resolve_seeds({})['tags'] == []

        print("  ok  tags and filter mode reach the seeds")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_tag_scopes_the_probe_rather_than_replacing_it():
    """Naming a shelf is not naming a document."""
    print("Testing that a tag does not suppress the candidate probe...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_context import resolve_seeds, seeds_are_explicit

            tag_only = resolve_seeds({'tags': ['Contracts']})
            assert not seeds_are_explicit(tag_only), (
                "a tag was treated as an explicit document choice. A document answers "
                "'which documents'; a tag answers 'which shelf', and the probe is still what "
                "decides which documents on that shelf are worth naming. Treating a tag as "
                "explicit would hand the planner every document carrying it."
            )

            picked = resolve_seeds({'selected_document_ids': ['doc1']})
            assert seeds_are_explicit(picked), (
                'a picked document must still turn the probe off'
            )

        print("  ok  a tag scopes the probe; a document replaces it")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_probe_and_the_run_filter_by_the_same_tags():
    """Both search paths must pass the tags, under the name hybrid_search actually uses."""
    print("Testing that both search paths pass the tags...")
    try:
        # hybrid_search takes `tags_filter`, not `tags`. Passing `tags=` type-checks, imports
        # and passes every test that drives a fake search -- and raises TypeError the first
        # time a real step runs. That exact class of mismatch has already reached production
        # once in this feature, so the parameter name is asserted against the real signature.
        search_fn = _function(_tree(SEARCH), 'hybrid_search')
        assert search_fn is not None, 'hybrid_search not found'
        accepted = {a.arg for a in search_fn.args.args} | {
            a.arg for a in search_fn.args.kwonlyargs
        }
        assert 'tags_filter' in accepted, (
            'hybrid_search no longer takes tags_filter; the callers below need updating'
        )

        for module, function_name in (
            (CONTEXT, 'resolve_candidate_documents'),
            (ADAPTERS, 'run_document_search'),
        ):
            node = _function(_tree(module), function_name)
            assert node is not None, f'{function_name} not found in {module}'

            passed = set()
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == 'hybrid_search'
                ):
                    passed = {kw.arg for kw in call.keywords}

            assert passed, f'{function_name} does not call hybrid_search'
            missing = {'tags_filter', 'document_filter_mode'} - passed
            assert not missing, (
                f"{function_name} calls hybrid_search without {sorted(missing)}. The planner "
                f"would be offered, or the run would return, documents the user's tag "
                f"selection had already excluded."
            )
            unknown = passed - accepted
            assert not unknown, (
                f"{function_name} passes {sorted(unknown)} to hybrid_search, which does not "
                f"accept it -- this raises TypeError at run time only"
            )

        print("  ok  both paths filter by tag, under the real parameter name")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_picked_document_reaches_the_planner_by_name():
    """The approval card cannot do its job with a uuid."""
    print("Testing that picked documents carry their names...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_context import (
                resolve_candidate_documents,
                resolve_seeds,
            )

            seeds = resolve_seeds({
                'selected_document_ids': ['doc1', 'doc2'],
                'context_documents': [
                    {'id': 'doc1', 'label': 'Q3 Contract.pdf', 'scope_kind': 'personal'},
                    {'id': 'doc2', 'label': 'Q4 Contract.pdf', 'scope_kind': 'group'},
                ],
            })
            assert seeds['document_labels'] == {
                'doc1': 'Q3 Contract.pdf',
                'doc2': 'Q4 Contract.pdf',
            }, f"labels were not read off the request: {seeds.get('document_labels')}"

            candidates, probed = resolve_candidate_documents('anything', 'user-1', seeds=seeds)
            assert not probed, 'a picked document must still suppress the probe'

            names = {c['document_id']: c['file_name'] for c in candidates}
            assert names == {
                'doc1': 'Q3 Contract.pdf',
                'doc2': 'Q4 Contract.pdf',
            }, (
                f"seeded candidates reached the planner unnamed: {names}. The planner cannot "
                f"write 'compare the Q3 and Q4 contracts' if it was never told which document "
                f"is which."
            )
            assert all(c['selected_by_user'] for c in candidates), (
                'a picked document must be marked as the user\'s choice'
            )

        print("  ok  picked documents reach the planner by name")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_name_reaches_the_approval_card():
    """The whole chain, end to end: composer -> seeds -> candidates -> plan inputs."""
    print("Testing the label chain to the plan card...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_context import (
                resolve_candidate_documents,
                resolve_seeds,
            )
            from functions_orchestration_schema import build_plan_inputs

            seeds = resolve_seeds({
                'selected_document_ids': ['doc1'],
                'context_documents': [{'id': 'doc1', 'label': 'Q3 Contract.pdf'}],
            })
            candidates, _ = resolve_candidate_documents('anything', 'user-1', seeds=seeds)

            # The route derives its label map from the candidates, exactly like this.
            labels = {
                c['document_id']: (c.get('title') or c.get('file_name'))
                for c in candidates
            }

            plan = {
                'steps': [{
                    'step_id': 's1',
                    'capability_id': 'document_analyze',
                    'enabled': True,
                    'arguments': {'document_ids': ['doc1', 'doc9']},
                }],
            }
            inputs = build_plan_inputs(plan, seeds=seeds, document_labels=labels)

            by_id = {d['document_id']: d for d in inputs['documents']}
            assert by_id['doc1']['display_name'] == 'Q3 Contract.pdf', (
                f"the name did not survive to the card: {by_id['doc1']}"
            )
            assert by_id['doc1']['selected_by_user'] is True

            # A document the planner introduced has no label and no claim to being the
            # user's choice. Falling back to the id is honest; claiming a name is not.
            assert by_id['doc9']['display_name'] == 'doc9'
            assert by_id['doc9']['selected_by_user'] is False

        print("  ok  the name reaches the approval card, and only where it is real")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_supplied_label_cannot_widen_access():
    """Names come from the browser. Access must not."""
    print("Testing that labels grant nothing...")
    try:
        tree = _tree('route_backend_orchestration.py')
        node = _function(tree, '_authorized_document_ids')
        assert node is not None, '_authorized_document_ids not found'

        body = ast.dump(node)
        for label_field in ('document_labels', 'context_documents', 'label', 'file_name'):
            assert label_field not in body, (
                f"_authorized_document_ids reads {label_field}. Names are supplied by the "
                f"browser; authorization must be decided from the ids alone, or a client "
                f"could widen its own access by describing a document differently."
            )
        assert 'document_ids' in body, 'authorization must still be decided from the ids'

        print("  ok  authorization ignores anything the browser named")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_found_documents_carry_their_workspace():
    """A discovered document with no workspace cannot be offered back to the user."""
    print("Testing that search citations carry scope...")
    try:
        source = _tree(ADAPTERS)
        node = _function(source, '_citations_from_search_results')
        assert node is not None, '_citations_from_search_results not found'

        body = ast.dump(node)
        for field in ('group_id', 'public_workspace_id'):
            assert f"'{field}'" in body, (
                f"search citations drop {field}, which the index does select. The composer "
                f"groups context chips by workspace, so a document the run found has no home "
                f"without it."
            )

        print("  ok  citations carry the workspace a document came from")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_step_can_read_what_an_earlier_step_found():
    """A plan can say "search, then analyse what you found"."""
    print("Testing the cross-step document reference...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_schema import validate_plan

            plan = validate_plan({
                'intent': {'summary': 'Analyse the relevant contracts'},
                'steps': [
                    {
                        'step_id': 'find',
                        'capability_id': 'document_search',
                        'arguments': {'query': 'contracts'},
                    },
                    {
                        'step_id': 'read',
                        'capability_id': 'document_analyze',
                        'arguments': {
                            'analysis_prompt': 'Summarise the payment terms.',
                            'documents_from_step': 'find',
                        },
                    },
                    {'step_id': 'answer', 'capability_id': 'respond', 'arguments': {}},
                ],
            }, settings=_PERMISSIVE, available_capability_ids=_CAPABILITIES)

            validation = plan['validation']
            assert validation['ok'], f"a valid reference was rejected: {validation['errors']}"

            by_id = {s['step_id']: s for s in plan['steps']}
            assert 'read' in by_id, 'the analysing step was dropped'
            assert by_id['read']['arguments']['documents_from_step'] == 'find'

            # The reference must imply the dependency. Without it the topological pass is
            # free to run the analysis first, and it would resolve to nothing.
            assert 'find' in by_id['read']['depends_on'], (
                f"the reference did not create a dependency: {by_id['read']['depends_on']}. "
                f"The executor would be free to analyse before searching."
            )

            order = [s['step_id'] for s in plan['steps']]
            assert order.index('find') < order.index('read'), (
                f"the referenced step must run first: {order}"
            )

        print("  ok  a step can read what an earlier step found")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_bad_document_reference_is_caught():
    """A reference that could never resolve must not reach an adapter."""
    print("Testing bad document references...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_schema import validate_plan

            def analyse(reference, extra=None):
                arguments = {
                    'analysis_prompt': 'Summarise.',
                    'documents_from_step': reference,
                }
                arguments.update(extra or {})
                return validate_plan({
                    'intent': {'summary': 'x'},
                    'steps': [
                        {'step_id': 'search', 'capability_id': 'web_search',
                         'arguments': {'query': 'x'}},
                        {'step_id': 'read', 'capability_id': 'document_analyze',
                         'arguments': arguments},
                        {'step_id': 'answer', 'capability_id': 'respond', 'arguments': {}},
                    ],
                }, settings=_PERMISSIVE, available_capability_ids=_CAPABILITIES)

            # A web search produces notes, not documents. Reading documents from it would
            # resolve to nothing every single time.
            plan = analyse('search')
            assert 'read' not in {s['step_id'] for s in plan['steps']}, (
                'a step reading documents from a web search should not have survived'
            )

            # Unless it has documents of its own, in which case the reference is dropped and
            # the step still means something.
            plan = analyse('search', {'document_ids': ['doc1']})
            by_id = {s['step_id']: s for s in plan['steps']}
            assert 'read' in by_id, 'a step with its own documents should survive'
            assert 'documents_from_step' not in by_id['read']['arguments'], (
                'the unusable reference should have been removed'
            )
            assert by_id['read']['arguments']['document_ids'] == ['doc1']
            assert plan['validation']['repairs'], 'dropping a reference should be reported'

            # A step naming itself could never resolve.
            plan = analyse('read')
            assert 'read' not in {s['step_id'] for s in plan['steps']}

            # A step that is not in the plan at all.
            plan = analyse('nonexistent')
            assert 'read' not in {s['step_id'] for s in plan['steps']}

        print("  ok  unusable references are repaired or dropped")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_reference_cannot_dodge_the_document_ceiling():
    """The administrator's limit must apply to documents that arrive at run time."""
    print("Testing the document ceiling on a reference...")
    try:
        source = _read(ADAPTERS)
        resolver = _function(ast.parse(source), '_resolve_step_document_ids')
        assert resolver is not None, '_resolve_step_document_ids must exist'

        body = ast.dump(resolver)
        # The validator trims what a plan *names*. It cannot trim what a search has not run
        # yet, so without this the reference is a way around a configured maximum.
        assert 'get_capability_document_limit' in body, (
            "_resolve_step_document_ids does not apply the administrator's document "
            "ceiling. The validator caps the documents a plan names, but documents "
            "arriving through documents_from_step never pass through it."
        )

        # And the caller must actually tell it which capability's limit applies.
        analyze = _function(ast.parse(source), 'run_document_analyze')
        called = False
        for node in ast.walk(analyze):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == '_resolve_step_document_ids'
            ):
                passed = {kw.arg for kw in node.keywords}
                assert {'settings', 'capability_id'} <= passed, (
                    f"run_document_analyze resolves documents without {sorted({'settings', 'capability_id'} - passed)}, "
                    f"so no ceiling can be applied"
                )
                called = True
        assert called, 'run_document_analyze must resolve its documents through the helper'

        print("  ok  a run-time document still respects the configured ceiling")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_executor_records_what_each_step_found():
    """A reference resolves from per-step documents, so they must be recorded per step."""
    print("Testing per-step document recording...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_executor import RunContext

            context = RunContext(run_id='r1', plan_id='p1', conversation_id='c1', user_id='u1')
            assert hasattr(context, 'step_documents'), (
                'RunContext must record which documents each step found, or a reference '
                'has nothing to resolve against'
            )

            context.merge_step_result({
                'evidence': [
                    {'document_id': 'doc1', 'source_kind': 'narrative'},
                    {'document_id': 'doc2', 'source_kind': 'narrative'},
                ],
            }, step_id='find')

            assert context.step_documents['find'] == ['doc1', 'doc2'], (
                f"per-step documents were not recorded: {context.step_documents}"
            )
            # And the run-level list still works, since the ledger reads it.
            assert context.documents_touched == ['doc1', 'doc2']

            # A step that found nothing records an empty list rather than nothing at all,
            # so a reference to it resolves to "none" rather than to "unknown".
            context.merge_step_result({'evidence': []}, step_id='empty')
            assert context.step_documents['empty'] == []

        print("  ok  each step's documents are recorded against its id")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_picked_tags_reach_the_plan,
        test_a_tag_scopes_the_probe_rather_than_replacing_it,
        test_the_probe_and_the_run_filter_by_the_same_tags,
        test_a_picked_document_reaches_the_planner_by_name,
        test_the_name_reaches_the_approval_card,
        test_a_supplied_label_cannot_widen_access,
        test_found_documents_carry_their_workspace,
        test_a_step_can_read_what_an_earlier_step_found,
        test_a_bad_document_reference_is_caught,
        test_a_reference_cannot_dodge_the_document_ceiling,
        test_the_executor_records_what_each_step_found,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
