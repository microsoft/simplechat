# test_assist_reference_canonicalization.py
"""
Functional test for the canonical form of `#` references in a plan-editor Ask AI request.
Version: 0.261.198
Implemented in: 0.261.198
Refs: microsoft/simplechat#1556

This test ensures that a request's `#` documents and tags have one canonical, bounded form,
whatever order, duplicates or extra fields the browser sent, and that the form is part of the
request's identity: the submission fingerprint covers it, so the same id with different chips
is a different request, while a reordered or repeated selection is the same one. An Ask without
references keeps exactly the request, and so the fingerprint, it had before references existed.

The cases live in ``fixtures/plan_reference_canonicalization.json``. The browser's copy of the
rules (``application/v2_ui/src/lib/planReferences.ts``) is checked against the same file, so the
two cannot drift apart without a failing test.

It also ensures the chips and search notice stored on the editor's turns are bounded display data:
sanitized, only on the turns they belong to, and never more than the thread can show.
"""

import hashlib
import importlib
import json
import sys
import unittest
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_ROOT))

from test_support.app_stubs import APP_ROOT, stubbed_config  # noqa: E402
from test_support.orchestration_revisions import AtomicMemoryContainer  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_assist_references as references_module  # noqa: E402

FIXTURE = json.loads(
    TEST_ROOT.joinpath('fixtures', 'plan_reference_canonicalization.json').read_text(encoding='utf-8')
)


def _import_with_config(module_name, **config_values):
    """Import a module that reads a few config names, without caching it for later tests."""
    with stubbed_config(**config_values):
        previously_loaded = module_name in sys.modules
        module = importlib.import_module(module_name)
        if not previously_loaded:
            sys.modules.pop(module_name, None)
    return module


plan_revisions = _import_with_config(
    'functions_orchestration_plan_revisions',
    cosmos_orchestration_runs_container=AtomicMemoryContainer('conversation_id'),
    cosmos_orchestration_run_steps_container=AtomicMemoryContainer('run_id'),
    cognitive_services_scope='https://cognitiveservices.azure.com/.default',
)


def case_input(case):
    if 'repeat' in case:
        return [dict(case['repeat']['item']) for _ in range(case['repeat']['count'])]
    return case['input']


def reference(kind, item_id, scope_kind='personal', scope_id=None, label=None, **extra):
    value = {'kind': kind, 'id': item_id, 'scope': {'kind': scope_kind, 'id': scope_id}}
    if label is not None:
        value['label'] = label
    value.update(extra)
    return value


def ask(**fields):
    return {
        'conversation_id': 'conversation-1', 'expected_version': 'version-1',
        'submission_id': 'submission-1', 'action': 'ask',
        'instruction': 'Use the budget document.', **fields,
    }


def fingerprint(data):
    """The fingerprint ``claim_plan_revision`` holds a submission id to."""
    request = plan_revisions._normalize_request(data, 'conversation-1')
    return hashlib.sha256(plan_revisions._json_text(request).encode('utf-8')).hexdigest()


class FixtureTests(unittest.TestCase):
    def test_the_fixture_limits_are_the_server_limits(self):
        self.assertEqual(FIXTURE['label_limit'], references_module.REFERENCE_LABEL_LIMIT)
        self.assertEqual(FIXTURE['request_limit'], references_module.REQUEST_REFERENCE_LIMIT)
        self.assertGreaterEqual(len(FIXTURE['labels']), 15)
        self.assertGreaterEqual(len(FIXTURE['requests']), 30)

    def test_labels_match_the_shared_cases(self):
        for case in FIXTURE['labels']:
            with self.subTest(case=case['name']):
                self.assertEqual(references_module.sanitize_reference_label(case['input']), case['expected'])

    def test_requests_match_the_shared_cases(self):
        for case in FIXTURE['requests']:
            with self.subTest(case=case['name']):
                value = case_input(case)
                if 'error' in case:
                    with self.assertRaises(references_module.ReferenceRequestError) as failure:
                        references_module.canonical_request_references(value)
                    self.assertEqual(failure.exception.code, case['error']['code'])
                    self.assertEqual(failure.exception.message, case['error']['message'])
                else:
                    self.assertEqual(references_module.canonical_request_references(value), case['expected'])

    def test_canonical_form_is_stable_when_applied_again(self):
        for case in FIXTURE['requests']:
            if 'error' in case:
                continue
            with self.subTest(case=case['name']):
                once = references_module.canonical_request_references(case_input(case))
                self.assertEqual(references_module.canonical_request_references(once), once)


