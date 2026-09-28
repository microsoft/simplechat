# test_assist_thread_submission_id.py
"""
Functional test for client submission ids on the scoped AI assist threads.
Version: 0.261.196
Implemented in: 0.261.196
Refs: microsoft/simplechat#1552

This test ensures that the personal and shared diagram, chart and image assist routes accept an
optional client ``submission_id``. The id is stored on both turns of an exchange. A retry of a
stored exchange is answered from storage, with no model call, no second revision, no write and no
event. The same id arriving with a different message is refused with a 409 ``submission_conflict``,
a malformed id is rejected with a 400, and a request without an id behaves exactly as before. A
failed model call leaves no transcript turn behind, and access is checked before a stored exchange
is replayed.

It also ensures submission ids never reach a model prompt, and that the plan editor keeps only ids
that follow the same rule.

The route handlers are the production functions, extracted from their modules and run against the
real revision storage helpers. Only the model, Cosmos, authorization and event seams are replaced,
and nothing touches the network.
"""

import ast
import copy
import importlib
import json
import logging
import sys
import unittest
import uuid
from functools import lru_cache
from pathlib import Path
from unittest.mock import Mock

from flask import Flask, jsonify, request

TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_ROOT))

# Application paths and the config seam must exist before any application module is imported.
from test_support.app_stubs import APP_ROOT, stubbed_config  # noqa: E402
from test_support.orchestration_revisions import AtomicMemoryContainer  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_assist_submissions as submissions  # noqa: E402
import functions_image_edit as image_edit  # noqa: E402
import functions_message_block_revisions as blocks  # noqa: E402
import functions_message_image_revisions as images  # noqa: E402


def _import_with_config(module_name, **config_values):
    """Import a module that reads a few config names, without caching it for later tests."""
    with stubbed_config(**config_values):
        previously_loaded = module_name in sys.modules
        module = importlib.import_module(module_name)
        if not previously_loaded:
            sys.modules.pop(module_name, None)
    return module


block_assist = _import_with_config(
    'functions_block_revision_assist',
    AzureOpenAI=object,
    cognitive_services_scope='https://cognitiveservices.azure.com/.default',
)
plan_revisions = _import_with_config(
    'functions_orchestration_plan_revisions',
    cosmos_orchestration_runs_container=AtomicMemoryContainer('conversation_id'),
    cosmos_orchestration_run_steps_container=AtomicMemoryContainer('run_id'),
    cognitive_services_scope='https://cognitiveservices.azure.com/.default',
)


@lru_cache(maxsize=None)
def _route_tree(file_name):
    return ast.parse(APP_ROOT.joinpath(file_name).read_text(encoding='utf-8-sig'))


def load_route_function(file_name, name, namespace):
    """Execute one production function, without its decorators, in a prepared namespace."""
    matches = [
        node for node in ast.walk(_route_tree(file_name))
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f'Expected exactly one {name} in {file_name}, found {len(matches)}')
    node = copy.deepcopy(matches[0])
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(APP_ROOT / file_name), 'exec'), namespace)
    return namespace[name]


def error_response(message='An unexpected error occurred'):
    return jsonify({'error': message}), 500


class FakeImageServiceError(Exception):
    code = 'image_unavailable'


SUBMISSION_NAMES = {
    'SUBMISSION_CONFLICT': submissions.SUBMISSION_CONFLICT,
    'SUBMISSION_CONFLICT_CODE': submissions.SUBMISSION_CONFLICT_CODE,
    'SUBMISSION_CONFLICT_MESSAGE': submissions.SUBMISSION_CONFLICT_MESSAGE,
    'SUBMISSION_REPLAY': submissions.SUBMISSION_REPLAY,
    'SubmissionIdError': submissions.SubmissionIdError,
    'classify_submission': submissions.classify_submission,
    'normalize_submission_id': submissions.normalize_submission_id,
}

BLOCK_NAMES = {
    'BLOCK_MAX_CHAT_CONTENT_LENGTH': blocks.MAX_CHAT_CONTENT_LENGTH,
    'ORIGIN_AI': blocks.ORIGIN_AI,
    'BlockRevisionConflictError': blocks.BlockRevisionConflictError,
    'BlockRevisionError': blocks.BlockRevisionError,
    'append_block_chat_turn': blocks.append_block_chat_turn,
    'apply_block_revision': blocks.apply_block_revision,
    'current_block_source': blocks.current_block_source,
    'read_block_chat': blocks.read_block_chat,
    'read_block_entry': blocks.read_block_entry,
    'read_block_revisions': blocks.read_block_revisions,
    'validate_block_index': blocks.validate_block_index,
    'validate_block_kind': blocks.validate_block_kind,
    'validate_source_hash': blocks.validate_source_hash,
    'BlockAssistError': block_assist.BlockAssistError,
    'normalize_instruction': block_assist.normalize_instruction,
}

