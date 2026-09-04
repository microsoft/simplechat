#!/usr/bin/env python3
"""
Functional test for the chat orchestration run ledger.
Version: 0.261.059
Implemented in: 0.261.059

Every turn re-plans, so a conversation accumulates runs. Without a memory of them, turn
five re-searches exactly what turn two already found and re-asks a question the user has
already answered. The ledger is what prevents that, and it is a planner input rather than
a display artefact.

It also has to be bounded, because a long conversation would otherwise spend the planner's
entire context describing itself. This test ensures the bounds hold, that trimming
sacrifices the oldest detail first, and that the ledger reports honestly when its view is
partial -- a planner that believes it has seen everything will confidently assert that
something was never looked at.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _runs(count, summary_length=40):
    return [
        {
            'id': f'run_{index}',
            'turn_index': index,
            'status': 'completed',
            'plan_summary': {
                'intent_summary': f'Turn {index}: ' + ('x' * summary_length),
                'capabilities_used': ['document_search', 'respond'],
            },
            'documents_touched': [
                {'document_id': f'doc_{index}', 'display_name': f'Document {index}'}
            ],
            'artifacts': [{'kind': 'table', 'name': f'table_{index}.csv'}],
        }
        for index in range(count)
    ]


def test_run_count_bound():
    """Only the configured number of most recent runs is carried."""
    print("Testing orchestration ledger run bound...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_context as context

            ledger = context.build_run_ledger(
                _runs(20), settings={'chat_orchestration_ledger_max_runs': 5}
            )
            assert len(ledger['runs']) <= 5, f"Kept {len(ledger['runs'])} runs"
            assert ledger['truncated'] is True

            # The runs kept are the recent ones: a follow-up question is almost always
            # about what just happened.
            kept = [entry['turn_index'] for entry in ledger['runs']]
            assert max(kept) == 19, f"The newest run was dropped: {kept}"

            small = context.build_run_ledger(
                _runs(3), settings={'chat_orchestration_ledger_max_runs': 10}
            )
            assert len(small['runs']) == 3
            assert small['truncated'] is False, (
                "Nothing was dropped, so nothing should claim it was"
            )

            # Zero is a real configuration meaning "plan every turn from scratch".
            none = context.build_run_ledger(
                _runs(3), settings={'chat_orchestration_ledger_max_runs': 0}
            )
            assert none['runs'] == []
            assert none['truncated'] is True

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_byte_bound_compacts_oldest_first():
    """Over budget, old entries lose their detail before new ones do."""
    print("Testing orchestration ledger byte bound...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_context as context
            import json

            ledger = context.build_run_ledger(
                _runs(10, summary_length=200),
                settings={
                    'chat_orchestration_ledger_max_runs': 10,
                    'chat_orchestration_ledger_max_bytes': 1500,
                },
            )

            size = len(json.dumps(ledger, default=str).encode('utf-8'))
            assert size <= 1500, f"Ledger overran its budget at {size} bytes"
            assert ledger['truncated'] is True

            newest = ledger['runs'][-1]
            assert 'capabilities_used' in newest, (
                "A ledger that cannot afford to describe the previous turn has no value"
            )

            # Anything compacted was compacted from the front.
            compacted = [
                index for index, entry in enumerate(ledger['runs'])
                if 'capabilities_used' not in entry
            ]
            if compacted:
                assert compacted == list(range(len(compacted))), (
                    f"Compaction was not oldest-first: {compacted}"
                )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_answered_questions_carry_forward():
    """The planner can see what the user has already been asked."""
    print("Testing orchestration ledger answered questions...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_context as context

            runs = _runs(2)
            runs[0]['answered_questions'] = [
                {'elicitation_id': 'ask_1', 'question': 'Which quarter?', 'answer': 'Q3'}
            ]

            collected = context.collect_answered_questions(runs)
            assert len(collected) == 1

            ledger = context.build_run_ledger(runs, answered_questions=collected)
            assert ledger['answered_questions'][0]['question'] == 'Which quarter?', (
                "Asking the same question twice is the most obvious way for this feature "
                "to feel broken, and the ledger is what prevents it"
            )
            assert ledger['answered_questions'][0]['answer'] == 'Q3'

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_seeds_suppress_the_candidate_probe():
    """A user who picked documents has already answered the question the probe asks."""
    print("Testing orchestration candidate resolution...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_context as context

            seeds = context.resolve_seeds({
                'selected_document_ids': ['d1', 'd2'],
                'doc_scope': 'personal',
                'web_search_enabled': True,
            })
            assert context.seeds_are_explicit(seeds) is True
            assert seeds['document_ids'] == ['d1', 'd2']
            assert seeds['web_search'] is True

            candidates, probed = context.resolve_candidate_documents('anything', 'user1',
                                                                    seeds=seeds)
            assert probed is False, "No probe should run when the user already chose"
            assert [c['document_id'] for c in candidates] == ['d1', 'd2']
            assert all(c['selected_by_user'] for c in candidates)

            # Several chunks of one document say no more than the best of them does.
            aggregated = context._aggregate_candidates([
                {'document_id': 'a', 'file_name': 'A.pdf', 'score': 0.2},
                {'document_id': 'a', 'file_name': 'A.pdf', 'score': 0.9, 'title': 'Annual'},
                {'document_id': 'b', 'file_name': 'B.csv', 'score': 0.5, 'group_id': 'g1'},
            ])
            assert [c['document_id'] for c in aggregated] == ['a', 'b']
            assert aggregated[0]['score'] == 0.9
            assert aggregated[1]['scope'] == 'group'

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.261.059")

    tests = [
        test_run_count_bound,
        test_byte_bound_compacts_oldest_first,
        test_answered_questions_carry_forward,
        test_seeds_suppress_the_candidate_probe,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