class RequestIdentityTests(unittest.TestCase):
    def test_no_references_keeps_the_request_it_had_before_references_existed(self):
        plain = plan_revisions._normalize_request(ask(), 'conversation-1')
        self.assertNotIn('references', plain)
        for empty in (None, []):
            with self.subTest(references=empty):
                request = plan_revisions._normalize_request(ask(references=empty), 'conversation-1')
                self.assertNotIn('references', request)
                self.assertEqual(request, plain)
                self.assertEqual(fingerprint(ask(references=empty)), fingerprint(ask()))

    def test_the_same_selection_in_any_order_is_the_same_request(self):
        budget = reference('document', 'doc-budget', label='Budget.pdf')
        plans = reference('document', 'doc-plans', 'group', 'group-a', 'Plans.docx')
        finance = reference('tag', 'finance', 'public', 'public-a', 'finance')
        first = fingerprint(ask(references=[budget, plans, finance]))
        self.assertEqual(fingerprint(ask(references=[finance, budget, plans])), first)
        self.assertEqual(fingerprint(ask(references=[plans, budget, plans, finance, budget])), first)
        request = plan_revisions._normalize_request(
            ask(references=[finance, budget, plans]), 'conversation-1',
        )
        # Ordered by kind, then workspace kind, workspace id and id.
        self.assertEqual(
            [(item['kind'], item['id']) for item in request['references']],
            [('document', 'doc-plans'), ('document', 'doc-budget'), ('tag', 'finance')],
        )

    def test_a_different_selection_is_a_different_request(self):
        budget = reference('document', 'doc-budget', label='Budget.pdf')
        plans = reference('document', 'doc-plans', 'group', 'group-a', 'Plans.docx')
        base = fingerprint(ask(references=[budget]))
        for name, changed in (
            ('another document', [plans]),
            ('an added document', [budget, plans]),
            ('none', []),
            ('another label', [reference('document', 'doc-budget', label='Budget (final).pdf')]),
            ('another workspace', [reference('document', 'doc-budget', 'group', 'group-a', 'Budget.pdf')]),
            ('a tag with the same id', [reference('tag', 'doc-budget', label='Budget.pdf')]),
        ):
            with self.subTest(change=name):
                self.assertNotEqual(fingerprint(ask(references=changed)), base)

    def test_display_only_and_whitespace_differences_are_the_same_request(self):
        canonical = fingerprint(ask(references=[reference('document', 'doc-budget', label='Budget.pdf')]))
        for name, variant in (
            ('workspace name', reference('document', 'doc-budget', 'personal', None, 'Budget.pdf')),
            ('padded id and label', reference('document', ' doc-budget\t', label='\u00a0Budget.pdf ')),
            ('blank personal workspace id', reference('document', 'doc-budget', 'personal', '  ', 'Budget.pdf')),
        ):
            if name == 'workspace name':
                variant['scope']['name'] = 'My workspace'
            with self.subTest(variant=name):
                self.assertEqual(fingerprint(ask(references=[variant])), canonical)

    def test_invalid_references_are_refused_with_the_shared_codes(self):
        for case in FIXTURE['requests']:
            if 'error' not in case:
                continue
            with self.subTest(case=case['name']):
                with self.assertRaises(plan_revisions.PlanRevisionError) as failure:
                    plan_revisions._normalize_request(ask(references=case_input(case)), 'conversation-1')
                self.assertEqual(failure.exception.status_code, 400)
                self.assertEqual(failure.exception.code, case['error']['code'])
                self.assertEqual(failure.exception.message, case['error']['message'])

    def test_only_ask_accepts_references(self):
        for action, fields in (
            ('restore', {'source_run_id': 'run-1'}),
            ('discard', {}),
            ('answer', {
                'elicitation_id': 'question-1', 'elicitation_revision': 0,
                'elicitation_response': {'action': 'accept', 'content': {}},
            }),
        ):
            with self.subTest(action=action):
                data = {
                    'conversation_id': 'conversation-1', 'expected_version': 'version-1',
                    'submission_id': 'submission-1', 'action': action, **fields,
                    'references': [reference('document', 'doc-budget', label='Budget.pdf')],
                }
                with self.assertRaises(plan_revisions.PlanRevisionError) as failure:
                    plan_revisions._normalize_request(data, 'conversation-1')
                self.assertEqual(failure.exception.status_code, 400)
                self.assertEqual(failure.exception.code, 'invalid_request')

    def test_a_request_can_hold_every_reference_it_may_send(self):
        # The widest labels a request may carry are 200 four-byte characters each.
        largest = [
            reference('document', 'd' * 512, 'group', f'group-{index:02d}' + 'g' * 500, '\U0001f600' * 200)
            for index in range(references_module.REQUEST_REFERENCE_LIMIT)
        ]
        request = plan_revisions._normalize_request(
            ask(instruction='x' * plan_revisions.EDIT_INSTRUCTION_LIMIT, references=largest), 'conversation-1',
        )
        self.assertEqual(len(request['references']), references_module.REQUEST_REFERENCE_LIMIT)
        self.assertLess(
            len(plan_revisions._json_text(request).encode('utf-8')), plan_revisions.EDIT_REQUEST_MAX_BYTES,
        )


