# test_orchestration_plan_revision_store.py
"""
Functional tests for the pre-execution plan revision persistence boundary.
Version: 0.261.104
Implemented in: 0.261.102

Uses real storage helpers and SDK batch formatting with an atomic in-memory container.
No Azure network, model, or main-thread message writes are needed.
"""

import importlib
import json
import unittest
import uuid
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from azure.core.exceptions import AzureError
from azure.cosmos import exceptions

from test_support.app_stubs import stubbed_config
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


def canonical_plan():
    return {
        'run_id': 'run_original', 'plan_id': 'plan_original',
        'turn_id': 'turn1', 'conversation_id': 'conv1', 'user_id': 'user1',
        'revision': 0, 'status': 'awaiting_approval', 'planner_contract_version': 1,
        'intent': {'summary': 'Compare the selected sources.', 'complexity': 'simple'},
        'approval': {'mode': 'timed', 'state': 'pending', 'timeout_seconds': 10},
        'steps': [
            {
                'step_id': 'search', 'capability_id': 'document_search', 'title': 'Find sources',
                'arguments': {'query': 'Original request', 'document_ids': ['doc1', 'doc2']},
                'enabled': True, 'depends_on': [], 'status': 'pending',
            },
            {
                'step_id': 'compare', 'capability_id': 'document_compare', 'title': 'Compare sources',
                'arguments': {'document_ids': ['doc1'], 'right_document_ids': ['doc2']},
                'enabled': True, 'depends_on': ['search'], 'status': 'pending',
            },
            {
                'step_id': 'answer', 'capability_id': 'respond', 'title': 'Answer',
                'arguments': {}, 'enabled': True, 'depends_on': ['compare'], 'status': 'pending',
            },
        ],
    }


def editor_question():
    return {
        'elicitation_id': 'ask_current', 'run_id': 'run_original', 'revision': 1,
        'message': 'Which topic should the answer focus on?',
        'requested_schema': {
            'type': 'object', 'properties': {'topic': {'type': 'string'}},
            'required': ['topic'],
        },
        'ui_hints': {},
    }


class PlanRevisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.runs = AtomicMemoryContainer('conversation_id')
        with stubbed_config(
            cosmos_orchestration_runs_container=self.runs,
            cosmos_orchestration_run_steps_container=AtomicMemoryContainer('run_id'),
            cognitive_services_scope='https://cognitiveservices.azure.com/.default',
        ):
            self.store = importlib.import_module('functions_orchestration_runs')
            self.revisions = importlib.import_module('functions_orchestration_plan_revisions')
        patcher = patch.object(self.store, 'cosmos_orchestration_runs_container', self.runs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.context = {
            'turn_id': 'turn1', 'user_message': 'Original request',
            'user_message_id': 'message1', 'user_message_fingerprint': 'original-message-fingerprint',
            'original_seeds': {'document_ids': ['doc1', 'doc2']},
            'seeds': {'document_ids': ['doc1', 'doc2']},
            'resolved_message': 'Original effective request',
            'conversation_context': {
                'messages': [{'id': 'prior-user', 'fingerprint': 'original-snapshot'}],
                'truncated': False,
            },
            'answered_questions': [], 'planning_token_usage': {'total_tokens': 10},
        }
        self.store.create_orchestration_run(
            canonical_plan(), 'user1', 'conv1', turn_index=7,
            request_fingerprint='original-seed-fingerprint', turn_context=self.context,
            initial_updates={'snapshot': {'fingerprint': 'immutable-snapshot'}},
            idempotent=True,
        )
        self.original = self.read()

    def read(self, run_id='run_original', **kwargs):
        return self.revisions.read_revision_run(run_id, 'user1', 'conv1', **kwargs)

    def hold(self, **kwargs):
        return self.revisions.begin_plan_edit(
            'run_original', 'user1', 'conv1', plan_id='plan_original', **kwargs,
        )

    def request(self, record, **overrides):
        return {
            'conversation_id': 'conv1', 'expected_version': record.get('edit_version', ''),
            'submission_id': str(uuid.uuid4()), 'action': 'ask',
            'instruction': 'Focus the comparison on pricing.', **overrides,
        }

    def claim(self, record, body=None, **overrides):
        return self.revisions.claim_plan_revision(
            record['id'], 'user1', 'conv1', body or self.request(record, **overrides),
        )

    def publish(self, record, *, body=None, **kwargs):
        claim = self.claim(record, body)
        return self.revisions.complete_plan_revision(
            claim, kind='plan', document=deepcopy(record['plan']), **kwargs,
        )

    def ordinary_replan(self, *, expected=None, plan=None):
        if plan is None:
            plan = canonical_plan()
            plan.update(run_id='run_replanned', plan_id='plan_replanned', revision=1)
        return self.store.create_orchestration_run(
            plan, 'user1', 'conv1', turn_context=self.context,
            idempotent=True, expected_previous_run=expected or self.original,
        )

    def discard_request(self, record, **overrides):
        return {
            'conversation_id': 'conv1', 'submission_id': str(uuid.uuid4()),
            'expected_version': record['edit_version'], 'action': 'discard', **overrides,
        }

    def assert_error(self, code, function, *args, status=409, **kwargs):
        with self.assertRaises(self.revisions.PlanRevisionError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.status_code, status)
        return caught.exception

    def run_plan(self, record, **kwargs):
        return self.revisions.claim_plan_run(record['id'], 'user1', 'conv1', **kwargs)

    def test_application_version(self):
        assert_app_version_at_least('0.261.102')

    def test_hold_is_durable_and_overlay_does_not_change_canonical_steps(self):
        overlay = {'disabled_step_ids': ['compare'], 'removed_document_ids': {'search': ['doc2']}}
        held = self.hold(edits=overlay)
        self.assertEqual(held['plan']['steps'], self.original['plan']['steps'])
        self.assertEqual(held['edit_narrowing'], overlay)
        self.assertEqual(held['edit_version'], held['plan']['edit_version'])
        uuid.UUID(held['edit_version'])
        self.assertEqual(held['plan']['approval']['mode'], 'manual')
        self.assertEqual(held['approval'], held['plan']['approval'])
        self.assertEqual(held['status'], 'awaiting_approval')
        self.assertEqual(held['revision_root_run_id'], held['id'])
        self.assertNotEqual(held['_etag'], self.original['_etag'])
        again = self.hold(edits={'disabled_step_ids': []})
        self.assertEqual(again, held)
        self.assert_error('plan_changed', self.hold, expected_version='old')

    def test_unheld_hydration_is_read_only(self):
        state = self.revisions.plan_editor_state(self.original, 'user1')
        self.assertEqual(state['version'], '')
        self.assertEqual(state['plan']['approval']['mode'], 'timed')
        self.assertEqual(self.read(), self.original)
        self.assertEqual([row['origin'] for row in state['history']], ['original'])

    def test_container_patch_seam_is_resolved_dynamically(self):
        replacement = AtomicMemoryContainer('conversation_id')
        replacement.create_item(self.original)
        with patch.object(self.store, 'cosmos_orchestration_runs_container', replacement):
            held = self.hold()
            self.assertEqual(self.read()['edit_version'], held['edit_version'])
        self.assertNotIn('edit_version', self.read())
        self.assertIn('edit_version', replacement.read_item('run_original', 'conv1'))

    def test_hold_rejects_wrong_plan_and_settled_or_started_states(self):
        self.assert_error(
            'plan_changed', self.revisions.begin_plan_edit,
            'run_original', 'user1', 'conv1', plan_id='wrong-plan',
        )
        for status in ('running', 'completed', 'failed', 'cancelled', 'superseded', 'approved'):
            with self.subTest(status=status):
                self.runs.upsert_item({**self.original, 'status': status})
                self.assert_error('plan_changed', self.hold)
        self.runs.upsert_item({**self.original, 'started_at': '2026-09-07T12:00:00+00:00'})
        self.assert_error('plan_changed', self.hold)

    def test_run_wins_race_with_first_hold(self):
        winner = []
        self.runs.before_replace = lambda: winner.append(self.run_plan(self.original))
        self.assert_error('plan_changed', self.hold)
        self.assertEqual(self.read()['status'], 'running')
        self.assertNotIn('edit_version', self.read())
        self.assertEqual(len(winner), 1)

    def test_ordinary_replan_is_atomic_and_keeps_the_same_turn_index(self):
        saved = self.ordinary_replan()
        self.assertEqual(saved['turn_index'], self.original['turn_index'])
        self.assertEqual(self.read(follow_current=True)['id'], saved['id'])
        self.assertEqual(self.read()['status'], 'superseded')
        self.assertEqual(
            [row['id'] for row in self.store.list_conversation_runs('conv1', 'user1')],
            [saved['id']],
        )

    def test_ordinary_replan_loses_to_a_concurrent_hold(self):
        self.runs.before_batch = self.hold
        with self.assertRaises(self.store.ConversationContextError):
            self.ordinary_replan()
        self.assertEqual(len(self.runs.items), 1)
        self.assertEqual(self.read()['approval']['mode'], 'manual')
        self.assertNotIn('superseded_by_run_id', self.read())

    def test_ordinary_replan_cannot_replace_a_hold_observed_before_publication(self):
        self.hold()
        with self.assertRaises(self.store.ConversationContextError):
            self.ordinary_replan()
        self.assertEqual(self.runs.batch_calls, [])
        self.assertEqual(len(self.runs.items), 1)

    def test_ordinary_replan_retry_returns_the_saved_run_without_removing_its_hold(self):
        saved = self.ordinary_replan()
        held = self.revisions.begin_plan_edit(
            saved['id'], 'user1', 'conv1', plan_id=saved['plan']['plan_id'],
        )
        replay = self.ordinary_replan()
        self.assertEqual(replay, self.store._strip_cosmos_metadata(held))
        self.assertEqual(self.read(saved['id']), held)
        self.assertEqual(len(self.runs.batch_calls), 1)

    def test_ordinary_replan_lost_response_replays_the_existing_outcome(self):
        def lose_response():
            raise AzureError('Private lost replan response')

        self.runs.after_batch = lose_response
        with self.assertRaises(AzureError):
            self.ordinary_replan()
        saved = self.read('run_replanned')
        replay = self.ordinary_replan()
        self.assertEqual(replay, self.store._strip_cosmos_metadata(saved))
        self.assertEqual(len(self.runs.items), 2)
        self.assertEqual(len(self.runs.batch_calls), 1)

    def test_concurrent_same_run_replans_replay_one_atomic_outcome(self):
        winner = []
        self.runs.before_batch = lambda: winner.append(self.ordinary_replan())
        replay = self.ordinary_replan()
        self.assertEqual(replay, winner[0])
        self.assertEqual(len(self.runs.items), 2)
        self.assertEqual(self.read()['superseded_by_run_id'], replay['id'])

    def test_idempotent_same_run_retry_never_resets_a_newer_hold(self):
        held = self.hold()
        replay = self.ordinary_replan(plan=canonical_plan())
        self.assertEqual(replay, self.store._strip_cosmos_metadata(held))
        self.assertEqual(self.read(), held)
        self.assertEqual(self.runs.batch_calls, [])

    def test_ordinary_replan_rejects_started_and_settled_previous_records(self):
        for status, started_at in (
            ('running', None), ('completed', None), ('failed', None),
            ('cancelled', None), ('superseded', None), ('archived', None),
            ('draft', '2026-09-07T12:00:00+00:00'),
        ):
            with self.subTest(status=status, started_at=started_at):
                self.runs.upsert_item({**self.original, 'status': status, 'started_at': started_at})
                with self.assertRaises(self.store.ConversationContextError):
                    self.ordinary_replan(expected=self.read())
                self.assertEqual(len(self.runs.items), 1)
        self.assertEqual(self.runs.batch_calls, [])

    def test_ordinary_replan_replay_cannot_return_another_owners_record(self):
        saved = self.ordinary_replan()
        self.runs.upsert_item({**saved, 'user_id': 'other-user'})
        with self.assertRaises(self.store.ConversationContextError):
            self.ordinary_replan()
        self.assertEqual(len(self.runs.batch_calls), 1)

    def test_hold_wins_race_with_legacy_run(self):
        winner = []
        self.runs.before_replace = lambda: winner.append(self.hold())
        self.assert_error('plan_changed', self.run_plan, self.original)
        self.assertEqual(self.read()['status'], 'awaiting_approval')
        self.assertEqual(self.read()['edit_version'], winner[0]['edit_version'])

    def test_competing_claims_have_one_winner(self):
        held = self.hold()
        winner = []
        self.runs.before_replace = lambda: winner.append(self.claim(held))
        self.assert_error('edit_in_progress', self.claim, held)
        self.assertEqual(self.read()['edit_claim']['claim_id'], winner[0]['claim_id'])
        self.assertTrue(self.revisions.plan_editor_state(self.read(), 'user1')['busy'])
        self.assert_error('edit_in_progress', self.run_plan, held, expected_version=held['edit_version'])

    def test_claim_captures_latest_overlay_without_mutating_plan(self):
        held = self.hold(edits={'disabled_step_ids': ['search']})
        saved = self.claim(held)
        self.assertEqual(saved['request']['edits']['disabled_step_ids'], ['search'])
        self.assertEqual(saved['record']['plan']['steps'], self.original['plan']['steps'])
        self.revisions.release_plan_revision(saved)
        overlay = {'disabled_step_ids': ['compare'], 'removed_document_ids': {'search': ['doc2']}}
        newer = self.claim(self.read(), edits=overlay)
        self.assertEqual(newer['record']['edit_narrowing'], overlay)
        self.assertEqual(newer['request']['edits'], overlay)

    def test_unknown_full_plan_oversized_and_invalid_payloads_are_rejected(self):
        held = self.hold()
        for overrides in (
            {'plan': canonical_plan()}, {'action': 'execute'}, {'instruction': ' '},
            {'instruction': 'a' * 2001}, {'instruction': []}, {'submission_id': []},
            {'source_run_id': 'not-an-ask-field'}, {'edits': {'steps': []}},
            {'edits': {'disabled_step_ids': ['unknown']}},
            {'edits': {'disabled_step_ids': ['answer']}},
            {'edits': {'removed_document_ids': {'search': ['not-present']}}},
            {'edits': {'removed_document_ids': {'unknown': ['doc1']}}},
            {'edits': {'disabled_step_ids': 'search'}},
        ):
            with self.subTest(overrides=overrides):
                self.assert_error('invalid_request', self.claim, held, status=400, **overrides)
        self.assert_error(
            'request_too_large', self.claim, held, status=413,
            instruction='x' * (self.revisions.EDIT_REQUEST_MAX_BYTES + 1),
        )
        self.assertIsNone(self.read()['edit_claim'])
        self.assert_error('plan_changed', self.claim, held, expected_version='stale')
        self.assert_error('plan_changed', self.claim, self.original, expected_version='')

    def test_publication_mints_identity_and_preserves_immutable_context(self):
        held = self.hold()
        claim = self.claim(held)
        candidate = deepcopy(held['plan'])
        candidate.update({
            'plan_id': 'model-plan', 'run_id': 'model-run', 'revision': 999,
            'user_id': 'model-user', 'turn_id': 'model-turn', 'conversation_id': 'model-conversation',
            'started_at': 'yesterday', 'token_usage': {'provider': 'private-provider'},
            'evidence': ['stale'], 'raw_provider_response': 'private-provider',
        })
        for step in candidate['steps']:
            step.update(status='completed', result={'private': 'runtime'}, started_at='yesterday')
        candidate_context = {
            **deepcopy(self.context), 'user_message': 'attempted replacement',
            'user_message_id': 'replacement', 'user_message_fingerprint': 'replacement',
            'conversation_context': {'messages': []}, 'snapshot': {'changed': True},
            'original_seeds': {}, 'turn_id': 'replacement', 'conversation_id': 'replacement',
            'user_id': 'replacement', 'request_fingerprint': 'replacement', 'turn_index': 99,
            'seeds': {'document_ids': ['doc1']}, 'resolved_message': 'A revised effective task.',
            'edit_user_urls': ['https://user.example.test'], 'config': {'secret': 'private-config'},
        }
        chat = [{'role': 'assistant', 'content': 'Updated the plan.', 'timestamp': '2026-09-07'}]
        saved = self.revisions.complete_plan_revision(
            claim, kind='plan', document=candidate, turn_context=candidate_context, chat=chat,
            instruction='Focus on pricing.',
        )
        self.assertNotIn(saved['id'], ('model-run', held['id']))
        self.assertNotIn(saved['plan']['plan_id'], ('model-plan', held['plan']['plan_id']))
        self.assertEqual(saved['plan']['run_id'], saved['id'])
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['plan']['revision'], 1)
        self.assertEqual(saved['turn_index'], 7)
        for key in self.revisions._IMMUTABLE_FIELDS:
            self.assertEqual(saved[key], held[key], key)
        self.assertEqual(saved['resolved_message'], candidate_context['resolved_message'])
        self.assertEqual(saved['seeds'], candidate_context['seeds'])
        self.assertEqual(saved['edit_user_urls'], candidate_context['edit_user_urls'])
        self.assertEqual(saved['edit_chat'], chat)
        self.assertEqual(saved['edit_narrowing'], {'disabled_step_ids': [], 'removed_document_ids': {}})
        self.assertEqual(saved['parent_run_id'], held['id'])
        self.assertEqual(saved['revision_root_run_id'], held['id'])
        self.assertEqual(saved['approval']['mode'], 'manual')
        self.assertIsNone(saved['started_at'])
        self.assertEqual(saved['artifacts'], [])
        self.assertNotIn('config', saved)
        self.assertNotIn('private-provider', json.dumps(saved))
        for step in saved['plan']['steps']:
            self.assertEqual(step['status'], 'pending')
            self.assertNotIn('result', step)
            self.assertNotIn('started_at', step)
        before = self.read()
        self.assertEqual(before['status'], 'superseded')
        self.assertEqual(before['superseded_by_run_id'], saved['id'])
        self.assertEqual(before['plan']['steps'], held['plan']['steps'])
        self.assertEqual(before['edit_submissions'][0]['result_run_id'], saved['id'])
        self.assertEqual(self.runs.batch_calls[-1][0]['ifMatch'], claim['record']['_etag'])

    def test_completed_retry_replays_before_old_version_or_supersession_checks(self):
        held = self.hold()
        body = self.request(held)
        saved = self.publish(held, body=body)
        replay = self.claim(held, body)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['outcome_run_id'], saved['id'])
        self.assertEqual(len(self.runs.batch_calls), 1)
        self.assert_error('submission_conflict', self.claim, held, {**body, 'instruction': 'Different'})
        self.assert_error('plan_changed', self.revisions.complete_plan_revision, replay, kind='message')

    def test_runtime_url_provenance_survives_later_revisions_without_new_context(self):
        held = self.hold()
        urls = [f'https://user{index}.example.test/report' for index in range(8)]
        first = self.publish(held, turn_context={'edit_user_urls': urls})
        later = self.publish(first)
        self.assertEqual(first['edit_user_urls'], urls)
        self.assertEqual(later['edit_user_urls'], urls)
        self.assertNotIn('edit_user_urls', self.revisions.plan_editor_state(later, 'user1'))
        executed = self.run_plan(later, expected_version=later['edit_version'])
        self.assertEqual(executed['edit_user_urls'], urls)

    def test_lost_batch_response_is_replayed_without_a_second_publication(self):
        held = self.hold()
        body = self.request(held)
        claim = self.claim(held, body)

        def lose_response():
            raise AzureError('Private lost response')

        self.runs.after_batch = lose_response
        with self.assertRaises(AzureError):
            self.revisions.complete_plan_revision(claim, kind='plan', document=held['plan'])
        self.revisions.release_plan_revision(claim)
        replay = self.claim(held, body)
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.read(follow_current=True)['id'], replay['outcome_run_id'])
        self.assertEqual(len(self.runs.items), 2)
        self.assertEqual(len(self.runs.batch_calls), 1)

    def test_failure_of_second_batch_operation_is_atomic_and_retry_ids_are_stable(self):
        held = self.hold()
        body = self.request(held)
        claim = self.claim(held, body)
        before = deepcopy(self.runs.items)
        self.runs.fail_batch_at = 1
        with self.assertRaises(exceptions.CosmosBatchOperationError):
            self.revisions.complete_plan_revision(claim, kind='plan', document=held['plan'])
        self.assertEqual(self.runs.items, before)
        attempted = self.runs.batch_calls[-1][1]['resourceBody']
        self.revisions.release_plan_revision(claim)
        self.runs.fail_batch_at = None
        retry = self.claim(self.read(), body)
        saved = self.revisions.complete_plan_revision(retry, kind='plan', document=held['plan'])
        self.assertEqual(saved['id'], attempted['id'])
        self.assertEqual(saved['plan']['plan_id'], attempted['plan']['plan_id'])

    def test_expired_claim_cannot_publish_or_clear_newer_lease(self):
        held = self.hold()
        body = self.request(held)
        first = self.claim(held, body)
        later = self.revisions._now() + timedelta(seconds=self.revisions.EDIT_CLAIM_SECONDS + 1)
        with patch.object(self.revisions, '_now', return_value=later):
            self.assert_error(
                'plan_changed', self.revisions.complete_plan_revision,
                first, kind='plan', document=held['plan'],
            )
            retry = self.claim(held, body)
            self.assertNotEqual(first['claim_id'], retry['claim_id'])
            self.revisions.release_plan_revision(first)
            self.assertEqual(self.read()['edit_claim']['claim_id'], retry['claim_id'])
            saved = self.revisions.complete_plan_revision(retry, kind='plan', document=held['plan'])
        self.assertEqual(saved['revision'], 1)
        self.assert_error(
            'plan_changed', self.revisions.complete_plan_revision,
            first, kind='plan', document=held['plan'],
        )

    def test_delayed_batch_cannot_overwrite_a_newer_publication(self):
        held = self.hold()
        original_claim = self.claim(held)
        saved = []

        def competitor():
            later = self.revisions._now() + timedelta(seconds=self.revisions.EDIT_CLAIM_SECONDS + 1)
            with patch.object(self.revisions, '_now', return_value=later):
                replacement_claim = self.claim(held)
                saved.append(self.revisions.complete_plan_revision(
                    replacement_claim, kind='plan', document=held['plan'],
                ))

        self.runs.before_batch = competitor
        error = self.assert_error(
            'plan_changed', self.revisions.complete_plan_revision,
            original_claim, kind='plan', document=held['plan'],
        )
        self.assertEqual(error.current_run_id, saved[0]['id'])
        self.assertEqual(len(self.runs.items), 2)
        self.assertEqual(self.read(follow_current=True)['id'], saved[0]['id'])

    def test_released_submission_id_cannot_be_rebound_to_a_different_request(self):
        held = self.hold()
        body = self.request(held)
        claim = self.claim(held, body)
        self.revisions.release_plan_revision(claim)
        self.assertIsNone(self.read()['edit_claim'])
        self.assert_error('submission_conflict', self.claim, held, {**body, 'instruction': 'Other task'})
        self.assertFalse(self.claim(held, body)['replayed'])

    def test_question_outcome_keeps_private_context_off_the_live_plan(self):
        held = self.hold()
        claim = self.claim(held)
        question = editor_question()
        private = {
            'elicitation': question, 'instruction': 'private-instruction',
            'turn_context': {'seeds': {'private': 'private-seed'}, 'resolved_message': 'Unaccepted task'},
            'base_plan': deepcopy(held['plan']), 'user_content': 'private-user-content',
        }
        saved = self.revisions.complete_plan_revision(
            claim, kind='elicitation', document=question, pending=private,
            turn_context={'resolved_message': 'Unaccepted task', 'planning_token_usage': {'total_tokens': 25}},
            chat=[{'role': 'assistant', 'content': question['message']}],
        )
        self.assertEqual(saved['plan']['steps'], held['plan']['steps'])
        self.assertEqual(saved['resolved_message'], held['resolved_message'])
        self.assertEqual(saved['planning_token_usage']['total_tokens'], 25)
        self.assertNotEqual(saved['edit_version'], held['edit_version'])
        state = self.revisions.plan_editor_state(saved, 'user1')
        self.assertEqual(state['pending'], question)
        self.assertNotIn('private-', json.dumps(state))
        self.assert_error('edit_in_progress', self.claim, saved)
        self.assert_error('edit_in_progress', self.run_plan, saved, expected_version=saved['edit_version'])
        body = {
            'conversation_id': 'conv1', 'submission_id': 'answer1',
            'expected_version': saved['edit_version'], 'action': 'answer',
            'elicitation_id': question['elicitation_id'], 'elicitation_revision': question['revision'],
            'elicitation_response': {'action': 'accept', 'content': {'topic': 'pricing'}},
            'elicitation_context': {},
        }
        self.assert_error('plan_changed', self.claim, saved, {**body, 'elicitation_id': 'ask_stale'})
        answer = self.claim(saved, body)
        self.assertEqual(answer['record']['edit_pending'], private)
        final = self.revisions.complete_plan_revision(answer, kind='plan', document=held['plan'])
        self.assertIsNone(final['edit_pending'])
        self.assertEqual(final['revision'], 1)

    def test_discard_preserves_plan_and_replays_after_question_is_cleared(self):
        held = self.hold()
        question_claim = self.claim(held)
        asked = self.revisions.complete_plan_revision(
            question_claim, kind='elicitation',
            pending={'elicitation': editor_question(), 'turn_context': self.context},
        )
        body = {
            'conversation_id': 'conv1', 'submission_id': 'discard1',
            'expected_version': asked['edit_version'], 'action': 'discard',
        }
        claim = self.claim(asked, body)
        saved = self.revisions.complete_plan_revision(claim, kind='discard')
        self.assertIsNone(saved['edit_pending'])
        self.assertEqual(saved['plan']['steps'], held['plan']['steps'])
        self.assertEqual(saved['resolved_message'], held['resolved_message'])
        self.assertTrue(self.claim(asked, body)['replayed'])
        self.assert_error(
            'plan_changed', self.claim, saved,
            {**body, 'submission_id': 'discard2', 'expected_version': saved['edit_version']},
        )
        self.assertEqual(self.run_plan(saved, expected_version=saved['edit_version'])['status'], 'running')

    def test_discard_revokes_an_active_worker_without_a_pending_question(self):
        held = self.hold(edits={'disabled_step_ids': ['compare']})
        worker = self.claim(held)
        body = self.discard_request(held)
        self.assert_error(
            'plan_changed', self.claim, held, {**body, 'expected_version': 'stale'},
        )
        discard = self.claim(held, body)
        self.assertNotEqual(discard['claim_id'], worker['claim_id'])
        self.revisions.release_plan_revision(worker)
        self.assertEqual(self.read()['edit_claim']['claim_id'], discard['claim_id'])
        self.assert_error('edit_in_progress', self.claim, held, body)
        self.assert_error(
            'plan_changed', self.revisions.complete_plan_revision,
            worker, kind='plan', document=held['plan'],
        )
        saved = self.revisions.complete_plan_revision(discard, kind='discard')
        self.assertEqual(saved['plan']['steps'], held['plan']['steps'])
        self.assertEqual(saved['edit_narrowing'], held['edit_narrowing'])
        self.assertEqual(saved['status'], 'awaiting_approval')
        self.assertEqual(saved['approval']['mode'], 'manual')
        self.assertIsNone(saved['edit_claim'])
        self.assertIsNone(saved['edit_pending'])
        self.assertNotEqual(saved['edit_version'], held['edit_version'])
        self.assertTrue(self.claim(held, body)['replayed'])
        self.assertEqual(len(self.runs.items), 1)
        self.assertEqual(self.run_plan(saved, expected_version=saved['edit_version'])['status'], 'running')

    def test_discard_loses_when_an_edit_commits_before_its_conditional_write(self):
        held = self.hold()
        worker = self.claim(held)
        outcomes = []
        self.runs.before_replace = lambda: outcomes.append(self.revisions.complete_plan_revision(
            worker, kind='plan', document=held['plan'],
        ))
        error = self.assert_error('plan_changed', self.claim, held, self.discard_request(held))
        self.assertEqual(error.current_run_id, outcomes[0]['id'])
        self.assertEqual(self.read(follow_current=True)['id'], outcomes[0]['id'])
        self.assertEqual(len(self.runs.items), 2)

    def test_discard_prevents_an_already_prepared_late_batch_from_publishing(self):
        held = self.hold()
        worker = self.claim(held)
        outcomes = []

        def discard_first():
            discard = self.claim(held, self.discard_request(held))
            outcomes.append(self.revisions.complete_plan_revision(discard, kind='discard'))

        self.runs.before_batch = discard_first
        self.assert_error(
            'plan_changed', self.revisions.complete_plan_revision,
            worker, kind='plan', document=held['plan'],
        )
        self.revisions.release_plan_revision(worker)
        self.assertEqual(self.read(), outcomes[0])
        self.assertEqual(len(self.runs.items), 1)
        self.assertEqual(self.read()['plan']['steps'], held['plan']['steps'])

    def test_run_uses_saved_narrowing_and_rejects_duplicate_start(self):
        overlay = {'disabled_step_ids': ['compare'], 'removed_document_ids': {'search': ['doc2']}}
        held = self.hold(edits=overlay)
        self.assert_error('plan_changed', self.run_plan, held)
        self.assert_error('plan_changed', self.run_plan, held, expected_version='stale')
        claimed = self.run_plan(held, expected_version=held['edit_version'], plan_id='plan_original')
        self.assertEqual(claimed['status'], 'running')
        self.assertEqual(claimed['plan']['status'], 'running')
        self.assertEqual(claimed['approval']['state'], 'approved')
        self.assertEqual(claimed['approval']['approved_by'], 'user1')
        self.assertEqual(claimed['approval'], claimed['plan']['approval'])
        self.assertFalse(claimed['plan']['steps'][1]['enabled'])
        self.assertEqual(claimed['plan']['steps'][0]['arguments']['document_ids'], ['doc1'])
        self.assertEqual(claimed['plan']['steps'][2]['capability_id'], 'respond')
        self.assert_error('already_run', self.run_plan, claimed, expected_version=claimed['edit_version'])

    def test_untouched_legacy_plan_runs_without_version_and_write_failure_propagates(self):
        self.runs.fail_writes = True
        with self.assertRaises(AzureError):
            self.run_plan(self.original)
        self.assertEqual(self.read(), self.original)
        self.runs.fail_writes = False
        claimed = self.run_plan(
            self.original, edits={'disabled_step_ids': ['compare']},
            conversation_context=self.context['conversation_context'],
        )
        self.assertEqual(claimed['status'], 'running')
        self.assertNotIn('edit_version', claimed)
        self.assertFalse(claimed['plan']['steps'][1]['enabled'])

    def test_run_rejects_cancelled_settled_and_previously_started_records(self):
        for status in ('cancelled', 'failed', 'superseded', 'archived'):
            with self.subTest(status=status):
                self.runs.upsert_item({**self.original, 'status': status})
                self.assert_error('plan_changed', self.run_plan, self.original)
        for status in ('running', 'completed'):
            with self.subTest(status=status):
                self.runs.upsert_item({**self.original, 'status': status})
                self.assert_error('already_run', self.run_plan, self.original)
        self.runs.upsert_item({**self.original, 'status': 'failed', 'started_at': 'yesterday'})
        self.assert_error('already_run', self.run_plan, self.original)

    def test_ownership_non_run_ids_and_availability_failures(self):
        for run_id, user_id, conversation_id in (
            ('run_original', 'other-user', 'conv1'),
            ('run_original', 'user1', 'other-conversation'),
            (['run_original'], 'user1', 'conv1'),
            ('../run_original', 'user1', 'conv1'),
            ('\ud800', 'user1', 'conv1'),
        ):
            self.assert_error(
                'not_found', self.revisions.read_revision_run,
                run_id, user_id, conversation_id, status=404,
            )
        non_run = {**self.original, 'record_type': 'pending_elicitation'}
        self.runs.upsert_item(non_run)
        self.assert_error('not_found', self.read, status=404)
        self.runs.upsert_item({**self.original, 'record_type': None, 'plan': {}})
        self.assert_error('not_found', self.read, status=404)
        self.runs.upsert_item(self.original)
        self.runs.fail_reads = True
        with self.assertRaises(AzureError):
            self.read()
        self.runs.fail_reads = False
        self.runs.fail_queries = True
        with self.assertRaises(AzureError):
            self.revisions.plan_editor_state(self.original, 'user1')

    def test_foreign_revision_targets_and_restore_sources_are_not_followed(self):
        held = self.hold()
        other = deepcopy(held)
        other.update(id='run_other', run_id='run_other', revision=1)
        other['plan'].update(run_id='run_other', plan_id='plan_other', revision=1)
        for changes in (
            {'user_id': 'other-user'}, {'turn_id': 'other-turn'},
            {'revision_root_run_id': 'other-root'}, {'conversation_id': 'other-conversation'},
        ):
            with self.subTest(changes=changes):
                candidate = deepcopy(other)
                candidate.update(changes)
                for key in ('user_id', 'turn_id', 'conversation_id'):
                    if key in changes:
                        candidate['plan'][key] = changes[key]
                self.runs.upsert_item(candidate)
                self.runs.upsert_item({**held, 'superseded_by_run_id': 'run_other', 'status': 'superseded'})
                self.assert_error('not_found', self.read, status=404, follow_current=True)
                self.runs.upsert_item(held)
                body = {
                    'conversation_id': 'conv1', 'expected_version': held['edit_version'],
                    'submission_id': str(uuid.uuid4()), 'action': 'restore', 'source_run_id': 'run_other',
                }
                self.assert_error('not_found', self.claim, held, body, status=404)
                self.runs.items.pop(('conv1', 'run_other'), None)

    def test_superseded_runs_are_readable_but_hidden_from_normal_run_views(self):
        held = self.hold()
        current = self.publish(held)
        self.assertEqual(self.read()['id'], held['id'])
        self.assertEqual(self.store.get_orchestration_run(held['id'], 'user1', 'conv1')['id'], held['id'])
        self.assertEqual(self.read(follow_current=True)['id'], current['id'])
        self.assertEqual(
            [row['id'] for row in self.store.list_conversation_runs('conv1', 'user1')], [current['id']],
        )
        self.assertEqual(self.store.get_latest_turn_run('conv1', 'user1', 'turn1')['id'], current['id'])
        self.assertEqual(self.store.next_turn_index('conv1', 'user1'), 8)
        error = self.assert_error(
            'plan_changed', self.run_plan, held, expected_version=held['edit_version'],
        )
        self.assertEqual(error.current_run_id, current['id'])
        with patch.object(self.runs, 'query_items', return_value=[self.read(), current]):
            self.assertEqual(len(self.store.list_conversation_runs('conv1', 'user1')), 1)
            self.assertEqual(self.store.get_latest_turn_run('conv1', 'user1', 'turn1')['id'], current['id'])

    def test_history_is_paged_and_preserves_original_without_snapshot_arrays(self):
        current = self.hold()
        for index in range(45):
            current = self.publish(current, instruction=f'Edit {index + 1}')
        unrelated = deepcopy(current)
        unrelated.update(id='run_other', run_id='run_other', revision=500, revision_root_run_id='run_other')
        unrelated['plan'].update(run_id='run_other', plan_id='plan_other', revision=500)
        self.runs.upsert_item(unrelated)
        cursor = None
        history = []
        while True:
            state = self.revisions.plan_editor_state(current, 'user1', before_revision=cursor)
            self.assertLessEqual(len(state['history']), self.revisions.EDIT_HISTORY_PAGE_SIZE)
            history.extend(state['history'])
            cursor = state['next_before_revision']
            if cursor is None:
                break
        self.assertEqual([entry['revision'] for entry in history], list(range(45, -1, -1)))
        self.assertEqual(history[-1]['run_id'], self.original['id'])
        self.assertEqual(history[-1]['origin'], 'original')
        self.assertEqual(len(self.runs.items), 47)
        self.assertNotIn('history', current)
        self.assertEqual(self.read(follow_current=True)['id'], current['id'])
        self.assert_error(
            'invalid_request', self.revisions.plan_editor_state,
            current, 'user1', before_revision=-1, status=400,
        )

    def test_restore_creates_a_fresh_current_revision(self):
        held = self.hold()
        revised = self.publish(held, turn_context={'resolved_message': 'Pricing only'})
        body = {
            'conversation_id': 'conv1', 'submission_id': 'restore1',
            'expected_version': revised['edit_version'], 'action': 'restore',
            'source_run_id': held['id'],
        }
        claim = self.claim(revised, body)
        restored = self.revisions.complete_plan_revision(
            claim, kind='plan', document=self.read()['plan'], origin='restore',
            instruction='Restored original plan.', turn_context=self.context,
        )
        self.assertNotIn(restored['id'], (held['id'], revised['id']))
        self.assertEqual(restored['revision'], 2)
        self.assertEqual(restored['resolved_message'], self.context['resolved_message'])
        self.assertEqual(self.revisions.plan_editor_state(restored, 'user1')['history'][0]['origin'], 'restore')

    def test_editor_chat_and_completed_receipts_are_bounded(self):
        current = self.hold()
        chat = [
            {'role': 'user' if index % 2 else 'assistant', 'content': f'Turn {index}', 'timestamp': 'today'}
            for index in range(50)
        ]
        bodies = []
        for index in range(15):
            body = self.request(current)
            bodies.append(body)
            claim = self.claim(current, body)
            current = self.revisions.complete_plan_revision(claim, kind='message', chat=chat)
        self.assertEqual(len(current['edit_submissions']), self.revisions.EDIT_RETAINED_SUBMISSIONS)
        self.assertEqual(len(current['edit_chat']), 20)
        self.assertEqual(current['edit_chat'], chat[-20:])
        self.assertEqual(current['plan']['steps'], self.original['plan']['steps'])
        self.assertTrue(self.claim(current, bodies[-1])['replayed'])
        self.assertEqual(current['edit_attempts'], [])

    def test_safe_projection_excludes_private_record_and_provider_metadata(self):
        held = self.hold()
        held.update({
            'seeds': {'private': 'PRIVATE_SEEDS'}, 'config': {'key': 'PRIVATE_CONFIG'},
            'edit_chat': [
                {'role': 'system', 'content': 'PRIVATE_SYSTEM'},
                {'role': 'assistant', 'content': 'Safe reply', 'timestamp': 'today', 'raw': 'PRIVATE_CHAT'},
            ],
            'edit_pending': {
                'elicitation': {**editor_question(), 'token_usage': {'key': 'PRIVATE_PROVIDER'}},
                'instruction': 'PRIVATE_INSTRUCTION', 'turn_context': {'key': 'PRIVATE_CONTEXT'},
            },
        })
        held['plan'].update(raw_provider_response='PRIVATE_PLAN', seeds={'key': 'PRIVATE_PLAN_SEED'})
        held['plan']['steps'][0]['result'] = {'key': 'PRIVATE_STEP'}
        held['seeds']['web_search'] = True
        held['plan']['reasoning_adjustments'] = [{
            'requested_effort': 'minimal', 'effective_effort': 'low', 'mode': 'explicit',
            'adjustment_reason': 'reasoning_effort_unsupported', 'stage': 'planner',
            'model_name': 'gpt-5.6-luna', 'raw': 'PRIVATE_PROVIDER_RESPONSE',
        }, {
            'adjustment_reason': 'reasoning_effort_unsupported',
            'effective_effort': {'key': 'PRIVATE_MALFORMED_METADATA'},
        }]
        original_plan = deepcopy(held['plan'])
        state = self.revisions.plan_editor_state(held, 'user1')
        self.assertNotIn('PRIVATE_', json.dumps(state))
        self.assertNotIn('_etag', json.dumps(state))
        self.assertEqual(state['chat'][0]['content'], 'Safe reply')
        self.assertEqual(state['pending'], editor_question())
        self.assertEqual(state['plan']['inputs']['required_capabilities'], ['web_search'])
        self.assertEqual(len(state['plan']['reasoning_adjustments']), 1)
        self.assertEqual(state['plan']['reasoning_adjustments'][0]['effective_effort'], 'low')
        self.assertEqual(held['plan'], original_plan)
        self.assert_error('not_found', self.revisions.plan_editor_state, held, 'other-user', status=404)

    def test_release_does_not_hide_operational_failure_or_clear_pending_outcome(self):
        held = self.hold()
        claim = self.claim(held)
        self.runs.fail_writes = True
        with patch.object(self.revisions, 'log_event') as logged:
            self.revisions.release_plan_revision(claim)
        logged.assert_called_once()
        self.assertEqual(logged.call_args.kwargs['extra']['exception_type'], 'AzureError')
        self.assertNotIn('Private test storage failure', str(logged.call_args))
        self.assertEqual(self.read()['edit_claim']['claim_id'], claim['claim_id'])
        self.runs.fail_writes = False
        saved = self.revisions.complete_plan_revision(
            claim, kind='elicitation', pending={'elicitation': editor_question()},
        )
        self.revisions.release_plan_revision(claim)
        self.revisions.release_plan_revision(None)
        self.assertEqual(self.read(), saved)


if __name__ == '__main__':
    unittest.main()