IMAGE_NAMES = {
    'IMAGE_MAX_CHAT_CONTENT_LENGTH': images.MAX_CHAT_CONTENT_LENGTH,
    'IMAGE_ORIGIN_AI': images.ORIGIN_AI,
    'ImageRevisionConflictError': images.ImageRevisionConflictError,
    'ImageRevisionError': images.ImageRevisionError,
    'append_image_chat_turn': images.append_image_chat_turn,
    'read_image_revisions': images.read_image_revisions,
    'resolve_current_image_revision': images.resolve_current_revision,
    'resolve_image_message_content': images.resolve_image_message_content,
    'serialize_image_revisions': images.serialize_image_revisions,
    # _read_expected_revision_count raises the block vocabulary's error on both routes.
    'BlockRevisionError': blocks.BlockRevisionError,
    'AIConnectionError': FakeImageServiceError,
    'ImageGenerationError': FakeImageServiceError,
}

COMMON_NAMES = {
    'request': request,
    'jsonify': jsonify,
    'logging': logging,
    'debug_print': lambda *args, **kwargs: None,
    'resolve_mask_display_name': lambda user: 'Test User',
    'make_json_serializable': lambda value: value,
    'build_json_error_response': error_response,
}

ORIGINAL_SOURCE = 'graph TD\n  A[Start] --> B[Finish]'
REVISED_SOURCE = 'graph LR\n  A[Start] --> B[Finish]'
SOURCE_HASH = blocks.fingerprint_source(ORIGINAL_SOURCE)
INSTRUCTION = 'Make it horizontal.'
MALFORMED_IDS = ('has space', '<script>', 'quote"id', 'x' * 129, 42, ['submission-1'])


def block_message():
    return {
        'id': 'message-1', 'conversation_id': 'conversation-1', 'role': 'assistant',
        'content': f'```mermaid\n{ORIGINAL_SOURCE}\n```', 'timestamp': '2026-01-01T00:00:00Z',
        'metadata': {},
    }


def image_message():
    return {
        'id': 'image-1', 'conversation_id': 'conversation-1', 'role': 'image',
        'content': 'data:image/png;base64,AAAA', 'prompt': 'A cat on a red chair',
        'model_deployment_name': 'gpt-image-1', 'metadata': {},
    }


