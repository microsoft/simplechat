# test_orchestration_scope_reference_authorizer.py
"""
Functional test for the scope-only `#` reference authorizer.
Version: 0.261.201
Implemented in: 0.261.201

``resolve_scope_references`` authorizes the plan editor's Ask AI references (#1556), and
later the workflow assistant's, with no conversation. This test pins what it accepts --
personal, group and public documents and tags the acting user can read now -- and every
way it refuses one: chat attachments and whole workspaces, another user's document, a
workspace the user left or cannot see, a disabled workspace type, a deleted, unready or
unknown document, a missing tag, an allowlist, an over-limit list, and a failed check.
Every refusal names the reference by the label the user picked, never by a title read
from the server, and nothing a user typed reaches a log.
"""

import unittest
from unittest import mock

from test_support.orchestration_reference_world import (
    ALL_ENABLED,
    INTRUDER,
    OWNER,
    reference_world,
)
from test_support.versioning import assert_app_version_at_least


def ref(kind, reference_id, scope_kind='personal', scope_id=None, label='Picked label'):
    reference = {'kind': kind, 'id': reference_id, 'scope': {'kind': scope_kind, 'id': scope_id}}
    if label is not None:
        reference['label'] = label
    return reference


def doc(document_id, scope_kind='personal', scope_id=None, label='Picked label'):
    return ref('document', document_id, scope_kind, scope_id, label)


def tag(name, scope_kind='personal', scope_id=None, label=None):
    return ref('tag', name, scope_kind, scope_id, name if label is None else label)


class ScopeReferenceAuthorizerTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls._world_context = reference_world()
        cls.world = cls._world_context.__enter__()
        cls.context = cls.world.context

    @classmethod
    def tearDownClass(cls):
        cls._world_context.__exit__(None, None, None)

    def setUp(self):
        self.world.reset()

    def resolve(self, references, settings=ALL_ENABLED, **options):
        return self.context.resolve_scope_references(
            references, options.pop('user_id', OWNER), settings, **options,
        )

    def refused(self, references, settings=ALL_ENABLED, **options):
        with self.assertRaises(self.context.ScopeReferenceError) as caught:
            self.resolve(references, settings, **options)
        return caught.exception

    def call_names(self):
        return [call['fn'] for call in self.world.calls]

    # ---- accepted ------------------------------------------------------------------

    def test_accepts_documents_and_tags_in_every_workspace(self):
        result = self.resolve([
            doc('own'), doc('grp-doc', 'group', 'group-a'), doc('pub-doc', 'public', 'public-a'),
            tag('review'), tag('grp-tag', 'group', 'group-a'), tag('pub-tag', 'public', 'public-a'),
        ])

        self.assertEqual([
            {'kind': 'document', 'id': 'own', 'label': 'Own report',
             'scope': {'kind': 'personal', 'id': None, 'name': 'My workspace'}},
            {'kind': 'document', 'id': 'grp-doc', 'label': 'Group budget',
             'scope': {'kind': 'group', 'id': 'group-a', 'name': 'Finance team'}},
            {'kind': 'document', 'id': 'pub-doc', 'label': 'Public handbook',
             'scope': {'kind': 'public', 'id': 'public-a', 'name': 'Company handbook'}},
            {'kind': 'tag', 'id': 'review', 'label': 'review',
             'scope': {'kind': 'personal', 'id': None, 'name': 'My workspace'}},
            {'kind': 'tag', 'id': 'grp-tag', 'label': 'grp-tag',
             'scope': {'kind': 'group', 'id': 'group-a', 'name': 'Finance team'}},
            {'kind': 'tag', 'id': 'pub-tag', 'label': 'pub-tag',
             'scope': {'kind': 'public', 'id': 'public-a', 'name': 'Company handbook'}},
        ], result)

    def test_labels_come_from_the_server_not_the_request(self):
        result = self.resolve([doc('own', label='Something the browser claimed')])

        self.assertEqual('Own report', result[0]['label'])

    def test_duplicates_are_removed_and_order_is_kept(self):
        result = self.resolve([doc('own'), doc('own'), doc('grp-doc', 'group', 'group-a')])

        self.assertEqual(['own', 'grp-doc'], [item['id'] for item in result])

    def test_the_result_feeds_merge_elicitation_context(self):
        result = self.resolve([
            doc('own'), doc('grp-doc', 'group', 'group-a'), tag('pub-tag', 'public', 'public-a'),
        ])

        seeds = self.context.merge_elicitation_context({}, {'instruction': {'references': result}})

        self.assertEqual(['own', 'grp-doc'], seeds['document_ids'])
        self.assertEqual({'own': 'Own report', 'grp-doc': 'Group budget'}, seeds['document_labels'])
        self.assertEqual(['pub-tag'], seeds['tags'])
        self.assertEqual(['group-a'], seeds['active_group_ids'])
        self.assertEqual(['public-a'], seeds['active_public_workspace_ids'])
        self.assertEqual('all', seeds['doc_scope'])
        self.assertEqual('union', seeds['document_filter_mode'])
        self.assertEqual(result, seeds['elicitation_references'])

    def test_the_result_is_accepted_again_by_the_question_card_check(self):
        result = self.resolve([doc('own'), doc('grp-doc', 'group', 'group-a'), tag('review')])
        self.world.reset()

        again = self.context.resolve_elicitation_references(result, OWNER, 'conv', dict(ALL_ENABLED))

        self.assertEqual(result, again)

    def test_it_never_reads_a_conversation_or_its_messages(self):
        self.resolve([doc('own'), doc('grp-doc', 'group', 'group-a'), tag('review')])

        names = self.call_names()
        self.assertTrue(names)
        self.assertFalse([name for name in names if name.startswith(('conversations.', 'messages.'))])
        contexts = [call for call in self.world.calls if call['fn'] == 'resolve_document_contexts']
        self.assertTrue(all(call['arguments']['conversation_id'] is None for call in contexts))

    def test_an_empty_list_reads_nothing(self):
        self.assertEqual([], self.resolve([]))
        self.assertEqual([], self.world.calls)

    # ---- refused kinds ---------------------------------------------------------------

    def test_chat_attachments_and_whole_workspaces_are_refused_before_any_read(self):
        for reference in (
            ref('chat_attachment', 'att-ready', 'chat', 'conv'),
            ref('chat_attachment', 'att-ready', 'personal'),
            doc('att-ready', 'chat', 'conv'),
            ref('scope', 'group-a', 'group', 'group-a'),
            ref('scope', '', 'personal'),
        ):
            with self.subTest(reference=reference):
                self.world.reset()
                error = self.refused([reference])
                self.assertEqual('unsupported_kind', error.reason)
                self.assertEqual(0, error.reference_index)
                self.assertIn('cannot be used here', error.message)
                self.assertEqual([], self.world.calls)

    def test_malformed_references_are_invalid(self):
        for references in (
            None, {'kind': 'document', 'id': 'own'}, ['own'], [{'kind': 'document'}],
            [dict(doc('own'), extra=True)], [ref('folder', 'own')],
            [{'kind': 'document', 'id': 'own', 'scope': 'personal'}],
            [ref('document', 'own', 'tenant', 't')], [doc('grp-doc', 'group', None)],
            [ref('document', 42)], [doc('   ')], [doc('x' * 513)],
        ):
            with self.subTest(references=references):
                self.world.reset()
                error = self.refused(references)
                self.assertEqual('invalid_reference', error.reason)
                self.assertEqual([], [
                    name for name in self.call_names()
                    if name in ('resolve_document_contexts', 'resolve_authorized_source_manifest')
                ])

    # ---- refused access ----------------------------------------------------------------

    def test_another_users_document_is_unavailable_and_never_described(self):
        error = self.refused([doc('intruder-doc', label='Quarterly numbers')])

        self.assertEqual('document_unavailable', error.reason)
        self.assertEqual(
            '\u201cQuarterly numbers\u201d is no longer available to you. Remove it and pick another document.',
            error.message,
        )
        for secret in ('Secret merger plan', 'merger.pdf', 'intruder'):
            self.assertNotIn(secret, error.message)

    def test_an_unlabeled_refusal_is_described_generically(self):
        document = self.refused([doc('intruder-doc', label=None)])
        blank = self.refused([doc('intruder-doc', label=' \u00a0\x00 ')])
        missing_tag = self.refused([tag('nope', label='')])

        self.assertTrue(document.message.startswith('A selected document is no longer available'))
        self.assertTrue(blank.message.startswith('A selected document is no longer available'))
        self.assertTrue(missing_tag.message.startswith('A selected tag no longer exists'))

    def test_the_intruder_cannot_read_the_owners_documents(self):
        error = self.refused([doc('own', label='Own report')], user_id=INTRUDER)

        self.assertEqual('document_unavailable', error.reason)

    def test_a_foreign_personal_workspace_is_unavailable(self):
        error = self.refused([doc('own', 'personal', INTRUDER)])

        self.assertEqual('workspace_unavailable', error.reason)
        self.assertNotIn('resolve_document_contexts', self.call_names())

    def test_the_users_own_personal_workspace_id_is_accepted(self):
        result = self.resolve([doc('own', 'personal', OWNER)])

        self.assertEqual({'kind': 'personal', 'id': None, 'name': 'My workspace'}, result[0]['scope'])

    def test_a_group_the_user_left_or_that_is_gone_is_unavailable(self):
        for reference in (doc('grp-left-doc', 'group', 'group-left'), doc('grp-doc', 'group', 'group-gone')):
            with self.subTest(reference=reference):
                self.world.reset()
                error = self.refused([reference])
                self.assertEqual('workspace_unavailable', error.reason)
                self.assertIn('\u201cPicked label\u201d is in a workspace you can no longer use', error.message)
                self.assertNotIn('resolve_document_contexts', self.call_names())

    def test_a_group_document_picked_from_another_workspace_is_unavailable(self):
        for reference in (doc('grp-doc'), doc('grp-doc', 'group', 'group-b')):
            with self.subTest(reference=reference):
                self.world.reset()
                self.assertEqual('document_unavailable', self.refused([reference]).reason)

    def test_a_public_workspace_the_user_cannot_see_or_that_is_gone_is_unavailable(self):
        for reference in (doc('pub-hidden-doc', 'public', 'public-hidden'), doc('pub-doc', 'public', 'public-gone')):
            with self.subTest(reference=reference):
                self.world.reset()
                self.assertEqual('workspace_unavailable', self.refused([reference]).reason)

    def test_disabled_workspace_types_are_refused(self):
        cases = (
            (dict(ALL_ENABLED, enable_user_workspace=False), doc('own')),
            (dict(ALL_ENABLED, enable_group_workspaces=False), doc('grp-doc', 'group', 'group-a')),
            (dict(ALL_ENABLED, enable_public_workspaces=False), doc('pub-doc', 'public', 'public-a')),
            (dict(ALL_ENABLED, enable_group_workspaces=False), tag('grp-tag', 'group', 'group-a')),
            (None, doc('own')),
            ({}, tag('review')),
        )
        for settings, reference in cases:
            with self.subTest(settings=settings, reference=reference):
                self.world.reset()
                error = self.refused([reference], settings)
                self.assertEqual('workspace_disabled', error.reason)
                self.assertIn('turned off', error.message)
                self.assertEqual([], self.world.calls)

    def test_an_allowlist_limits_the_workspaces(self):
        personal_only = [{'scope': 'personal', 'id': OWNER}]

        self.assertEqual('own', self.resolve([doc('own')], allowed_workspaces=personal_only)[0]['id'])
        self.assertEqual('workspace_locked', self.refused(
            [doc('grp-doc', 'group', 'group-a')], allowed_workspaces=personal_only,
        ).reason)
        self.assertEqual('workspace_locked', self.refused([doc('own')], allowed_workspaces=[]).reason)
        self.assertEqual('grp-doc', self.resolve(
            [doc('grp-doc', 'group', 'group-a')], allowed_workspaces=None,
        )[0]['id'])

    # ---- refused documents and tags ----------------------------------------------------

    def test_a_deleted_document_is_unavailable_not_a_failed_check(self):
        error = self.refused([doc('ghost', label='Old draft')])

        self.assertEqual('document_unavailable', error.reason)
        self.assertIn('\u201cOld draft\u201d is no longer available to you', error.message)
        self.assertNotIn('resolve_authorized_source_manifest', self.call_names())

    def test_only_resolvable_documents_reach_the_manifest(self):
        error = self.refused([doc('own'), doc('ghost', label='Old draft')])

        self.assertEqual('document_unavailable', error.reason)
        self.assertEqual(1, error.reference_index)
        manifests = [call for call in self.world.calls if call['fn'] == 'resolve_authorized_source_manifest']
        self.assertEqual([['own']], [call['arguments']['requested_sources'] for call in manifests])

    def test_unready_documents_are_refused(self):
        for document_id in ('own-processing', 'own-failed', 'own-bad-progress'):
            with self.subTest(document_id=document_id):
                self.world.reset()
                error = self.refused([doc(document_id, label='My upload')])
                self.assertEqual('document_not_ready', error.reason)
                self.assertEqual(
                    '\u201cMy upload\u201d is still processing or failed to process. Wait for it to finish, or remove it.',
                    error.message,
                )

    def test_a_legacy_document_without_progress_is_ready(self):
        self.assertEqual('Legacy memo', self.resolve([doc('own-legacy')])[0]['label'])

    def test_a_missing_tag_is_refused(self):
        for reference in (tag('nope'), tag('Review'), tag('grp-tag')):
            with self.subTest(reference=reference):
                self.world.reset()
                error = self.refused([reference])
                self.assertEqual('tag_unavailable', error.reason)
                self.assertEqual(
                    f'The tag \u201c{reference["label"]}\u201d no longer exists in its workspace. '
                    'Remove it and pick another tag.',
                    error.message,
                )

    def test_the_first_failing_reference_is_reported(self):
        cases = (
            ([doc('own'), doc('ghost'), doc('own-processing')], 1, 'document_unavailable'),
            ([doc('own'), doc('own'), doc('ghost')], 2, 'document_unavailable'),
            ([doc('own'), tag('nope')], 1, 'tag_unavailable'),
            ([doc('own'), doc('grp-left-doc', 'group', 'group-left')], 1, 'workspace_unavailable'),
            ([tag('review'), ref('chat_attachment', 'att-ready', 'chat', 'conv')], 1, 'unsupported_kind'),
        )
        for references, index, reason in cases:
            with self.subTest(references=references):
                self.world.reset()
                error = self.refused(references)
                self.assertEqual((reason, index), (error.reason, error.reference_index))

    # ---- bounds and failed checks ------------------------------------------------------

    def test_over_limit_lists_are_refused_before_any_read(self):
        error = self.refused([doc(f'own-{index}') for index in range(101)])
        self.assertEqual(('too_many', 'Attach at most 100 documents or tags.'), (error.reason, error.message))
        self.assertEqual([], self.world.calls)

        error = self.refused([doc('own'), doc('own-2'), tag('review')], limit=2)
        self.assertEqual(('too_many', 'Attach at most 2 documents or tags.'), (error.reason, error.message))
        self.assertEqual([], self.world.calls)

    def test_a_failed_check_is_retryable(self):
        cases = (
            ({'contexts_raise': True}, [doc('own')]),
            ({'short_contexts': True}, [doc('own'), doc('own-2')]),
            ({'manifest_raise': True}, [doc('own')]),
            ({'tags_raise': True}, [tag('review')]),
        )
        for flags, references in cases:
            with self.subTest(flags=flags):
                self.world.reset(**flags)
                error = self.refused(references)
                self.assertEqual('verification_failed', error.reason)
                self.assertEqual(
                    'The selected documents or tags could not be checked right now. Please retry.',
                    error.message,
                )

    def test_an_unexpected_failure_is_a_failed_check(self):
        with mock.patch.object(self.context, '_authorize_references', side_effect=KeyError('boom')):
            error = self.refused([doc('own')])

        self.assertEqual('verification_failed', error.reason)
        self.assertIsNone(error.reference_index)

    # ---- untrusted labels --------------------------------------------------------------

    def test_labels_in_messages_are_bounded_plain_text(self):
        markup = self.refused([doc('ghost', label='<img src=x onerror=alert(1)>')])
        controls = self.refused([doc('ghost', label='\x00Bad\x1f label\u202e\u2066\ufeff')])
        long_label = self.refused([doc('ghost', label='L' * 300)])

        self.assertIn('\u201c<img src=x onerror=alert(1)>\u201d', markup.message)
        self.assertIn('\u201cBad label\u201d', controls.message)
        self.assertEqual('Bad label', controls.label)
        self.assertEqual(200, len(long_label.label))
        self.assertIn('\u201c' + 'L' * 200 + '\u201d', long_label.message)

    def test_logs_carry_no_labels_or_identities(self):
        logged = []
        with mock.patch.object(self.context, 'log_event', side_effect=lambda *args, **kwargs: logged.append((args, kwargs))):
            self.refused([doc('intruder-doc', label='Quarterly numbers')])
            self.world.reset(manifest_raise=True)
            self.refused([doc('own', label='Board minutes')])

        self.assertTrue(logged)
        text = repr(logged)
        for secret in ('Quarterly numbers', 'Board minutes', 'intruder-doc', 'Secret merger plan', "'own'"):
            self.assertNotIn(secret, text)
        rejected = [kwargs['extra'] for args, kwargs in logged if 'rejected' in args[0]]
        self.assertEqual([{'reason': 'document_unavailable', 'reference_index': 0}], rejected[:1])

    def test_the_error_is_still_an_elicitation_context_error(self):
        error = self.refused([doc('ghost')])

        self.assertIsInstance(error, self.context.ElicitationContextError)
        self.assertEqual(error.message, str(error))


if __name__ == '__main__':
    assert_app_version_at_least('0.261.201')
    unittest.main(verbosity=2)
