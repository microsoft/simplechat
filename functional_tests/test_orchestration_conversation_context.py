# test_orchestration_conversation_context.py
"""
Functional regressions for bounded, conversation-aware orchestration.
Version: 0.261.139
Implemented in: 0.261.096
Resolver response compatibility and bounded recovery: 0.261.103
Single orchestration contract updated in: 0.261.139

Exercises the real history, resolution, planner prompt, and selected adapter code with external
model/search boundaries replaced. No Azure resources or credentials are used.
"""

import importlib
import json
import sys
import types
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from httpx import Request, Response
from openai import AuthenticationError, BadRequestError, RateLimitError

from test_support.app_stubs import stubbed_app_imports, stubbed_config
from test_support.versioning import assert_app_version_at_least
from test_support.orchestration_research import document_action_policy_module


LATEST = 'Which are open on Wednesdays?'
RESOLVED = (
    'Which of the wineries discussed near Grants Pass, Oregon, are open on Wednesdays '
    'for our Medford to Crescent City trip after our 1 PM arrival?'
)


def message(message_id, role, content, minute=0, **extra):
    return {
        'id': message_id,
        'conversation_id': 'conv1',
        'role': role,
        'content': content,
        'timestamp': f'2026-09-01T12:{minute:02d}:00+00:00',
        **extra,
    }


def winery_history():
    return [
        message('u1', 'user', 'Find wineries open Wednesday on our Medford to Crescent City trip. '
                'We arrive around 1 PM.', 1),
        message('a1', 'assistant', 'Here are wineries around Medford.', 2),
        message('u2', 'user', 'How about wineries near Grants Pass?', 3),
        message('a2', 'assistant', 'Troon Vineyard, Schmidt Family Vineyards, and Wooldridge Creek.', 4),
    ]


