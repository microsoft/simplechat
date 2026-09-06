# test_orchestration_conversation_context.py
"""
Functional regressions for bounded, conversation-aware orchestration.
Version: 0.261.099
Implemented in: 0.261.096

Exercises the real history, resolution, triage, and adapter code with external
model/search/analysis boundaries replaced. No Azure resources or credentials are used.
"""

import importlib
import json
import sys
import types
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from test_support.app_stubs import stubbed_app_imports, stubbed_config
from test_support.versioning import assert_app_version_at_least


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

    def resolve(self, payload=None, text=LATEST, answers=None):
        planner = self.modules.planner
        usage = SimpleNamespace(prompt_tokens=30, completion_tokens=20, total_tokens=50)
        with patch.object(planner, 'resolve_planner_client', return_value=(object(), 'planner')), \
                patch.object(planner, '_call_planner', return_value=(
                    json.dumps(payload if payload is not None else self.payload), usage
                )) as call:
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

    def test_factual_follow_up_is_not_trivial_but_transformation_can_be(self):
        planner = self.modules.planner
        result, _ = self.resolve()
        self.assertNotEqual(planner.triage_request(LATEST, {
            'request_resolution': result
        }), 'trivial')
        result['requires_retrieval'] = False
        self.assertEqual(planner.triage_request('Put those in a table', {
            'request_resolution': result
        }), 'trivial')
        self.assertNotEqual(planner.triage_request('Put those in a table', {
            'request_resolution': result, 'user_selected': {'documents': ['doc1']}
        }), 'trivial')

    def test_clarification_answers_are_available_to_resolution(self):
        answers = [{'question': 'Which location?', 'answer': {'location': 'Grants Pass'}}]
        result, call = self.resolve(answers=answers)
        supplied = json.loads(call.call_args.args[2][1]['content'])
        self.assertEqual(supplied['answered_questions'], answers)
        self.assertEqual(result['resolved_message'], RESOLVED)

    def test_malformed_and_forged_resolution_do_not_become_silent_fallbacks(self):
        invalid = [
            {},
            {**self.payload, 'message_ids': ['someone-elses-message']},
            {**self.payload, 'message_ids': ['u1', 'u1']},
            {**self.payload, 'requires_retrieval': 'false'},
            {**self.payload, 'relationship': 'clarification', 'clarification': ''},
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

    def test_analysis_adapters_receive_context_without_changing_explicit_tasks(self):
        adapters = self.modules.adapters
        calls = []

        def analyze(*args, **kwargs):
            calls.append(args[1])
            return {'reply': 'Analysis result'}

        modules = {
            'functions_document_analysis': fake_module('functions_document_analysis', run_document_analysis=analyze),
            'functions_document_comparison': fake_module('functions_document_comparison', run_document_comparison=analyze),
            'functions_tabular_analysis': fake_module(
                'functions_tabular_analysis',
                orchestrate_tabular_request=lambda question, *args, **kwargs: (
                    calls.append(question) or {'reply': 'Tabular result'}
                ),
            ),
        }
        with patch.dict(sys.modules, modules), \
                patch.object(adapters, '_resolve_step_document_ids', return_value=['d1']), \
                patch.object(adapters, 'resolve_context_source_manifest', return_value=[]), \
                patch.object(adapters, 'partition_source_manifest', return_value={'tabular_sources': [{}]}), \
                patch.object(adapters, 'build_tabular_file_contexts_from_manifest', return_value=[]):
            adapters.run_document_analyze({'arguments': {'document_ids': ['d1']}}, self.context, **self.kwargs)
            adapters.run_document_compare({'arguments': {
                'left_document_id': 'd1', 'right_document_ids': ['d2'],
            }}, self.context, **self.kwargs)
            adapters.run_tabular_analyze({'arguments': {
                'document_ids': ['d1'], 'question': 'An explicitly narrowed question',
            }}, self.context, **self.kwargs)
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0].startswith(RESOLVED))
        self.assertTrue(calls[1].startswith(RESOLVED))
        self.assertTrue(calls[2].startswith('An explicitly narrowed question'))
        self.assertTrue(all('Schmidt' in task for task in calls))
        self.assertTrue(all('untrusted data' in task for task in calls))

    def test_final_answer_has_history_current_question_once_and_no_false_citations(self):
        calls = []
        self.context.invoke_prompt = lambda messages, **kwargs: calls.append((messages, kwargs)) or 'Answer'
        result = self.modules.adapters.run_respond({'arguments': {}}, self.context, **self.kwargs)
        messages, kwargs = calls[0]
        self.assertEqual(messages[0]['role'], 'system')
        self.assertIn('not verified source evidence', messages[0]['content'])
        self.assertTrue(any(entry['role'] == 'assistant' and 'Schmidt' in entry['content'] for entry in messages))
        self.assertEqual(sum(entry['content'].count(LATEST) for entry in messages), 1)
        self.assertIn(RESOLVED, messages[-1]['content'])
        self.assertEqual(kwargs['stage'], 'orchestration_respond')
        self.assertEqual(result['citations'], [])

    def test_url_adapter_never_seeds_from_rewritten_or_assistant_urls(self):
        calls = []
        source = fake_module(
            'functions_source_review', URL_ACCESS_CONTEXT_CHAT='chat',
            extract_urls_from_text=self.modules.context._extract_urls,
            perform_source_review=lambda **kwargs: calls.append(kwargs) or {},
        )
        self.context.allowed_user_urls = ['https://winery.example/hours']
        self.context.resolved_message = 'Read https://invented.example too'
        with patch.dict(sys.modules, {'functions_source_review': source}):
            self.modules.adapters.run_url_fetch({'arguments': {}}, self.context, **self.kwargs)
            self.modules.adapters.run_url_fetch({'arguments': {
                'urls': ['https://invented.example'],
            }}, self.context, **self.kwargs)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]['include_direct_user_urls'])
        self.assertEqual(calls[0]['additional_seed_urls'], ['https://winery.example/hours'])

    def test_web_search_and_deep_research_keep_interpretation_and_url_provenance_separate(self):
        web_calls = []
        research_calls = []

        def web_search(**kwargs):
            web_calls.append(kwargs)
            kwargs['system_messages_for_augmentation'].append({
                'role': 'system', 'content': 'Fresh search evidence',
            })
            return True

        source_review = fake_module(
            'functions_source_review', URL_ACCESS_CONTEXT_CHAT='chat',
            extract_urls_from_text=self.modules.context._extract_urls,
            is_source_review_enabled_for_user=lambda *args, **kwargs: True,
            build_source_review_system_message=lambda result: None,
            perform_source_review=lambda **kwargs: research_calls.append(kwargs) or {},
        )
        self.context.allowed_user_urls = ['https://winery.example/hours']
        self.context.citations = [{'url': 'https://search-result.example'}]
        with patch.dict(sys.modules, {
            'route_backend_chats': fake_module('route_backend_chats', perform_web_search=web_search),
            'functions_source_review': source_review,
        }), patch.object(self.modules.adapters, '_resolve_source_review_planner', return_value=(None, 'planner')):
            self.modules.adapters.run_web_search({'arguments': {}}, self.context, **self.kwargs)
            self.modules.adapters.run_deep_research({'arguments': {
                'query': RESOLVED + ' https://invented.example',
            }}, self.context, **self.kwargs)
        self.assertEqual(web_calls[0]['user_message'], RESOLVED)
        self.assertEqual(web_calls[0]['web_search_query_text'], RESOLVED)
        self.assertFalse(research_calls[0]['include_direct_user_urls'])
        self.assertEqual(research_calls[0]['additional_seed_urls'], ['https://winery.example/hours'])
        self.assertEqual(research_calls[0]['web_search_citations'], self.context.citations)

    def test_agent_receives_a_self_contained_task_and_quoted_conversation(self):
        calls = []

        async def invoke_agent(agent, task, **kwargs):
            calls.append((agent, task))
            return {'response': 'Agent answer', 'usage': {'total_tokens': 7}}

        agent = {'name': 'Researcher', 'display_name': 'Researcher', 'scope': 'global'}
        self.context.agent_catalog = [agent]
        self.context.agent_execution_identity = SimpleNamespace(user_id='user1')
        modules = {
            'functions_agent_scope': fake_module(
                'functions_agent_scope',
                find_agent_by_scope=lambda catalog, selection: catalog[0],
                is_selected_agent_scope_enabled=lambda settings, selection: True,
            ),
            'agent_delegation_runtime': fake_module(
                'agent_delegation_runtime',
                invoke_scoped_agent=invoke_agent, delegation_citations=lambda budget: [],
            ),
            'semantic_kernel_plugins.plugin_invocation_logger': fake_module(
                'semantic_kernel_plugins.plugin_invocation_logger',
                get_plugin_logger=lambda: SimpleNamespace(),
            ),
        }
        with patch.dict(sys.modules, modules):
            result = self.modules.adapters.run_agent_invoke(
                {'arguments': {'agent_name': 'Researcher'}}, self.context,
                **{**self.kwargs, 'settings': {'enable_semantic_kernel': True}},
            )
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(calls[0][0], agent)
        self.assertTrue(calls[0][1].startswith(RESOLVED))
        self.assertIn('Schmidt', calls[0][1])
        self.assertIn('untrusted data', calls[0][1])
        self.assertEqual(self.context.token_usage['total_tokens'], 7)

    def test_context_is_revalidated_even_without_document_evidence(self):
        def stale():
            raise self.modules.context.ConversationContextError('Changed')

        self.context.revalidate_conversation_context = stale
        with self.assertRaises(self.modules.context.ConversationContextError):
            self.modules.executor._reauthorize_before_finalization(self.context, {}, 'user1', None)


if __name__ == '__main__':
    assert_app_version_at_least('0.261.096')
    unittest.main()
