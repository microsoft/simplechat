# test_orchestration_elicitation_context.py
"""
Behavioral coverage for persisted inline clarification and execution context.
Version: 0.261.139
Implemented in: 0.261.096
Conversation-context, prompt-snapshot, and action integration: 0.261.099
Atomic revision-store fixture isolation: 0.261.103
Single orchestration contract updated in: 0.261.139

Covers the clarification behavior that remains in the Gather / Reason / Render
contract: planner prompt guidance, file-answer normalization, answer accumulation,
rich prompt snapshots, and elicitation reference merging. Removed route-level legacy
respond/phase execution mechanics are covered by newer harness tests instead.
"""

import importlib
import json
import sys
import types
import unittest
from contextlib import contextmanager
from copy import deepcopy

from azure.cosmos import exceptions

from test_support.app_stubs import stubbed_config
from test_support.versioning import assert_app_version_at_least


class MemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}

    def create_item(self, body):
        document = deepcopy(body)
        self.items[(document[self.partition_field], document['id'])] = document
        return deepcopy(document)

    def read_item(self, item, partition_key):
        document = self.items.get((partition_key, item))
        if document is None:
            raise exceptions.CosmosResourceNotFoundError(status_code=404)
        return deepcopy(document)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        values = {item['name']: item['value'] for item in parameters or []}
        items = [deepcopy(document) for (partition, _), document in self.items.items()
                 if partition_key is None or partition == partition_key]
        if '@document_id' in values:
            items = [item for item in items if item.get('id') == values['@document_id']]
        return items


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


def question(multiple=True, generic=False):
    fields = {
        'files': {'type': 'array', 'items': {'type': 'string'}, 'title': 'Choose source files'}
        if multiple else {'type': 'string', 'title': 'Choose a source file'},
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
            'fields': {'files': {'input': 'files', 'candidates': [reference('suggested')]}},
        },
    }


def reference(document_id, kind='document', scope_kind='personal', scope_id=None):
    return {
        'kind': kind, 'id': document_id, 'label': 'untrusted browser label',
        'scope': {'kind': scope_kind, 'id': scope_id, 'name': 'untrusted workspace name'},
    }