class RouteHarness(unittest.TestCase):
    """Runs an extracted handler under a Flask request context."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test-only-session-key'
        self.logs = Mock()
        self.denied = False

    def call(self, handler, body, *args):
        with self.app.test_request_context(json=body):
            result = handler(*args)
            response, status = result if isinstance(result, tuple) else (result, result.status_code)
            return status, response.get_json()


class BlockAssistContract:
    """Behaviour both the personal and the shared diagram assist routes must have."""

    def body(self, **overrides):
        return {
            'conversation_id': 'conversation-1', 'instruction': INSTRUCTION,
            'block_kind': 'mermaid', 'block_index': 0, 'source_hash': SOURCE_HASH,
            'original_source': ORIGINAL_SOURCE, **overrides,
        }

    def edit(self, settings, source, instruction, **kwargs):
        self.model_requests.append({
            'source': source, 'instruction': instruction,
            'chat_turns': copy.deepcopy(kwargs.get('chat_turns')),
        })
        if self.model_failures:
            raise self.model_failures.pop(0)
        return {'source': REVISED_SOURCE if len(self.model_requests) == 1 else f'{REVISED_SOURCE}\n  B --> C'}

    def stored_entry(self):
        return blocks.read_block_entry(self.stored, 'mermaid', 0, SOURCE_HASH) or {}

    def stored_chat(self):
        return [
            (turn['role'], turn['content'], turn.get('submission_id'))
            for turn in self.stored_entry().get('chat') or []
        ]

    def test_a_request_without_an_id_behaves_exactly_as_before(self):
        status, payload = self.send(self.body())
        self.assertEqual(status, 200, payload)
        self.assertEqual(set(payload) - {'conversation_id'}, {'success', 'message_id', 'source', 'block_revisions'})
        self.assertEqual(payload['source'], REVISED_SOURCE)
        self.assertEqual(self.stored_chat(), [
            ('user', INSTRUCTION, None), ('assistant', REVISED_SOURCE, None),
        ])
        for turn in self.stored_entry()['chat']:
            self.assertNotIn('submission_id', turn)
        self.assertEqual(len(self.model_requests), 1)
        self.assertEqual(self.writes(), 1)

    def test_a_blank_id_is_treated_as_no_id(self):
        status, payload = self.send(self.body(submission_id='   '))
        self.assertEqual(status, 200, payload)
        self.assertNotIn('replayed', payload)
        self.assertEqual([turn[2] for turn in self.stored_chat()], [None, None])

    def test_an_id_is_stored_on_both_turns_and_a_retry_is_answered_from_storage(self):
        first_status, first = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(first_status, 200, first)
        self.assertNotIn('replayed', first)
        self.assertEqual(self.stored_chat(), [
            ('user', INSTRUCTION, 'submission-1'), ('assistant', REVISED_SOURCE, 'submission-1'),
        ])
        returned_chat = first['block_revisions']['mermaid']['0']['chat']
        self.assertEqual([turn['submission_id'] for turn in returned_chat], ['submission-1'] * 2)
        revisions_before = copy.deepcopy(self.stored_entry()['revisions'])

        status, replay = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 200, replay)
        self.assertIs(replay['replayed'], True)
        self.assertEqual(replay['source'], REVISED_SOURCE)
        self.assertEqual(replay['block_revisions'], first['block_revisions'])
        self.assertEqual(len(self.model_requests), 1)
        self.assertEqual(self.writes(), 1)
        self.assertEqual(self.stored_entry()['revisions'], revisions_before)

    def test_a_retry_that_differs_only_in_surrounding_whitespace_is_still_a_replay(self):
        self.send(self.body(submission_id='submission-1'))
        status, replay = self.send(self.body(submission_id='submission-1', instruction=f'  {INSTRUCTION}\r\n'))
        self.assertEqual(status, 200, replay)
        self.assertIs(replay['replayed'], True)
        self.assertEqual(len(self.model_requests), 1)

    def test_a_reused_id_with_a_different_message_is_refused(self):
        self.send(self.body(submission_id='submission-1'))
        status, payload = self.send(self.body(submission_id='submission-1', instruction='Make it vertical.'))
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload['code'], submissions.SUBMISSION_CONFLICT_CODE)
        self.assertEqual(payload['error'], submissions.SUBMISSION_CONFLICT_MESSAGE)
        # A revision conflict carries the stored revisions; this one must be distinguishable.
        self.assertNotIn('block_revisions', payload)
        self.assertEqual(len(self.model_requests), 1)
        self.assertEqual(self.writes(), 1)

    def test_a_revision_conflict_keeps_its_shape_and_has_no_submission_code(self):
        status, payload = self.send(self.body(submission_id='submission-1', expected_revision_count=5))
        self.assertEqual(status, 409, payload)
        self.assertNotIn('code', payload)
        self.assertIn('block_revisions', payload)
        self.assertEqual(self.stored_chat(), [])

    def test_a_malformed_id_is_rejected_before_the_model_is_called(self):
        for submission_id in MALFORMED_IDS:
            with self.subTest(submission_id=submission_id):
                status, payload = self.send(self.body(submission_id=submission_id))
                self.assertEqual(status, 400, payload)
                self.assertIn('submission_id', payload['error'])
        self.assertEqual(self.model_requests, [])
        self.assertEqual(self.writes(), 0)

    def test_a_failed_edit_leaves_no_turn_and_its_retry_calls_the_model(self):
        self.model_failures.append(block_assist.BlockAssistError('The model did not return a diagram'))
        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 502, payload)
        self.assertEqual(self.stored_chat(), [])
        self.assertEqual(self.writes(), 0)

        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 200, payload)
        self.assertNotIn('replayed', payload)
        self.assertEqual(len(self.model_requests), 2)
        self.assertEqual([turn[2] for turn in self.stored_chat()], ['submission-1'] * 2)

    def test_access_is_checked_before_a_stored_exchange_is_replayed(self):
        self.send(self.body(submission_id='submission-1'))
        self.denied = True
        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 403, payload)
        self.assertEqual(set(payload), {'error'})
        self.assertEqual(len(self.model_requests), 1)

    def test_the_model_is_shown_stored_turns_without_their_ids(self):
        self.send(self.body(submission_id='submission-1'))
        status, payload = self.send(self.body(submission_id='submission-2', instruction='Add a third step.'))
        self.assertEqual(status, 200, payload)
        replayed_turns = self.model_requests[1]['chat_turns']
        self.assertEqual([turn['content'] for turn in replayed_turns], [INSTRUCTION, REVISED_SOURCE])
        for turn in replayed_turns:
            self.assertEqual(set(turn), {'role', 'content'})
        self.assertNotIn('submission', json.dumps(self.model_requests))
        self.assertEqual(
            [turn[2] for turn in self.stored_chat()],
            ['submission-1', 'submission-1', 'submission-2', 'submission-2'],
        )


class PersonalBlockAssistRouteTests(BlockAssistContract, RouteHarness):
    def setUp(self):
        super().setUp()
        self.stored = block_message()
        self.model_requests = []
        self.model_failures = []
        self.persist = Mock(side_effect=self._persist)
        namespace = {
            **COMMON_NAMES, **SUBMISSION_NAMES, **BLOCK_NAMES,
            'log_event': self.logs,
            'get_current_user_id': lambda: 'user-1',
            'get_current_user_info': lambda: {'userId': 'user-1', 'displayName': 'Test User'},
            'get_settings': lambda: {},
            '_load_block_revision_message': self._load,
            '_find_originating_user_request': Mock(return_value=''),
            'request_block_edit': self.edit,
            'persist_chat_reply': self.persist,
            'cosmos_messages_container': Mock(),
        }
        load_route_function('route_backend_chats.py', '_read_expected_revision_count', namespace)
        self.handler = load_route_function('route_backend_chats.py', 'assist_message_block_revision_api', namespace)

    def _load(self, user_id, conversation_id, message_id):
        if self.denied:
            return None, (jsonify({'error': 'You can only edit your own conversations'}), 403)
        return copy.deepcopy(self.stored), None

    def _persist(self, container, message_doc):
        self.stored = copy.deepcopy(message_doc)
        return copy.deepcopy(message_doc)

    def send(self, body):
        return self.call(self.handler, body, 'message-1')

    def writes(self):
        return self.persist.call_count

    def test_the_chart_kind_follows_the_same_rule(self):
        chart = '{"type": "bar", "data": {"labels": ["A"], "datasets": [{"data": [1]}]}}'
        chart_hash = blocks.fingerprint_source(chart)
        self.stored['content'] = f'```simplechart\n{chart}\n```'
        body = self.body(
            block_kind='simplechart', source_hash=chart_hash, original_source=chart,
            submission_id='chart-submission',
        )
        status, first = self.send(body)
        self.assertEqual(status, 200, first)
        chat = blocks.read_block_entry(self.stored, 'simplechart', 0, chart_hash)['chat']
        self.assertEqual([turn['submission_id'] for turn in chat], ['chart-submission'] * 2)
        status, replay = self.send(body)
        self.assertEqual(status, 200, replay)
        self.assertIs(replay['replayed'], True)
        self.assertEqual(len(self.model_requests), 1)


class SharedBlockAssistRouteTests(BlockAssistContract, RouteHarness):
    def setUp(self):
        super().setUp()
        self.stored = block_message()
        self.model_requests = []
        self.model_failures = []
        self.events = []
        namespace = {
            **COMMON_NAMES, **SUBMISSION_NAMES, **BLOCK_NAMES,
            'log_event': self.logs,
            '_require_collaboration_feature_enabled': lambda: None,
            '_get_current_collaboration_user': lambda: {'user_id': 'user-2', 'display_name': 'Participant'},
            '_load_collaboration_block_revision_message': self._load,
            '_find_collaboration_originating_request': Mock(return_value=''),
            '_save_collaboration_block_revisions': self._save,
            'get_settings': lambda: {},
            'request_block_edit': self.edit,
            'CosmosResourceNotFoundError': LookupError,
        }
        load_route_function('route_backend_collaboration.py', '_read_collaboration_expected_revision_count', namespace)
        self.handler = load_route_function(
            'route_backend_collaboration.py', 'assist_collaboration_block_revision_api', namespace,
        )

    def _load(self, user_id, conversation_id, message_id):
        if self.denied:
            raise PermissionError('Only participants can change this conversation')
        return copy.deepcopy(self.stored)

    def _save(self, conversation_id, message_id, message_doc, user_id):
        self.stored = copy.deepcopy(message_doc)
        revisions = blocks.read_block_revisions(message_doc)
        self.events.append({
            'type': 'collaboration.message.block_revised', 'message_id': message_id,
            'block_revisions': copy.deepcopy(revisions), 'updated_by_user_id': user_id,
        })
        return revisions

    def send(self, body):
        return self.call(self.handler, body, 'conversation-1', 'message-1')

    def writes(self):
        return len(self.events)

    def test_the_room_event_carries_the_ids_so_every_open_editor_can_reconcile(self):
        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 200, payload)
        chat = self.events[0]['block_revisions']['mermaid']['0']['chat']
        self.assertEqual([turn['submission_id'] for turn in chat], ['submission-1'] * 2)
        self.send(self.body(submission_id='submission-1'))
        self.assertEqual(len(self.events), 1)


class ImageRevisionContract:
    """Behaviour both the personal and the shared image revision routes must have."""

    def body(self, **overrides):
        return {'conversation_id': 'conversation-1', 'instruction': 'Make the chair blue.', **overrides}

    def revise(self, settings, message_doc, **kwargs):
        self.model_requests.append({key: copy.deepcopy(value) for key, value in kwargs.items() if key != 'reload_message'})
        if self.model_failures:
            raise self.model_failures.pop(0)
        target = kwargs['reload_message']()
        origin = kwargs['origin']
        instruction = str(kwargs.get('instruction') or '').strip() if origin == images.ORIGIN_AI else ''
        current = images.current_image_prompt(target)
        prompt = image_edit.compose_edit_prompt(current, instruction) if instruction else (
            kwargs.get('prompt') or current
        )
        images.apply_image_revision(
            target,
            {'blob_container': 'images', 'blob_path': f'owner/revision-{len(self.model_requests)}.png'},
            origin=origin, prompt=prompt, instruction=instruction, model='gpt-image-1', method='edit',
            author_id='user-1', author_name='Test User',
            expected_revision_count=kwargs.get('expected_revision_count'),
            expected_current_revision_id=kwargs.get('expected_current_revision_id') or '',
        )
        return {
            'message': target, 'method': 'edit', 'model': 'gpt-image-1',
            'prompt': prompt, 'instruction': instruction,
        }

    def stored_chat(self):
        return [
            (turn['role'], turn.get('submission_id'))
            for turn in images.read_image_revisions(self.stored).get('chat') or []
        ]

    def test_a_request_without_an_id_behaves_exactly_as_before(self):
        status, payload = self.send(self.body())
        self.assertEqual(status, 200, payload)
        self.assertEqual(
            set(payload) - {'conversation_id'},
            {'success', 'message_id', 'method', 'model_deployment_name', 'image_url', 'image_revisions'},
        )
        self.assertEqual(self.stored_chat(), [('user', None), ('assistant', None)])
        for turn in payload['image_revisions']['chat']:
            self.assertNotIn('submission_id', turn)
        self.assertEqual(self.writes(), 1)

    def test_an_id_is_stored_on_both_turns_and_a_retry_is_answered_from_storage(self):
        first_status, first = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(first_status, 200, first)
        self.assertNotIn('replayed', first)
        self.assertEqual(self.stored_chat(), [('user', 'submission-1'), ('assistant', 'submission-1')])
        self.assertEqual(
            [turn['submission_id'] for turn in first['image_revisions']['chat']], ['submission-1'] * 2,
        )
        self.assertNotIn('submission_id', self.model_requests[0])

        status, replay = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 200, replay)
        self.assertIs(replay['replayed'], True)
        self.assertEqual(replay['image_url'], first['image_url'])
        self.assertEqual(replay['image_revisions'], first['image_revisions'])
        self.assertEqual(replay['method'], first['method'])
        self.assertEqual(replay['model_deployment_name'], first['model_deployment_name'])
        self.assertEqual(len(self.model_requests), 1)
        self.assertEqual(self.writes(), 1)

    def test_a_reused_id_with_a_different_message_is_refused(self):
        self.send(self.body(submission_id='submission-1'))
        status, payload = self.send(self.body(submission_id='submission-1', instruction='Make it green.'))
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload['code'], submissions.SUBMISSION_CONFLICT_CODE)
        self.assertNotIn('image_revisions', payload)
        self.assertEqual(len(self.model_requests), 1)
        self.assertEqual(self.writes(), 1)

    def test_a_malformed_id_is_rejected_before_the_model_is_called(self):
        for submission_id in MALFORMED_IDS:
            with self.subTest(submission_id=submission_id):
                status, payload = self.send(self.body(submission_id=submission_id))
                self.assertEqual(status, 400, payload)
        self.assertEqual(self.model_requests, [])
        self.assertEqual(self.writes(), 0)

    def test_a_version_without_an_instruction_ignores_the_id(self):
        self.send(self.body(submission_id='submission-1'))
        for origin, extra in (('prompt', {'prompt': 'A dog on a red chair'}), ('control', {})):
            with self.subTest(origin=origin):
                status, payload = self.send(self.body(
                    submission_id='submission-1', origin=origin, instruction='', **extra,
                ))
                self.assertEqual(status, 200, payload)
                self.assertNotIn('replayed', payload)
        self.assertEqual(len(self.model_requests), 3)
        self.assertEqual(self.stored_chat(), [('user', 'submission-1'), ('assistant', 'submission-1')])

    def test_a_failed_edit_leaves_no_turn_and_its_retry_calls_the_model(self):
        self.model_failures.append(FakeImageServiceError('The image model is unavailable.'))
        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 503, payload)
        self.assertEqual(self.stored_chat(), [])
        self.assertEqual(self.writes(), 0)

        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 200, payload)
        self.assertNotIn('replayed', payload)
        self.assertEqual(len(self.model_requests), 2)
        self.assertEqual(self.stored_chat(), [('user', 'submission-1'), ('assistant', 'submission-1')])

    def test_access_is_checked_before_a_stored_exchange_is_replayed(self):
        self.send(self.body(submission_id='submission-1'))
        self.denied = True
        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 403, payload)
        self.assertEqual(set(payload), {'error'})
        self.assertEqual(len(self.model_requests), 1)


def image_error_response(exc):
    return {'error': str(exc), 'error_code': exc.code}, 503


class PersonalImageRevisionRouteTests(ImageRevisionContract, RouteHarness):
    def setUp(self):
        super().setUp()
        self.stored = image_message()
        self.model_requests = []
        self.model_failures = []
        self.persist = Mock(side_effect=self._persist)
        container = Mock()
        container.read_item.side_effect = lambda item, partition_key: copy.deepcopy(self.stored)
        namespace = {
            **COMMON_NAMES, **SUBMISSION_NAMES, **IMAGE_NAMES,
            'log_event': self.logs,
            'get_current_user_id': lambda: 'user-1',
            'get_current_user_info': lambda: {'userId': 'user-1', 'displayName': 'Test User'},
            'get_settings': lambda: {'enable_image_generation': True},
            '_load_image_revision_message': self._load,
            '_image_revision_owner_id': lambda conversation, user_id: user_id,
            'revise_image_message': self.revise,
            'image_generation_error_log_context': lambda exc: {'error_code': exc.code},
            'image_generation_error_response': image_error_response,
            'persist_chat_reply': self.persist,
            'cosmos_messages_container': container,
        }
        load_route_function('route_backend_chats.py', '_read_expected_revision_count', namespace)
        self.handler = load_route_function('route_backend_chats.py', 'add_message_image_revision_api', namespace)

    def _load(self, user_id, conversation_id, message_id):
        if self.denied:
            return None, (jsonify({'error': 'You can only edit your own conversations'}), 403)
        stored = copy.deepcopy(self.stored)
        return {
            'conversation': {'id': conversation_id, 'user_id': 'user-1'},
            'message': stored, 'content': stored['content'],
        }, None

    def _persist(self, container, message_doc):
        self.stored = copy.deepcopy(message_doc)
        return copy.deepcopy(message_doc)

    def send(self, body):
        return self.call(self.handler, body, 'image-1')

    def writes(self):
        return self.persist.call_count


class SharedImageRevisionRouteTests(ImageRevisionContract, RouteHarness):
    def setUp(self):
        super().setUp()
        self.stored = image_message()
        self.mirror = {
            'id': 'shared-image-1', 'conversation_id': 'conversation-1', 'role': 'image',
            'content': 'shared-image-placeholder',
            'metadata': {'source_conversation_id': 'owner-conversation', 'source_message_id': 'image-1'},
        }
        self.model_requests = []
        self.model_failures = []
        self.events = []
        container = Mock()
        container.read_item.side_effect = lambda item, partition_key: copy.deepcopy(self.stored)
        namespace = {
            **COMMON_NAMES, **SUBMISSION_NAMES, **IMAGE_NAMES,
            'log_event': self.logs,
            '_require_collaboration_feature_enabled': lambda: None,
            '_get_current_collaboration_user': lambda: {'user_id': 'user-2', 'display_name': 'Participant'},
            'get_settings': lambda: {'enable_image_generation': True},
            '_load_collaboration_image_revision_message': self._load,
            '_save_collaboration_image_revisions': self._save,
            'build_collaboration_image_url': self._image_url,
            'revise_image_message': self.revise,
            'image_generation_error_response': image_error_response,
            'cosmos_messages_container': container,
            'CosmosResourceNotFoundError': LookupError,
        }
        load_route_function('route_backend_collaboration.py', '_read_collaboration_expected_revision_count', namespace)
        self.handler = load_route_function(
            'route_backend_collaboration.py', 'add_collaboration_image_revision_api', namespace,
        )

    @staticmethod
    def _image_url(conversation_id, message_id, message_doc):
        base = f'/api/collaboration/conversations/{conversation_id}/messages/{message_id}/image'
        return images.resolve_image_message_content(message_doc, base)

    def _load(self, user_id, conversation_id, message_id):
        if self.denied:
            raise PermissionError('Only participants can change this conversation')
        source = copy.deepcopy(self.stored)
        return {
            'message': copy.deepcopy(self.mirror), 'source': source,
            'source_conversation_id': 'owner-conversation', 'content': source['content'],
        }

    def _save(self, conversation_id, message_id, message_doc, source_doc, user_id):
        self.stored = copy.deepcopy(source_doc)
        mirror = copy.deepcopy(message_doc)
        mirror.setdefault('metadata', {})[images.IMAGE_REVISIONS_METADATA_KEY] = copy.deepcopy(
            source_doc['metadata'][images.IMAGE_REVISIONS_METADATA_KEY]
        )
        self.mirror = mirror
        message_doc['metadata'] = copy.deepcopy(mirror['metadata'])
        revisions = images.serialize_image_revisions(images.read_image_revisions(source_doc))
        self.events.append({
            'type': 'collaboration.message.image_revised', 'message_id': message_id,
            'image_revisions': copy.deepcopy(revisions), 'updated_by_user_id': user_id,
        })
        return revisions

    def send(self, body):
        return self.call(self.handler, body, 'conversation-1', 'shared-image-1')

    def writes(self):
        return len(self.events)

    def test_the_room_event_carries_the_ids_so_every_open_editor_can_reconcile(self):
        status, payload = self.send(self.body(submission_id='submission-1'))
        self.assertEqual(status, 200, payload)
        chat = self.events[0]['image_revisions']['chat']
        self.assertEqual([turn['submission_id'] for turn in chat], ['submission-1'] * 2)
        self.send(self.body(submission_id='submission-1'))
        self.assertEqual(len(self.events), 1)


class SubmissionHelperTests(unittest.TestCase):
    def test_application_version(self):
        assert_app_version_at_least('0.261.196')

    def test_ids_the_editors_mint_are_accepted(self):
        for value in (str(uuid.uuid4()), 'turn-1767225600000-k3j9x2', 'a' * 128, 'plan.edit:1_2-3'):
            with self.subTest(value=value):
                self.assertEqual(submissions.normalize_submission_id(value), value)

    def test_absent_and_blank_ids_mean_no_id(self):
        for value in (None, '', '   '):
            with self.subTest(value=value):
                self.assertIsNone(submissions.normalize_submission_id(value))
        self.assertEqual(submissions.normalize_submission_id('  padded-id  '), 'padded-id')

    def test_malformed_ids_are_refused(self):
        for value in MALFORMED_IDS + ('line\nbreak', 'slash/id', 'hash#id', 'é-accent'):
            with self.subTest(value=value):
                with self.assertRaises(submissions.SubmissionIdError):
                    submissions.normalize_submission_id(value)

    def test_classification_compares_only_the_matching_user_turn(self):
        chat = [
            {'role': 'user', 'content': 'Legacy turn without an id'},
            {'role': 'assistant', 'content': 'Legacy reply'},
            {'role': 'user', 'content': 'Make it blue.', 'submission_id': 'submission-1'},
            {'role': 'assistant', 'content': 'A blue chair', 'submission_id': 'submission-1'},
            {'role': 'assistant', 'content': 'Orphaned reply', 'submission_id': 'submission-2'},
        ]
        classify = submissions.classify_submission
        self.assertEqual(classify(chat, None, 'Make it blue.', 4000), submissions.SUBMISSION_NEW)
        self.assertEqual(classify(None, 'submission-1', 'Make it blue.', 4000), submissions.SUBMISSION_NEW)
        self.assertEqual(classify(chat, 'submission-9', 'Make it blue.', 4000), submissions.SUBMISSION_NEW)
        self.assertEqual(classify(chat, 'submission-2', 'Orphaned reply', 4000), submissions.SUBMISSION_NEW)
        self.assertEqual(classify(chat, 'submission-1', '  Make it blue.  ', 4000), submissions.SUBMISSION_REPLAY)
        self.assertEqual(classify(chat, 'submission-1', 'Make it red.', 4000), submissions.SUBMISSION_CONFLICT)
        long_turn = [{'role': 'user', 'content': 'x' * 10, 'submission_id': 'long'}]
        self.assertEqual(classify(long_turn, 'long', 'x' * 25, 10), submissions.SUBMISSION_REPLAY)

    def test_every_store_agrees_on_the_longest_id(self):
        self.assertEqual(blocks.MAX_SUBMISSION_ID_LENGTH, submissions.MAX_SUBMISSION_ID_LENGTH)
        self.assertEqual(images.MAX_SUBMISSION_ID_LENGTH, submissions.MAX_SUBMISSION_ID_LENGTH)


class StorageGuardTests(unittest.TestCase):
    def seeded_block(self):
        message = block_message()
        blocks.apply_block_revision(
            message, 'mermaid', 0, REVISED_SOURCE, SOURCE_HASH,
            original_source=ORIGINAL_SOURCE, origin=blocks.ORIGIN_AI,
        )
        return message

    def seeded_image(self):
        message = image_message()
        images.apply_image_revision(
            message, {'blob_container': 'images', 'blob_path': 'owner/revision-1.png'},
            origin=images.ORIGIN_AI, prompt='A blue chair', instruction='Make it blue.',
        )
        return message

    def test_block_turns_store_an_id_only_when_one_is_sent(self):
        message = self.seeded_block()
        blocks.append_block_chat_turn(message, 'mermaid', 0, 'user', 'First', SOURCE_HASH)
        blocks.append_block_chat_turn(
            message, 'mermaid', 0, 'user', 'Second', SOURCE_HASH, submission_id='submission-1',
        )
        chat = blocks.read_block_entry(message, 'mermaid', 0, SOURCE_HASH)['chat']
        self.assertNotIn('submission_id', chat[0])
        self.assertEqual(chat[1]['submission_id'], 'submission-1')
        self.assertEqual(blocks.read_block_chat({'chat': chat}), [
            {'role': 'user', 'content': 'First'}, {'role': 'user', 'content': 'Second'},
        ])
        for invalid in (42, '', 'x' * 129):
            with self.subTest(submission_id=invalid):
                with self.assertRaises(blocks.BlockRevisionError):
                    blocks.append_block_chat_turn(
                        message, 'mermaid', 0, 'user', 'Third', SOURCE_HASH, submission_id=invalid,
                    )

    def test_image_turns_store_and_serialize_an_id_only_when_one_is_sent(self):
        message = self.seeded_image()
        images.append_image_chat_turn(message, 'user', 'First')
        images.append_image_chat_turn(message, 'user', 'Second', submission_id='submission-1')
        serialized = images.serialize_image_revisions(images.read_image_revisions(message))['chat']
        self.assertNotIn('submission_id', serialized[0])
        self.assertEqual(serialized[1]['submission_id'], 'submission-1')
        self.assertNotIn('blob_path', json.dumps(serialized))
        for invalid in (42, '', 'x' * 129):
            with self.subTest(submission_id=invalid):
                with self.assertRaises(images.ImageRevisionError):
                    images.append_image_chat_turn(message, 'user', 'Third', submission_id=invalid)


class ModelPromptTests(unittest.TestCase):
    """Submission ids are bookkeeping, and no model is ever shown one."""

    STORED_TURNS = [
        {
            'role': 'user', 'content': 'OLD CHAT CONTENT', 'timestamp': '2026-01-01T00:00:00+00:00',
            'submission_id': 'stored-submission-id',
        },
        {
            'role': 'assistant', 'content': REVISED_SOURCE, 'timestamp': '2026-01-01T00:00:01+00:00',
            'submission_id': 'stored-submission-id',
        },
    ]

    def test_block_assist_messages_replay_turns_as_role_and_content_only(self):
        messages = block_assist.build_assist_messages(
            REVISED_SOURCE, 'Add a third step.', chat_turns=copy.deepcopy(self.STORED_TURNS),
        )
        for message in messages:
            self.assertEqual(set(message), {'role', 'content'})
        serialized = json.dumps(messages)
        self.assertIn('OLD CHAT CONTENT', serialized)
        self.assertNotIn('stored-submission-id', serialized)
        self.assertNotIn('2026-01-01', serialized)

    def test_image_edit_prompt_is_composed_without_the_transcript(self):
        message = image_message()
        images.apply_image_revision(
            message, {'blob_container': 'images', 'blob_path': 'owner/revision-1.png'},
            origin=images.ORIGIN_AI, prompt='A blue chair', instruction='Make it blue.',
        )
        for turn in self.STORED_TURNS:
            images.append_image_chat_turn(
                message, turn['role'], turn['content'], submission_id=turn['submission_id'],
            )
        prompt = image_edit.compose_edit_prompt(images.current_image_prompt(message), 'Make it green.')
        self.assertIn('A blue chair', prompt)
        self.assertNotIn('OLD CHAT CONTENT', prompt)
        self.assertNotIn('stored-submission-id', prompt)
        for turn in images.read_image_chat(images.read_image_revisions(message)):
            self.assertEqual(set(turn), {'role', 'content'})

    def test_the_image_edit_never_reads_the_transcript(self):
        tree = ast.parse(Path(image_edit.__file__).read_text(encoding='utf-8-sig'))
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == 'revise_image_message'
        )
        body = function.body[1:] if ast.get_docstring(function) else function.body
        names = set()
        for statement in body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    names.add(node.value)
        self.assertFalse({name for name in names if 'chat' in name.lower()}, names)
        self.assertFalse({name for name in names if 'submission' in name.lower()}, names)


class PlanChatTurnTests(unittest.TestCase):
    def test_stored_plan_turns_keep_only_ids_that_follow_the_shared_rule(self):
        chat = [
            {'role': 'user', 'content': 'Kept', 'timestamp': 't1', 'submission_id': 'submission-1'},
            {'role': 'assistant', 'content': 'Kept too', 'timestamp': 't2', 'submission_id': str(uuid.uuid4())},
            *(
                {'role': 'user', 'content': f'Dropped {index}', 'timestamp': 't3', 'submission_id': invalid}
                for index, invalid in enumerate(MALFORMED_IDS)
            ),
            {'role': 'assistant', 'content': 'Legacy', 'timestamp': 't4'},
        ]
        bounded = plan_revisions._bounded_chat(chat)
        self.assertEqual(len(bounded), len(chat))
        self.assertEqual(bounded[0]['submission_id'], 'submission-1')
        self.assertIn('submission_id', bounded[1])
        for turn in bounded[2:]:
            self.assertNotIn('submission_id', turn)
            self.assertEqual(set(turn), {'role', 'content', 'timestamp'})

    def test_a_plan_edit_request_uses_the_same_id_rule(self):
        base = {
            'conversation_id': 'conversation-1', 'expected_version': 'version-1',
            'action': 'ask', 'instruction': 'Focus on the main findings.',
        }
        accepted = plan_revisions._normalize_request({**base, 'submission_id': 'client-id.1:ok'}, 'conversation-1')
        self.assertEqual(accepted['submission_id'], 'client-id.1:ok')
        for invalid in (*MALFORMED_IDS, None, '', ' padded '):
            with self.subTest(submission_id=invalid):
                with self.assertRaises(plan_revisions.PlanRevisionError) as failure:
                    plan_revisions._normalize_request({**base, 'submission_id': invalid}, 'conversation-1')
                self.assertEqual(failure.exception.status_code, 400)
                self.assertEqual(failure.exception.code, 'invalid_request')


if __name__ == '__main__':
    unittest.main()
