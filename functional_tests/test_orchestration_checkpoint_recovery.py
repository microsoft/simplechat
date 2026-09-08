# test_orchestration_checkpoint_recovery.py
"""Functional regressions for durable, checkpoint-only orchestration recovery.

Version: 0.261.105
Implemented in: 0.261.105
Runs real Flask endpoints, executor, checkpoint codec, conditional batches and
assistant persistence against AtomicMemoryContainer; no live services.
"""

import json
import unittest
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import threading
from unittest.mock import patch

from azure.core.exceptions import AzureError

from test_support.orchestration_recovery import RecoveryFixture, frames
from test_support.versioning import assert_app_version_at_least


class CheckpointRecoveryTests(unittest.TestCase):
    def _crash_retry(self, fixture, child, phase):
        manager_type = fixture.route.ExecutionCheckpoints
        original_initialize = manager_type.initialize
        original_save = manager_type.save_step
        namespace = fixture.route.prepare_retry.__globals__

        def crash(manager):
            manager.lease.close()
            fixture.runs.items[('conv1', child['run_id'])]['execution_lease']['expires_at'] = (
                namespace['_now']() - timedelta(seconds=2)
            ).isoformat()
            raise namespace['CheckpointError']('ownership_lost')

        def initialize(manager):
            if phase == 'before_initialize':
                crash(manager)
            original_initialize(manager)
            if phase == 'after_initialize':
                crash(manager)

        def save(manager, record):
            original_save(manager, record)
            if phase == 'after_first_copy' and record['step_id'] == 'a':
                crash(manager)

        with patch.object(manager_type, 'initialize', initialize), patch.object(manager_type, 'save_step', save):
            events = frames(fixture.run_attempt(child['plan']))
        self.assertFalse(any(event.get('type') == 'orchestration_done' for event in events))

    def test_inherited_effect_checkpoints_survive_crashes_and_chained_retries(self):
        for phase in ('before_initialize', 'after_initialize', 'after_first_copy'):
            with self.subTest(phase=phase), RecoveryFixture() as fixture:
                fixture.fail_b = False
                fixture.model.answer_error = RuntimeError('answer failed')
                plan = fixture.plan_attempt()
                fixture.run_attempt(plan)
                child = fixture.retry(plan['run_id'], confirm_external_effects=False).get_json()['run']
                self.assertEqual(child['recovery']['reused_step_ids'], ['a', 'b', 'c'])
                self.assertEqual(child['recovery']['retry_step_ids'], ['answer'])
                self._crash_retry(fixture, child, phase)
                detail = fixture.detail(child['run_id'])
                self.assertEqual(detail['finalization_status'], 'interrupted')
                self.assertEqual(detail['recovery']['reused_step_ids'], ['a', 'b', 'c'])
                self.assertEqual(detail['recovery']['retry_step_ids'], ['answer'])
                self.assertFalse(detail['recovery']['requires_confirmation'])
                hydrated = fixture.client.get(
                    f"/api/v2/orchestration/runs/{child['run_id']}/steps?conversation_id=conv1"
                ).get_json()['steps']
                self.assertEqual([step['step_id'] for step in hydrated], ['a', 'b', 'c'])
                self.assertTrue(all(step['status'] == 'completed' and step['reused'] for step in hydrated))
                self.assertNotIn('payload_digest', json.dumps(hydrated))
                old_token = fixture.runs.read_item(child['run_id'], 'conv1')['execution_lease']['token']
                response = fixture.retry(child['run_id'], confirm_external_effects=False)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                namespace = fixture.route.prepare_retry.__globals__
                old_store = namespace['checkpoint_store'](
                    fixture.runs.read_item(child['run_id'], 'conv1'), lambda: True, token=old_token,
                )
                with self.assertRaises(namespace['CheckpointError']):
                    old_store.initialize()
                third = response.get_json()['run']
                self._crash_retry(fixture, third, 'after_initialize')
                fourth = fixture.retry(third['run_id'], confirm_external_effects=False).get_json()['run']
                fixture.model.answer_error = None
                done = next(
                    event for event in frames(fixture.run_attempt(fourth['plan']))
                    if event.get('type') == 'orchestration_done'
                )
                self.assertEqual(done['status'], 'completed')
                self.assertEqual(fixture.calls, ['a', 'b', 'c'])
                record = fixture.runs.read_item(fourth['run_id'], 'conv1')
                self.assertTrue(all(
                    step.get('reused_from_run_id') == plan['run_id']
                    for step in record['execution_steps'] if step['step_id'] != 'answer'
                ))

    def test_invalid_inherited_checkpoints_block_without_repeating_effects(self):
        for damage in ('missing_run', 'deleted', 'deleted_checkpoint', 'missing_manifest', 'corrupt_chunk', 'owner', 'turn', 'plan', 'binding', 'digest', 'missing_reference'):
            with self.subTest(damage=damage), RecoveryFixture() as fixture:
                fixture.fail_b = False
                fixture.model.answer_error = RuntimeError('answer failed')
                plan = fixture.plan_attempt()
                fixture.run_attempt(plan)
                child = fixture.retry(plan['run_id'], confirm_external_effects=False).get_json()['run']
                self._crash_retry(fixture, child, 'after_first_copy')
                original = fixture.runs.items[('conv1', plan['run_id'])]
                interrupted = fixture.runs.items[('conv1', child['run_id'])]
                if damage == 'missing_run':
                    del fixture.runs.items[('conv1', plan['run_id'])]
                elif damage == 'deleted':
                    original['checkpoints_deleted'] = True
                elif damage == 'deleted_checkpoint':
                    fixture.steps.items[(plan['run_id'], 'checkpoint:lifecycle')]['deleted'] = True
                elif damage == 'missing_manifest':
                    key = next(key for key, row in fixture.steps.items.items()
                               if key[0] == plan['run_id'] and row.get('step_id') == 'b'
                               and row.get('record_type') == 'checkpoint_manifest')
                    del fixture.steps.items[key]
                elif damage == 'corrupt_chunk':
                    row = next(row for key, row in fixture.steps.items.items()
                               if key[0] == plan['run_id'] and row.get('step_id') == 'b'
                               and row.get('record_type') == 'checkpoint_chunk')
                    row['data'] = 'invalid private checkpoint bytes'
                elif damage == 'owner':
                    original['user_id'] = 'other-user'
                elif damage == 'turn':
                    original['turn_id'] = 'other-turn'
                elif damage == 'plan':
                    original['plan']['steps'][1]['arguments']['task'] = 'Different external action'
                elif damage == 'binding':
                    original['execution_binding'] = 'different-binding'
                elif damage == 'digest':
                    interrupted['inherited_checkpoints']['b']['payload_digest'] = 'different-digest'
                else:
                    interrupted['inherited_checkpoints'].pop('b')
                response = fixture.client.post(f"/api/v2/orchestration/runs/{child['run_id']}/retry", json={
                    'conversation_id': 'conv1', 'submission_id': 'damaged-retry',
                    'expected_version': interrupted['recovery_version'], 'confirm_external_effects': False,
                })
                self.assertIn(response.status_code, (404, 409, 503), response.get_data(as_text=True))
                self.assertEqual(fixture.calls, ['a', 'b', 'c'])
                self.assertFalse(interrupted.get('latest_attempt_run_id'))
                detail = fixture.client.get(
                    f"/api/v2/orchestration/runs/{child['run_id']}?conversation_id=conv1"
                )
                self.assertEqual(detail.status_code, 503)
                self.assertEqual(detail.get_json()['code'], 'recovery_unavailable')

    def test_inherited_success_does_not_waive_confirmation_for_new_failed_effects(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            child = fixture.retry(plan['run_id']).get_json()['run']
            fixture.run_attempt(child['plan'])
            detail = fixture.detail(child['run_id'])
            self.assertEqual(detail['recovery']['reused_step_ids'], ['a'])
            self.assertTrue(detail['recovery']['requires_confirmation'])
            denied = fixture.retry(child['run_id'], confirm_external_effects=False)
            self.assertEqual(denied.status_code, 409)
            self.assertEqual(denied.get_json()['code'], 'confirmation_required')
            self.assertEqual(fixture.calls, ['a', 'b', 'b'])

    def test_lost_publication_and_run_link_acknowledgements_reconcile_saved_message(self):
        for boundary in ('message', 'run_link', 'lease_release'):
            with self.subTest(boundary=boundary), RecoveryFixture() as fixture:
                plan = fixture.plan_attempt()
                original_replace = fixture.runs.replace_item
                lost = []

                def replace(item, body, **kwargs):
                    saved = original_replace(item, body, **kwargs)
                    if not lost and (
                        (boundary == 'run_link' and body.get('assistant_message_id'))
                        or (boundary == 'lease_release' and body.get('assistant_message_id') and not body.get('execution_lease'))
                    ):
                        lost.append(True)
                        raise AzureError('private lost run acknowledgement')
                    return saved

                def lose_message_ack():
                    lost.append(True)
                    raise AzureError('private lost batch acknowledgement')

                if boundary == 'message':
                    fixture.messages.after_batch = lose_message_ack
                with patch.object(fixture.runs, 'replace_item', replace):
                    events = frames(fixture.run_attempt(plan))
                self.assertTrue(lost)
                done = next(event for event in events if event.get('type') == 'orchestration_done')
                detail = fixture.detail(plan['run_id'])
                self.assertTrue(done['message_saved'])
                self.assertTrue(detail['message_saved'])
                self.assertEqual(done['finalization_status'], 'saved')
                self.assertEqual(detail['finalization_status'], 'saved')
                self.assertEqual(detail['failure']['code'], 'step_timeout')
                self.assertTrue(detail['recovery']['eligible'])
                self.assertEqual(detail['assistant_message_id'], done['message_id'])
                saved = fixture.messages.read_item(done['message_id'], 'conv1')
                self.assertEqual(saved['metadata']['orchestration']['finalization_status'], 'saved')
                self.assertTrue(saved['metadata']['orchestration']['message_saved'])
                child = fixture.retry(plan['run_id']).get_json()['run']
                self.assertNotIn('finalization_status', child)
                self.assertNotIn('message_saved', child)
                self.assertIsNone(child.get('assistant_message_id'))

    def test_ambiguous_publication_rejects_missing_or_different_durable_documents(self):
        for damage in ('no_commit', 'missing_message', 'missing_guard', 'read_failure', 'content', 'citations', 'metadata', 'guard_token', 'guard_owner', 'guard_run', 'guard_digest', 'deleted_run', 'expired_run'):
            with self.subTest(damage=damage), RecoveryFixture() as fixture:
                plan = fixture.plan_attempt()
                namespace = fixture.route.prepare_retry.__globals__

                def damage_commit():
                    guard = fixture.messages.items[('conv1', namespace['_publication_id'](plan['run_id']))]
                    key = ('conv1', guard['published_message_id'])
                    if damage == 'missing_message':
                        del fixture.messages.items[key]
                    elif damage == 'missing_guard':
                        del fixture.messages.items[('conv1', guard['id'])]
                    elif damage == 'read_failure':
                        fixture.messages.fail_reads = True
                    elif damage == 'content':
                        fixture.messages.items[key]['content'] = 'Different saved content'
                    elif damage == 'citations':
                        fixture.messages.items[key]['hybrid_citations'] = [{'document_id': 'different-document'}]
                    elif damage == 'metadata':
                        fixture.messages.items[key]['metadata']['orchestration']['run_id'] = 'other-run'
                    elif damage == 'guard_token':
                        guard['token'] = 'different-worker'
                    elif damage == 'guard_owner':
                        guard['user_id'] = 'other-user'
                    elif damage == 'guard_run':
                        guard['run_id'] = 'other-run'
                    elif damage == 'guard_digest':
                        guard['document_digest'] = 'different-digest'
                    elif damage == 'deleted_run':
                        fixture.runs.items[('conv1', plan['run_id'])]['checkpoints_deleted'] = True
                    elif damage == 'expired_run':
                        fixture.runs.items[('conv1', plan['run_id'])]['execution_lease']['expires_at'] = '2020-01-01T00:00:00Z'
                    raise AzureError('private ambiguous publication')

                if damage == 'no_commit':
                    fixture.messages.before_batch = lambda: setattr(fixture.messages, 'fail_writes', True)
                else:
                    fixture.messages.after_batch = damage_commit
                events = frames(fixture.run_attempt(plan))
                done = [event for event in events if event.get('type') == 'orchestration_done']
                self.assertFalse(any(event.get('message_saved') for event in done))
                stored = fixture.runs.items[('conv1', plan['run_id'])]
                self.assertFalse(stored.get('assistant_message_id'))
                if damage not in ('deleted_run', 'expired_run'):
                    self.assertEqual(done[0]['finalization_status'], 'failed')
                    self.assertFalse(fixture.detail(plan['run_id'])['recovery']['eligible'])
                self.assertNotIn('private ambiguous publication', json.dumps(events))

    def test_terminal_publication_projects_pending_until_release_then_saved_or_failed(self):
        for failure in (False, True):
            with self.subTest(failure=failure), RecoveryFixture() as fixture:
                plan = fixture.plan_attempt()
                pending = []

                def before_publish():
                    pending.append(fixture.detail(plan['run_id']))
                    self.assertEqual(pending[-1]['status'], 'failed')
                    self.assertEqual(pending[-1]['finalization_status'], 'pending')
                    self.assertIsNone(pending[-1]['assistant_message_id'])
                    self.assertEqual(pending[-1]['recovery']['reason_code'], 'execution_live')
                    self.assertFalse(pending[-1]['recovery']['eligible'])
                    if failure:
                        fixture.messages.fail_writes = True

                fixture.messages.before_batch = before_publish
                events = frames(fixture.run_attempt(plan))
                self.assertEqual(len(pending), 1)
                done = next(event for event in events if event.get('type') == 'orchestration_done')
                detail = fixture.detail(plan['run_id'])
                expected = 'failed' if failure else 'saved'
                self.assertEqual(done['finalization_status'], expected)
                self.assertEqual(detail['finalization_status'], expected)
                self.assertEqual(detail['message_saved'], not failure)
                if not failure:
                    message = fixture.messages.read_item(done['message_id'], 'conv1')
                    self.assertEqual(message['metadata']['orchestration']['finalization_status'], 'saved')

    def test_expired_finalization_and_legacy_projection_do_not_claim_missing_messages(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            record = fixture.runs.items[('conv1', plan['run_id'])]
            record.update({'status': 'failed', 'started_at': '2020-01-01T00:00:00Z'})
            legacy = fixture.detail(plan['run_id'])
            self.assertNotIn('finalization_status', legacy)
            self.assertNotIn('message_saved', legacy)
            record.update({
                'finalization_status': 'pending',
                'execution_lease': {'token': 'expired-worker', 'expires_at': '2020-01-01T00:00:00Z'},
            })
            expired = fixture.detail(plan['run_id'])
            self.assertEqual(expired['finalization_status'], 'interrupted')
            self.assertNotIn('message_saved', expired)
            self.assertIsNone(expired.get('assistant_message_id'))

    def test_application_version(self):
        assert_app_version_at_least('0.261.105')

    def test_successful_content_about_errors_is_not_a_runtime_failure(self):
        with RecoveryFixture() as fixture:
            fixture.fail_b = False
            fixture.model.answer_response = SimpleNamespace(
                choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
                    content='The log mentions timeout, cancelled, HTTP 504 and error, but the requested inspection succeeded.',
                ))],
            )
            done = next(event for event in frames(fixture.run_attempt(fixture.plan_attempt())) if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'completed')
            self.assertEqual(done['failures'], [])

    def test_effect_before_checkpoint_failure_requires_confirmation_and_keeps_a(self):
        with RecoveryFixture() as fixture:
            fixture.fail_b = False
            plan = fixture.plan_attempt()
            def fail_commit(step, context, kwargs):
                if step['step_id'] == 'b':
                    fixture.steps.fail_writes = True
            fixture.before_adapter = fail_commit
            done = next(event for event in frames(fixture.run_attempt(plan)) if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'failed')
            self.assertTrue(done['recovery']['requires_confirmation'])
            self.assertTrue(done['recovery']['eligible'])
            fixture.steps.fail_writes = False
            fixture.before_adapter = None
            response = fixture.retry(plan['run_id'], confirm_external_effects=False)
            self.assertEqual(response.get_json()['code'], 'confirmation_required')
            child = fixture.retry(plan['run_id']).get_json()['run']
            fixture.run_attempt(child['plan'])
            self.assertEqual(fixture.calls, ['a', 'b', 'b', 'c'])

    def test_committed_checkpoint_is_reused_when_progress_publication_was_lost(self):
        with RecoveryFixture() as fixture:
            fixture.fail_b = False
            fixture.model.answer_error = RuntimeError('answer unavailable')
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            record = fixture.runs.items[('conv1', plan['run_id'])]
            interrupted = next(step for step in record['execution_steps'] if step['step_id'] == 'b')
            interrupted.update({'status': 'running', 'checkpoint_available': False, 'effects_uncertain': True})
            fixture.steps.items[(plan['run_id'], f"{plan['run_id']}:b")].update(interrupted)
            detail = fixture.detail(plan['run_id'])
            self.assertEqual(detail['recovery']['reused_step_ids'], ['a', 'b', 'c'])
            self.assertFalse(detail['recovery']['requires_confirmation'])
            response = fixture.retry(plan['run_id'], confirm_external_effects=False)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            fixture.model.answer_error = None
            fixture.run_attempt(response.get_json()['run']['plan'])
            self.assertEqual(fixture.calls, ['a', 'b', 'c'])

    def test_total_deadline_does_not_invoke_another_model_to_report_failure(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            clock = [0.0]
            fixture.settings['chat_orchestration_total_timeout_seconds'] = 2
            fixture.settings['chat_orchestration_step_timeout_seconds'] = 10
            fixture.before_adapter = lambda *_args: clock.__setitem__(0, 5.0)
            model_calls = len(fixture.model.calls)
            with patch.dict(fixture.route.execute_plan.__globals__, {'time': SimpleNamespace(monotonic=lambda: clock[0])}):
                events = frames(fixture.run_attempt(plan))
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['failure']['code'], 'run_timeout')
            self.assertEqual(done['status'], 'failed')
            self.assertEqual(len(fixture.model.calls), model_calls)
            self.assertTrue(done['full_content'])

    def test_failed_attempt_is_saved_and_retry_reuses_a_without_new_user_message(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            events = frames(fixture.run_attempt(plan))
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'failed')
            self.assertEqual(done['outcome'], 'partial')
            self.assertEqual(done['failure']['code'], 'step_timeout')
            self.assertTrue(done['message_saved'])
            self.assertEqual(fixture.calls, ['a', 'b'])
            original = fixture.detail(plan['run_id'])
            initial_steps = fixture.client.get(
                f"/api/v2/orchestration/runs/{plan['run_id']}/steps?conversation_id=conv1"
            ).get_json()['steps']
            self.assertEqual(
                {step['step_id']: step['status'] for step in initial_steps},
                {'a': 'completed', 'b': 'failed', 'c': 'skipped', 'answer': 'completed'},
            )
            self.assertTrue(original['recovery']['eligible'])
            self.assertTrue(original['recovery']['requires_confirmation'])
            denied = fixture.retry(plan['run_id'], confirm_external_effects=False)
            self.assertEqual(denied.status_code, 409, denied.get_data(as_text=True))
            self.assertEqual(denied.get_json()['code'], 'confirmation_required')
            response = fixture.retry(plan['run_id'])
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            child = response.get_json()['run']
            self.assertEqual(child['attempt_index'], 2)
            self.assertEqual(child['approval']['mode'], 'manual')
            self.assertEqual(child['turn_id'], original['turn_id'])
            self.assertEqual(fixture.calls, ['a', 'b'])
            fixture.fail_b = False
            events2 = frames(fixture.run_attempt(child['plan']))
            done2 = next(event for event in events2 if event.get('type') == 'orchestration_done')
            self.assertEqual(done2['status'], 'completed', events2)
            self.assertEqual(fixture.calls, ['a', 'b', 'b', 'c'])
            self.assertTrue(any(event.get('reused') for event in events2))
            restored_steps = fixture.client.get(
                f"/api/v2/orchestration/runs/{child['run_id']}/steps?conversation_id=conv1"
            ).get_json()['steps']
            self.assertEqual([step['step_id'] for step in restored_steps], ['a', 'b', 'c', 'answer'])
            self.assertTrue(all(step['status'] == 'completed' for step in restored_steps))
            self.assertTrue(restored_steps[0]['reused'])
            self.assertTrue(restored_steps[0]['checkpoint_available'])
            self.assertEqual(restored_steps[0]['reused_from_run_id'], plan['run_id'])
            self.assertNotIn('checkpoint_chunk', json.dumps(restored_steps))
            self.assertNotIn('input_fingerprint', json.dumps(restored_steps))
            user_messages = [row for row in fixture.messages.items.values() if row.get('id', '').startswith('user_turn_')]
            self.assertLessEqual(len(user_messages), 1)
            self.assertIn('Saved findings a', json.dumps(fixture.model.calls[-1]))

    def test_errors_never_leak_and_synthesis_failure_has_model_independent_reply(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.model.answer_error = RuntimeError('OTHER_SECRET_SENTINEL https://provider.internal/error')
            events = frames(fixture.run_attempt(plan))
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            detail = fixture.detail(plan['run_id'])
            steps = fixture.client.get(f"/api/v2/orchestration/runs/{plan['run_id']}/steps?conversation_id=conv1").get_json()
            visible = json.dumps([events, detail, steps, list(fixture.messages.items.values()), fixture.model.calls])
            self.assertNotIn('SECRET_SENTINEL', visible)
            self.assertEqual(done['failure']['code'], 'step_timeout')
            self.assertIn('model_failed', [failure['code'] for failure in done['failures']])
            self.assertTrue(done['full_content'])
            self.assertTrue(done['message_saved'])
            self.assertNotIn('checkpoint_chunk', json.dumps(steps))
            self.assertNotIn('input_fingerprint', json.dumps(steps))

    def test_retry_is_idempotent_and_old_attempt_cannot_branch(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            first = fixture.retry(plan['run_id'])
            self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
            again = fixture.retry(plan['run_id'])
            self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
            self.assertEqual(first.get_json()['run']['run_id'], again.get_json()['run']['run_id'])
            competing = fixture.retry(plan['run_id'], submission_id='another-tab')
            self.assertEqual(competing.status_code, 409)
            self.assertEqual(competing.get_json()['code'], 'recovery_changed')
            self.assertEqual(len([row for row in fixture.runs.items.values() if row.get('retry_of_run_id')]), 1)
            self.assertEqual(fixture.calls, ['a', 'b'])

    def test_third_attempt_restores_second_attempt_successes_and_regenerates_answer(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            child = fixture.retry(plan['run_id']).get_json()['run']
            fixture.fail_b = False
            fixture.model.answer_error = RuntimeError('private synthesizer failure')
            fixture.run_attempt(child['plan'])
            second = fixture.detail(child['run_id'])
            self.assertEqual(second['recovery']['reused_step_ids'], ['a', 'b', 'c'])
            third_response = fixture.retry(child['run_id'], submission_id='third')
            self.assertEqual(third_response.status_code, 200, third_response.get_data(as_text=True))
            fixture.model.answer_error = None
            third = third_response.get_json()['run']
            events = frames(fixture.run_attempt(third['plan']))
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'completed', events)
            self.assertEqual(fixture.calls, ['a', 'b', 'b', 'c'])
            self.assertEqual(len([event for event in events if event.get('reused')]), 3)
            self.assertNotIn('superseded_by_run_id', fixture.runs.read_item(child['run_id'], 'conv1'))
            self.assertEqual(fixture.detail(plan['run_id'])['recovery']['current_run_id'], third['run_id'])

    def test_two_tabs_racing_publish_only_one_successor(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            competitor = []
            fixture.runs.before_batch = lambda: competitor.append(fixture.retry(plan['run_id'], submission_id='tab-two'))
            response = fixture.retry(plan['run_id'], submission_id='tab-one')
            self.assertEqual(competitor[0].status_code, 200, competitor[0].get_data(as_text=True))
            self.assertEqual(response.status_code, 409)
            self.assertEqual(len([row for row in fixture.runs.items.values() if row.get('retry_of_run_id')]), 1)

    def test_expired_worker_cannot_publish_after_retry_claim(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            recovery = fixture.route.prepare_retry.__globals__
            prepared = []
            def expire_and_retry(step, context, kwargs):
                if step['step_id'] != 'b':
                    return
                fixture.runs.items[('conv1', plan['run_id'])]['execution_lease']['expires_at'] = (
                    recovery['_now']() - timedelta(seconds=2)
                ).isoformat()
                prepared.append(fixture.retry(plan['run_id']))
            fixture.before_adapter = expire_and_retry
            events = frames(fixture.run_attempt(plan))
            self.assertEqual(prepared[0].status_code, 200, prepared[0].get_data(as_text=True))
            self.assertFalse(any(event.get('type') == 'orchestration_done' for event in events))
            self.assertTrue(any(event.get('error') for event in events))
            self.assertFalse(any(
                (row.get('metadata') or {}).get('orchestration', {}).get('run_id') == plan['run_id']
                for row in fixture.messages.items.values()
            ))

    def test_heartbeat_runs_during_blocked_adapter_and_preserves_concurrent_stop(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            recovery = fixture.route.prepare_retry.__globals__
            observed = []
            def block_and_stop(step, context, kwargs):
                if step['step_id'] != 'a':
                    return
                before = fixture.runs.read_item(plan['run_id'], 'conv1')['execution_lease']['heartbeat_at']
                threading.Event().wait(0.06)
                current = fixture.runs.read_item(plan['run_id'], 'conv1')
                observed.append(current['execution_lease']['heartbeat_at'] != before)
                lease = fixture.route.ExecutionLease(current, lambda: True)
                fixture.runs.before_replace = lambda: recovery['request_cancellation'](
                    plan['run_id'], 'user1', 'conv1', lambda: True,
                )
                lease.renew()
                observed.append(lease.cancel_requested())
            fixture.before_adapter = block_and_stop
            with patch.dict(recovery, {'HEARTBEAT_SECONDS': 0.01}):
                events = frames(fixture.run_attempt(plan))
            self.assertEqual(observed, [True, True])
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'cancelled')

    def test_stream_disconnect_does_not_cancel_or_lose_terminal_persistence(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            release = threading.Event()
            fixture.before_adapter = lambda step, *_args: release.wait(2) if step['step_id'] == 'a' else None
            response = fixture.client.post('/api/v2/orchestration/run', json={
                'conversation_id': 'conv1', 'run_id': plan['run_id'],
            }, buffered=False)
            response.close()
            release.set()
            for _ in range(100):
                record = fixture.runs.read_item(plan['run_id'], 'conv1')
                if record.get('assistant_message_id') and not record.get('execution_lease'):
                    break
                threading.Event().wait(0.02)
            self.assertTrue(record.get('assistant_message_id'))
            self.assertNotEqual(record['status'], 'cancelled')
            self.assertFalse(record.get('cancellation_requested_at'))

    def test_message_publication_batch_rejects_a_worker_fenced_after_its_last_read(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            recovery = fixture.route.prepare_retry.__globals__
            children = []
            def fence_before_publish():
                fixture.runs.items[('conv1', plan['run_id'])]['execution_lease']['expires_at'] = (
                    recovery['_now']() - timedelta(seconds=1)
                ).isoformat()
                children.append(fixture.retry(plan['run_id']))
            fixture.messages.before_batch = fence_before_publish
            events = frames(fixture.run_attempt(plan))
            self.assertEqual(children[0].status_code, 200, children[0].get_data(as_text=True))
            self.assertFalse(any(event.get('type') == 'orchestration_done' for event in events))
            self.assertFalse(any(
                (row.get('metadata') or {}).get('orchestration', {}).get('run_id') == plan['run_id']
                for row in fixture.messages.items.values()
            ))

    def test_revoked_agent_or_model_blocks_preparation_without_replaying_success(self):
        for boundary in ('agent', 'model'):
            with self.subTest(boundary=boundary), RecoveryFixture() as fixture:
                plan = fixture.plan_attempt()
                fixture.run_attempt(plan)
                patcher = (
                    patch.object(fixture.route, 'resolve_agent_catalog', return_value=[])
                    if boundary == 'agent' else
                    patch.object(fixture.route, 'resolve_orchestration_model', side_effect=PermissionError('private detail'))
                )
                with patcher:
                    response = fixture.retry(plan['run_id'])
                self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
                self.assertEqual(response.get_json()['code'], 'recovery_unavailable')
                self.assertEqual(fixture.calls, ['a', 'b'])

    def test_deletion_removes_chunks_and_fences_late_checkpoint_and_message_writes(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            recovery = fixture.route.prepare_retry.__globals__
            record = fixture.runs.read_item(plan['run_id'], 'conv1')
            store = recovery['checkpoint_store'](record, lambda: True, token='late-worker')
            recovery['cleanup_conversation_checkpoints'](
                'conv1', 'user1', lambda: True, message_container=fixture.messages,
                conversation_container=fixture.conversations,
            )
            self.assertFalse(any(
                row.get('record_type') in ('checkpoint_chunk', 'checkpoint_manifest')
                for row in fixture.steps.items.values()
            ))
            with self.assertRaises(recovery['CheckpointError']):
                store.initialize()
            self.assertEqual(fixture.client.get(
                f"/api/v2/orchestration/runs/{plan['run_id']}?conversation_id=conv1"
            ).status_code, 404)

    def test_legacy_absent_checkpoints_are_readable_but_never_replayed(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            record = fixture.runs.items[('conv1', plan['run_id'])]
            record.update({'status': 'failed', 'started_at': '2020-01-01T00:00:00Z', 'error': 'PRIVATE_LEGACY_ERROR'})
            detail = fixture.detail(plan['run_id'])
            self.assertEqual(detail['recovery']['reason_code'], 'legacy_no_checkpoints')
            self.assertNotIn('PRIVATE_LEGACY_ERROR', json.dumps(detail))
            self.assertEqual(fixture.calls, [])

    def test_corrupt_chunk_context_change_and_revoked_owner_block_without_replay(self):
        for scenario in ('corrupt', 'context', 'owner'):
            with self.subTest(scenario=scenario), RecoveryFixture() as fixture:
                plan = fixture.plan_attempt()
                fixture.run_attempt(plan)
                if scenario == 'corrupt':
                    row = next(row for row in fixture.steps.items.values() if row.get('record_type') == 'checkpoint_chunk')
                    row['data'] = 'corrupt'
                elif scenario == 'context':
                    fixture.messages.items[('conv1', 'u1')]['content'] = 'Changed prior context'
                else:
                    fixture.conversations.items[('conv1', 'conv1')]['user_id'] = 'other-user'
                record = fixture.runs.read_item(plan['run_id'], 'conv1')
                response = fixture.client.post(f"/api/v2/orchestration/runs/{plan['run_id']}/retry", json={
                    'conversation_id': 'conv1', 'submission_id': 'retry',
                    'expected_version': record['recovery_version'], 'confirm_external_effects': True,
                })
                self.assertIn(response.status_code, (404, 409), response.get_data(as_text=True))
                self.assertEqual(fixture.calls, ['a', 'b'])

    def test_lost_publication_response_returns_the_committed_attempt(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.run_attempt(plan)
            def lose_response():
                raise AzureError('private lost reply')
            fixture.runs.after_batch = lose_response
            response = fixture.retry(plan['run_id'])
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertEqual(response.get_json()['run']['attempt_index'], 2)

    def test_explicit_stop_is_not_a_timeout(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            def stop(step, context, kwargs):
                if step['step_id'] == 'b':
                    response = fixture.client.post(f"/api/v2/orchestration/cancel/{plan['run_id']}", json={'conversation_id': 'conv1'})
                    self.assertEqual(response.status_code, 200)
            fixture.before_adapter = stop
            done = next(event for event in frames(fixture.run_attempt(plan)) if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'cancelled')
            self.assertEqual(done['failure']['code'], 'user_cancelled')
            self.assertTrue(done['message_saved'])

    def test_checkpoint_failure_before_effects_prevents_adapter_execution(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.steps.fail_writes = True
            events = frames(fixture.run_attempt(plan))
            self.assertEqual(fixture.calls, [])
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'failed')
            self.assertFalse(done['recovery']['eligible'])

    def test_unavailable_message_store_reports_not_saved(self):
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            fixture.before_adapter = lambda *_args: setattr(fixture.messages, 'fail_writes', True)
            events = frames(fixture.run_attempt(plan))
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertFalse(done['message_saved'])
            self.assertIsNone(done['message_id'])
            self.assertTrue(any(event.get('error') for event in events))


class CheckpointCodecTests(unittest.TestCase):
    def test_structured_engine_failure_wins_over_an_explanatory_reply(self):
        with RecoveryFixture() as fixture:
            classify = fixture.modules.adapters._tabular_evidence_status
            self.assertEqual(classify('failed', 'The service did not finish.', []), 'failed')
            self.assertEqual(classify('foreground', 'The source mentions errors and cancellation.', []), 'completed')
            failed_analysis = {
                'reply': 'SECRET_PROVIDER_BODY',
                'coverage': {'documents': [{
                    'document_id': 'd', 'total_windows': 2, 'processed_windows': 1, 'failed_windows': 1,
                }]},
            }
            engine = SimpleNamespace(run_document_analysis=lambda *args, **kwargs: failed_analysis)
            with patch.dict('sys.modules', {'functions_document_analysis': engine}):
                result = fixture.modules.adapters.run_document_analyze(
                    {'arguments': {'document_ids': ['d'], 'analysis_prompt': 'Read the document'}},
                    {'invoke_prompt': lambda *_args, **_kwargs: None}, settings={}, user_id='user1',
                    emit=lambda _event: None, cancel_requested=lambda: False,
                )
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('SECRET_PROVIDER_BODY', json.dumps(result))

    def test_exception_types_and_structured_http_status_never_parse_error_prose(self):
        with RecoveryFixture() as fixture:
            normalize = fixture.route.execute_plan.__globals__['failure_from_exception']
            self.assertEqual(normalize(TimeoutError('cancelled by user'))['code'], 'provider_timeout')
            self.assertEqual(normalize(ConnectionError('SECRET'))['code'], 'connection_failed')
            http_error = RuntimeError('SECRET https://private')
            http_error.status_code = 504
            failure = normalize(http_error)
            self.assertEqual(failure['code'], 'provider_http_error')
            self.assertEqual(failure['provider_status'], 504)
            self.assertNotIn('SECRET', json.dumps(failure))

    def test_source_versions_revocation_and_expired_artifacts_block_reuse(self):
        with RecoveryFixture() as fixture:
            namespace = fixture.route.prepare_retry.__globals__
            validate = namespace['_validate_payload_sources']
            error = namespace['CheckpointError']
            context = fixture.route.RunContext(user_id='user1', conversation_id='conv1')
            current = {
                'document_id': 'doc', 'authorization_status': 'authorized',
                'source_version': 'v1', 'source_revision': 'etag1', 'scope': 'personal', 'scope_id': 'user1',
            }
            context.resolve_source_manifest = lambda ids: [deepcopy(current)]
            payload = {'state': {'documents_touched': ['doc'], 'execution_manifest': [deepcopy(current)]}}
            validate(payload, context, {}, 'user1')
            for key, value in (
                ('authorization_status', 'denied'), ('source_version', 'v2'),
                ('source_revision', 'etag2'), ('scope_id', 'another-user'),
            ):
                original = current[key]
                current[key] = value
                with self.assertRaises(error):
                    validate(payload, context, {}, 'user1')
                current[key] = original
            payload['state']['artifacts'] = [{'artifact_message_id': 'expired'}]
            context.validate_checkpoint_artifacts = lambda artifacts: False
            with self.assertRaises(error):
                validate(payload, context, {}, 'user1')

    def test_json_byte_bounds_immutability_integrity_and_authorization(self):
        with RecoveryFixture() as fixture:
            recovery = fixture.route.prepare_retry.__globals__
            checkpoint_type = recovery['CheckpointStore']
            error_type = recovery['CheckpointError']
            namespace = checkpoint_type.commit.__globals__
            authorized = [True]
            store = checkpoint_type(
                fixture.steps, run_id='codec-run', user_id='user1', conversation_id='conv1',
                turn_id='codec-turn', token='codec-token', authorize=lambda: authorized[0],
            )
            store.initialize()
            context = fixture.route.RunContext(run_id='codec-run', user_id='user1', conversation_id='conv1')
            context.notes = ['漢字🙂' * 70000]
            step = {'step_id': 'a'}
            result = fixture.route.execute_plan.__globals__['build_step_result'](notes=context.notes)
            payload = store.commit(step, result, context, input_fingerprint='input', binding='binding')
            self.assertEqual(store.load('a'), payload)
            self.assertGreater(len([row for row in fixture.steps.items.values() if row.get('record_type') == 'checkpoint_chunk']), 1)
            self.assertTrue(all(len(namespace['json_bytes'](row)) < namespace['MAX_DOCUMENT_BYTES'] for row in fixture.steps.items.values()))
            with self.assertRaises(error_type), patch.dict(namespace, {'MAX_CHECKPOINT_BYTES': 100}):
                store.commit({'step_id': 'large'}, result, context, input_fingerprint='input', binding='binding')
            with self.assertRaises(error_type):
                store.commit(step, {**result, 'message': 'different'}, context, input_fingerprint='input', binding='binding')
            bad = next(row for row in fixture.steps.items.values() if row.get('record_type') == 'checkpoint_chunk')
            bad['data'] = 'broken'
            with self.assertRaises(error_type):
                store.load('a')
            authorized[0] = False
            with self.assertRaises(error_type):
                store.load('a')
            for value in (float('nan'), object(), {1: 'non-string key'}):
                with self.assertRaises(error_type):
                    namespace['json_bytes'](value)

    def test_effective_inputs_include_undeclared_earlier_findings(self):
        with RecoveryFixture() as fixture:
            namespace = fixture.route.prepare_retry.__globals__
            context = fixture.route.RunContext(run_id='r', user_id='user1', conversation_id='conv1')
            step = {'step_id': 'action', 'capability_id': 'action_invoke', 'arguments': {}, 'depends_on': []}
            before = namespace['step_input_fingerprint'](step, context, 'binding')
            context.notes.append('An earlier step found different input')
            self.assertNotEqual(before, namespace['step_input_fingerprint'](step, context, 'binding'))


if __name__ == '__main__':
    unittest.main()