@contextmanager
def installed_modules(stubs):
    originals = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class ElicitationContextTests(unittest.TestCase):
    def setUp(self):
        self.conversations = MemoryContainer('id')
        self.messages = MemoryContainer('conversation_id')
        self.conversations.create_item({'id': 'conv', 'user_id': 'owner', 'title': 'Review'})
        self.documents = {
            key: {'id': key, 'user_id': 'owner', 'file_name': f'{key}.pdf',
                  'title': f'Authoritative {key}', 'percentage_complete': 100,
                  'status': 'Processing complete', 'tags': ['review']}
            for key in ('suggested', 'own', 'second')
        }
        self.settings = {
            'enable_user_workspace': True,
            'enable_group_workspaces': True,
            'enable_public_workspaces': True,
        }
        self.config = stubbed_config(
            cosmos_conversations_container=self.conversations,
            cosmos_messages_container=self.messages,
            cognitive_services_scope='https://cognitiveservices.azure.com/.default',
        )
        self.config.__enter__()
        self.addCleanup(self.config.__exit__, None, None, None)
        self.modules_context = installed_modules({
            'functions_search_service': module(
                'functions_search_service', resolve_document_contexts=self.resolve_document_contexts,
            ),
            'functions_mixed_source_orchestration': module(
                'functions_mixed_source_orchestration',
                resolve_authorized_source_manifest=self.resolve_authorized_source_manifest,
            ),
            'functions_documents': module(
                'functions_documents', get_workspace_tags=lambda *args, **kwargs: [{'name': 'review'}],
            ),
            'functions_group': module(
                'functions_group', assert_group_role=lambda *args, **kwargs: 'User',
                find_group_by_id=lambda group_id: {'id': group_id, 'name': f'Group {group_id}'},
            ),
            'functions_public_workspaces': module(
                'functions_public_workspaces',
                get_user_visible_public_workspace_ids_from_settings=lambda user_id: ['public-a'],
                find_public_workspace_by_id=lambda workspace_id: {'id': workspace_id, 'name': workspace_id},
            ),
        })
        self.modules_context.__enter__()
        self.addCleanup(self.modules_context.__exit__, None, None, None)
        for name in ('functions_orchestration_context', 'functions_orchestration_planner'):
            sys.modules.pop(name, None)
        self.context = importlib.import_module('functions_orchestration_context')
        self.planner = importlib.import_module('functions_orchestration_planner')

    def resolve_document_contexts(self, document_ids, user_id, **kwargs):
        contexts = []
        for document_id in document_ids:
            document = self.documents.get(document_id)
            if not document:
                contexts.append(None)
            else:
                contexts.append({'scope': 'personal', 'document': deepcopy(document)})
        return contexts

    def resolve_authorized_source_manifest(self, document_ids, user_id, **kwargs):
        return [{
            'document_id': document_id, 'authorization_status': 'authorized',
            'scope': 'personal', 'scope_id': None,
            'file_name': self.documents[document_id]['file_name'],
            'display_name': self.documents[document_id]['title'],
        } for document_id in document_ids if document_id in self.documents]

    def test_planner_prompt_keeps_clarification_and_file_answer_rules(self):
        prompt = self.planner.PLANNER_SYSTEM_PROMPT
        self.assertIn('"kind":"elicitation"', prompt)
        self.assertIn('ui_hints.fields[field].input to "files"', prompt)
        self.assertIn('NEVER put an enum on a file field', prompt)
        self.assertIn('Do not repeat a\nquestion', prompt)
        self.assertIn('clarifications or earlier runs already answered or declined', prompt)

    def test_file_answers_use_references_not_string_enums(self):
        raw_question = question(generic=True)
        self.assertNotIn('enum', raw_question['requested_schema']['properties']['files']['items'])
        response, context = self.context.normalize_elicitation_answer(
            raw_question,
            {'action': 'accept', 'content': {
                'files': ['suggested'], 'style': 'brief', 'sections': ['risks'],
                'approved': False, 'count': 0,
            }},
            {'files': {'references': [reference('own')]}},
            'owner', 'conv', self.settings,
        )
        self.assertEqual({'suggested', 'own'}, set(response['content']['files']))
        self.assertIs(False, response['content']['approved'])
        self.assertEqual(0, response['content']['count'])
        labels = {item['id']: item['label'] for item in context['files']['references']}
        self.assertEqual('Authoritative suggested', labels['suggested'])
        self.assertEqual('Authoritative own', labels['own'])

    def test_single_file_question_rejects_multiple_files_and_tags_alone(self):
        raw_question = question(multiple=False)
        with self.assertRaises(self.context.ElicitationContextError):
            self.context.normalize_elicitation_answer(
                raw_question, {'action': 'accept', 'content': {}},
                {'files': {'references': [reference('own'), reference('second')]}},
                'owner', 'conv', self.settings,
            )
        with self.assertRaises(self.context.ElicitationContextError):
            self.context.normalize_elicitation_answer(
                raw_question, {'action': 'accept', 'content': {}},
                {'files': {'references': [reference('review', kind='tag')]}},
                'owner', 'conv', self.settings,
            )

    def test_decline_and_cancel_strip_current_reply_context(self):
        for action in ('decline', 'cancel'):
            with self.subTest(action=action):
                response, context = self.context.normalize_elicitation_answer(
                    question(), {'action': action, 'content': {'files': ['do-not-carry']}},
                    {'files': {'text': 'private', 'references': [reference('own')]}},
                    'owner', 'conv', self.settings,
                )
                self.assertEqual({'action': action, 'content': {}}, response)
                self.assertEqual({}, context)

    def test_answers_accumulate_in_user_request_without_reasking_declined_questions(self):
        request = self.context.build_elicitation_user_request('Review the sources.', [
            {'question': 'Which files?', 'action': 'accept', 'answer': {'files': ['own']},
             'context': {'files': {'text': 'First clarification wording.'}}},
            {'question': 'What tone?', 'action': 'decline', 'answer': {'tone': 'brief'}},
            {'question': 'Which sections?', 'action': 'accept', 'answer': {'sections': ['risks']},
             'context': {'sections': {'text': 'Second clarification wording.'}}},
        ])
        self.assertIn('First clarification wording.', request)
        self.assertIn('Second clarification wording.', request)
        self.assertNotIn('"tone": "brief"', request)
        self.assertIn('Do not repeat a\nquestion', self.planner.PLANNER_SYSTEM_PROMPT)

    def test_prompt_snapshot_mismatch_is_rejected_but_matching_snapshot_is_preserved(self):
        schema = {'requested_schema': {'properties': {'style': {'type': 'string'}}, 'required': ['style']}}
        with self.assertRaises(self.context.ElicitationContextError):
            self.context.normalize_elicitation_answer(
                schema, {'action': 'accept', 'content': {'style': 'brief'}},
                {'style': {'text': 'Different composer wording', 'prompt_info': {
                    'content': 'Apply the prompt.', 'template_content': 'Apply the prompt.',
                    'composer_text': 'Frozen wording', 'composer_embedded': False,
                    'user_text': 'Frozen wording',
                }}},
                'owner', 'conv', self.settings,
            )
        response, context = self.context.normalize_elicitation_answer(
            schema, {'action': 'accept', 'content': {'style': 'brief'}},
            {'style': {'text': 'Frozen wording', 'prompt_info': {
                'content': 'Apply the prompt.', 'template_content': 'Apply the prompt.',
                'composer_text': 'Frozen wording', 'composer_embedded': False,
                'user_text': 'Frozen wording',
            }}},
            'owner', 'conv', self.settings,
        )
        self.assertEqual({'style': 'brief'}, response['content'])
        self.assertEqual('Apply the prompt.', context['style']['prompt_info']['content'])

    def test_merge_elicitation_context_preserves_existing_filters_and_adds_scope(self):
        seeds = {'document_ids': ['own'], 'tags': ['review'], 'doc_scope': 'personal'}
        merged = self.context.merge_elicitation_context(seeds, {
            'files': {'references': [
                reference('second'),
                reference('group-a', kind='scope', scope_kind='group', scope_id='group-a'),
            ]},
        })
        self.assertEqual(['own', 'second'], merged['document_ids'])
        self.assertEqual(['review'], merged['tags'])
        self.assertEqual(['group-a'], merged['active_group_ids'])
        self.assertEqual('all', merged['doc_scope'])
        self.assertNotIn('document_filter_mode', merged)

    def test_rich_answer_urls_keep_user_provenance(self):
        urls = self.context.conversation_user_urls('Read the selected report.', answered_questions=[
            {'action': 'accept', 'answer': {}, 'context': {'style': {
                'text': 'Use https://accepted.example/report',
                'prompt_info': {'content': 'Compare with https://prompt.example/report'},
                'references': [{'label': 'https://label-only.example'}],
            }}},
            {'action': 'decline', 'answer': {}, 'context': {'style': {'text': 'https://declined.example'}}},
        ])
        self.assertEqual(['https://prompt.example/report', 'https://accepted.example/report'], urls)

    def test_prompt_snapshots_use_rich_context_budget_without_widening_primitive_answers(self):
        text = 'x' * 12000
        answers = [{
            'question': 'Choose a style.', 'action': 'accept', 'answer': {'style': 'brief'},
            'context': {'style': {'text': text, 'prompt_info': {'content': text, 'original_content': text}}},
        }]
        self.assertGreater(len(json.dumps(answers)), self.context.CLARIFICATION_MAX_BYTES)
        self.context.validate_clarification_answers(answers)
        with self.assertRaises(self.context.ConversationContextError):
            self.context.validate_clarification_answers([{'answer': 'x' * 32769}])
        oversized = deepcopy(answers)
        oversized[0]['context']['style']['text'] = 'x' * self.context.ELICITATION_CONTEXT_BYTE_LIMIT
        with self.assertRaises(self.context.ConversationContextError):
            self.context.validate_clarification_answers(oversized)


if __name__ == '__main__':
    assert_app_version_at_least('0.261.139')
    unittest.main(verbosity=2)