def fake_module(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


def load_modules():
    # These tests need actual policy behavior, not the document engine's Azure bootstrap.
    policy = patch.dict(sys.modules, {'functions_document_actions': document_action_policy_module()})
    policy.start()
    unittest.addModuleCleanup(policy.stop)
    with stubbed_config(cognitive_services_scope='https://cognitiveservices.azure.com/.default'):
        return SimpleNamespace(**{
            name: importlib.import_module(f'functions_orchestration_{name}')
            for name in ('context', 'planner', 'adapters', 'executor')
        })


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()
        cls.context = cls.modules.context

    def test_full_short_turns_and_recent_order(self):
        history = winery_history()
        history[-1]['content'] = 'Names and descriptions. ' * 30 + 'Wooldridge Creek Winery.'
        snapshot = self.context.build_conversation_snapshot(list(reversed(history)))
        self.assertEqual([item['id'] for item in snapshot['messages']], ['u1', 'a1', 'u2', 'a2'])
        self.assertEqual(snapshot['messages'][-1]['content'], history[-1]['content'])
        self.assertFalse(snapshot['truncated'])

    def test_masks_hidden_records_and_inactive_attempts_are_excluded(self):
        history = [
            message('masked', 'user', 'SECRET', metadata={'masked': True}),
            message('inactive', 'assistant', 'Obsolete', metadata={
                'thread_info': {'active_thread': False}
            }),
            message('artifact', 'assistant', 'Hidden', metadata={'is_generated_chat_artifact': True}),
            message('tool', 'tool', 'Tool payload'),
            message('system', 'system', 'A stored system instruction'),
            message('partial', 'user', 'Winery SECRET open Wednesday', metadata={
                'masked_ranges': [{'start': 7, 'end': 13}]
            }),
        ]
        snapshot = self.context.build_conversation_snapshot(history)
        self.assertEqual([entry['id'] for entry in snapshot['messages']], ['partial'])
        self.assertNotIn('SECRET', json.dumps(snapshot))

    def test_text_blocks_only_and_original_turn_is_not_history(self):
        history = [
            message('blocks', 'user', [
                {'type': 'text', 'text': 'Wineries near Grants Pass'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,SECRET'}},
            ], 1),
            message('current', 'user', LATEST, 2, metadata={
                'orchestration': {'turn_id': 'turn1'}
            }),
        ]
        snapshot = self.context.build_conversation_snapshot(history, turn_id='turn1')
        self.assertEqual([entry['id'] for entry in snapshot['messages']], ['blocks'])
        self.assertNotIn('base64', json.dumps(snapshot))
        self.assertNotIn(LATEST, json.dumps(snapshot))

    def test_mixed_legacy_and_threaded_messages_stay_chronological(self):
        history = winery_history()
        history[0]['metadata'] = {'thread_info': {'thread_id': 'thread1', 'active_thread': True}}
        snapshot = self.context.build_conversation_snapshot(history)
        self.assertEqual(snapshot['messages'][0]['id'], 'u1')
        self.assertEqual(snapshot['messages'][-1]['id'], 'a2')

    def test_count_limit_zero_limit_and_ledger_are_independent(self):
        history = winery_history()
        snapshot = self.context.build_conversation_snapshot(history, {
            'conversation_history_limit': 2,
            'chat_orchestration_ledger_max_runs': 0,
        })
        self.assertEqual(len(snapshot['messages']), 2)
        self.assertTrue(snapshot['truncated'])
        empty = self.context.build_conversation_snapshot(history, {'conversation_history_limit': 0})
        self.assertEqual(empty['messages'], [])
        self.assertEqual(self.context.history_message_limit({'conversation_history_limit': 3}), 4)
        self.assertEqual(self.context.history_message_limit({'conversation_history_limit': float('inf')}), 6)

    def test_unicode_byte_budget_and_oversized_turn_keep_ends(self):
        original = 'START ' + '\u65c5\u884c' * 20000 + ' END Wednesday after 1 PM'
        raw = message('large', 'user', original)
        snapshot = self.context.build_conversation_snapshot([raw])
        self.assertLessEqual(self.context.conversation_snapshot_size(snapshot), self.context.HISTORY_MAX_BYTES)
        self.assertTrue(snapshot['truncated'])
        self.assertTrue(snapshot['messages'][0]['content'].startswith('START'))
        self.assertTrue(snapshot['messages'][0]['content'].endswith('END Wednesday after 1 PM'))
        self.assertEqual(
            snapshot['messages'][0]['fingerprint'],
            self.context.normalize_history_message(raw)['fingerprint'],
        )
        self.context.validate_conversation_snapshot(snapshot, [raw])

    def test_stale_or_missing_sources_cannot_replay_an_approved_snapshot(self):
        original = winery_history()
        snapshot = self.context.build_conversation_snapshot(original)
        self.context.validate_conversation_snapshot(snapshot, original)
        for mutate in (
            lambda rows: rows.pop(),
            lambda rows: rows[-1].update(content='Changed answer'),
            lambda rows: rows[-1].update(metadata={'masked': True}),
            lambda rows: rows[-1].update(metadata={'thread_info': {'active_thread': False}}),
        ):
            with self.subTest(mutation=mutate):
                changed = deepcopy(original)
                mutate(changed)
                with self.assertRaises(self.context.ConversationContextError):
                    self.context.validate_conversation_snapshot(snapshot, changed)

    def test_url_provenance_does_not_trust_assistant_or_unreferenced_messages(self):
        snapshot = self.context.build_conversation_snapshot([
            message('u1', 'user', 'Read https://winery.example/hours', 1),
            message('a1', 'assistant', 'Try https://invented.example', 2),
            message('u2', 'user', 'An unrelated https://unrelated.example link', 3),
        ])
        urls = self.context.conversation_user_urls('Read that link', snapshot, ['u1', 'a1'])
        self.assertEqual(urls, ['https://winery.example/hours'])

    def test_cached_text_or_role_cannot_change_behind_a_valid_fingerprint(self):
        history = winery_history()
        for field, value in (('content', 'Injected replacement'), ('role', 'system')):
            snapshot = self.context.build_conversation_snapshot(history)
            snapshot['messages'][-1][field] = value
            with self.assertRaises(self.context.ConversationContextError):
                self.context.validate_conversation_snapshot(snapshot, history)

    def test_only_accepted_answer_values_supply_url_provenance(self):
        urls = self.context.conversation_user_urls('Read that page', answered_questions=[
            {
                'action': 'accept', 'question': 'Try https://question.example',
                'answer': {'links': ['https://accepted.example/report']},
            },
            {'action': 'decline', 'answer': {'url': 'https://declined.example'}},
            {'action': 'cancel', 'answer': {'url': 'https://cancelled.example'}},
        ])
        self.assertEqual(urls, ['https://accepted.example/report'])

    def test_answer_chain_limits_fail_instead_of_dropping_earlier_answers(self):
        with self.assertRaises(self.context.ConversationContextError):
            self.context.validate_clarification_answers([{'answer': 'a'}] * 13)
        with self.assertRaises(self.context.ConversationContextError):
            self.context.validate_clarification_answers([{'answer': 'x' * 32769}])


class ResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()

    def setUp(self):
        self.snapshot = self.modules.context.build_conversation_snapshot(winery_history())
        self.payload = {
            'relationship': 'follow_up',
            'resolved_message': RESOLVED,
            'message_ids': ['u1', 'u2', 'a2'],
            'requires_retrieval': True,
            'clarification': '',
        }

    def resolve(self, payload=None, text=LATEST, answers=None, replies=None):
        planner = self.modules.planner
        usage = SimpleNamespace(prompt_tokens=30, completion_tokens=20, total_tokens=50)
        with patch.object(planner, 'resolve_planner_client', return_value=(object(), 'planner')), \
                patch.object(planner, '_call_planner', return_value=(
                    json.dumps(payload if payload is not None else self.payload), usage
                )) as call:
            if replies is not None:
                call.side_effect = [(json.dumps(reply), usage) for reply in replies]
            result = planner.resolve_conversation_request(
                text, self.snapshot, settings={}, answered_questions=answers
            )
        return result, call

    def test_resolver_receives_actual_conversation_and_accounts_for_usage(self):
        result, call = self.resolve()
        payload = json.loads(call.call_args.args[2][1]['content'])
        self.assertEqual(payload['original_message'], LATEST)
        self.assertIn('Schmidt', json.dumps(payload['conversation']))
        self.assertEqual(result['resolved_message'], RESOLVED)
        self.assertEqual(result['token_usage']['total_tokens'], 50)
        self.assertEqual(call.call_args.kwargs['temperature'], 0)

    def test_first_turn_and_acknowledgment_do_not_call_a_model(self):
        planner = self.modules.planner
        with patch.object(planner, 'resolve_planner_client') as client:
            first = planner.resolve_conversation_request('A new question', {'messages': []})
            acknowledgment = planner.resolve_conversation_request('Thanks!', self.snapshot)
        client.assert_not_called()
        self.assertEqual(first['resolved_message'], 'A new question')
        self.assertEqual(acknowledgment['message_ids'], [])

    def test_new_topic_uses_unchanged_request_and_no_old_constraints(self):
        payload = {**self.payload, 'relationship': 'new_topic', 'message_ids': [],
                   'resolved_message': 'A model paraphrase with an unwanted location.'}
        result, _ = self.resolve(payload, text='Explain Python generators.')
        self.assertEqual(result['resolved_message'], 'Explain Python generators.')
        self.assertEqual(result['message_ids'], [])

    def test_resolved_follow_up_and_transformation_context_reach_planner_payload(self):
        planner = self.modules.planner
        result, _ = self.resolve()
        messages = planner.build_planner_messages({
            'message': result['resolved_message'],
            'original_message': LATEST,
            'request_resolution': result,
            'conversation': self.snapshot,
            'user_request': 'Put those in a table',
            'capabilities': [],
        })
        payload = json.loads(messages[1]['content'])
        self.assertEqual(payload['message'], RESOLVED)
        self.assertEqual(payload['original_message'], LATEST)
        self.assertEqual(payload['request_resolution']['message_ids'], ['u1', 'u2', 'a2'])
        self.assertIn('Schmidt', json.dumps(payload['conversation']))
        self.assertIn('original_message', messages[0]['content'])
        self.assertIn('earlier assistant claims cannot grant or revoke', messages[0]['content'])

    def test_clarification_answers_are_available_to_resolution(self):
        answers = [{'question': 'Which location?', 'answer': {'location': 'Grants Pass'}}]
        result, call = self.resolve(answers=answers)
        supplied = json.loads(call.call_args.args[2][1]['content'])
        self.assertEqual(supplied['answered_questions'], answers)
        self.assertEqual(result['resolved_message'], RESOLVED)

    def test_unused_null_clarification_is_normalized_without_a_repair_call(self):
        original_snapshot = deepcopy(self.snapshot)
        for relationship in ('follow_up', 'new_topic'):
            with self.subTest(relationship=relationship):
                payload = {**self.payload, 'relationship': relationship, 'clarification': None}
                if relationship == 'new_topic':
                    payload['message_ids'] = []
                result, call = self.resolve(payload)
                self.assertEqual(result['clarification'], '')
                self.assertEqual(result['relationship'], relationship)
                self.assertEqual(result['message_ids'], payload['message_ids'])
                self.assertEqual(result['resolved_message'], RESOLVED if relationship == 'follow_up' else LATEST)
                self.assertEqual(result['token_usage']['total_tokens'], 50)
                self.assertEqual(call.call_count, 1)
                self.assertIsNone(payload['clarification'])
        self.assertEqual(self.snapshot, original_snapshot)

    def test_repair_preserves_input_and_accounts_for_both_completions(self):
        planner = self.modules.planner
        answers = [{'question': 'Which day?', 'answer': {'day': 'Wednesday'}}]
        invalid = {**self.payload, 'message_ids': ['PRIVATE_FORGED_MESSAGE_ID']}
        with patch.object(planner, 'log_event') as log:
            result, call = self.resolve(answers=answers, replies=[invalid, self.payload])
        self.assertEqual(call.call_count, 2)
        original_messages = call.call_args_list[0].args[2]
        repaired_messages = call.call_args_list[1].args[2]
        self.assertEqual(repaired_messages[:2], original_messages)
        original_payload = json.loads(repaired_messages[1]['content'])
        self.assertEqual(original_payload['answered_questions'], answers)
        self.assertEqual(original_payload['original_message'], LATEST)
        self.assertIn('Schmidt', json.dumps(original_payload['conversation']))
        self.assertIn('unknown_message_ids', repaired_messages[-1]['content'])
        self.assertNotIn('PRIVATE_FORGED_MESSAGE_ID', json.dumps(repaired_messages))
        self.assertNotIn('PRIVATE_FORGED_MESSAGE_ID', repr(log.call_args_list))
        self.assertEqual(result['message_ids'], self.payload['message_ids'])
        self.assertEqual(result['token_usage'], {
            'prompt_tokens': 60, 'completion_tokens': 40, 'total_tokens': 100,
        })

    def test_unparseable_output_can_be_repaired_without_replaying_it(self):
        result, call = self.resolve(replies=['PRIVATE_INVALID_OUTPUT', self.payload])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result['resolved_message'], RESOLVED)
        self.assertIn('invalid_json', call.call_args.args[2][-1]['content'])
        self.assertNotIn('PRIVATE_INVALID_OUTPUT', json.dumps(call.call_args.args[2]))

    def test_persistent_invalid_output_has_an_exact_attempt_limit_and_safe_reason(self):
        planner = self.modules.planner
        invalid = {**self.payload, 'resolved_message': 'PRIVATE_MODEL_TEXT', 'requires_retrieval': 'false'}
        with patch.object(planner, 'resolve_planner_client', return_value=(object(), 'planner')), \
                patch.object(planner, '_call_planner', return_value=(json.dumps(invalid), None)) as call, \
                patch.object(planner, 'log_event') as log:
            with self.assertRaises(planner.ConversationResolutionError) as failure:
                planner.resolve_conversation_request(LATEST, self.snapshot)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(failure.exception.attempts, 2)
        self.assertEqual(failure.exception.reason, 'invalid_retrieval_flag')
        self.assertNotIn('PRIVATE_MODEL_TEXT', str(failure.exception))
        self.assertNotIn('PRIVATE_MODEL_TEXT', repr(log.call_args_list))

    def model_response(self, *, finish_reason='stop', refusal=None, content=None):
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    content=json.dumps(self.payload) if content is None else content,
                    refusal=refusal,
                ),
            )],
            usage=SimpleNamespace(prompt_tokens=30, completion_tokens=20, total_tokens=50),
        )

    def test_refused_incomplete_and_absent_completions_are_not_repaired(self):
        planner = self.modules.planner
        cases = [
            (self.model_response(finish_reason='content_filter'), 'model_refusal'),
            (self.model_response(refusal='PRIVATE_REFUSAL'), 'model_refusal'),
            (self.model_response(finish_reason='length'), 'incomplete_completion'),
            (self.model_response(content=''), 'empty_completion'),
            (SimpleNamespace(choices=[]), 'empty_completion'),
        ]
        for response, reason in cases:
            with self.subTest(reason=reason):
                client = Mock()
                client.chat.completions.create.return_value = response
                with patch.object(planner, 'resolve_planner_client', return_value=(client, 'planner')), \
                        patch.object(planner, 'log_event') as log:
                    with self.assertRaises(planner.ConversationResolutionError) as failure:
                        planner.resolve_conversation_request(LATEST, self.snapshot)
                self.assertEqual(client.chat.completions.create.call_count, 1)
                self.assertEqual(failure.exception.attempts, 1)
                self.assertEqual(failure.exception.reason, reason)
                self.assertNotIn('PRIVATE_REFUSAL', repr(log.call_args_list))

    def test_provider_failures_are_not_retried_as_json_format_or_schema_failures(self):
        planner = self.modules.planner
        for error_type, status in (
            (AuthenticationError, 401), (RateLimitError, 429), (BadRequestError, 400),
        ):
            with self.subTest(status=status):
                client = Mock()
                response = Response(status, request=Request('POST', 'https://model.example.test/completions'))
                client.chat.completions.create.side_effect = error_type(
                    'PRIVATE_PROVIDER_DETAIL', response=response,
                    body={'error': {'code': 'content_filter', 'message': 'PRIVATE_PROVIDER_DETAIL'}},
                )
                with patch.object(planner, 'resolve_planner_client', return_value=(client, 'planner')), \
                        patch.object(planner, 'log_event') as log:
                    with self.assertRaises(planner.ConversationResolutionError) as failure:
                        planner.resolve_conversation_request(LATEST, self.snapshot)
                self.assertEqual(client.chat.completions.create.call_count, 1)
                self.assertEqual(failure.exception.reason, 'model_request_failed')
                self.assertNotIn('PRIVATE_PROVIDER_DETAIL', repr(log.call_args_list))
                self.assertNotIn('PRIVATE_PROVIDER_DETAIL', str(failure.exception))

    def test_unsupported_json_format_keeps_the_compatible_fallback(self):
        planner = self.modules.planner
        response = Response(400, request=Request('POST', 'https://model.example.test/completions'))
        error = BadRequestError('Unsupported format', response=response, body={'error': {
            'message': "'response_format' of type 'json_object' is not supported with this model.",
            'param': None, 'code': None,
        }})
        client = Mock()
        client.chat.completions.create.side_effect = [error, self.model_response()]
        with patch.object(planner, 'resolve_planner_client', return_value=(client, 'planner')):
            result = planner.resolve_conversation_request(LATEST, self.snapshot)
        calls = client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn('response_format', calls[0].kwargs)
        self.assertNotIn('response_format', calls[1].kwargs)
        self.assertEqual(result['message_ids'], self.payload['message_ids'])
        self.assertEqual(result['token_usage']['total_tokens'], 50)

    def test_malformed_and_forged_resolution_do_not_become_silent_fallbacks(self):
        invalid = [
            {},
            {**self.payload, 'message_ids': ['someone-elses-message']},
            {**self.payload, 'message_ids': ['u1', 'u1']},
            {**self.payload, 'requires_retrieval': 'false'},
            {**self.payload, 'relationship': 'clarification', 'clarification': ''},
            {**self.payload, 'relationship': 'clarification', 'clarification': None},
            {**self.payload, 'clarification': False},
            {**self.payload, 'message_ids': []},
            {**self.payload, 'message_ids': None},
            {**self.payload, 'message_ids': [{}]},
            {**self.payload, 'resolved_message': None},
            {**self.payload, 'relationship': 'new_topic'},
            {**self.payload, 'resolved_message': 'x' * 6001},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(self.modules.planner.ConversationResolutionError):
                    self.resolve(payload)


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()

    def setUp(self):
        self.snapshot = self.modules.context.build_conversation_snapshot(winery_history())
        self.context = self.modules.executor.RunContext(
            user_id='user1', conversation_id='conv1', user_message=LATEST,
            resolved_message=RESOLVED, conversation_context=self.snapshot,
            context_message_ids=['u1', 'u2', 'a2'], invoke_prompt=lambda *args, **kwargs: 'Answer',
        )
        self.kwargs = {'settings': {}, 'user_id': 'user1', 'emit': None, 'cancel_requested': None}

    def test_document_search_fallback_uses_the_resolved_request(self):
        calls = []
        search = fake_module('functions_search', hybrid_search=lambda query, *args, **kwargs: (
            calls.append(query) or []
        ))
        with patch.dict(sys.modules, {'functions_search': search}):
            result = self.modules.adapters.run_document_search({'arguments': {}}, self.context, **self.kwargs)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(calls, [RESOLVED])

    def test_url_provenance_is_captured_for_external_gatherers(self):
        self.context.allowed_user_urls = ['https://winery.example/hours']
        self.context.resolved_message = 'Read https://invented.example too'
        self.assertEqual(self.context.allowed_user_urls, ['https://winery.example/hours'])
        self.assertNotIn('https://invented.example', self.context.allowed_user_urls)


if __name__ == '__main__':
    assert_app_version_at_least('0.261.139')
    unittest.main()