class StoredTurnTests(unittest.TestCase):
    def test_user_turn_chips_are_bounded_display_data(self):
        chips = [
            reference('document', 'doc-1', label='Budget.pdf'),
            reference('tag', 'finance', 'group', 'group-a'),
            reference('document', 'doc-2', 'public', 'public-a', '  \u202eReport\u202c.pdf\n'),
            reference('document', 'doc-3', 'group', 'group-a', 'L' * 300),
            reference('chat_attachment', 'file-1', 'chat', 'conversation-1', 'Upload.pdf'),
            reference('document', 'doc-4', 'chat', 'conversation-1', 'Chat doc'),
            reference('document', 'x' * 513, label='Too long'),
            reference('document', '', label='Blank'),
            {'kind': 'document', 'id': 'doc-5', 'scope': 'personal', 'label': 'Bad scope'},
            'not a reference',
            None,
        ]
        [turn] = plan_revisions._bounded_chat([
            {'role': 'user', 'content': 'Use these.', 'timestamp': 't1', 'references': chips},
        ])
        self.assertEqual(turn['references'], [
            {'kind': 'document', 'id': 'doc-1', 'label': 'Budget.pdf', 'scope': {'kind': 'personal', 'id': None}},
            {'kind': 'tag', 'id': 'finance', 'label': 'Selected tag', 'scope': {'kind': 'group', 'id': 'group-a'}},
            {'kind': 'document', 'id': 'doc-2', 'label': 'Report.pdf', 'scope': {'kind': 'public', 'id': 'public-a'}},
            {'kind': 'document', 'id': 'doc-3', 'label': 'L' * 200, 'scope': {'kind': 'group', 'id': 'group-a'}},
        ])

    def test_a_turn_keeps_at_most_one_request_of_chips(self):
        chips = [reference('document', f'doc-{index}', label=f'Doc {index}') for index in range(30)]
        [turn] = plan_revisions._bounded_chat([
            {'role': 'user', 'content': 'Use these.', 'timestamp': 't1', 'references': chips},
        ])
        self.assertEqual(len(turn['references']), references_module.REQUEST_REFERENCE_LIMIT)
        self.assertEqual(turn['references'][0]['id'], 'doc-0')

    def test_chips_belong_to_user_turns_and_notices_to_assistant_turns(self):
        chip = [reference('document', 'doc-1', label='Budget.pdf')]
        notice = {'kind': 'search_limited', 'documents': ['Budget.pdf'], 'tags': [], 'more': 0}
        turns = plan_revisions._bounded_chat([
            {'role': 'user', 'content': 'Q', 'timestamp': 't1', 'references': chip, 'scope_notice': notice},
            {'role': 'assistant', 'content': 'A', 'timestamp': 't2', 'references': chip, 'scope_notice': notice},
        ])
        self.assertIn('references', turns[0])
        self.assertNotIn('scope_notice', turns[0])
        self.assertNotIn('references', turns[1])
        self.assertEqual(turns[1]['scope_notice'], notice)

    def test_search_notices_are_sanitized_and_bounded(self):
        cases = (
            ('plain', {'kind': 'search_limited', 'documents': ['A.pdf'], 'tags': ['t'], 'more': 2},
             {'kind': 'search_limited', 'documents': ['A.pdf'], 'tags': ['t'], 'more': 2}),
            ('labels are sanitized and blanks dropped',
             {'kind': 'search_limited', 'documents': [' A\u200e.pdf ', '', 7, None], 'tags': ['\x07'], 'more': 0},
             {'kind': 'search_limited', 'documents': ['A.pdf'], 'tags': [], 'more': 0}),
            ('lists are bounded',
             {'kind': 'search_limited', 'documents': [f'D{i}' for i in range(30)], 'tags': [f'T{i}' for i in range(30)], 'more': 0},
             {'kind': 'search_limited', 'documents': [f'D{i}' for i in range(20)], 'tags': [f'T{i}' for i in range(20)], 'more': 0}),
            ('a missing list is empty', {'kind': 'search_limited', 'tags': ['t']},
             {'kind': 'search_limited', 'documents': [], 'tags': ['t'], 'more': 0}),
        )
        for name, stored, expected in cases:
            with self.subTest(case=name):
                [turn] = plan_revisions._bounded_chat([
                    {'role': 'assistant', 'content': 'Done.', 'timestamp': 't', 'scope_notice': stored},
                ])
                self.assertEqual(turn['scope_notice'], expected)
        for more in (True, -1, 1001, 1.5, '3', None):
            with self.subTest(more=more):
                [turn] = plan_revisions._bounded_chat([{
                    'role': 'assistant', 'content': 'Done.', 'timestamp': 't',
                    'scope_notice': {'kind': 'search_limited', 'documents': ['A.pdf'], 'tags': [], 'more': more},
                }])
                self.assertEqual(turn['scope_notice']['more'], 0)

    def test_empty_or_unknown_notices_and_chips_are_left_out(self):
        for name, extra in (
            ('empty notice', {'scope_notice': {'kind': 'search_limited', 'documents': [], 'tags': []}}),
            ('unknown notice kind', {'scope_notice': {'kind': 'other', 'documents': ['A.pdf']}}),
            ('notice that is not an object', {'scope_notice': 'Limited to A.pdf'}),
        ):
            with self.subTest(case=name):
                [turn] = plan_revisions._bounded_chat([
                    {'role': 'assistant', 'content': 'Done.', 'timestamp': 't', **extra},
                ])
                self.assertEqual(set(turn), {'role', 'content', 'timestamp'})
        for name, chips in (('empty', []), ('not a list', 'doc-1'), ('only malformed', [None, {'kind': 'tag'}])):
            with self.subTest(chips=name):
                [turn] = plan_revisions._bounded_chat([
                    {'role': 'user', 'content': 'Q', 'timestamp': 't', 'references': chips},
                ])
                self.assertEqual(set(turn), {'role', 'content', 'timestamp'})


if __name__ == '__main__':
    assert_app_version_at_least('0.261.198')
    unittest.main()
