# test_mixed_mode_history_and_memory_supersede_fix.py
#!/usr/bin/env python3
"""
Functional test for mixed-mode conversation history ordering and superseded saved-memory handling.
Version: 0.261.379
Implemented in: 0.261.379

This test ensures that:
1. sort_messages_by_thread interleaves unthreaded orchestration turns and threaded manual
   chat turns in chronological order rather than placing all orchestration turns before
   all manual turns, while preserving retry thread chains and older legacy message ordering.
2. Saved instruction and fact memory prompts explicitly treat updated saved memories as an
   intentional profile update rather than a note inconsistency, forbidding quoting, contrasting,
   or flagging superseded earlier assistant prefixes, names, call signs, or roles.
"""

import ast
import copy
from datetime import datetime, timedelta
import os
import sys

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
FUNCTIONS_CHAT_FILE = os.path.join(APP_DIR, 'functions_chat.py')
FACT_MEMORY_CONTEXT_FILE = os.path.join(APP_DIR, 'functions_fact_memory_context.py')
ORCHESTRATION_COMPOSITION_FILE = os.path.join(APP_DIR, 'functions_orchestration_composition.py')
ORCHESTRATION_PLANNER_FILE = os.path.join(APP_DIR, 'functions_orchestration_planner.py')
ROUTE_CHATS_FILE = os.path.join(APP_DIR, 'route_backend_chats.py')
FIX_DOC_FILE = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'MIXED_MODE_HISTORY_ORDER_AND_SUPERSEDED_MEMORY_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_sort_messages_by_thread():
    source = read_file_text(FUNCTIONS_CHAT_FILE)
    parsed = ast.parse(source, filename=FUNCTIONS_CHAT_FILE)
    target_nodes = [
        copy.deepcopy(node)
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == 'sort_messages_by_thread'
    ]
    assert len(target_nodes) == 1, 'Expected sort_messages_by_thread in functions_chat.py'
    module = ast.Module(body=target_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, FUNCTIONS_CHAT_FILE, 'exec'), namespace)
    return namespace['sort_messages_by_thread']


def test_mixed_manual_and_orchestration_turns_preserve_chronological_order():
    """Verify alternating manual (threaded) and orchestration (unthreaded) turns stay chronological."""
    print('Testing mixed manual and orchestration turn ordering...')
    sort_messages_by_thread = load_sort_messages_by_thread()
    base_time = datetime(2026, 10, 22, 19, 30, 0)

    messages = []
    expected_ids = []
    for turn in range(1, 10):
        user_ts = (base_time + timedelta(seconds=turn * 20)).isoformat()
        asst_ts = (base_time + timedelta(seconds=turn * 20 + 5)).isoformat()
        if turn % 2 == 1:
            thread_id = f'manual-thread-{turn}'
            user_id = f'conv_user_{turn}'
            asst_id = f'conv_assistant_{turn}'
            messages.append({
                'id': user_id,
                'role': 'user',
                'content': f'Manual user turn {turn}',
                'timestamp': user_ts,
                'metadata': {
                    'thread_info': {
                        'thread_id': thread_id,
                        'previous_thread_id': None,
                        'active_thread': True,
                        'thread_attempt': 1,
                    },
                },
            })
            messages.append({
                'id': asst_id,
                'role': 'assistant',
                'content': f'Manual assistant turn {turn}',
                'timestamp': asst_ts,
                'metadata': {
                    'thread_info': {
                        'thread_id': thread_id,
                        'previous_thread_id': None,
                        'active_thread': True,
                        'thread_attempt': 1,
                    },
                },
            })
        else:
            user_id = f'user_orchestration_{turn}'
            asst_id = f'assistant_orchestration_{turn}'
            messages.append({
                'id': user_id,
                'role': 'user',
                'content': f'Orchestration user turn {turn}',
                'timestamp': user_ts,
                'metadata': {
                    'orchestration': {'turn_id': f'orch-turn-{turn}'},
                    'orchestration_turn_id': f'orch-turn-{turn}',
                },
            })
            messages.append({
                'id': asst_id,
                'role': 'assistant',
                'content': f'Orchestration assistant turn {turn}',
                'timestamp': asst_ts,
                'metadata': {
                    'orchestration': {'turn_id': f'orch-turn-{turn}', 'run_id': f'run-{turn}'},
                },
            })
        expected_ids.extend([user_id, asst_id])

    ordered = sort_messages_by_thread(messages)
    ordered_ids = [msg['id'] for msg in ordered]
    assert ordered_ids == expected_ids, (
        f'Expected chronological mixed-mode order {expected_ids}, got {ordered_ids}'
    )
    print('Mixed manual and orchestration turn ordering passed!')
    return True


