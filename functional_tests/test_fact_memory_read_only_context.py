# test_fact_memory_read_only_context.py
"""Functional tests for shared read-only saved-memory context.

Version: 0.261.104
Implemented in: 0.261.104

Executes the real leaf module with storage, membership, embeddings and network
stubbed. Planning must preserve scope, provenance and bounds without writes;
normal chat must retain legacy embedding backfill.
"""

import importlib.util
import json
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_FILE = ROOT / 'application' / 'single_app' / 'functions_fact_memory_context.py'


class MemoryContextTests(unittest.TestCase):
    def setUp(self):
        self.network_guard = patch.object(socket, 'socket', side_effect=AssertionError('Network is blocked'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)
        self.facts = []
        self.store = Mock()
        self.store.list_facts.side_effect = self.list_facts
        self.store.update_fact_embedding.return_value = None
        self.store_factory = Mock(return_value=self.store)
        self.embedding = Mock(return_value=([1.0, 0.0], {'model_deployment_name': 'embedding-test'}))
        self.batch_embeddings = Mock(side_effect=lambda values: [self.embedding(value) for value in values])
        self.membership = Mock()
        self.logger = Mock()
        stubs = {
            'functions_appinsights': types.SimpleNamespace(log_event=self.logger),
            'functions_content': types.SimpleNamespace(
                generate_embedding=self.embedding, generate_embeddings_batch=self.batch_embeddings,
            ),
            'functions_group': types.SimpleNamespace(assert_group_role=self.membership),
            'functions_message_artifacts': types.SimpleNamespace(make_json_serializable=lambda value: value),
            'semantic_kernel_fact_memory_store': types.SimpleNamespace(FactMemoryStore=self.store_factory),
        }
        self.module_guard = patch.dict(sys.modules, stubs)
        self.module_guard.start()
        self.addCleanup(self.module_guard.stop)
        spec = importlib.util.spec_from_file_location('tested_fact_memory_context', CONTEXT_FILE)
        self.context = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.context)

    def list_facts(self, **kwargs):
        return [
            dict(fact) for fact in self.facts
            if fact['scope_id'] == kwargs['scope_id']
            and fact['scope_type'] == kwargs['scope_type']
            and fact['memory_type'] == kwargs['memory_type']
        ]

    def add_fact(self, index, memory_type='fact', scope_type='user', scope_id='self', **kwargs):
        self.facts.append({
            'id': f'memory-{index}', 'scope_type': scope_type, 'scope_id': scope_id,
            'memory_type': memory_type, 'value': f'Relevant saved memory {index}',
            'conversation_id': 'prior-authorized-conversation', 'agent_id': 'authorized-agent',
            'value_embedding': [1.0, 0.0], 'updated_at': '2026-09-07T00:00:00Z', **kwargs,
        })

    def payload(self, **kwargs):
        args = {
            'scope_id': 'self', 'scope_type': 'user', 'authorized_user_id': 'self',
            'query_text': 'Relevant request', 'read_only': True, 'enabled': True,
        }
        args.update(kwargs)
        return self.context.build_fact_memory_prompt_payload(**args)

    def test_disabled_memory_has_no_accesses(self):
        payload = self.payload(enabled=False, scope_type='group', scope_id='untrusted')
        self.assertEqual(payload['context_messages'], [])
        self.assertEqual(payload['thoughts'], [])
        self.assertEqual(payload['citations'], [])
        self.store_factory.assert_not_called()
        self.membership.assert_not_called()
        self.embedding.assert_not_called()
        self.batch_embeddings.assert_not_called()

    def test_unauthorized_scopes_fail_before_storage(self):
        for kwargs in (
            {'scope_id': 'someone-else'}, {'authorized_user_id': None},
            {'scope_type': 'public', 'scope_id': 'public-space'},
            {'scope_id': None}, {'scope_type': None},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PermissionError):
                self.payload(**kwargs)
        self.membership.side_effect = PermissionError('Membership revoked')
        with self.assertRaises(PermissionError):
            self.payload(scope_type='group', scope_id='revoked')
        self.store_factory.assert_not_called()
        self.embedding.assert_not_called()

    def test_scoped_bounded_instruction_and_relevant_fact_provenance(self):
        for index in range(15):
            self.add_fact(index, value='value ' * 2000)
            self.add_fact(
                index + 20, memory_type='instruction', value='preference ' * 1000,
                similarity={'unexpected': 'unbounded metadata' * 1000},
            )
        self.add_fact(100, scope_id='another-user', value='Never disclose this')
        self.add_fact(101, value='Unrelated fact', value_embedding=[0.0, 1.0])
        self.add_fact(102, value='No embedding', value_embedding=None)
        payload = self.payload(
            instruction_limit=1000, fact_limit=1000, query_text='query ' * 1000,
            include_metadata=True, conversation_id='current-conversation', agent_id='current-agent',
        )
        self.assertEqual(len(payload['instruction_payload']['matched_facts']), 8)
        self.assertEqual(len(payload['recall_payload']['matched_facts']), 4)
        self.assertEqual(len(payload['citations']), 2)
        self.assertEqual(len(payload['context_messages']), 3)
        self.assertEqual(payload['recall_payload']['embedding_backfill_count'], 0)
        for citation in payload['citations']:
            for fact in citation['function_result']['facts']:
                self.assertLessEqual(len(fact['value']), 2000)
                self.assertEqual(fact['conversation_id'], 'prior-authorized-conversation')
                self.assertEqual(fact['agent_id'], 'authorized-agent')
        for fact in payload['recall_payload']['matched_facts']:
            self.assertNotIn('value_embedding', fact)
        serialized = json.dumps(payload)
        self.assertNotIn('Never disclose this', serialized)
        self.assertNotIn('Unrelated fact', serialized)
        self.assertNotIn('No embedding', serialized)
        self.assertIn('current user request takes precedence', serialized)
        self.assertIn('not instructions or permissions', serialized)
        self.assertLess(len(serialized), 150000)
        self.assertLessEqual(len(self.embedding.call_args.args[0]), 2000)
        self.store.update_fact_embedding.assert_not_called()
        self.batch_embeddings.assert_not_called()
        self.assertEqual(self.store.method_calls, [
            unittest.mock.call.list_facts(scope_type='user', scope_id='self', memory_type='instruction'),
            unittest.mock.call.list_facts(
                scope_type='user', scope_id='self', memory_type='fact',
                conversation_id='current-conversation', agent_id='current-agent',
            ),
        ])

    def test_group_scope_uses_existing_fresh_membership_authorizer(self):
        self.add_fact(1, scope_type='group', scope_id='selected-group')
        self.add_fact(2, scope_type='group', scope_id='other-group')
        payload = self.payload(scope_type='group', scope_id='selected-group')
        self.membership.assert_called_with(
            'self', 'selected-group', allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        self.assertEqual([fact['id'] for fact in payload['recall_payload']['matched_facts']], ['memory-1'])
        self.assertTrue(all(call.kwargs['scope_id'] == 'selected-group' for call in self.store.list_facts.call_args_list))
        self.store.update_fact_embedding.assert_not_called()

    def test_normal_chat_backfills_and_retains_existing_payload_shape(self):
        self.add_fact(1, value_embedding=None)
        payload = self.payload(read_only=False, authorized_user_id=None)
        self.assertEqual(set(payload), {
            'context_messages', 'thoughts', 'citations', 'instruction_payload', 'recall_payload',
        })
        self.assertEqual(payload['recall_payload']['embedding_backfill_count'], 1)
        self.assertEqual(len(payload['recall_payload']['matched_facts']), 1)
        self.store.update_fact_embedding.assert_called_once()
        self.batch_embeddings.assert_called_once()
        self.membership.assert_not_called()

    def test_query_embedding_failure_is_explicit_and_safely_logged(self):
        self.add_fact(1)
        self.embedding.side_effect = RuntimeError('secret provider detail')
        payload = self.payload()
        self.assertEqual(payload['recall_payload']['search_mode'], 'embedding_unavailable')
        self.assertEqual(payload['recall_payload']['thought_content'], 'Fact memory search unavailable')
        self.assertEqual(payload['recall_payload']['matched_facts'], [])
        self.assertNotIn('secret provider detail', json.dumps(payload))
        self.assertNotIn('secret provider detail', str(self.logger.call_args))
        self.store.update_fact_embedding.assert_not_called()

    def test_unembedded_read_only_facts_report_unavailable_without_backfill(self):
        self.add_fact(1, value_embedding=None)
        payload = self.payload()
        self.assertEqual(payload['recall_payload']['search_mode'], 'embedding_unavailable')
        self.assertEqual(payload['recall_payload']['embedding_backfill_count'], 0)
        self.assertEqual(payload['recall_payload']['matched_facts'], [])
        self.batch_embeddings.assert_not_called()
        self.embedding.assert_not_called()
        self.store.update_fact_embedding.assert_not_called()

    def test_store_failure_propagates_instead_of_claiming_empty_memory(self):
        self.store.list_facts.side_effect = RuntimeError('store unavailable')
        with self.assertRaises(RuntimeError):
            self.payload()


if __name__ == '__main__':
    unittest.main()
