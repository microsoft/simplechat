# test_orchestration_reference_authorizer_golden.py
"""
Golden parity for question-card (clarification) reference authorization.
Version: 0.261.198
Implemented in: 0.261.198

The plan editor's `#` references (#1556) share an authorization core with
``resolve_elicitation_references``. The fixture beside this test was captured from that
function *before* the core was factored out of it. Every case must still produce the
same result or error, byte for byte, and make the same calls into the document,
workspace, tag and conversation boundaries.

Never regenerate the fixture to make this test pass. A difference is a behavior change
in the question card, and has to be justified or fixed rather than re-recorded.
"""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from test_support.orchestration_reference_world import (
    ALL_ENABLED,
    INTRUDER,
    OWNER,
    outcome,
    reference_world,
)
from test_support.versioning import assert_app_version_at_least


GOLDEN_PATH = Path(__file__).resolve().parent / 'fixtures' / 'orchestration_elicitation_reference_golden.json'


def ref(kind, reference_id, scope_kind='personal', scope_id=None, label='Picked label', name='Picked workspace'):
    return {
        'kind': kind, 'id': reference_id, 'label': label,
        'scope': {'kind': scope_kind, 'id': scope_id, 'name': name},
    }


def doc(document_id, scope_kind='personal', scope_id=None):
    return ref('document', document_id, scope_kind, scope_id)


def attachment(document_id, conversation_id='conv'):
    return ref('chat_attachment', document_id, 'chat', conversation_id)


