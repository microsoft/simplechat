# test_orchestration_memory_context.py
"""Functional regressions for audience-bound orchestration memory.

Version: 0.261.139
Implemented in: 0.261.104
Single orchestration contract updated in: 0.261.139

Uses the shared memory reader and the Gather / Reason / Render compose adapter seam.
Only storage, membership, embedding and model boundaries are replaced. Planning and
answering may read memory but must never write it.
"""

import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

import pytest
from azure.core.exceptions import AzureError

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.app_stubs import stubbed_config
from test_support.orchestration_harness_execution import decoded_frames, input_binding
from test_support.versioning import assert_app_version_at_least


class OrchestrationMemoryTests(unittest.TestCase):
    def setUp(self):
        with stubbed_config(cognitive_services_scope='https://cognitiveservices.azure.com/.default'):
            sys.modules.pop('functions_orchestration_memory', None)
            sys.modules.pop('functions_orchestration_composition', None)
            self.memory = importlib.import_module('functions_orchestration_memory')
            self.composition = importlib.import_module('functions_orchestration_composition')
        self.conversation = {'id': 'conv1', 'user_id': 'user1'}
        self.settings = {'enable_fact_memory_plugin': True, 'enable_group_workspaces': True}
        self.fact_calls = []
        self.group_membership = Mock(return_value='User')
        self.module_patches = patch.dict(sys.modules, {
            'functions_fact_memory_context': self.fact_memory_module(),
            'functions_group': types.SimpleNamespace(assert_group_role=self.group_membership),
        })
        self.module_patches.start()
        self.addCleanup(self.module_patches.stop)

    def fact_memory_module(self):
        def build_fact_memory_prompt_payload(**kwargs):
            self.fact_calls.append(kwargs)
            scope_id = kwargs['scope_id']
            if scope_id == 'missing-embedding':
                return {
                    'context_messages': [{'role': 'system', 'content': 'Prefer an accessible itinerary.'}],
                    'citations': [{'plugin_name': 'fact_memory', 'id': 'fact-1'}],
                    'instruction_payload': {'context_messages': [
                        {'role': 'system', 'content': 'Prefer accessibility.'},
                    ]},
                    'recall_payload': {'search_mode': 'embedding_unavailable'},
                }
            return {
                'context_messages': [
                    {'role': 'system', 'content': f'Saved memory for {scope_id}: Crescent City.'},
                ],
                'citations': [{'plugin_name': 'fact_memory', 'id': f'fact-{scope_id}'}],
                'instruction_payload': {'context_messages': [
                    {'role': 'system', 'content': 'Prefer an accessible itinerary.'},
                ]},
                'recall_payload': {'search_mode': 'semantic'},
            }
        return types.SimpleNamespace(build_fact_memory_prompt_payload=build_fact_memory_prompt_payload)

    def test_private_planning_memory_is_scoped_and_read_only(self):
        result = self.memory.load_orchestration_memory(
            'user1', self.conversation, 'Which wineries are open?', settings=self.settings,
        )
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['scope'], {'type': 'user', 'id': 'user1'})
        self.assertIn('Crescent City', json.dumps(result['context_messages']))
        self.assertEqual(self.fact_calls[0]['read_only'], True)
        self.assertEqual(self.fact_calls[0]['authorized_user_id'], 'user1')

    def test_group_workspace_reads_only_authorized_group_memory(self):
        result = self.memory.load_orchestration_memory(
            'user1', self.conversation, 'Review group facts.', settings=self.settings,
            seeds={'doc_scope': 'group', 'active_group_ids': ['group1']},
        )
        self.assertEqual(result['scope'], {'type': 'group', 'id': 'group1'})
        self.assertIn('group1', json.dumps(result['context_messages']))
        self.assertEqual(self.fact_calls[0]['scope_type'], 'group')
        self.assertEqual(self.fact_calls[0]['scope_id'], 'group1')

    def test_disabled_memory_performs_no_reads_or_embeddings(self):
        result = self.memory.load_orchestration_memory(
            'user1', self.conversation, 'Any memory?', settings={'enable_fact_memory_plugin': False},
        )
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(result['context_messages'], [])
        self.assertEqual(self.fact_calls, [])
        self.group_membership.assert_not_called()

    def test_shared_source_owner_does_not_load_personal_or_group_memory(self):
        conversation = {
            **self.conversation,
            'conversation_kind': 'collaboration_source',
            'collaboration_conversation_id': 'shared-conversation',
            'chat_type': 'personal_single_user',
            'is_hidden': True,
        }
        result = self.memory.load_orchestration_memory(
            'user1', conversation, 'Any memory?', settings=self.settings,
            seeds={'doc_scope': 'group', 'active_group_ids': ['group1']},
        )
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['context_messages'], [])
        self.assertIn('shared conversations', result['notices'][0])
        self.assertEqual(self.fact_calls, [])
        self.group_membership.assert_not_called()

    def test_audience_change_blocks_saved_plan(self):
        audience = self.memory.validate_memory_audience(self.conversation, 'user1')
        changed = {**self.conversation, 'is_hidden': True, 'collaboration_conversation_id': 'shared'}
        with self.assertRaises(self.memory.OrchestrationMemoryError) as failure:
            self.memory.validate_memory_audience(changed, 'user1', expected=audience)
        self.assertEqual(failure.exception.code, 'memory_audience_changed')

    def test_revoked_group_scope_blocks_run_before_memory_reuse(self):
        self.group_membership.side_effect = PermissionError('revoked')
        with self.assertRaises(self.memory.OrchestrationMemoryError) as failure:
            self.memory.validate_memory_context(
                self.conversation, 'user1', scope={'type': 'group', 'id': 'group1'},
            )
        self.assertEqual(failure.exception.code, 'memory_scope_unavailable')
        self.group_membership.assert_called_with(
            'user1', 'group1', allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )

    def test_memory_storage_failure_is_safe_and_does_not_disclose_provider_details(self):
        def fail(**kwargs):
            raise AzureError('PRIVATE_CONNECTION_STRING')
        sys.modules['functions_fact_memory_context'].build_fact_memory_prompt_payload = fail
        with self.assertRaises(self.memory.OrchestrationMemoryError) as failure:
            self.memory.load_orchestration_memory(
                'user1', self.conversation, 'Any memory?', settings=self.settings,
            )
        self.assertEqual(failure.exception.code, 'memory_context_unavailable')
        self.assertNotIn('PRIVATE_CONNECTION_STRING', str(failure.exception))

    def test_missing_fact_embeddings_are_reported_without_backfill(self):
        result = self.memory.load_orchestration_memory(
            'user1', self.conversation, 'Any memory?', settings=self.settings,
            seeds={'doc_scope': 'group', 'active_group_ids': ['missing-embedding']},
        )
        self.assertEqual(result['status'], 'partial')
        self.assertIn('could not be searched', result['notices'][0])
        self.assertIn('accessible itinerary', json.dumps(result['context_messages']))

    def test_compose_reloads_saved_memory_at_answer_time(self):
        calls = []
        context = types.SimpleNamespace(
            memory_context={'context_messages': [{'role': 'system', 'content': 'OLD MEMORY'}]},
            reload_memory_context=lambda: calls.append('reload') or {
                'context_messages': [{'role': 'system', 'content': 'NEWLY SAVED MEMORY'}],
                'notices': ['Latest user instruction overrides saved memory.'],
            },
        )
        result = self.composition._answer_memory(context)
        self.assertEqual(calls, ['reload'])
        self.assertIn('NEWLY SAVED MEMORY', json.dumps(result))
        self.assertNotIn('OLD MEMORY', json.dumps(result))