def test_retry_thread_chain_and_legacy_messages_preserved():
    """Verify retry chains and pre-threading legacy messages still order properly."""
    print('Testing retry thread chains alongside unthreaded messages...')
    sort_messages_by_thread = load_sort_messages_by_thread()
    base_time = datetime(2026, 10, 22, 12, 0, 0)

    messages = [
        {
            'id': 'legacy-1',
            'role': 'user',
            'content': 'Legacy first',
            'timestamp': (base_time + timedelta(seconds=0)).isoformat(),
        },
        {
            'id': 't1-user-attempt-1',
            'role': 'user',
            'content': 'Turn 1 user',
            'timestamp': (base_time + timedelta(seconds=10)).isoformat(),
            'metadata': {'thread_info': {'thread_id': 'thread-1', 'previous_thread_id': None}},
        },
        {
            'id': 't1-asst-attempt-1',
            'role': 'assistant',
            'content': 'Turn 1 assistant',
            'timestamp': (base_time + timedelta(seconds=11)).isoformat(),
            'metadata': {'thread_info': {'thread_id': 'thread-1', 'previous_thread_id': None}},
        },
        {
            'id': 'orch-mid-user',
            'role': 'user',
            'content': 'Orchestration turn 2 user',
            'timestamp': (base_time + timedelta(seconds=20)).isoformat(),
            'metadata': {'orchestration': {'turn_id': 'orch-2'}},
        },
        {
            'id': 'orch-mid-asst',
            'role': 'assistant',
            'content': 'Orchestration turn 2 assistant',
            'timestamp': (base_time + timedelta(seconds=21)).isoformat(),
            'metadata': {'orchestration': {'turn_id': 'orch-2'}},
        },
        {
            'id': 't3-user',
            'role': 'user',
            'content': 'Turn 3 user',
            'timestamp': (base_time + timedelta(seconds=30)).isoformat(),
            'metadata': {'thread_info': {'thread_id': 'thread-3', 'previous_thread_id': None}},
        },
        {
            'id': 't1-user-attempt-2',
            'role': 'user',
            'content': 'Turn 1 user retry',
            'timestamp': (base_time + timedelta(seconds=50)).isoformat(),
            'metadata': {'thread_info': {'thread_id': 'thread-1', 'previous_thread_id': None}},
        },
    ]

    ordered = sort_messages_by_thread(messages)
    ordered_ids = [msg['id'] for msg in ordered]
    assert ordered_ids == [
        'legacy-1',
        't1-user-attempt-1',
        't1-asst-attempt-1',
        't1-user-attempt-2',
        'orch-mid-user',
        'orch-mid-asst',
        't3-user',
    ], f'Unexpected ordering: {ordered_ids}'
    print('Retry thread chains and unthreaded interleaving passed!')
    return True


def test_superseded_memory_guidance_across_manual_and_orchestration():
    """Verify superseded-memory non-disclosure guidance in memory, composition, planner, and chat routes."""
    print('Testing superseded-memory guidance and version alignment...')
    assert_app_version_at_least('0.261.379')

    fact_memory_source = read_file_text(FACT_MEMORY_CONTEXT_FILE)
    composition_source = read_file_text(ORCHESTRATION_COMPOSITION_FILE)
    planner_source = read_file_text(ORCHESTRATION_PLANNER_FILE)
    fix_doc_source = read_file_text(FIX_DOC_FILE)

    assert 'intentional profile update, not a note inconsistency' in fact_memory_source
    assert 'never repeat, mention, quote, contrast, or flag obsolete names, call signs, or roles' in fact_memory_source
    assert 'intentional profile update rather than a note inconsistency' in composition_source
    assert 'quote, contrast, or flag superseded earlier assistant values.' in composition_source
    assert 'never instructing compose to mention, quote, contrast, or flag superseded earlier assistant' in planner_source
    assert 'Fixed/Implemented in version: **0.261.379**' in fix_doc_source

    print('Superseded-memory guidance and version alignment passed!')
    return True


if __name__ == '__main__':
    tests = [
        test_mixed_manual_and_orchestration_turns_preserve_chronological_order,
        test_retry_thread_chain_and_legacy_messages_preserved,
        test_superseded_memory_guidance_across_manual_and_orchestration,
    ]
    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())
    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
