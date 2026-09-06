# test_orchestration_elicitation_context.py
"""
Behavioral coverage for persisted inline clarification and execution context.
Version: 0.261.096
Implemented in: 0.261.096

Drives the actual Flask plan/answer/run handlers, planner normalization, Cosmos state
helpers, source manifest, document-context resolver, executor, and adapters. Only external
storage/model/authentication services are replaced. No Azure credentials or files needed.
"""

import ast
import importlib
import json
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import werkzeug
from azure.cosmos import exceptions
from flask import Blueprint, Flask, request

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.app_stubs import APP_ROOT, stubbed_config  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


class MemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}
        self.sequence = 0
        self.queries = []
        self.fail_next_create = False

    def _write(self, body):
        self.sequence += 1
        document = deepcopy(body)
        document['_etag'] = str(self.sequence)
        self.items[(document[self.partition_field], document['id'])] = document
        return deepcopy(document)

    def read_item(self, item, partition_key):
        document = self.items.get((partition_key, item))
        if document is None:
            raise exceptions.CosmosResourceNotFoundError(status_code=404)
        return deepcopy(document)

    def create_item(self, body):
        if self.fail_next_create:
            self.fail_next_create = False
            raise RuntimeError('provider failure: must never reach a browser')
        if (body[self.partition_field], body['id']) in self.items:
            raise exceptions.CosmosResourceExistsError(status_code=409)
        return self._write(body)

    def upsert_item(self, body):
        return self._write(body)

    def replace_item(self, item, body, etag, match_condition):
        current = self.read_item(item, body[self.partition_field])
        if current['_etag'] != etag:
            raise exceptions.CosmosHttpResponseError(status_code=412)
        if not match_condition:
            raise AssertionError('An unconditional pending-question write is unsafe.')
        return self._write(body)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        self.queries.append(query)
        values = {item['name']: item['value'] for item in parameters or []}
        items = [
            deepcopy(document) for (partition, _), document in self.items.items()
            if partition_key is None or partition == partition_key
        ]
        for parameter, field in (('@user_id', 'user_id'), ('@document_id', 'id'), ('@run_id', 'id')):
            if parameter in values:
                items = [item for item in items if item.get(field) == values[parameter]]
        if 'record_type' in query:
            items = [item for item in items if item.get('record_type') in (None, 'orchestration_run')]
        if 'MAX(c.turn_index)' in query:
            return [max((item.get('turn_index', 0) for item in items), default=None)]
        if 'ORDER BY c.turn_index DESC' in query:
            items.sort(key=lambda item: item.get('turn_index', 0), reverse=True)
        return items


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


@contextmanager
def installed_modules(stubs):
    names = set(stubs) | {
        'route_backend_orchestration', 'functions_search_service',
        'functions_orchestration_context', 'functions_orchestration_schema',
        'functions_orchestration_registry', 'functions_orchestration_runs',
        'functions_orchestration_executor', 'functions_orchestration_adapters',
        'functions_orchestration_planner', 'functions_orchestration_events',
    }
    originals = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    sys.modules.update(stubs)
    try:
        yield
    finally:
        # Restore only the application seams; removing newly imported native extensions
        # from sys.modules would try to initialize them twice on the next test.
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def reference(document_id, kind='document', scope_kind='personal', scope_id=None):
    return {
        'kind': kind, 'id': document_id, 'label': 'untrusted browser label',
        'scope': {'kind': scope_kind, 'id': scope_id, 'name': 'untrusted workspace name'},
    }


def question(multiple=True, generic=False):
    fields = {
        'files': {
            'type': 'array', 'items': {'type': 'string'}, 'title': 'Choose source files',
        } if multiple else {'type': 'string', 'title': 'Choose a source file'},
    }
    if generic:
        fields.update({
            'style': {'type': 'string', 'enum': ['brief', 'detailed']},
            'sections': {'type': 'array', 'items': {'type': 'string', 'enum': ['risks', 'actions']}},
            'approved': {'type': 'boolean'},
            'count': {'type': 'integer'},
        })
    return {
        'kind': 'elicitation', 'message': 'Which sources and preferences should I use?',
        'requested_schema': {'type': 'object', 'properties': fields, 'required': list(fields)},
        'ui_hints': {
            'pages': [['files']],
            'fields': {'files': {'input': 'files', 'candidate_ids': ['suggested', 'invented-filename.pdf']}},
        },
    }


def planned(document_ids=None, capability='document_analyze'):
    steps = []
    if document_ids:
        steps.append({
            'step_id': 'gather', 'capability_id': capability,
            'title': 'Read the selected sources',
            'arguments': {
                'document_ids': document_ids,
                'analysis_prompt' if capability == 'document_analyze' else 'query': 'Read the sources',
            },
            'depends_on': [],
        })
    steps.append({
        'step_id': 'answer', 'capability_id': 'respond', 'title': 'Answer',
        'arguments': {'instruction': 'Give the answer.'},
        'depends_on': ['gather'] if document_ids else [],
    })
    return {'kind': 'plan', 'intent': {'summary': 'Review the request'}, 'steps': steps}


def preference_question():
    return {
        'kind': 'elicitation', 'message': 'Choose a response style.',
        'requested_schema': {
            'properties': {'style': {'type': 'string', 'enum': ['brief', 'detailed']}},
            'required': ['style'],
        },
    }


def search_plan(document_ids=None):
    plan = planned(document_ids or ['own'], capability='document_search')
    if document_ids is None:
        plan['steps'][0]['arguments'].pop('document_ids')
    return plan


def frames(response):
    return [
        json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
        if line.startswith('data: ')
    ]


def event_document(response, event_type):
    events = frames(response)
    match = next((item for item in events if item.get('type') == event_type), None)
    if not match:
        raise AssertionError(f'Expected {event_type}: {response.status_code}, {events}')
    return match['elicitation' if event_type == 'orchestration_elicitation' else 'plan']


class ElicitationContextTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Flask 2.x's test client reads a version attribute removed by Werkzeug 3.x.
        self.stack.enter_context(patch.object(werkzeug, '__version__', version('werkzeug'), create=True))
        self.conversations = MemoryContainer('id')
        self.messages = MemoryContainer('conversation_id')
        self.runs = MemoryContainer('conversation_id')
        self.steps = MemoryContainer('run_id')
        self.conversations.create_item({'id': 'conv', 'user_id': 'owner', 'title': 'Review'})
        self.conversations.create_item({'id': 'other', 'user_id': 'someone-else'})
        self.documents = {
            key: {
                'id': key, 'user_id': 'owner', 'file_name': f'{key}.pdf',
                'title': f'Authoritative {key}', 'percentage_complete': 100,
                'status': 'Processing complete', 'tags': ['review'],
            }
            for key in ('suggested', 'own', 'second')
        }
        self.documents['denied'] = {
            'id': 'denied', 'user_id': 'someone-else', 'file_name': 'private.pdf',
            'percentage_complete': 100,
        }
        self.group_ids = {'group-a'}
        self.public_ids = {'public-a', 'public-b'}
        self.settings = {
            'enable_chat_orchestration': True,
            'enable_user_workspace': True,
            'enable_group_workspaces': True,
            'enable_public_workspaces': True,
            'chat_orchestration_approval_mode': 'manual',
            'gpt_model': {'selected': [{'deploymentName': 'original-model'}]},
        }
        self.model_outputs = []
        self.planner_contexts = []
        self.builder_contexts = []
        self.answer_prompts = []
        self.document_reads = []
        self.analysis_calls = []
        self.search_calls = []
        self.executed_contexts = []
        self.after_analysis = None

        self.stack.enter_context(stubbed_config(
            cosmos_conversations_container=self.conversations,
            cosmos_messages_container=self.messages,
            cosmos_orchestration_runs_container=self.runs,
            cosmos_orchestration_run_steps_container=self.steps,
            cognitive_services_scope='https://cognitiveservices.azure.com/.default',
            CLIENTS={},
        ))
        sys.modules['functions_settings'].get_settings = lambda: self.settings
        stubs = {
            'functions_authentication': module(
                'functions_authentication',
                get_current_user_id=lambda: request.headers.get('X-Test-User', 'owner'),
                get_current_user_info=lambda: {},
                login_required=lambda function: function,
                user_required=lambda function: function,
            ),
            'swagger_wrapper': module(
                'swagger_wrapper',
                get_auth_security=lambda: [],
                swagger_route=lambda **kwargs: lambda function: function,
            ),
            'functions_citation_tracking': module(
                'functions_citation_tracking',
                merge_cited_documents_into_conversation=lambda *args, **kwargs: None,
            ),
            'functions_conversation_cache': module(
                'functions_conversation_cache',
                invalidate_conversation_cache_for_item=lambda *args, **kwargs: None,
            ),
            'functions_group': module(
                'functions_group',
                get_user_groups=lambda user_id: [{'id': group_id} for group_id in self.group_ids],
                assert_group_role=self.assert_group_role,
                find_group_by_id=lambda group_id: {'id': group_id, 'name': f'Group {group_id}'},
            ),
            'functions_public_workspaces': module(
                'functions_public_workspaces',
                get_user_visible_public_workspace_ids_from_settings=lambda user_id: list(self.public_ids),
                find_public_workspace_by_id=lambda workspace_id: {'id': workspace_id, 'name': workspace_id},
            ),
            'functions_documents': module(
                'functions_documents',
                get_document_record=self.get_document_record,
                get_ordered_document_chunks=self.get_ordered_document_chunks,
                get_document_blob_storage_info=lambda *args, **kwargs: (None, None),
                get_workspace_tags=lambda *args, **kwargs: [{'name': 'review'}],
            ),
            'functions_search': module(
                'functions_search',
                SEARCH_DEFAULT_TOP_N=12, SEARCH_MAX_TOP_N=50,
                normalize_search_scope=lambda scope: scope or 'all',
                normalize_search_id_list=lambda values: [values] if isinstance(values, str) else list(values or []),
                normalize_search_top_n=lambda value, default, maximum: min(value or default, maximum),
                hybrid_search=self.hybrid_search,
            ),
            'functions_debug': module('functions_debug', debug_print=lambda *args, **kwargs: None),
            'functions_model_endpoint_identity_header': module(
                'functions_model_endpoint_identity_header',
                build_model_endpoint_identity_headers=lambda *args, **kwargs: {},
            ),
            'functions_document_actions': module(
                'functions_document_actions',
                is_document_action_enabled=lambda *args, **kwargs: True,
                get_document_action_max_documents=lambda *args, **kwargs: 2,
            ),
            'functions_document_analysis': module(
                'functions_document_analysis', run_document_analysis=self.analyze,
            ),
            'functions_source_review': module(
                'functions_source_review', extract_urls_from_text=lambda text: [],
            ),
            'functions_agent_catalog': module(
                'functions_agent_catalog', build_accessible_agent_catalog=lambda *args, **kwargs: [],
            ),
        }
        self.stack.enter_context(installed_modules(stubs))
        self.route = importlib.import_module('route_backend_orchestration')
        self.schema = importlib.import_module('functions_orchestration_schema')
        self.context = importlib.import_module('functions_orchestration_context')
        self.store = importlib.import_module('functions_orchestration_runs')
        self.planner = importlib.import_module('functions_orchestration_planner')
        self.executor = importlib.import_module('functions_orchestration_executor')
        self.search_service = importlib.import_module('functions_search_service')
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=self.answer)))
        self.stack.enter_context(patch.object(self.planner, 'resolve_planner_client', return_value=(client, 'model')))
        self.stack.enter_context(patch.object(self.route, 'resolve_planner_client', return_value=(client, 'model')))
        self.stack.enter_context(patch.object(self.planner, '_call_planner', side_effect=self.plan))
        self.stack.enter_context(patch.object(self.route, 'capture_execution_identity', return_value=None))

        real_builder = self.route.build_planner_context
        real_executor = self.route.execute_plan

        def build_context(*args, **kwargs):
            context = real_builder(*args, **kwargs)
            self.builder_contexts.append(deepcopy(context))
            return context

        def execute(plan, context, **kwargs):
            self.executed_contexts.append(context)
            return real_executor(plan, context, **kwargs)

        self.stack.enter_context(patch.object(self.route, 'build_planner_context', side_effect=build_context))
        self.stack.enter_context(patch.object(self.route, 'execute_plan', side_effect=execute))
        app = Flask(__name__)
        app.secret_key = 'test-only'
        blueprint = Blueprint('orchestration_test', __name__)
        self.route.register_route_backend_orchestration(blueprint)
        app.register_blueprint(blueprint)
        self.client = app.test_client()

    def assert_group_role(self, user_id, group_id, **kwargs):
        if group_id not in self.group_ids:
            raise PermissionError('private provider details')
        return 'User'

    def get_document_record(self, user_id, document_id, group_id=None, public_workspace_id=None):
        document = self.documents.get(document_id)
        if not document:
            return None
        if group_id:
            return deepcopy(document) if document.get('group_id') == group_id else None
        if public_workspace_id:
            return deepcopy(document) if document.get('public_workspace_id') == public_workspace_id else None
        if document.get('group_id') or document.get('public_workspace_id'):
            return None
        if document.get('user_id') == user_id or any(
            item.startswith(f'{user_id},') for item in document.get('shared_user_ids', [])
        ):
            return deepcopy(document)
        return None

    def get_ordered_document_chunks(self, document_id, user_id, **kwargs):
        document = self.search_service.get_document_record(user_id, document_id, **kwargs)
        if not document:
            return []
        self.document_reads.append(document_id)
        return [{
            'id': f'{document_id}_chunk', 'document_id': document_id,
            'file_name': document['file_name'], 'chunk_text': f'Actual contents of {document_id}.',
            'page_number': 1, 'chunk_sequence': 1,
        }]

    def hybrid_search(self, query, user_id, document_ids=None, **kwargs):
        self.search_calls.append({'document_ids': document_ids, **deepcopy(kwargs)})
        ids = document_ids or ['suggested']
        return [
            {'document_id': document_id, 'file_name': self.documents[document_id]['file_name'],
             'title': self.documents[document_id].get('title'), 'score': 1.0,
             'chunk_text': f'Actual contents of {document_id}.'}
            for document_id in ids if document_id in self.documents
        ]

    def analyze(self, user_id, prompt, document_ids, invoke_prompt, **kwargs):
        self.analysis_calls.append({'prompt': prompt, 'document_ids': document_ids, **kwargs})
        items = []
        for document_id in document_ids:
            payload = self.search_service.get_document_chunks_payload(
                document_id, user_id, conversation_id=kwargs.get('conversation_id'),
                doc_scope=kwargs.get('doc_scope'), active_group_ids=kwargs.get('active_group_ids'),
                active_public_workspace_id=kwargs.get('active_public_workspace_id'),
            )
            items.append({'document_id': document_id, 'text': payload['chunks'][0]['chunk_text']})
        if self.after_analysis:
            self.after_analysis()
        return {
            'reply': 'Reviewed the source.', 'document_ids': document_ids,
            'document_analysis_items': items,
            'coverage': {'documents': [
                {'document_id': document_id, 'total_windows': 1, 'processed_windows': 1}
                for document_id in document_ids
            ]},
        }

    def plan(self, client, deployment, messages):
        self.planner_contexts.append(json.loads(messages[1]['content']))
        if not self.model_outputs:
            raise AssertionError('Unexpected planner call.')
        return json.dumps(self.model_outputs.pop(0)), None

    def answer(self, **kwargs):
        self.answer_prompts.append(kwargs['messages'])
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='Completed answer.'))],
            usage=None,
        )

    def begin(self, raw_question=None, **overrides):
        self.model_outputs.append(raw_question or question())
        payload = {
            'message': 'Review my sources and prepare a recommendation.',
            'conversation_id': 'conv', 'turn_id': 'turn-1',
            **overrides,
        }
        response = self.client.post('/api/v2/orchestration/plan', json=payload)
        return event_document(response, 'orchestration_elicitation')

    def reply_payload(self, elicitation, content=None, context=None, **overrides):
        payload = {
            'message': 'This tampered message must not replace the original.',
            'conversation_id': 'conv', 'turn_id': 'turn-1', 'revision': 999,
            'elicitation_id': elicitation['elicitation_id'],
            'elicitation_revision': elicitation['revision'],
            'elicitation_submission_id': f"submission-{elicitation['revision']}",
            'elicitation_response': {'action': 'accept', 'content': content or {}},
        }
        if context is not None:
            payload['elicitation_context'] = context
        payload.update(overrides)
        return payload

    def post_reply(self, payload):
        return self.client.post('/api/v2/orchestration/plan', json=payload)

    def run_plan(self, plan):
        return self.client.post('/api/v2/orchestration/run', json={
            'run_id': plan['run_id'], 'conversation_id': 'conv',
        })

    def assert_run_completed(self, plan):
        response = self.run_plan(plan)
        self.assertEqual(200, response.status_code)
        events = frames(response)
        self.assertFalse(any(item.get('error') for item in events), events)
        self.assertTrue(any(
            item.get('type') == 'orchestration_done' and item.get('status') == 'completed'
            for item in events
        ), events)
        return events

    def test_split_and_combined_answer_prompts_reach_execution_once(self):
        answer_text = 'Use British spelling.'
        prompt_text = 'Include a separate accessibility risk section.'
        for combined in (False, True):
            with self.subTest(combined=combined):
                turn_id = f'prompt-{combined}'
                elicitation = self.begin(preference_question(), turn_id=turn_id)
                self.model_outputs.append(planned())
                field_context = {
                    'text': f'{prompt_text}\n\n{answer_text}' if combined else answer_text,
                    'prompt_info': {'content': prompt_text, 'user_text': answer_text},
                }
                plan = event_document(self.post_reply(self.reply_payload(
                    elicitation, {'style': 'brief'}, {'style': field_context}, turn_id=turn_id,
                )), 'orchestration_plan')
                self.assert_run_completed(plan)
                user_request = self.executed_contexts[-1].user_request
                self.assertEqual(1, user_request.count(answer_text))
                self.assertEqual(1, user_request.count(prompt_text))
                model_messages = json.dumps(self.answer_prompts[-1])
                self.assertEqual(1, model_messages.count(answer_text))
                self.assertEqual(1, model_messages.count(prompt_text))

    def test_chat_file_search_keeps_tagged_workspace_context(self):
        self.messages.create_item({
            'id': 'chat-source', 'conversation_id': 'conv', 'role': 'file',
            'filename': 'notes.md', 'file_content': 'Content from the selected chat attachment.',
        })
        for explicit_ids in (False, True):
            with self.subTest(explicit_ids=explicit_ids):
                turn_id = f'tagged-chat-{explicit_ids}'
                elicitation = self.begin(question(multiple=False), turn_id=turn_id)
                self.model_outputs.append(search_plan(['chat-source'] if explicit_ids else None))
                plan = event_document(self.post_reply(self.reply_payload(
                    elicitation, context={'files': {'references': [
                        reference('chat-source', 'chat_attachment', 'chat', 'conv'),
                        reference('review', kind='tag'),
                    ]}}, turn_id=turn_id,
                )), 'orchestration_plan')
                self.search_calls.clear()
                self.assert_run_completed(plan)
                self.assertEqual(1, len(self.search_calls))
                search = self.search_calls[0]
                self.assertIsNone(search['document_ids'])
                self.assertEqual(['review'], search['tags_filter'])
                self.assertEqual('union', search['document_filter_mode'])
                self.assertEqual('personal', search['doc_scope'])
                model_messages = json.dumps(self.answer_prompts[-1])
                self.assertIn('Content from the selected chat attachment.', model_messages)
                self.assertIn('Actual contents of suggested.', model_messages)

    def test_chat_file_search_keeps_explicit_workspace_context(self):
        self.messages.create_item({
            'id': 'chat-source', 'conversation_id': 'conv', 'role': 'file',
            'filename': 'notes.md', 'file_content': 'Content from the selected chat attachment.',
        })
        for original_file in (False, True):
            with self.subTest(original_file=original_file):
                turn_id = f'workspace-context-{original_file}'
                options = {'selected_document_ids': ['own'], 'doc_scope': 'personal'} if original_file else {}
                elicitation = self.begin(question(multiple=False), turn_id=turn_id, **options)
                self.model_outputs.append(search_plan())
                plan = event_document(self.post_reply(self.reply_payload(
                    elicitation, context={'files': {'references': [
                        reference('chat-source', 'chat_attachment', 'chat', 'conv'),
                        reference('personal', kind='scope'),
                    ]}}, turn_id=turn_id,
                )), 'orchestration_plan')
                self.search_calls.clear()
                self.assert_run_completed(plan)
                self.assertEqual(2 if original_file else 1, len(self.search_calls))
                workspace_call = next(item for item in self.search_calls if item['document_ids'] is None)
                self.assertIsNone(workspace_call['tags_filter'])
                self.assertEqual('personal', workspace_call['doc_scope'])
                model_messages = json.dumps(self.answer_prompts[-1])
                self.assertIn('Content from the selected chat attachment.', model_messages)
                self.assertIn('Actual contents of suggested.', model_messages)
                if original_file:
                    self.assertIn('Actual contents of own.', model_messages)

    def test_chat_file_keeps_original_tag_scope_beside_added_workspace_scope(self):
        self.messages.create_item({
            'id': 'chat-source', 'conversation_id': 'conv', 'role': 'file',
            'filename': 'notes.md', 'file_content': 'Content from the selected chat attachment.',
        })
        self.documents['group-doc'] = {
            'id': 'group-doc', 'group_id': 'group-a', 'file_name': 'group.pdf',
            'percentage_complete': 100, 'tags': ['review'],
        }

        def scoped_search(query, user_id, document_ids=None, **kwargs):
            self.search_calls.append({'document_ids': document_ids, **deepcopy(kwargs)})
            document_id = 'group-doc' if kwargs.get('doc_scope') == 'group' else 'suggested'
            return [{
                'document_id': document_id, 'file_name': f'{document_id}.pdf',
                'chunk_text': f'Actual contents of {document_id}.',
            }]

        self.stack.enter_context(patch.object(sys.modules['functions_search'], 'hybrid_search', scoped_search))
        elicitation = self.begin(tags=['review'], doc_scope='personal', document_filter_mode='union')
        self.model_outputs.append(search_plan())
        plan = event_document(self.post_reply(self.reply_payload(
            elicitation, context={'files': {'references': [
                reference('chat-source', 'chat_attachment', 'chat', 'conv'),
                reference('group-a', kind='scope', scope_kind='group', scope_id='group-a'),
            ]}},
        )), 'orchestration_plan')
        self.search_calls.clear()
        self.assert_run_completed(plan)
        self.assertEqual({'personal', 'group'}, {item['doc_scope'] for item in self.search_calls})
        self.assertTrue(all(item['tags_filter'] == ['review'] for item in self.search_calls))
        group_call = next(item for item in self.search_calls if item['doc_scope'] == 'group')
        self.assertEqual(['group-a'], group_call['active_group_ids'])
        model_messages = json.dumps(self.answer_prompts[-1])
        self.assertIn('Content from the selected chat attachment.', model_messages)
        self.assertIn('Actual contents of suggested.', model_messages)
        self.assertIn('Actual contents of group-doc.', model_messages)

    def test_shared_group_references_resolve_in_their_selected_scope_in_any_order(self):
        self.group_ids.add('group-b')
        group_documents = MemoryContainer('id')
        empty_documents = MemoryContainer('id')
        for document_id, group_id, shares in (
            ('group-doc-a', 'group-a', []),
            ('group-doc-b', 'group-b', ['group-a,approved']),
        ):
            document = {
                'id': document_id, 'group_id': group_id, 'shared_group_ids': shares,
                'file_name': f'{document_id}.pdf', 'percentage_complete': 100,
            }
            self.documents[document_id] = document
            group_documents.create_item(document)

        # Exercise the shipping document-record authorization code, not a stub that
        # forgets approved sharing and therefore hides scope-order dependence.
        filename = APP_ROOT / 'functions_documents.py'
        tree = ast.parse(filename.read_text(encoding='utf-8'))
        reader = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == 'get_document_record'
        )
        namespace = {
            'CosmosResourceNotFoundError': exceptions.CosmosResourceNotFoundError,
            '_get_documents_container': lambda group_id=None, **kwargs: (
                group_documents if group_id is not None else empty_documents
            ),
            '_normalize_document_enhanced_citations': deepcopy,
        }
        exec(compile(ast.Module(body=[reader], type_ignores=[]), str(filename), 'exec'), namespace)
        self.stack.enter_context(patch.object(
            self.search_service, 'get_document_record', namespace['get_document_record'],
        ))
        selected = [
            reference('group-doc-a', scope_kind='group', scope_id='group-a'),
            reference('group-doc-b', scope_kind='group', scope_id='group-b'),
        ]
        for item in selected:
            resolved = self.context.resolve_elicitation_references([item], 'owner', 'conv', self.settings)
            self.assertEqual(item['scope']['id'], resolved[0]['scope']['id'])
        shared_scopes = [
            reference('group-doc-b', scope_kind='group', scope_id='group-a'),
            reference('group-doc-b', scope_kind='group', scope_id='group-b'),
        ]
        resolved = self.context.resolve_elicitation_references(shared_scopes, 'owner', 'conv', self.settings)
        self.assertEqual(['group-a', 'group-b'], [item['scope']['id'] for item in resolved])
        for index, ordered in enumerate((selected, list(reversed(selected)))):
            with self.subTest(order=[item['id'] for item in ordered]):
                self.model_outputs.clear()
                turn_id = f'shared-groups-{index}'
                elicitation = self.begin(turn_id=turn_id)
                self.model_outputs.append(planned([item['id'] for item in ordered]))
                plan = event_document(self.post_reply(self.reply_payload(
                    elicitation, context={'files': {'references': ordered}}, turn_id=turn_id,
                )), 'orchestration_plan')
                self.assert_run_completed(plan)
                actual = {
                    item['id']: item['scope']['id']
                    for item in self.executed_contexts[-1].elicitation_references
                }
                self.assertEqual({'group-doc-a': 'group-a', 'group-doc-b': 'group-b'}, actual)
                model_messages = json.dumps(self.answer_prompts[-1])
                self.assertIn('Actual contents of group-doc-a.', model_messages)
                self.assertIn('Actual contents of group-doc-b.', model_messages)
        denied_share = group_documents.read_item('group-doc-b', 'group-doc-b')
        denied_share['shared_group_ids'] = ['group-a,pending']
        group_documents.upsert_item(denied_share)
        with self.assertRaises(self.context.ElicitationContextError):
            self.context.resolve_elicitation_references([shared_scopes[0]], 'owner', 'conv', self.settings)

    def test_clarification_preserves_existing_document_tag_filter(self):
        self.documents['own']['tags'] = ['not-review']

        def filtered_search(query, user_id, document_ids=None, **kwargs):
            self.search_calls.append({'document_ids': document_ids, **deepcopy(kwargs)})
            selected = set(document_ids or [])
            tags = set(kwargs.get('tags_filter') or [])
            union = kwargs.get('document_filter_mode') == 'union'
            result = []
            for document_id in ('own', 'second', 'suggested'):
                matches_document = not selected or document_id in selected
                matches_tag = not tags or tags.issubset(self.documents[document_id].get('tags', []))
                matches = (
                    matches_document or matches_tag
                    if union and selected and tags
                    else matches_document and matches_tag
                )
                if matches:
                    result.append({
                        'document_id': document_id, 'file_name': f'{document_id}.pdf',
                        'chunk_text': f'Actual contents of {document_id}.', 'score': 1,
                    })
            return result

        self.stack.enter_context(patch.object(sys.modules['functions_search'], 'hybrid_search', filtered_search))
        for index, (mode, supplemental) in enumerate((
            ('intersection', False), ('intersection', True),
            (None, False), (None, True), ('union', False),
        )):
            with self.subTest(mode=mode, supplemental=supplemental):
                turn_id = f'filter-{index}'
                options = {'document_filter_mode': mode} if mode is not None else {}
                elicitation = self.begin(
                    preference_question(), turn_id=turn_id, selected_document_ids=['own'],
                    tags=['review'], doc_scope='personal', **options,
                )
                self.model_outputs.append(search_plan())
                extra = {'style': {'references': [reference('second')]}} if supplemental else None
                plan = event_document(self.post_reply(self.reply_payload(
                    elicitation, {'style': 'brief'}, extra, turn_id=turn_id,
                )), 'orchestration_plan')
                record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
                if not supplemental:
                    self.assertEqual(record['original_seeds'], record['seeds'])
                self.search_calls.clear()
                self.assert_run_completed(plan)
                expected_mode = mode or 'intersection'
                self.assertEqual(expected_mode, self.executed_contexts[-1].document_filter_mode)
                self.assertEqual(expected_mode, self.search_calls[0]['document_filter_mode'])
                expected = {'own', 'second', 'suggested'} if mode == 'union' else {'second'} if supplemental else set()
                found = set(self.executed_contexts[-1].documents_touched)
                self.assertEqual(expected, found)

    def test_real_plan_answer_run_preserves_original_and_rich_context(self):
        original_prompt = {'id': 'main', 'name': 'Main prompt', 'content': 'Original prompt wording'}
        elicitation = self.begin(
            question(generic=True), prompt_info=original_prompt,
            model_deployment='original-model', agent_info={'name': 'main-agent'},
        )
        self.assertEqual(2, elicitation['contract_version'])
        candidates = elicitation['ui_hints']['fields']['files']['candidates']
        self.assertEqual(['suggested'], [item['id'] for item in candidates])
        self.assertEqual('Authoritative suggested', candidates[0]['label'])
        self.assertNotIn('enum', elicitation['requested_schema']['properties']['files']['items'])
        self.assertEqual([], self.store.list_conversation_runs('conv', 'owner'))
        self.assertEqual(0, self.store.next_turn_index('conv', 'owner'))
        self.assertEqual(0, len(self.messages.items))

        self.model_outputs.append(planned(['own']))
        payload = self.reply_payload(
            elicitation,
            {'files': [], 'style': 'brief', 'sections': ['risks', 'actions'], 'approved': False, 'count': 0},
            {
                'files': {'references': [reference('own')]},
                'style': {
                    'text': 'Expanded supplemental prompt: prioritize accessibility.',
                    'prompt_info': {
                        'id': 'answer-prompt', 'name': 'Answer prompt',
                        'content': 'Expanded supplemental prompt: prioritize accessibility.',
                        'original_content': 'Prioritize {{topic}}.',
                        'variables': {'topic': 'accessibility'}, 'edited': False,
                    },
                    'references': [
                        reference('review', kind='tag'), reference('personal', kind='scope'),
                    ],
                },
            },
            model_deployment='tampered-model', agent_info={'name': 'tampered-agent'},
            prompt_info={'content': 'tampered original prompt'},
        )
        plan = event_document(self.post_reply(payload), 'orchestration_plan')
        self.assertEqual(1, plan['revision'])
        record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
        self.assertEqual(['own'], record['seeds']['document_ids'])
        self.assertEqual(original_prompt, record['seeds']['prompt'])
        self.assertEqual('original-model', record['seeds']['model']['model_deployment'])
        self.assertEqual('main-agent', record['seeds']['agent']['name'])
        self.assertEqual(['review'], record['seeds']['tags'])
        self.assertEqual(['own'], record['answered_questions'][0]['answer']['files'])
        self.assertIs(False, record['answered_questions'][0]['answer']['approved'])
        self.assertEqual(0, record['answered_questions'][0]['answer']['count'])
        for context in self.builder_contexts[-2:]:
            self.assertIn('prioritize accessibility', context['user_request'])
            self.assertEqual(1, len(context['clarifications']))
        self.assertEqual(1, len(self.messages.items))

        duplicate = event_document(self.post_reply(payload), 'orchestration_plan')
        self.assertEqual(plan['run_id'], duplicate['run_id'])
        self.assertEqual(1, len(self.messages.items))
        self.assertEqual(2, len(self.planner_contexts))
        self.assertEqual(1, len(self.store.list_conversation_runs('conv', 'owner')))
        frames(self.run_plan(plan))
        self.assertEqual(['own'], self.document_reads)
        self.assertEqual('personal', self.analysis_calls[0]['doc_scope'])
        self.assertIn('prioritize accessibility', self.analysis_calls[0]['prompt'])
        self.assertIn('prioritize accessibility', json.dumps(self.answer_prompts))
        self.assertIn('Actual contents of own.', json.dumps(self.answer_prompts))
        self.assertEqual(record['user_message'], self.executed_contexts[0].user_message)
        self.assertNotIn('tampered', self.executed_contexts[0].user_request)
        # Retrying an accepted reply after execution must not reset the run to draft.
        self.post_reply(payload).get_data()
        self.assertEqual('completed', self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')['status'])

    def test_chat_attachment_file_and_image_are_real_sources(self):
        for role, filename in (('file', 'notes.md'), ('image', 'photo.png')):
            with self.subTest(role=role):
                turn_id = f'turn-{role}'
                message_id = f'upload-{role}'
                self.messages.create_item({
                    'id': message_id, 'conversation_id': 'conv', 'role': role,
                    'filename': filename, 'metadata': {'is_user_upload': True},
                    'file_content' if role == 'file' else 'extracted_text': f'Content of the {role} upload.',
                })
                elicitation = self.begin(question(multiple=False), turn_id=turn_id)
                self.model_outputs.append(planned([message_id], capability='document_search'))
                payload = self.reply_payload(
                    elicitation, context={'files': {'references': [
                        reference(message_id, 'chat_attachment', 'chat', 'conv'),
                    ]}}, turn_id=turn_id,
                )
                plan = event_document(self.post_reply(payload), 'orchestration_plan')
                self.search_calls.clear()
                self.assert_run_completed(plan)
                self.assertEqual([], self.search_calls, 'A chat file alone must not trigger workspace search')
                self.assertIn(f'Content of the {role} upload.', json.dumps(self.answer_prompts))
                self.assertEqual('chat', self.executed_contexts[-1].elicitation_references[0]['scope']['kind'])

    def test_primitive_only_legacy_reply_and_trivial_continuation(self):
        self.settings['chat_orchestration_ledger_max_runs'] = 0
        raw = {
            'kind': 'elicitation', 'message': 'Choose the response preferences.',
            'requested_schema': {
                'properties': {
                    'style': {'type': 'string', 'enum': ['brief', 'detailed']},
                    'sections': {'type': 'array', 'items': {'type': 'string', 'enum': ['risks', 'actions']}},
                    'approved': {'type': 'boolean'}, 'count': {'type': 'integer'},
                },
                'required': ['style', 'sections', 'approved', 'count'],
            },
        }
        elicitation = self.begin(raw)
        payload = self.reply_payload(
            elicitation, {'style': 'brief', 'sections': ['risks'], 'approved': False, 'count': 0},
        )
        for key in ('elicitation_id', 'elicitation_revision', 'elicitation_submission_id'):
            payload.pop(key)
        payload['elicitation'] = {'requested_schema': {'properties': {}}}
        with patch.object(self.route, 'triage_request', return_value='trivial'):
            plan = event_document(self.post_reply(payload), 'orchestration_plan')
        self.assertEqual(1, len(self.planner_contexts), 'A trivial continuation must not spend another planner call')
        self.assertEqual(1, plan['revision'])
        record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
        self.assertIs(False, record['answered_questions'][0]['answer']['approved'])
        self.assertEqual(0, record['answered_questions'][0]['answer']['count'])
        frames(self.run_plan(plan))
        self.assertIn('"approved": false', self.executed_contexts[-1].user_request)
        self.assertIn('"count": 0', self.executed_contexts[-1].user_request)
        duplicate = event_document(self.post_reply(payload), 'orchestration_plan')
        self.assertEqual(plan['run_id'], duplicate['run_id'])

    def test_answers_accumulate_across_questions_and_retries(self):
        first = self.begin()
        self.model_outputs.append({
            'kind': 'elicitation', 'message': 'What tone should I use?',
            'requested_schema': {
                'properties': {'tone': {'type': 'string', 'enum': ['formal', 'friendly']}},
                'required': ['tone'],
            },
        })
        first_payload = self.reply_payload(first, context={
            'files': {'text': 'First clarification wording.', 'references': [reference('own')]},
        })
        second = event_document(self.post_reply(first_payload), 'orchestration_elicitation')
        self.assertEqual(1, second['revision'])
        self.assertEqual(0, len(self.messages.items))
        replay = event_document(self.post_reply(first_payload), 'orchestration_elicitation')
        self.assertEqual(second['elicitation_id'], replay['elicitation_id'])
        self.assertEqual(2, len(self.planner_contexts))
        self.assertIn('First clarification wording.', self.planner_contexts[-1]['user_request'])
        self.model_outputs.append(planned(['own']))
        second_payload = self.reply_payload(
            second, {'tone': 'friendly'}, {'tone': {'text': 'Second clarification wording.'}},
        )
        plan = event_document(self.post_reply(second_payload), 'orchestration_plan')
        self.assertEqual(2, plan['revision'])
        record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
        self.assertEqual(2, len(record['answered_questions']))
        for context in self.builder_contexts[-2:]:
            self.assertIn('First clarification wording.', context['user_request'])
            self.assertIn('Second clarification wording.', context['user_request'])
        stale = {**first_payload, 'elicitation_submission_id': 'late-answer'}
        self.assertEqual(409, self.post_reply(stale).status_code)
        changed_retry = deepcopy(second_payload)
        changed_retry['elicitation_response']['content']['tone'] = 'formal'
        self.assertEqual(409, self.post_reply(changed_retry).status_code)
        frames(self.run_plan(plan))
        self.assertIn('First clarification wording.', json.dumps(self.answer_prompts))
        self.assertIn('Second clarification wording.', json.dumps(self.answer_prompts))

    def test_suggested_and_own_file_cardinality_and_true_enums(self):
        elicitation = self.begin(question(generic=True))
        valid = {'files': ['suggested'], 'style': 'brief', 'sections': ['risks'], 'approved': False, 'count': 0}
        for invalid in (
            {**valid, 'sections': []}, {**valid, 'style': 'not-offered'},
            {**valid, 'unknown': True}, {**valid, 'files': ['not-a-file.pdf']},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(400, self.post_reply(self.reply_payload(
                    elicitation, invalid, {'style': {'text': 'Optional explanation cannot bypass the choices.'}},
                )).status_code)
        self.model_outputs.append(planned(['own', 'suggested']))
        payload = self.reply_payload(
            elicitation, valid, {'files': {'references': [reference('own')]}},
        )
        plan = event_document(self.post_reply(payload), 'orchestration_plan')
        record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
        self.assertEqual({'own', 'suggested'}, set(record['answered_questions'][0]['answer']['files']))

        single = self.begin(question(multiple=False), turn_id='single')
        too_many = self.reply_payload(
            single, {'files': 'suggested'}, {'files': {'references': [reference('own')]}}, turn_id='single',
        )
        self.assertEqual(400, self.post_reply(too_many).status_code)
        for supplemental in (
            reference('review', kind='tag'),
            reference('', kind='scope'),
        ):
            payload = self.reply_payload(
                single, context={'files': {'references': [supplemental]}}, turn_id='single',
            )
            response = self.post_reply(payload)
            self.assertEqual(400, response.status_code)
            self.assertIn('files', response.get_json()['field_errors'])

    def test_group_and_multiple_public_sources_keep_original_selections(self):
        for document_id, scope_id, scope_field in (
            ('group-doc', 'group-a', 'group_id'),
            ('public-doc', 'public-a', 'public_workspace_id'),
            ('another-public-doc', 'public-b', 'public_workspace_id'),
        ):
            self.documents[document_id] = {
                'id': document_id, scope_field: scope_id, 'file_name': f'{document_id}.pdf',
                'title': f'Authoritative {document_id}', 'percentage_complete': 100,
            }
        elicitation = self.begin(
            selected_document_ids=['group-doc'], doc_scope='group', active_group_ids=['group-a'],
        )
        self.model_outputs.append(planned(['public-doc', 'another-public-doc']))
        payload = self.reply_payload(elicitation, context={'files': {'references': [
            reference('public-doc', scope_kind='public', scope_id='public-a'),
            reference('another-public-doc', scope_kind='public', scope_id='public-b'),
        ]}})
        plan = event_document(self.post_reply(payload), 'orchestration_plan')
        record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
        self.assertEqual(['group-doc', 'public-doc', 'another-public-doc'], record['seeds']['document_ids'])
        self.assertEqual(['group-a'], record['seeds']['active_group_ids'])
        self.assertEqual(['public-a', 'public-b'], record['seeds']['active_public_workspace_ids'])
        self.assertEqual('all', record['seeds']['doc_scope'])
        frames(self.run_plan(plan))
        self.assertEqual(['public-a', 'public-b'], self.analysis_calls[0]['active_public_workspace_id'])
        self.assertEqual('public-a', self.executed_contexts[0].active_public_workspace_id)
        self.assertEqual(['public-doc', 'another-public-doc'], self.document_reads)

    def test_unapproved_shares_failed_processing_and_non_file_messages_are_rejected(self):
        elicitation = self.begin()
        self.documents['denied']['shared_user_ids'] = ['owner,pending']
        self.messages.create_item({
            'id': 'assistant-not-upload', 'conversation_id': 'conv', 'role': 'assistant',
            'content': 'Not a file', 'filename': 'fake.pdf',
        })
        self.messages.create_item({
            'id': 'workspace-upload-wrapper', 'conversation_id': 'conv', 'role': 'file',
            'filename': 'own.pdf', 'workspace_document_id': 'own', 'file_content_source': 'workspace',
        })
        invalid = [
            reference('denied'),
            reference('assistant-not-upload', 'chat_attachment', 'chat', 'conv'),
            reference('workspace-upload-wrapper', 'chat_attachment', 'chat', 'conv'),
            reference('own', scope_kind='public', scope_id='hidden-public'),
        ]
        for selected in invalid:
            with self.subTest(selected=selected):
                payload = self.reply_payload(elicitation, context={'files': {'references': [selected]}})
                self.assertEqual(400, self.post_reply(payload).status_code)
        for status, percentage in (
            ('Failed', 100), ('Queued for processing', None), ('Processing', 'invalid'),
            ('Queued for processing', 100),
        ):
            with self.subTest(status=status):
                self.documents['own'].update({'status': status, 'percentage_complete': percentage})
                payload = self.reply_payload(elicitation, context={'files': {'references': [reference('own')]}})
                self.assertEqual(400, self.post_reply(payload).status_code)
        with patch.object(self.search_service, 'resolve_document_contexts', side_effect=RuntimeError('private endpoint')):
            self.assertEqual(400, self.post_reply(self.reply_payload(
                elicitation, context={'files': {'references': [reference('own')]}},
            )).status_code)

    def test_refusals_strip_every_current_reply_field(self):
        for action in ('decline', 'cancel'):
            with self.subTest(action=action):
                turn_id = f'turn-{action}'
                elicitation = self.begin(turn_id=turn_id)
                self.model_outputs.append(planned())
                payload = self.reply_payload(
                    elicitation, turn_id=turn_id,
                    elicitation_response={'action': action, 'content': {'files': ['do-not-carry-this']}},
                    elicitation_context={'malformed': {'text': 'do-not-carry-this', 'storage_url': 'private'}},
                )
                plan = event_document(self.post_reply(payload), 'orchestration_plan')
                record = self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')
                self.assertEqual({}, record['answered_questions'][0]['answer'])
                self.assertEqual({}, record['answered_questions'][0]['context'])
                self.assertNotIn('do-not-carry-this', json.dumps(record))
                self.assertNotIn('elicitation_references', record['seeds'])
                self.assertIn('own', self.documents)

    def test_identity_binding_and_expired_legacy_question(self):
        elicitation = self.begin()
        valid = self.reply_payload(elicitation, {'files': ['suggested']})
        for overrides in (
            {'elicitation_id': 'another-question'}, {'elicitation_revision': 20},
            {'turn_id': 'another-turn'}, {'conversation_id': 'other'},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(409, self.post_reply({**valid, **overrides}).status_code)
        denied = self.client.post(
            '/api/v2/orchestration/plan', json=valid, headers={'X-Test-User': 'someone-else'},
        )
        self.assertEqual(409, denied.status_code)
        missing = dict(valid)
        for key in ('elicitation_id', 'elicitation_revision', 'elicitation_submission_id'):
            missing.pop(key)
        missing['turn_id'] = 'never-persisted'
        missing['elicitation'] = elicitation
        expired = self.post_reply(missing)
        self.assertEqual(409, expired.status_code)
        self.assertEqual('elicitation_expired', expired.get_json()['code'])
        self.assertEqual(1, len(self.planner_contexts))

    def test_invalid_or_unready_sources_retain_editable_question(self):
        elicitation = self.begin()
        for selected in (
            reference('denied'),
            reference('own', scope_kind='group', scope_id='not-a-member'),
            reference('own', 'chat_attachment', 'chat', 'other'),
            {**reference('own'), 'storage_url': 'https://private.invalid'},
        ):
            with self.subTest(selected=selected):
                response = self.post_reply(self.reply_payload(elicitation, context={'files': {'references': [selected]}}))
                self.assertEqual(400, response.status_code)
                self.assertIn('files', response.get_json().get('field_errors', {}))
                self.assertNotIn('private provider details', response.get_data(as_text=True))
                self.assertEqual('pending', self.store.get_pending_elicitation('owner', 'conv', 'turn-1')['status'])
        self.documents['own']['percentage_complete'] = 50
        self.documents['own']['status'] = 'Processing'
        payload = self.reply_payload(elicitation, context={'files': {'references': [reference('own')]}})
        self.assertEqual(400, self.post_reply(payload).status_code)
        self.documents['own']['percentage_complete'] = 100
        self.documents['own']['status'] = 'Processing complete'
        self.model_outputs.append(planned(['own']))
        plan = event_document(self.post_reply(payload), 'orchestration_plan')
        self.assertEqual(['own'], self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')['seeds']['document_ids'])

    def test_lock_and_feature_gates_are_enforced(self):
        elicitation = self.begin()
        conversation = self.conversations.read_item('conv', 'conv')
        conversation.update({'scope_locked': True, 'locked_contexts': [{'scope': 'group', 'id': 'group-a'}]})
        self.conversations.upsert_item(conversation)
        payload = self.reply_payload(elicitation, context={'files': {'references': [reference('own')]}})
        response = self.post_reply(payload)
        self.assertEqual(400, response.status_code)
        self.assertIn('locked', response.get_json()['details'][0])
        conversation['scope_locked'] = False
        self.conversations.upsert_item(conversation)
        self.settings['enable_user_workspace'] = False
        self.assertEqual(400, self.post_reply(payload).status_code)

    def test_permission_is_rechecked_before_run_and_before_answer(self):
        elicitation = self.begin()
        self.model_outputs.append(planned(['own']))
        plan = event_document(self.post_reply(self.reply_payload(
            elicitation, context={'files': {'references': [reference('own')]}},
        )), 'orchestration_plan')
        self.documents['own']['user_id'] = 'revoked'
        self.assertEqual(409, self.run_plan(plan).status_code)
        self.assertFalse(self.answer_prompts)
        self.documents['own']['user_id'] = 'owner'
        self.after_analysis = lambda: self.documents['own'].update({'user_id': 'revoked'})
        events = frames(self.run_plan(plan))
        self.assertTrue(any(item.get('error') for item in events), events)
        self.assertFalse(self.answer_prompts)
        self.assertEqual('failed', self.store.get_orchestration_run(plan['run_id'], 'owner', 'conv')['status'])

    def test_partial_persistence_failure_retries_without_replanning(self):
        elicitation = self.begin()
        payload = self.reply_payload(elicitation, {'files': ['suggested']})
        self.model_outputs.append(planned(['suggested']))
        self.runs.fail_next_create = True
        failure = frames(self.post_reply(payload))
        self.assertTrue(any(item.get('error') for item in failure), failure)
        pending = self.store.get_pending_elicitation('owner', 'conv', 'turn-1')
        self.assertIsNotNone(pending['prepared'])
        self.assertIsNone(pending['claim'])
        self.assertEqual(1, len(self.messages.items))
        plan = event_document(self.post_reply(payload), 'orchestration_plan')
        self.assertEqual(2, len(self.planner_contexts))
        self.assertEqual(1, len(self.messages.items))
        self.assertEqual(plan['run_id'], self.store.list_conversation_runs('conv', 'owner')[0]['run_id'])

    def test_pending_records_never_become_runs(self):
        elicitation = self.begin()
        pending = self.store.get_pending_elicitation('owner', 'conv', 'turn-1')
        pending_id = pending['id']
        self.assertIsNone(self.store.get_orchestration_run(pending_id, 'owner', 'conv'))
        self.assertIsNone(self.store.update_orchestration_run(pending_id, 'owner', {'status': 'running'}, 'conv'))
        self.assertEqual([], self.store.list_run_steps(pending_id, 'owner', 'conv'))
        self.assertEqual(404, self.run_plan({'run_id': pending_id}).status_code)
        self.runs.create_item({
            'id': 'legacy-run', 'user_id': 'owner', 'conversation_id': 'conv', 'turn_index': 4,
        })
        self.assertEqual(5, self.store.next_turn_index('conv', 'owner'))
        self.assertEqual(['legacy-run'], [item['id'] for item in self.store.list_conversation_runs('conv', 'owner')])
        ledger = self.context.build_run_ledger([pending])
        self.assertEqual([], ledger['runs'])
        self.assertNotIn('run_id', pending)
        self.assertEqual(elicitation['elicitation_id'], pending['question']['elicitation_id'])

    def test_conditional_claims_reject_double_finish_and_stale_etags(self):
        elicitation = self.begin()
        first = self.store.claim_elicitation_submission(
            'owner', 'conv', 'turn-1', 'fingerprint',
            elicitation_id=elicitation['elicitation_id'], revision=0, submission_id='first',
        )
        with self.assertRaises(self.store.ElicitationStateError) as error:
            self.store.claim_elicitation_submission(
                'owner', 'conv', 'turn-1', 'fingerprint',
                elicitation_id=elicitation['elicitation_id'], revision=0, submission_id='first',
            )
        self.assertEqual('elicitation_in_progress', error.exception.code)
        stale = deepcopy(first['record'])
        self.store._replace_pending(first['record'], {'test_transition': True})
        with self.assertRaises(self.store.ElicitationStateError):
            self.store._replace_pending(stale, {'test_transition': False})
        self.store.release_elicitation_submission(first)
        self.assertIsNone(self.store.get_pending_elicitation('owner', 'conv', 'turn-1')['claim'])
        second = self.store.claim_elicitation_submission(
            'owner', 'conv', 'turn-1', 'another-fingerprint',
            elicitation_id=elicitation['elicitation_id'], revision=0, submission_id='second',
        )
        self.store.release_elicitation_submission(first)
        self.assertEqual(second['claim']['token'], self.store.get_pending_elicitation('owner', 'conv', 'turn-1')['claim']['token'])

    def test_upload_success_branches_return_the_persisted_message_id(self):
        source = (APP_ROOT / 'route_frontend_chats.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        upload = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'upload_file')
        successes = []
        for call in ast.walk(upload):
            if not isinstance(call, ast.Call) or getattr(call.func, 'id', None) != 'jsonify' or not call.args:
                continue
            body = call.args[0]
            if not isinstance(body, ast.Dict):
                continue
            values = {key.value: value for key, value in zip(body.keys, body.values) if isinstance(key, ast.Constant)}
            if 'message' in values and 'conversation_id' in values:
                successes.append(values)
        self.assertEqual(2, len(successes))
        for values in successes:
            self.assertEqual('file_message_id', values['file_message_id'].id)
            self.assertIn('workspace_document_id', values)
            self.assertIn('workspace_document', values)


if __name__ == '__main__':
    assert_app_version_at_least('0.261.096')
    unittest.main(verbosity=2)