CASES = [
    # Bounds and conversation ownership
    {'name': 'references_not_a_list', 'references': {'kind': 'document', 'id': 'own'}},
    {'name': 'references_none', 'references': None},
    {'name': 'references_over_limit', 'references': [doc(f'own-{index}') for index in range(101)]},
    {'name': 'references_at_limit_with_duplicates', 'references': [doc('own')] * 100},
    {'name': 'references_empty', 'references': []},
    {'name': 'conversation_foreign', 'conversation_id': 'conv-foreign', 'references': [doc('own')]},
    {'name': 'conversation_missing', 'conversation_id': 'conv-missing', 'references': [doc('own')]},
    {'name': 'intruder_reads_owner_conversation', 'user_id': INTRUDER, 'references': [doc('intruder-doc')]},

    # Reference shape
    {'name': 'reference_not_a_dict', 'references': ['own']},
    {'name': 'reference_extra_key', 'references': [dict(doc('own'), extra=True)]},
    {'name': 'reference_bad_kind', 'references': [ref('folder', 'own')]},
    {'name': 'reference_scope_not_a_dict',
     'references': [{'kind': 'document', 'id': 'own', 'label': 'x', 'scope': 'personal'}]},
    {'name': 'reference_scope_extra_key',
     'references': [{'kind': 'document', 'id': 'own', 'scope': {'kind': 'personal', 'id': None, 'owner': 'x'}}]},
    {'name': 'reference_bad_scope_kind', 'references': [ref('document', 'own', 'tenant', 't')]},
    {'name': 'reference_id_not_text', 'references': [ref('document', 42)]},
    {'name': 'reference_id_too_long', 'references': [doc('x' * 513)]},
    {'name': 'reference_id_blank', 'references': [doc('   ')]},
    {'name': 'reference_scope_id_not_text', 'references': [ref('document', 'grp-doc', 'group', 7)]},
    {'name': 'group_reference_without_scope_id', 'references': [ref('document', 'grp-doc', 'group', None)]},
    {'name': 'chat_attachment_in_personal_scope', 'references': [ref('chat_attachment', 'att-ready', 'personal')]},
    {'name': 'document_in_chat_scope', 'references': [ref('document', 'att-ready', 'chat', 'conv')]},
    {'name': 'shape_error_after_valid_reference', 'references': [doc('own'), {'kind': 'document'}]},

    # Workspace authorization
    {'name': 'chat_attachment_other_conversation', 'references': [attachment('att-ready', 'conv-2')]},
    {'name': 'settings_none', 'settings': None, 'references': [doc('own')]},
    {'name': 'personal_disabled', 'settings': dict(ALL_ENABLED, enable_user_workspace=False),
     'references': [doc('own')]},
    {'name': 'group_disabled', 'settings': dict(ALL_ENABLED, enable_group_workspaces=False),
     'references': [doc('grp-doc', 'group', 'group-a')]},
    {'name': 'public_disabled', 'settings': dict(ALL_ENABLED, enable_public_workspaces=False),
     'references': [doc('pub-doc', 'public', 'public-a')]},
    {'name': 'personal_foreign_scope_id', 'references': [doc('own', 'personal', INTRUDER)]},
    {'name': 'personal_own_scope_id', 'references': [doc('own', 'personal', OWNER)]},
    {'name': 'locked_allows_personal_and_group', 'conversation_id': 'conv-locked',
     'references': [doc('own'), doc('grp-doc', 'group', 'group-a')]},
    {'name': 'locked_rejects_public', 'conversation_id': 'conv-locked',
     'references': [doc('pub-doc', 'public', 'public-a')]},
    {'name': 'locked_rejects_other_group', 'conversation_id': 'conv-locked',
     'references': [doc('grp-b-doc', 'group', 'group-b')]},
    {'name': 'locked_context_allows_public', 'conversation_id': 'conv-locked-context',
     'references': [doc('pub-doc', 'public', 'public-a')]},
    {'name': 'locked_context_rejects_personal', 'conversation_id': 'conv-locked-context',
     'references': [doc('own')]},
    {'name': 'locked_without_contexts', 'conversation_id': 'conv-locked-empty', 'references': [doc('own')]},
    {'name': 'group_left', 'references': [doc('grp-left-doc', 'group', 'group-left')]},
    {'name': 'group_gone', 'references': [doc('grp-doc', 'group', 'group-gone')]},
    {'name': 'public_hidden', 'references': [doc('pub-hidden-doc', 'public', 'public-hidden')]},
    {'name': 'public_gone', 'references': [doc('pub-doc', 'public', 'public-gone')]},
    {'name': 'group_checked_once_per_scope', 'references': [
        doc('grp-doc', 'group', 'group-a'), doc('grp-doc-2', 'group', 'group-a'),
        ref('tag', 'grp-tag', 'group', 'group-a'),
    ]},

    # Documents
    {'name': 'documents_across_workspaces', 'references': [
        doc('own'), doc('grp-doc', 'group', 'group-a'), doc('pub-doc', 'public', 'public-a'), doc('own-2'),
    ]},
    {'name': 'duplicates_removed', 'references': [
        doc('own'), doc('own'), doc('grp-doc', 'group', 'group-a'), doc('grp-doc', 'group', 'group-a'),
    ]},
    {'name': 'same_document_in_two_groups', 'references': [
        doc('grp-doc', 'group', 'group-a'), doc('grp-doc', 'group', 'group-b'),
    ]},
    {'name': 'label_from_file_name', 'references': [doc('own-file-only')]},
    {'name': 'label_falls_back_to_id', 'references': [doc('own-unnamed')]},
    {'name': 'long_display_name_truncated', 'references': [doc('own-long-name')]},
    {'name': 'unknown_document', 'references': [doc('ghost')]},
    {'name': 'another_users_document', 'references': [doc('intruder-doc')]},
    {'name': 'group_document_as_personal', 'references': [doc('grp-doc')]},
    {'name': 'group_document_in_other_group', 'references': [doc('grp-doc', 'group', 'group-b')]},
    {'name': 'processing_document', 'references': [doc('own-processing')]},
    {'name': 'failed_document', 'references': [doc('own-failed')]},
    {'name': 'legacy_document_without_progress', 'references': [doc('own-legacy')]},
    {'name': 'unreadable_progress', 'references': [doc('own-bad-progress')]},
    {'name': 'context_count_mismatch', 'flags': {'short_contexts': True}, 'references': [doc('own'), doc('own-2')]},
    {'name': 'context_lookup_raises', 'flags': {'contexts_raise': True}, 'references': [doc('own')]},
    {'name': 'manifest_raises', 'flags': {'manifest_raise': True}, 'references': [doc('own')]},
    {'name': 'error_after_valid_document', 'references': [doc('own'), doc('ghost')]},

    # Conversation attachments
    {'name': 'chat_attachment_ready', 'references': [attachment('att-ready')]},
    {'name': 'chat_attachment_workspace_wrapper', 'references': [attachment('att-wrapper')]},
    {'name': 'chat_attachment_without_message', 'references': [attachment('att-no-row')]},
    {'name': 'chat_attachment_processing', 'references': [attachment('att-processing')]},
    {'name': 'chat_attachment_query_fails', 'flags': {'messages_raise': True}, 'references': [attachment('att-ready')]},
    {'name': 'chat_attachment_that_is_a_workspace_document', 'references': [attachment('own')]},
    {'name': 'chat_attachment_with_workspace_document', 'references': [attachment('att-ready'), doc('own')]},

    # Tags and whole workspaces
    {'name': 'tags_in_each_workspace', 'references': [
        ref('tag', 'review'), ref('tag', 'grp-tag', 'group', 'group-a'), ref('tag', 'pub-tag', 'public', 'public-a'),
    ]},
    {'name': 'tag_missing', 'references': [ref('tag', 'nope')]},
    {'name': 'tag_case_must_match', 'references': [ref('tag', 'Review')]},
    {'name': 'tag_lookup_raises', 'flags': {'tags_raise': True}, 'references': [ref('tag', 'review')]},
    {'name': 'personal_workspace_scope_ids', 'references': [
        ref('scope', '', 'personal'), ref('scope', 'personal', 'personal'), ref('scope', OWNER, 'personal'),
    ]},
    {'name': 'workspace_scope_id_mismatch', 'references': [ref('scope', 'group-b', 'group', 'group-a')]},
    {'name': 'group_and_public_workspace_scopes', 'references': [
        ref('scope', 'group-a', 'group', 'group-a'), ref('scope', 'public-a', 'public', 'public-a'),
    ]},
    {'name': 'long_workspace_name_truncated', 'references': [ref('scope', 'group-long', 'group', 'group-long')]},
    {'name': 'mixed_order_kept', 'references': [
        ref('tag', 'budget'), doc('grp-doc', 'group', 'group-a'),
        ref('scope', 'group-a', 'group', 'group-a'), doc('own'),
    ]},
]