# Route/execution parity ports for the single orchestration contract.



def available_memory(text="Saved destination: Crescent City."):
    return {
        "audience": {"kind": "personal", "owner_id": "owner", "collaboration_id": ""},
        "status": "available", "scope_type": "user", "scope": {"type": "user", "id": "owner"},
        "context_messages": [{"role": "system", "content": text}],
        "instruction_messages": [], "citations": [{"plugin_name": "fact_memory", "id": "fact-1"}],
        "notices": [],
    }


def disabled_memory():
    return {
        "audience": {"kind": "personal", "owner_id": "owner", "collaboration_id": ""},
        "status": "disabled", "scope_type": None, "scope": None,
        "context_messages": [], "instruction_messages": [], "citations": [], "notices": [],
    }


def test_editing_refreshes_memory_without_persisting_raw_prompt_context(harness, monkeypatch):
    calls = []

    def load_memory(user_id, conversation, query_text, **kwargs):
        calls.append(query_text)
        return available_memory("NEWLY SAVED MEMORY")

    monkeypatch.setattr(harness.execution, "load_orchestration_memory", load_memory)
    harness.create(replies=["Answer using refreshed memory."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    saved = harness.read()
    assert "NEWLY SAVED MEMORY" not in json.dumps(saved)
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done["status"] == "completed"
    assert len(calls) == 2
    assert "NEWLY SAVED MEMORY" in json.dumps(harness.model_calls[-1]["messages"])
    assert "NEWLY SAVED MEMORY" not in json.dumps(harness.read())


def test_memory_disabled_during_execution_removes_final_context_and_citations(harness, monkeypatch):
    calls = []

    def load_memory(user_id, conversation, query_text, **kwargs):
        calls.append(dict(harness.settings))
        if len(calls) == 1:
            return available_memory("MUST_NOT_REACH_FINAL_ANSWER")
        return disabled_memory()

    monkeypatch.setattr(harness.execution, "load_orchestration_memory", load_memory)
    harness.create(replies=["Final answer without saved memory."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done["status"] == "completed"
    assert len(calls) == 2
    assert "MUST_NOT_REACH_FINAL_ANSWER" not in json.dumps(harness.model_calls[-1]["messages"])
    assert done.get("agent_citations") == []


def test_audience_change_during_synthesis_blocks_publication(harness, monkeypatch):
    monkeypatch.setattr(harness.execution, "load_orchestration_memory", lambda *args, **kwargs: available_memory())
    harness.create(replies=["PRIVATE_MEMORY_ANSWER"], final_response=input_binding("prepare"))
    execution = harness.prepare()
    completion = harness.clients[0].chat.completions.create

    def change_during_answer(**kwargs):
        response = completion(**kwargs)
        conversation = harness.conversations.read_item("conversation-1", "conversation-1")
        conversation["collaboration_conversation_id"] = "now-shared"
        harness.conversations.upsert_item(conversation)
        return response

    harness.clients[0].chat.completions.create = change_during_answer
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done["status"] == "failed"
    assert done["failure"]["code"] in {"context_unavailable", "result_invalid"}
    assert done["message_saved"] is True
    assert "PRIVATE_MEMORY_ANSWER" not in json.dumps(done)


def test_revoked_group_memory_scope_blocks_before_answer(harness, monkeypatch):
    functions_group = __import__("functions_group")
    monkeypatch.setattr(
        functions_group, "assert_group_role",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("revoked")),
    )
    harness.create(
        replies=["Must not be generated."], final_response=input_binding("prepare"),
        memory_scope={"type": "group", "id": "group1"},
    )
    with pytest.raises(harness.execution.HarnessExecutionError) as failure:
        harness.prepare()
    assert failure.value.code == "context_unavailable"
    assert harness.model_calls == []



if __name__ == '__main__':
    assert_app_version_at_least('0.261.139')
    unittest.main()