def run_cases():
    """Run every case against one world and return name -> outcome (with its call log)."""
    outcomes = {}
    with reference_world() as world:
        for case in CASES:
            world.reset(**case.get('flags', {}))
            settings = deepcopy(case['settings']) if 'settings' in case else dict(ALL_ENABLED)
            result = outcome(lambda: world.context.resolve_elicitation_references(
                deepcopy(case['references']),
                case.get('user_id', OWNER),
                case.get('conversation_id', 'conv'),
                settings,
            ))
            result['calls'] = world.calls
            outcomes[case['name']] = result
    return outcomes


def _serialized(value):
    return json.dumps(value, ensure_ascii=False)


class ElicitationReferenceGoldenTests(unittest.TestCase):
    maxDiff = None

    def test_every_case_matches_the_captured_golden(self):
        golden = json.loads(GOLDEN_PATH.read_text(encoding='utf-8'))
        golden.pop('_meta', None)
        actual = run_cases()
        self.assertEqual(sorted(golden), sorted(actual), 'The golden case list changed.')
        for name, expected in golden.items():
            with self.subTest(case=name):
                expected_outcome = {key: expected[key] for key in ('result', 'error') if key in expected}
                actual_outcome = {key: actual[name][key] for key in ('result', 'error') if key in actual[name]}
                self.assertEqual(_serialized(expected_outcome), _serialized(actual_outcome))
                self.assertEqual(_serialized(expected['calls']), _serialized(actual[name]['calls']))

    def test_the_golden_covers_success_and_every_error_family(self):
        golden = json.loads(GOLDEN_PATH.read_text(encoding='utf-8'))
        meta = golden.pop('_meta')
        self.assertEqual('feefa33bea95697015bd8a251abb9e9c336f7ea9', meta['captured_from'])
        successes = [name for name, item in golden.items() if 'result' in item and item['result']]
        messages = {item['error']['message'] for item in golden.values() if 'error' in item}
        self.assertGreaterEqual(len(successes), 15)
        for expected in (
            'Select at most 100 context references.',
            'That conversation is no longer available.',
            'That workspace capability is currently disabled.',
            'This conversation is locked to different workspaces.',
            'That workspace is not available. Select another reference.',
            'A selected file is unavailable or no longer authorized. Select another file.',
            'A selected file is still processing or failed. Wait for it to finish, retry the upload, or remove it.',
            'The selected files could not be verified. Please retry.',
            'That tag is no longer available in the selected workspace.',
        ):
            self.assertIn(expected, messages)


if __name__ == '__main__':
    assert_app_version_at_least('0.261.198')
    unittest.main(verbosity=2)
