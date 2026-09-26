# test_orchestration_v2_plan_backend.py
"""Saved plan editing, restoration, and private admission-context persistence.

Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
Refs: microsoft/simplechat#1509

Exercise the real planner/compiler, revision/run stores, immutable result readers,
and current source authorization. Replace only model, Cosmos, and unrelated
catalog/memory I/O boundaries. Block network access. A saved plan from the removed
earlier contract is refused, never edited, claimed or replanned.
"""

import importlib
import inspect
import json
import socket
import sys
import unittest
import uuid
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_support.app_stubs import APP_ROOT, stubbed_config
from test_support.orchestration_research import document_action_policy_module
from test_support.orchestration_revisions import AtomicMemoryContainer


EXTERNAL_CALLBACK_NAMES = (
    'external_source_preflight', 'external_source_admission', 'external_source_authorizer',
    'capture_external_source_configuration',
)


def binding(step_id=None, output_name='answer', *, alias=None):
    return {
        'version': 'orchestration-input-binding-v1',
        'step_id': step_id, 'output_name': None if alias else output_name,
        'existing_result': alias,
    }


class V2PlanBackendTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sys, 'path', [str(APP_ROOT), *sys.path]))
        self.stack.enter_context(patch.object(
            socket.socket, 'connect', side_effect=AssertionError('Unexpected external I/O'),
        ))
        policy_name = 'functions_document_actions'
        previous_policy = sys.modules.get(policy_name)
        sys.modules[policy_name] = document_action_policy_module()
        if previous_policy is None:
            self.addCleanup(sys.modules.pop, policy_name, None)
        else:
            self.addCleanup(sys.modules.__setitem__, policy_name, previous_policy)
        self.runs = AtomicMemoryContainer('conversation_id')
        with stubbed_config(
            cosmos_orchestration_runs_container=self.runs,
            cosmos_orchestration_run_steps_container=AtomicMemoryContainer('run_id'),
            cognitive_services_scope='offline-scope',
        ):
            self.editor = importlib.import_module('functions_orchestration_plan_editing')
            self.revisions = importlib.import_module('functions_orchestration_plan_revisions')
            self.store = importlib.import_module('functions_orchestration_runs')
            self.schema = importlib.import_module('functions_orchestration_schema')
            self.planner = importlib.import_module('functions_orchestration_planner')
            self.registry = importlib.import_module('functions_orchestration_registry')
            self.services = importlib.import_module('functions_orchestration_services')
            self.external_sources = importlib.import_module('functions_orchestration_external_sources')
            self.exports = importlib.import_module('functions_generated_export_registry')
            fixtures = importlib.import_module('test_support.orchestration_results')
        self.stack.enter_context(patch.object(self.store, 'cosmos_orchestration_runs_container', self.runs))
        self.fixture = fixtures.ResultFixture()
        self.task = self.fixture.save()
        self.reference = self.task.output('findings')
        self.aliases = {'saved_findings': self.reference}
        self.wire_aliases = {alias: reference.to_dict() for alias, reference in self.aliases.items()}
        self.resolve_aliases = Mock(side_effect=lambda record: self.services.admitted_result_aliases(
            record, self.fixture.service,
        ))
        self.settings = {
            'enable_chat_orchestration': True,
            'enable_user_workspace': True, 'chat_orchestration_max_steps': 8,
        }
        self.snapshot = {'messages': [], 'truncated': False}
        self.profiles = self.services.composition_profiles()
        self.responses = []
        self.model_calls = []

        def complete(**request):
            self.model_calls.append(deepcopy(request))
            if not self.responses:
                raise AssertionError('Unexpected model call')
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    finish_reason='stop',
                    message=SimpleNamespace(content=json.dumps(self.responses.pop(0)), refusal=None),
                )],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
        self.model = SimpleNamespace(
            deployment='offline-planner', as_planner_client=lambda: client, close=Mock(),
            answer_model_selection=lambda: {
                'endpoint_id': 'offline', 'model_id': 'offline-answer', 'provider': 'aoai',
            },
        )
        for name, replacement in {
            'resolve_agent_catalog': lambda *args, **kwargs: [],
            'resolve_action_catalog': lambda *args, **kwargs: [],
            'resolve_candidate_documents': lambda *args, **kwargs: ([], False),
            'validate_memory_audience': lambda *args, **kwargs: None,
            'load_orchestration_memory': lambda *args, **kwargs: {'audience': None, 'scope': None},
            'resolve_orchestration_model': Mock(return_value=self.model),
        }.items():
            self.stack.enter_context(patch.object(self.editor, name, replacement))

    def make_rendering_service(self, *, user_id='owner'):
        artifacts = importlib.import_module('functions_orchestration_artifacts')
        unexpected_io = Mock(side_effect=AssertionError('Editing must not render, publish, or fetch artifacts'))
        before = deepcopy(self.runs.items)
        bound = self.services.OrchestrationServices(
            user_id=user_id, conversation_id='conversation-1',
            result_store=self.fixture.service.store, run_container=self.runs,
            read_conversation=lambda conversation_id: deepcopy(self.fixture.conversation),
            read_run=lambda run_id: deepcopy(self.fixture.runs.get(run_id)),
            source_resolver=self.fixture.resolve, source_metadata_reader=self.fixture.metadata,
            transport=artifacts.OrchestrationArtifactTransport(
                upload=unexpected_io, read_message=unexpected_io, open_stream=unexpected_io,
                delete=unexpected_io, blob_container='private-results',
            ),
            authorize_execution=unexpected_io, max_output_bytes=32 * 1024 * 1024,
        )
        bound.rendering.renderer = unexpected_io
        after = deepcopy(self.runs.items)
        self.assertEqual(after, before)
        unexpected_io.assert_not_called()
        return bound.rendering

    def make_external_provider(self):
        metadata_reader = Mock(side_effect=AssertionError('Discovery must not read external metadata'))
        self.addCleanup(metadata_reader.assert_not_called)
        return self.external_sources.OrchestrationExternalSourceProvider(
            user_id='owner', conversation_id='conversation-1',
            read_identity=metadata_reader, read_settings=metadata_reader,
            read_conversation=metadata_reader, read_run=metadata_reader,
            read_configuration=metadata_reader, configuration_admitter=metadata_reader,
            acquisition_validator=metadata_reader, agent_catalog_reader=metadata_reader,
            action_catalog_reader=metadata_reader, agent_resolver=metadata_reader,
            action_resolver=metadata_reader,
        )

    def make_external_callbacks(self):
        callbacks = {
            name: Mock(name=name, side_effect=AssertionError('Discovery must not invoke external-source callbacks'))
            for name in EXTERNAL_CALLBACK_NAMES if name != 'external_source_preflight'
        }
        provider = self.make_external_provider()
        callbacks['external_source_preflight'] = Mock(
            name='external_source_preflight', wraps=provider.preflight_gather_invocation,
        )
        return callbacks

    def plan(self, *, alias=True, profile=False, run_id='saved-plan', revision=0):
        steps = [{
            'step_id': 'draft', 'capability_id': 'compose',
            'arguments': {'instruction': 'Prepare a concise report from the complete named inputs.'},
            'inputs': {'evidence': {'binding': binding(alias='saved_findings')}} if alias else {},
            'outputs': (
                [{'name': 'deck', 'kind': 'structured-v1', 'profile': 'prepared_slide_deck_v1'}]
                if profile else [{'name': 'answer', 'kind': 'markdown-v1'}]
            ),
            'depends_on': [],
        }]
        raw = {
            'planner_contract_version': 2, 'run_id': run_id,
            'plan_id': f'plan-{run_id}', 'turn_id': 'turn-1', 'revision': revision,
            'intent': {'summary': 'Prepare the requested report.'}, 'steps': steps,
        }
        if not profile:
            raw['final_response'] = binding('draft')
        return self.schema.normalize_plan(
            raw, 'conversation-1', 'owner', settings=self.settings,
            existing_results=self.aliases if alias else {},
            composition_profiles=self.profiles,
        )

    @staticmethod
    def legacy_plan(*, run_id='saved-plan', revision=0):
        """A plan saved by the removed earlier contract, exactly as it was stored."""
        return {
            'planner_contract_version': 1, 'run_id': run_id, 'plan_id': f'plan-{run_id}',
            'turn_id': 'turn-1', 'revision': revision, 'conversation_id': 'conversation-1',
            'user_id': 'owner', 'status': 'awaiting_approval',
            'intent': {'summary': 'Prepare the requested report.'},
            'approval': {'mode': 'manual', 'state': 'pending'},
            'steps': [{
                'step_id': 'answer', 'capability_id': 'respond', 'phase': 'output',
                'arguments': {}, 'enabled': True, 'depends_on': [],
            }],
        }

    def save_legacy(self):
        """Store a run the way the removed contract saved it; nothing may reopen it."""
        record = self.save(alias=False)
        record['plan'] = self.legacy_plan(run_id=record['id'])
        record['planner_contract_version'] = 1
        record.pop('edit_version', None)
        self.runs.upsert_item(record)
        return deepcopy(record)

    def save(self, *, alias=True, profile=False, initial_updates=None):
        context = {
            'planner_contract_version': 2,
            'result_aliases': deepcopy(self.wire_aliases) if alias else {},
            'turn_id': 'turn-1', 'user_message': 'Prepare the requested report.',
            'user_message_id': 'user-message', 'user_message_fingerprint': 'message-fingerprint',
            'seeds': {}, 'original_seeds': {}, 'answered_questions': [],
            'resolved_message': 'Prepare the requested report.',
            'conversation_context': deepcopy(self.snapshot),
        }
        plan = self.plan(alias=alias, profile=profile)
        self.store.create_orchestration_run(
            plan, 'owner', 'conversation-1', turn_index=1, turn_context=context,
            initial_updates=initial_updates,
        )
        record = self.read()
        return record

    def save_native(self):
        record = self.save(alias=False)
        capabilities = self.editor.resolve_available_capabilities(
            self.settings, contract_version=2,
            request_context={'native_bridge_for_step': self.native_factory},
        )
        record['plan'] = self.schema.normalize_plan(
            {
                'planner_contract_version': 2, 'run_id': record['id'],
                'plan_id': record['plan']['plan_id'], 'turn_id': record['turn_id'],
                'steps': [{
                    'step_id': 'native-query', 'capability_id': 'tabular_analyze',
                    'arguments': {
                        'question': 'Keep all complete amount records.',
                        'document_ids': ['document-1'], 'native_operation': 'query',
                        'task_type': 'structured_export', 'query_expression': 'index == index',
                        'columns': ['amount'],
                    },
                }],
            },
            'conversation-1', 'owner', settings=self.settings, contract_version=2,
            available_capability_ids=[item['id'] for item in capabilities],
            authorized_document_ids={'document-1'},
        )
        self.runs.upsert_item(record)
        self.stack.enter_context(patch.object(
            self.editor, 'resolve_authorized_source_manifest',
            side_effect=lambda ids, user_id, **scope: self.fixture.resolve(ids, user_id=user_id, **scope),
        ))
        saved = self.read()
        return saved

    def catalog_subset(self, format_id, *, profiles=None):
        selected = [
            entry for entry in self.exports.get_generated_file_export_catalog()
            if entry['format_id'] == format_id
        ]
        if profiles is not None:
            selected[0]['profiles'] = [
                entry for entry in selected[0]['profiles'] if entry['profile'] in profiles
            ]
        return selected

    def save_render(self, *, output_format='md', profile='prepared_text_v1', alias_source=False):
        record = self.save()
        rendering = self.make_rendering_service()
        context = self.editor._turn_context(record)
        _agents, _actions, caller = self.editor._revision_catalogs(
            context, 'owner', self.settings, {}, contract_version=2, rendering_service=rendering,
        )
        capabilities = self.editor.resolve_available_capabilities(
            self.settings, contract_version=2, request_context=caller,
        )
        raw = deepcopy(record['plan'])
        raw['steps'].append({
            'step_id': 'file', 'capability_id': 'render_file',
            'arguments': {
                'file_name': f'report.{output_format}', 'output_format': output_format, 'profile': profile,
            },
            'inputs': {'source': {
                'binding': binding(alias='saved_findings') if alias_source else binding('draft'),
                'allow_partial': False,
            }},
            'outputs': [], 'depends_on': [] if alias_source else ['draft'],
        })
        record['plan'] = self.schema.normalize_plan(
            raw, 'conversation-1', 'owner', settings=self.settings, contract_version=2,
            available_capability_ids=[entry['id'] for entry in capabilities],
            existing_results=self.aliases, composition_profiles=self.profiles,
        )
        record['plan_summary'] = self.schema.summarize_plan(record['plan'])
        record['capabilities_used'] = list(record['plan_summary']['capabilities_used'])
        self.runs.upsert_item(record)
        saved = self.read()
        return saved, rendering

    def read(self, run_id='saved-plan'):
        return self.revisions.read_revision_run(run_id, 'owner', 'conversation-1')

    def validate(self, record, **kwargs):
        context = self.editor._turn_context(record)
        return self.editor.validate_edited_plan(
            record['plan'], context, 'owner', self.settings, {},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles, **kwargs,
        )

    def edit(self, record, reply, *, data=None, **kwargs):
        self.responses.append(reply)
        return self.editor.build_plan_edit_outcome(
            record, data or {'action': 'ask', 'instruction': 'Focus on the main findings.'},
            'owner', self.settings, identity={}, conversation_context=self.snapshot,
            conversation={'id': 'conversation-1', 'user_id': 'owner'},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles, **kwargs,
        )

    def reply(self, record):
        return {
            'kind': 'plan', 'revised_request': 'Prepare a concise report from the complete findings.',
            **{key: deepcopy(record['plan'][key]) for key in (
                'planner_contract_version', 'steps', 'final_response',
            ) if key in record['plan']},
        }

    def hold(self, record):
        return self.revisions.begin_plan_edit(
            record['id'], 'owner', 'conversation-1', plan_id=record['plan']['plan_id'],
        )

    def publish(self, record, document=None, context=None, *, origin='ai'):
        request = {
            'conversation_id': 'conversation-1', 'submission_id': uuid.uuid4().hex,
            'expected_version': record['edit_version'], 'action': 'ask', 'instruction': 'Refine the report.',
        }
        claim = self.revisions.claim_plan_revision(record['id'], 'owner', 'conversation-1', request)
        return self.revisions.complete_plan_revision(
            claim, kind='plan', document=document or record['plan'],
            turn_context=context or self.editor._turn_context(record), origin=origin,
        )

    def test_creation_preserves_private_wire_aliases_and_contract_without_mutable_sharing(self):
        record = self.save(initial_updates={'planner_contract_version': 1, 'result_aliases': {'forged': {}}})
        self.assertEqual(record['planner_contract_version'], 2)
        self.assertEqual(record['result_aliases'], self.wire_aliases)
        record['result_aliases'].clear()
        saved = self.read()
        self.assertEqual(saved['result_aliases'], self.wire_aliases)
        public = self.revisions.plan_editor_state(saved, 'owner')
        self.assertNotIn('result_aliases', public)
        self.assertNotIn('manifest_sha256', json.dumps(public))

    def test_creation_refuses_mismatched_or_invalid_admission_versions(self):
        for version in (1, True, '2', 3, None):
            with self.subTest(version=version):
                plan = self.plan()
                with self.assertRaises(self.store.ConversationContextError):
                    self.store.create_orchestration_run(
                        plan, 'owner', 'conversation-1', turn_index=1,
                        turn_context={'planner_contract_version': version},
                    )
        self.assertEqual(self.runs.items, {})

    def test_returned_admission_snapshot_does_not_share_the_callers_alias_dictionary(self):
        context = {
            'planner_contract_version': 2, 'turn_id': 'turn-1',
            'result_aliases': deepcopy(self.wire_aliases),
        }
        saved = self.store.create_orchestration_run(
            self.plan(), 'owner', 'conversation-1', turn_index=1, turn_context=context,
        )
        context['result_aliases'].clear()
        self.assertEqual(saved['result_aliases'], self.wire_aliases)

    def test_ordinary_replan_preserves_aliases_when_context_copy_is_omitted(self):
        original = self.save()
        next_plan = self.plan(run_id='replanned', revision=1)
        saved = self.store.create_orchestration_run(
            next_plan, 'owner', 'conversation-1', turn_index=1,
            turn_context={'turn_id': 'turn-1'}, expected_previous_run=original,
        )
        self.assertEqual(saved['planner_contract_version'], 2)
        self.assertEqual(saved['result_aliases'], self.wire_aliases)
        self.assertEqual(saved['plan']['steps'], next_plan['steps'])
        self.assertEqual(saved['parent_run_id'], original['id'])

    def test_ordinary_replan_cannot_migrate_the_saved_contract(self):
        original = self.save()
        legacy = self.legacy_plan(run_id='legacy-replan', revision=1)
        with self.assertRaises(self.store.ConversationContextError):
            self.store.create_orchestration_run(
                legacy, 'owner', 'conversation-1', turn_index=1,
                turn_context={'turn_id': 'turn-1'}, expected_previous_run=original,
            )
        current = self.read()
        self.assertEqual(current, original)
        self.assertEqual(len(self.runs.items), 1)

    def test_real_validation_preserves_bindings_outputs_and_final_response(self):
        original = self.save()
        before = deepcopy(original)
        checked = self.validate(original)
        self.assertEqual(checked['planner_contract_version'], 2)
        self.assertEqual(checked['steps'], original['plan']['steps'])
        self.assertEqual(checked['final_response'], original['plan']['final_response'])
        self.assertEqual(original, before)
        self.assertEqual(self.resolve_aliases.call_count, 1)
        self.assertTrue(self.fixture.source_reads)

    def test_legacy_saved_plan_without_top_level_admission_still_uses_its_v2_plan(self):
        record = self.save()
        record.pop('planner_contract_version')
        context = self.editor._turn_context(record)
        checked = self.validate(record)
        self.assertEqual(context['planner_contract_version'], 2)
        self.assertEqual(checked['planner_contract_version'], 2)

    def test_saved_contract_mismatch_or_unknown_version_is_not_normalized_to_v1(self):
        original = self.save()
        for field in ('record', 'plan'):
            for version in (1, True, '2', 3, None):
                with self.subTest(field=field, version=version):
                    record = deepcopy(original)
                    target = record if field == 'record' else record['plan']
                    target['planner_contract_version'] = version
                    with self.assertRaises(self.revisions.PlanRevisionError) as failure:
                        self.validate(record)
                    # A plan with no marker or the earlier marker gets the one legacy refusal;
                    # any other mismatch is a changed plan.
                    legacy = field == 'plan' and (version is None or type(version) is int and version == 1)
                    self.assertEqual(failure.exception.code, 'legacy_plan' if legacy else 'plan_changed')
        self.resolve_aliases.assert_not_called()

    def test_missing_alias_resolver_fails_closed_without_model_work(self):
        record = self.save()
        context = self.editor._turn_context(record)
        with self.assertRaises(self.revisions.PlanRevisionError) as failure:
            self.editor.validate_edited_plan(record['plan'], context, 'owner', self.settings, {})
        self.assertEqual(failure.exception.code, 'source_changed')
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.editor.build_plan_edit_outcome(
                record, {'action': 'ask', 'instruction': 'Refine the report.'}, 'owner', self.settings,
                identity={}, conversation_context=self.snapshot, conversation={},
            )
        self.assertEqual(self.model_calls, [])
        current = self.read()
        self.assertEqual(current, record)

    def test_revoked_source_access_rejects_edit_validation_and_claim(self):
        record = self.save()
        self.fixture.denied.add('document-1')
        for operation in (
            lambda: self.validate(record),
            lambda: self.edit(record, self.reply(record)),
            lambda: self.revisions.claim_plan_run(
                record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
            ),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(self.revisions.PlanRevisionError) as failure:
                    operation()
                self.assertEqual(failure.exception.code, 'source_changed')
        self.assertEqual(self.model_calls, [])
        current = self.read()
        self.assertEqual(current, record)

    def test_stored_aliases_must_belong_to_the_actor_and_conversation(self):
        record = self.save()
        for field, value in (('user_id', 'someone-else'), ('conversation_id', 'another-conversation')):
            with self.subTest(field=field):
                forged = deepcopy(record)
                forged['result_aliases']['saved_findings']['producer'][field] = value
                with self.assertRaises(self.revisions.PlanRevisionError):
                    self.validate(forged)
        self.resolve_aliases.assert_not_called()

    def test_alias_callback_cannot_add_drop_replace_or_return_wire_descriptors(self):
        record = self.save()
        changed = replace(self.reference, manifest_sha256='0' * 64)
        for resolved in (
            {}, {'extra': self.reference}, {**self.aliases, 'extra': self.reference},
            {'saved_findings': changed}, deepcopy(self.wire_aliases), None,
        ):
            with self.subTest(resolved=resolved):
                with patch.object(self, 'resolve_aliases', Mock(return_value=resolved)):
                    with self.assertRaises(self.revisions.PlanRevisionError):
                        self.validate(record)

    def test_authorizer_failure_is_safe_and_cannot_mutate_the_saved_alias_catalog(self):
        record = self.save()

        def rejected(context):
            context['result_aliases'].clear()
            raise PermissionError('PRIVATE_PROVIDER_AUTHORIZATION_DETAIL')

        with patch.object(self, 'resolve_aliases', Mock(side_effect=rejected)):
            with self.assertRaises(self.revisions.PlanRevisionError) as failure:
                self.validate(record)
        self.assertNotIn('PRIVATE_PROVIDER', str(failure.exception))
        self.assertEqual(record['result_aliases'], self.wire_aliases)

    def test_invalid_stored_descriptor_is_not_accepted_as_an_existing_result(self):
        record = self.save()
        for value in (None, [], {'saved_findings': self.reference}, {'bad alias': self.reference.to_dict()}):
            with self.subTest(value=value):
                record['result_aliases'] = value
                with self.assertRaises(self.revisions.PlanRevisionError):
                    self.validate(record)
        self.resolve_aliases.assert_not_called()

    def test_browser_alias_descriptors_are_not_a_revision_admission_channel(self):
        record = self.hold(self.save())
        request = {
            'conversation_id': 'conversation-1', 'submission_id': uuid.uuid4().hex,
            'expected_version': record['edit_version'], 'action': 'ask',
            'instruction': 'Use these descriptors.', 'result_aliases': deepcopy(self.wire_aliases),
        }
        with self.assertRaises(self.revisions.PlanRevisionError) as failure:
            self.revisions.claim_plan_revision(record['id'], 'owner', 'conversation-1', request)
        self.assertEqual(failure.exception.code, 'invalid_request')
        current = self.read()
        self.assertEqual(current, record)

    def test_inline_existing_result_descriptor_is_rejected_by_real_compiler(self):
        record = self.save()
        record['plan']['steps'][0]['inputs']['evidence']['binding']['existing_result'] = self.reference.to_dict()
        with self.assertRaises(self.revisions.PlanRevisionError) as failure:
            self.validate(record)
        self.assertEqual(failure.exception.code, 'source_changed')

    def test_real_edit_prompt_and_reply_keep_v2_and_only_advertise_authorized_alias_metadata(self):
        record = self.save()
        outcome = self.edit(record, self.reply(record))
        document = outcome['document']
        self.assertEqual(document['planner_contract_version'], 2)
        self.assertEqual(document['steps'], record['plan']['steps'])
        self.assertEqual(document['final_response'], record['plan']['final_response'])
        self.assertEqual(outcome['turn_context']['planner_contract_version'], 2)
        self.assertEqual(outcome['turn_context']['result_aliases'], self.wire_aliases)
        self.model.close.assert_called_once_with()
        payload = json.loads(self.model_calls[0]['messages'][1]['content'])
        self.assertEqual(payload['plan_edit']['current_plan']['planner_contract_version'], 2)
        self.assertEqual(payload['plan_edit']['current_plan']['final_response'], binding('draft'))
        self.assertEqual(payload['retained_results'][0]['alias'], 'saved_findings')
        self.assertNotIn('manifest_sha256', json.dumps(payload))
        self.assertNotIn('respond', [entry['id'] for entry in payload['capabilities']])

    def test_model_cannot_downgrade_a_v2_edit_or_invent_an_alias(self):
        record = self.save()
        for invalid in ('version', 'alias'):
            with self.subTest(invalid=invalid):
                reply = self.reply(record)
                if invalid == 'version':
                    reply['planner_contract_version'] = 1
                else:
                    reply['steps'][0]['inputs']['evidence']['binding']['existing_result'] = 'invented'
                with self.assertRaises(self.planner.PlannerError):
                    self.edit(record, reply)
        current = self.read()
        self.assertEqual(current, record)

    def test_composition_profile_uses_the_exact_shared_prepared_deck_schema(self):
        record = self.save(profile=True)
        checked = self.validate(record)
        outcome = self.edit(record, self.reply(record))
        payload = json.loads(self.model_calls[0]['messages'][1]['content'])
        expected_schema = self.exports.get_prepared_slide_deck_schema()
        self.assertEqual(payload['composition_profiles']['prepared_slide_deck_v1'], expected_schema)
        self.assertEqual(checked['steps'][0]['outputs'], record['plan']['steps'][0]['outputs'])
        self.assertEqual(outcome['document']['steps'][0]['outputs'], record['plan']['steps'][0]['outputs'])
        context = self.editor._turn_context(record)
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.editor.validate_edited_plan(
                record['plan'], context, 'owner', self.settings, {},
                result_alias_resolver=self.resolve_aliases, composition_profiles={},
            )

    def test_live_server_export_catalog_reaches_real_v2_validation_and_replanning(self):
        record = self.save()
        catalog = self.exports.get_generated_file_export_catalog()
        checked = self.validate(record, export_catalog=catalog)
        outcome = self.edit(record, self.reply(record), export_catalog=catalog)
        self.assertEqual(checked['planner_contract_version'], 2)
        self.assertEqual(outcome['document']['planner_contract_version'], 2)
        self.assertEqual(checked['steps'], record['plan']['steps'])

    def test_malformed_export_catalog_remains_an_operational_verification_failure(self):
        record = self.save()
        stale = self.exports.get_generated_file_export_catalog()
        stale[0]['profiles'][0]['profile'] = 'invented-profile'
        duplicate = self.catalog_subset('md')
        duplicate.append(deepcopy(duplicate[0]))
        redefined = self.catalog_subset('md')
        redefined[0]['media_type'] = 'application/invented'
        for catalog in (stale, duplicate, redefined, {}, 'catalog', {'invalid': object()}):
            with self.subTest(catalog=catalog):
                with self.assertRaises(self.registry.CapabilityResolutionError):
                    self.validate(record, export_catalog=catalog)
                with self.assertRaises(self.registry.CapabilityResolutionError):
                    self.edit(record, self.reply(record), export_catalog=catalog)
                with self.assertRaises(self.registry.CapabilityResolutionError):
                    self.revisions.claim_plan_run(
                        record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
                        export_catalog=catalog,
                    )
        self.assertEqual(self.model_calls, [])
        current = self.read()
        self.assertEqual(current, record)
        self.assertNotIn('execution_lease', current)

    def test_export_catalog_verification_preserves_the_exact_operational_error_and_cause(self):
        record, rendering = self.save_render()
        catalog = self.catalog_subset('md')
        checked = self.validate(record, export_catalog=catalog, rendering_service=rendering)
        self.assertEqual(checked['steps'], record['plan']['steps'])
        cause = ValueError('Private metadata verification detail')
        error = self.registry.CapabilityResolutionError('Catalog verification failed.')
        error.__cause__ = cause
        operations = (
            lambda: self.validate(record, export_catalog=catalog, rendering_service=rendering),
            lambda: self.edit(record, self.reply(record), export_catalog=catalog, rendering_service=rendering),
            lambda: self.revisions.claim_plan_run(
                record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
                export_catalog=catalog, composition_profiles=self.profiles,
            ),
        )
        with patch.object(self.revisions, 'resolve_admitted_export_catalog', side_effect=error):
            for operation in operations:
                with self.subTest(operation=operation):
                    with self.assertRaises(self.registry.CapabilityResolutionError) as failure:
                        operation()
                    self.assertIs(failure.exception, error)
                    self.assertIs(failure.exception.__cause__, cause)
        current = self.read()
        self.assertEqual(current, record)
        self.assertNotIn('execution_lease', current)
        self.assertEqual(self.model_calls, [])
        rendering.renderer.assert_not_called()

    def test_empty_export_catalog_preserves_non_file_work_without_advertising_render(self):
        record = self.hold(self.save())
        rendering = self.make_rendering_service()
        checked = self.validate(record, export_catalog=[], rendering_service=rendering)
        outcome = self.edit(record, self.reply(record), export_catalog=[], rendering_service=rendering)
        payload = json.loads(self.model_calls[0]['messages'][1]['content'])
        published = self.publish(record, outcome['document'], outcome['turn_context'])
        self.assertNotIn('render_file', [entry['id'] for entry in payload['capabilities']])
        self.assertEqual(checked['steps'], record['plan']['steps'])
        self.assertEqual(published['plan']['steps'], record['plan']['steps'])
        serialized = json.dumps({'outcome': outcome, 'published': published})
        self.assertNotIn('export_catalog', serialized)
        rendering.renderer.assert_not_called()

    def test_export_catalog_subset_preserves_files_edges_and_exact_planner_pairs(self):
        record, rendering = self.save_render()
        catalog = self.catalog_subset('md')
        default_checked = self.validate(record, rendering_service=rendering)
        with patch.object(self.editor, 'normalize_plan', wraps=self.editor.normalize_plan) as normalize:
            checked = self.validate(record, export_catalog=catalog, rendering_service=rendering)
        with patch.object(self.editor, 'plan_request', wraps=self.editor.plan_request) as planner:
            outcome = self.edit(record, self.reply(record), export_catalog=catalog, rendering_service=rendering)
        payload = json.loads(self.model_calls[0]['messages'][1]['content'])
        render = next(entry for entry in payload['capabilities'] if entry['id'] == 'render_file')
        pairs = {
            (entry['properties']['output_format']['const'], entry['properties']['profile']['const'])
            for entry in render['inputs']['oneOf']
        }
        self.assertEqual(pairs, {('md', 'prepared_text_v1')})
        self.assertEqual(normalize.call_args.kwargs['export_catalog'], catalog)
        self.assertEqual(planner.call_args.kwargs['export_catalog'], catalog)
        self.assertEqual(default_checked['steps'], record['plan']['steps'])
        self.assertEqual(checked['steps'], record['plan']['steps'])
        self.assertEqual(outcome['document']['steps'], record['plan']['steps'])
        self.assertEqual(outcome['document']['steps'][1]['depends_on'], ['draft'])
        rendering.renderer.assert_not_called()

    def test_unadmitted_export_catalog_pairs_fail_before_model_or_lease_without_dropping_files(self):
        record, rendering = self.save_render()
        for catalog in ([], self.catalog_subset('txt'), self.catalog_subset('md', profiles=[])):
            with self.subTest(catalog=catalog):
                with self.assertRaises(self.revisions.PlanRevisionError) as failure:
                    self.validate(record, export_catalog=catalog, rendering_service=rendering)
                self.assertEqual(failure.exception.code, 'source_changed')
                with self.assertRaises(self.schema.PlanValidationError) as failure:
                    self.edit(record, self.reply(record), export_catalog=catalog, rendering_service=rendering)
                self.assertEqual(failure.exception.code, 'capability_unavailable')
                with self.assertRaises(self.schema.PlanValidationError) as failure:
                    self.revisions.claim_plan_run(
                        record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
                        composition_profiles=self.profiles, export_catalog=catalog,
                    )
                self.assertEqual(failure.exception.code, 'capability_unavailable')
        current = self.read()
        self.assertEqual(current, record)
        self.assertNotIn('execution_lease', current)
        self.assertEqual(self.model_calls, [])
        rendering.renderer.assert_not_called()

    def test_export_catalog_profile_filter_does_not_substitute_a_different_real_profile(self):
        record, rendering = self.save_render(
            output_format='json', profile='exact_records_v1', alias_source=True,
        )
        allowed = self.catalog_subset('json', profiles=['exact_records_v1'])
        checked = self.validate(record, export_catalog=allowed, rendering_service=rendering)
        narrowed = self.catalog_subset('json', profiles=['structured_records_v1'])
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.validate(record, export_catalog=narrowed, rendering_service=rendering)
        with self.assertRaises(self.schema.PlanValidationError) as failure:
            self.edit(record, self.reply(record), export_catalog=narrowed, rendering_service=rendering)
        self.assertEqual(failure.exception.code, 'capability_unavailable')
        self.assertEqual(checked['steps'], record['plan']['steps'])
        self.assertEqual(checked['steps'][1]['arguments']['profile'], 'exact_records_v1')
        current = self.read()
        self.assertEqual(current, record)
        self.assertEqual(self.model_calls, [])

    def test_export_catalog_restore_uses_current_admission_without_saved_permissions(self):
        record, rendering = self.save_render()
        original = self.hold(record)
        newer = self.publish(original)
        outcome = self.editor.build_plan_edit_outcome(
            newer, {'action': 'restore', 'source_run_id': original['id']}, 'owner', self.settings,
            identity={}, conversation_context=self.snapshot, conversation={},
            result_alias_resolver=self.resolve_aliases, export_catalog=[], rendering_service=rendering,
        )
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.editor.validate_edited_plan(
                outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
                result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
                export_catalog=[], rendering_service=rendering,
            )
        checked = self.editor.validate_edited_plan(
            outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
            export_catalog=self.catalog_subset('md'), rendering_service=rendering,
        )
        restored = self.publish(newer, checked, outcome['turn_context'], origin='restore')
        serialized = json.dumps({'outcome': outcome, 'restored': restored})
        self.assertNotIn('export_catalog', serialized)
        self.assertEqual(restored['plan']['steps'], original['plan']['steps'])

    def test_export_catalog_pending_answer_rechecks_current_admission_before_model_work(self):
        record, rendering = self.save_render()
        question = {
            'kind': 'elicitation', 'message': 'Which report emphasis should be used?',
            'requested_schema': {
                'type': 'object', 'properties': {'emphasis': {'type': 'string'}},
                'required': ['emphasis'], 'additionalProperties': False,
            },
        }
        asked = self.edit(
            record, question, export_catalog=self.catalog_subset('md'), rendering_service=rendering,
        )
        record['edit_pending'] = asked['pending']
        with self.assertRaises(self.schema.PlanValidationError) as failure:
            self.edit(
                record, self.reply(record),
                data={'action': 'answer', 'elicitation_response': {
                    'action': 'accept', 'content': {'emphasis': 'Risks'},
                }},
                export_catalog=[], rendering_service=rendering,
            )
        self.assertEqual(failure.exception.code, 'capability_unavailable')
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual(record['edit_pending'], asked['pending'])
        serialized = json.dumps(asked)
        self.assertNotIn('export_catalog', serialized)

    def test_export_catalog_claim_validates_pairs_and_profiles_without_persisting_permissions(self):
        record, rendering = self.save_render()
        catalog = self.catalog_subset('md')
        with patch.object(self.revisions, 'apply_plan_edits', wraps=self.revisions.apply_plan_edits) as apply:
            claimed = self.revisions.claim_plan_run(
                record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
                export_catalog=catalog, composition_profiles=self.profiles,
            )
        self.assertEqual(apply.call_args.kwargs['export_catalog'], catalog)
        self.assertEqual(apply.call_args.kwargs['composition_profiles'], self.profiles)
        self.assertEqual(apply.call_args.kwargs['contract_version'], 2)
        self.assertEqual(claimed['plan']['steps'], record['plan']['steps'])
        self.assertEqual(claimed['status'], 'running')
        self.assertTrue(claimed['execution_lease'])
        serialized = json.dumps(claimed)
        self.assertNotIn('export_catalog', serialized)
        self.assertNotIn('composition_profiles', serialized)
        rendering.renderer.assert_not_called()

    def test_export_catalog_claim_keeps_prepared_composition_profiles_separate(self):
        record = self.save(profile=True)
        with self.assertRaises(self.schema.PlanValidationError):
            self.revisions.claim_plan_run(
                record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
                export_catalog=[], composition_profiles={},
            )
        current = self.read()
        self.assertEqual(current, record)
        claimed = self.revisions.claim_plan_run(
            record['id'], 'owner', 'conversation-1', result_alias_resolver=self.resolve_aliases,
            export_catalog=[], composition_profiles=self.profiles,
        )
        self.assertEqual(claimed['plan']['steps'], record['plan']['steps'])
        self.assertEqual(claimed['status'], 'running')

    def test_external_callbacks_are_forwarded_unchanged_for_v2_validation_without_io(self):
        callbacks = self.make_external_callbacks()
        native = Mock(side_effect=AssertionError('Discovery must not invoke native work'))
        rendering = self.make_rendering_service()
        record = self.save()
        with patch.object(
            self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
        ) as discover:
            checked = self.validate(
                record, native_bridge_for_step=native, rendering_service=rendering, **callbacks,
            )
        caller = discover.call_args.kwargs['request_context']
        self.assertIs(caller['native_bridge_for_step'], native)
        self.assertIs(caller['rendering_service'], rendering)
        context = self.editor._turn_context(record)
        serialized = json.dumps({'context': context, 'plan': checked})
        for name, callback in callbacks.items():
            self.assertIs(caller[name], callback)
            self.assertNotIn(name, serialized)
            callback.assert_not_called()
        self.assertEqual(checked['steps'], record['plan']['steps'])
        native.assert_not_called()
        rendering.authorize_execution.assert_not_called()
        rendering.renderer.assert_not_called()

    def test_external_callbacks_are_ephemeral_during_replanning_and_publication(self):
        callbacks = self.make_external_callbacks()
        record = self.hold(self.save())
        with patch.object(self.editor, 'plan_request', wraps=self.editor.plan_request) as planner:
            outcome = self.edit(record, self.reply(record), **callbacks)
        caller = planner.call_args.kwargs['request_context']
        published = self.publish(record, outcome['document'], outcome['turn_context'])
        serialized = json.dumps({'outcome': outcome, 'published': published})
        requests = json.dumps(self.model_calls)
        for name, callback in callbacks.items():
            self.assertIs(caller[name], callback)
            self.assertNotIn(name, serialized)
            self.assertNotIn(repr(callback), requests)
            callback.assert_not_called()
        self.assertEqual(published['plan']['steps'], record['plan']['steps'])
        self.assertEqual(published['result_aliases'], self.wire_aliases)

    def test_external_preflight_forwards_the_actual_bound_provider_guard_without_io(self):
        provider = self.make_external_provider()
        preflight = provider.preflight_gather_invocation
        callbacks = self.make_external_callbacks()
        callbacks['external_source_preflight'] = preflight
        record = self.save()
        with patch.object(
            self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
        ) as discover:
            checked = self.validate(record, **callbacks)
        with patch.object(self.editor, 'plan_request', wraps=self.editor.plan_request) as planner:
            outcome = self.edit(record, self.reply(record), **callbacks)
        self.assertIs(discover.call_args.kwargs['request_context']['external_source_preflight'], preflight)
        self.assertIs(planner.call_args.kwargs['request_context']['external_source_preflight'], preflight)
        self.assertIs(preflight.__self__, provider)
        self.assertIs(
            preflight.__func__,
            self.external_sources.OrchestrationExternalSourceProvider.preflight_gather_invocation,
        )
        self.assertEqual(checked['steps'], record['plan']['steps'])
        self.assertEqual(outcome['document']['steps'], record['plan']['steps'])
        serialized = json.dumps({'context': self.editor._turn_context(record), 'outcome': outcome})
        self.assertNotIn('external_source_preflight', serialized)
        for name, callback in callbacks.items():
            if name != 'external_source_preflight':
                callback.assert_not_called()

    def test_external_callbacks_require_all_four_callable_bindings_before_model_work(self):
        callbacks = self.make_external_callbacks()
        record = self.save()
        invalid_options = [
            {name: callbacks[name] for name in names}
            for count in range(1, len(EXTERNAL_CALLBACK_NAMES))
            for names in combinations(EXTERNAL_CALLBACK_NAMES, count)
        ]
        for name in EXTERNAL_CALLBACK_NAMES:
            for invalid in (False, True, 'initialized', {'ready': True}):
                invalid_options.append({**callbacks, name: invalid})
        for options in invalid_options:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.validate(record, **options)
                with self.assertRaises(ValueError):
                    self.edit(record, self.reply(record), **options)
        self.assertEqual(self.model_calls, [])
        current = self.read()
        self.assertEqual(current, record)
        for callback in callbacks.values():
            callback.assert_not_called()

    def test_external_callbacks_are_absent_by_default_despite_stored_or_settings_flags(self):
        record = self.save()
        flags = {name: True for name in EXTERNAL_CALLBACK_NAMES}
        record.update(flags)
        self.settings.update(flags)
        with patch.object(
            self.editor, 'build_capability_request_context', wraps=self.editor.build_capability_request_context,
        ) as build_context:
            checked = self.validate(record, **{name: None for name in EXTERNAL_CALLBACK_NAMES})
            outcome = self.edit(record, self.reply(record))
        for invocation in build_context.call_args_list:
            for name in EXTERNAL_CALLBACK_NAMES:
                self.assertNotIn(name, invocation.kwargs)
        serialized = json.dumps({'plan': checked, 'outcome': outcome})
        for name in EXTERNAL_CALLBACK_NAMES:
            self.assertNotIn(name, serialized)
        self.assertEqual(checked['planner_contract_version'], 2)
        self.assertEqual(outcome['document']['planner_contract_version'], 2)

    def test_external_callbacks_are_resupplied_for_restore_without_persistence(self):
        callbacks = self.make_external_callbacks()
        original = self.hold(self.save(profile=True))
        newer = self.publish(original)
        outcome = self.editor.build_plan_edit_outcome(
            newer, {'action': 'restore', 'source_run_id': original['id']}, 'owner', self.settings,
            identity={}, conversation_context=self.snapshot, conversation={},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles, **callbacks,
        )
        with patch.object(
            self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
        ) as discover:
            checked = self.editor.validate_edited_plan(
                outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
                result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles, **callbacks,
            )
        restored = self.publish(newer, checked, outcome['turn_context'], origin='restore')
        serialized = json.dumps({'outcome': outcome, 'restored': restored})
        for name, callback in callbacks.items():
            self.assertIs(discover.call_args.kwargs['request_context'][name], callback)
            self.assertNotIn(name, serialized)
            callback.assert_not_called()
        self.assertEqual(restored['plan']['steps'], original['plan']['steps'])
        self.assertEqual(restored['result_aliases'], self.wire_aliases)

    def test_external_callbacks_are_not_reused_from_pending_edit_answers(self):
        initial = self.make_external_callbacks()
        current = self.make_external_callbacks()
        record = self.save()
        question = {
            'kind': 'elicitation', 'message': 'Which report emphasis should be used?',
            'requested_schema': {
                'type': 'object', 'properties': {'emphasis': {'type': 'string'}},
                'required': ['emphasis'], 'additionalProperties': False,
            },
        }
        asked = self.edit(record, question, **initial)
        record['edit_pending'] = asked['pending']
        with patch.object(self.editor, 'plan_request', wraps=self.editor.plan_request) as planner:
            outcome = self.edit(
                record, self.reply(record),
                data={'action': 'answer', 'elicitation_response': {
                    'action': 'accept', 'content': {'emphasis': 'Risks'},
                }},
                **current,
            )
        serialized = json.dumps({'asked': asked, 'outcome': outcome})
        for name in EXTERNAL_CALLBACK_NAMES:
            self.assertIs(planner.call_args.kwargs['request_context'][name], current[name])
            self.assertNotIn(name, serialized)
            initial[name].assert_not_called()
            current[name].assert_not_called()
        self.assertEqual(outcome['document']['steps'], record['plan']['steps'])

    def test_external_callback_keywords_are_optional_and_keyword_only(self):
        for function in (
            self.editor.validate_edited_plan, self.editor.build_plan_edit_outcome, self.editor._revision_catalogs,
        ):
            parameters = inspect.signature(function).parameters
            for name in EXTERNAL_CALLBACK_NAMES:
                self.assertIsNone(parameters[name].default)
                self.assertEqual(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_typed_render_service_and_native_factory_are_ephemeral_v2_dependencies(self):
        rendering = self.make_rendering_service()
        native_factory = Mock(side_effect=AssertionError('Editing must not initialize native work'))
        record = self.save()
        with patch.object(
            self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
        ) as discover:
            checked = self.validate(
                record, native_bridge_for_step=native_factory,
                rendering_service=rendering,
            )
        caller = discover.call_args.kwargs['request_context']
        self.assertIs(caller['rendering_service'], rendering)
        self.assertIs(caller['native_bridge_for_step'], native_factory)
        self.assertEqual(checked['steps'], record['plan']['steps'])
        context = self.editor._turn_context(record)
        serialized = json.dumps({'context': context, 'plan': checked})
        self.assertNotIn('rendering_service', serialized)
        self.assertNotIn('native_bridge_for_step', serialized)
        rendering.authorize_execution.assert_not_called()
        rendering.renderer.assert_not_called()
        native_factory.assert_not_called()

    def test_render_requires_a_typed_actor_bound_service_not_boolean_or_factory_readiness(self):
        record = self.save()
        record['rendering_service'] = True
        self.settings['rendering_service'] = True
        with patch.object(
            self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
        ) as discover:
            checked = self.validate(record)
        caller = discover.call_args.kwargs['request_context']
        self.assertNotIn('rendering_service', caller)
        available = self.editor.resolve_available_capabilities(
            self.settings, contract_version=2, request_context=caller,
        )
        self.assertNotIn('render_file', [item['id'] for item in available])
        self.assertEqual(checked['planner_contract_version'], 2)
        factory = Mock(side_effect=AssertionError('An execution factory is not a discovery service'))
        foreign = self.make_rendering_service(user_id='someone-else')
        for invalid in (False, True, {'ready': True}, factory, foreign):
            with self.subTest(service=invalid):
                with self.assertRaises(ValueError):
                    self.validate(record, rendering_service=invalid)
        factory.assert_not_called()

    def test_render_service_replan_is_not_executed_or_persisted(self):
        rendering = self.make_rendering_service()
        record = self.hold(self.save())
        with patch.object(self.editor, 'plan_request', wraps=self.editor.plan_request) as planner:
            outcome = self.edit(record, self.reply(record), rendering_service=rendering)
        self.assertIs(planner.call_args.kwargs['request_context']['rendering_service'], rendering)
        serialized = json.dumps(outcome)
        self.assertNotIn('rendering_service', serialized)
        published = self.publish(record, outcome['document'], outcome['turn_context'])
        self.assertEqual(published['plan']['steps'], record['plan']['steps'])
        self.assertNotIn('rendering_service', published)
        rendering.authorize_execution.assert_not_called()
        rendering.renderer.assert_not_called()

    def test_typed_render_service_is_supplied_again_for_restore_validation(self):
        rendering = self.make_rendering_service()
        original = self.hold(self.save(profile=True))
        newer = self.publish(original)
        outcome = self.editor.build_plan_edit_outcome(
            newer, {'action': 'restore', 'source_run_id': original['id']}, 'owner', self.settings,
            identity={}, conversation_context=self.snapshot, conversation={},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
            rendering_service=rendering,
        )
        serialized = json.dumps(outcome)
        self.assertNotIn('rendering_service', serialized)
        checked = self.editor.validate_edited_plan(
            outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
            rendering_service=rendering,
        )
        restored = self.publish(newer, checked, outcome['turn_context'], origin='restore')
        self.assertEqual(restored['plan']['steps'], original['plan']['steps'])
        self.assertEqual(restored['result_aliases'], self.wire_aliases)
        rendering.authorize_execution.assert_not_called()
        rendering.renderer.assert_not_called()

    def test_typed_render_service_is_not_saved_in_pending_edit_answers(self):
        rendering = self.make_rendering_service()
        record = self.save()
        question = {
            'kind': 'elicitation', 'message': 'Which report emphasis should be used?',
            'requested_schema': {
                'type': 'object', 'properties': {'emphasis': {'type': 'string'}},
                'required': ['emphasis'], 'additionalProperties': False,
            },
        }
        asked = self.edit(record, question, rendering_service=rendering)
        serialized = json.dumps(asked)
        self.assertNotIn('rendering_service', serialized)
        record['edit_pending'] = asked['pending']
        outcome = self.edit(
            record, self.reply(record),
            data={'action': 'answer', 'elicitation_response': {
                'action': 'accept', 'content': {'emphasis': 'Risks'},
            }},
            rendering_service=rendering,
        )
        self.assertEqual(outcome['document']['steps'], record['plan']['steps'])
        serialized = json.dumps(outcome)
        self.assertNotIn('rendering_service', serialized)
        rendering.authorize_execution.assert_not_called()
        rendering.renderer.assert_not_called()

    def test_render_instance_is_the_only_added_discovery_field(self):
        rendering = self.make_rendering_service()
        record = self.save()
        context = self.editor._turn_context(record)
        _agents, _actions, original = self.editor._revision_catalogs(
            context, 'owner', self.settings, {}, contract_version=2,
        )
        _agents, _actions, caller = self.editor._revision_catalogs(
            context, 'owner', self.settings, {}, contract_version=2, rendering_service=rendering,
        )
        self.assertEqual(caller, {**original, 'rendering_service': rendering})
        rendering.authorize_execution.assert_not_called()
        rendering.renderer.assert_not_called()

    def test_editor_signatures_expose_only_the_confirmed_render_instance_keyword(self):
        for function in (self.editor.validate_edited_plan, self.editor.build_plan_edit_outcome):
            parameters = inspect.signature(function).parameters
            self.assertIn('rendering_service', parameters)
            self.assertIsNone(parameters['rendering_service'].default)
            self.assertNotIn('rendering_service_factory', parameters)

    def test_native_factory_is_forwarded_to_v2_validation_without_execution_or_persistence(self):
        self.native_factory = Mock(side_effect=AssertionError('Planning must not execute native work'))
        record = self.save_native()
        with patch.object(
            self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
        ) as discover:
            checked = self.validate(record, native_bridge_for_step=self.native_factory)
        caller = discover.call_args.kwargs['request_context']
        self.assertIs(caller['native_bridge_for_step'], self.native_factory)
        self.assertEqual(checked['steps'], record['plan']['steps'])
        self.assertEqual(checked['planner_contract_version'], 2)
        self.native_factory.assert_not_called()
        context = self.editor._turn_context(record)
        self.assertNotIn('native_bridge_for_step', context)
        serialized = json.dumps(checked)
        self.assertNotIn('native_bridge_for_step', serialized)

    def test_native_missing_boolean_or_flag_readiness_never_admits_a_saved_v2_native_plan(self):
        self.native_factory = Mock(side_effect=AssertionError('Planning must not execute native work'))
        record = self.save_native()
        record['native_bridge_for_step'] = True
        self.settings.update(native_bridge_for_step=True)
        for factory in (None, False, True, {'ready': True}):
            with self.subTest(factory=factory):
                with patch.object(
                    self.editor, 'resolve_available_capabilities', wraps=self.editor.resolve_available_capabilities,
                ) as discover:
                    with self.assertRaises(self.revisions.PlanRevisionError) as failure:
                        self.validate(record, native_bridge_for_step=factory)
                self.assertEqual(failure.exception.code, 'source_changed')
                self.assertNotIn('native_bridge_for_step', discover.call_args.kwargs['request_context'])
        self.native_factory.assert_not_called()

    def test_native_replan_uses_the_server_factory_only_in_ephemeral_request_context(self):
        self.native_factory = Mock(side_effect=AssertionError('Planning must not execute native work'))
        record = self.hold(self.save_native())
        with patch.object(self.editor, 'plan_request', wraps=self.editor.plan_request) as planner:
            outcome = self.edit(record, self.reply(record), native_bridge_for_step=self.native_factory)
        self.assertIs(planner.call_args.kwargs['request_context']['native_bridge_for_step'], self.native_factory)
        self.assertEqual(outcome['document']['steps'], record['plan']['steps'])
        payload = json.loads(self.model_calls[0]['messages'][1]['content'])
        self.assertIn('tabular_analyze', [item['id'] for item in payload['capabilities']])
        serialized = json.dumps(outcome)
        self.assertNotIn('native_bridge_for_step', serialized)
        published = self.publish(record, outcome['document'], outcome['turn_context'])
        self.assertNotIn('native_bridge_for_step', published)
        self.assertEqual(published['plan']['steps'], record['plan']['steps'])
        self.native_factory.assert_not_called()

    def test_native_restore_requires_a_fresh_server_factory_for_validation(self):
        self.native_factory = Mock(side_effect=AssertionError('Planning must not execute native work'))
        original = self.hold(self.save_native())
        newer = self.publish(original)
        outcome = self.editor.build_plan_edit_outcome(
            newer, {'action': 'restore', 'source_run_id': original['id']}, 'owner', self.settings,
            identity={}, conversation_context=self.snapshot, conversation={},
            native_bridge_for_step=self.native_factory,
        )
        serialized = json.dumps(outcome)
        self.assertNotIn('native_bridge_for_step', serialized)
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.editor.validate_edited_plan(
                outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
            )
        checked = self.editor.validate_edited_plan(
            outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
            native_bridge_for_step=self.native_factory,
        )
        restored = self.publish(newer, checked, outcome['turn_context'], origin='restore')
        self.assertEqual(restored['plan']['steps'], original['plan']['steps'])
        self.assertEqual(restored['planner_contract_version'], 2)
        self.native_factory.assert_not_called()

    def test_native_pending_answer_needs_the_current_factory_without_storing_it(self):
        self.native_factory = Mock(side_effect=AssertionError('Planning must not execute native work'))
        record = self.save_native()
        question = {
            'kind': 'elicitation', 'message': 'Which explanation should accompany these records?',
            'requested_schema': {
                'type': 'object', 'properties': {'emphasis': {'type': 'string'}},
                'required': ['emphasis'], 'additionalProperties': False,
            },
        }
        asked = self.edit(record, question, native_bridge_for_step=self.native_factory)
        serialized = json.dumps(asked)
        self.assertNotIn('native_bridge_for_step', serialized)
        record['edit_pending'] = asked['pending']
        outcome = self.edit(
            record, self.reply(record),
            data={'action': 'answer', 'elicitation_response': {
                'action': 'accept', 'content': {'emphasis': 'Show every record'},
            }},
            native_bridge_for_step=self.native_factory,
        )
        self.assertEqual(outcome['document']['steps'], record['plan']['steps'])
        self.assertEqual(outcome['turn_context']['planner_contract_version'], 2)
        serialized = json.dumps(outcome)
        self.assertNotIn('native_bridge_for_step', serialized)
        self.native_factory.assert_not_called()

    def test_revision_publication_and_projection_keep_the_complete_v2_graph(self):
        record = self.hold(self.save())
        outcome = self.edit(record, self.reply(record))
        checked = self.editor.validate_edited_plan(
            outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
        )
        published = self.publish(record, checked, outcome['turn_context'])
        public = self.revisions.plan_editor_state(published, 'owner')
        self.assertEqual(published['planner_contract_version'], 2)
        self.assertEqual(published['result_aliases'], self.wire_aliases)
        self.assertEqual(published['plan']['steps'], checked['steps'])
        self.assertEqual(published['plan']['final_response'], checked['final_response'])
        self.assertEqual(public['plan']['steps'], published['plan']['steps'])
        self.assertEqual(public['plan']['final_response'], checked['final_response'])
        self.assertNotIn('result_aliases', public['plan'])
        self.assertNotIn('manifest_sha256', json.dumps(public))

    def test_revision_keeps_inferred_and_explicit_dependency_edges(self):
        record = self.save()
        raw = deepcopy(record['plan'])
        raw['steps'].append({
            'step_id': 'summary', 'capability_id': 'compose',
            'arguments': {'instruction': 'Summarize the complete prepared report.'},
            'inputs': {'report': {'binding': binding('draft')}},
            'outputs': [{'name': 'answer', 'kind': 'text-v1'}],
            'depends_on': ['draft'],
        })
        raw['final_response'] = binding('summary')
        record['plan'] = self.schema.normalize_plan(
            raw, 'conversation-1', 'owner', settings=self.settings, contract_version=2,
            existing_results=self.aliases,
        )
        self.runs.upsert_item(record)
        current = self.read()
        held = self.hold(current)
        outcome = self.edit(held, self.reply(held))
        published = self.publish(held, outcome['document'], outcome['turn_context'])
        self.assertEqual(published['plan']['steps'], held['plan']['steps'])
        self.assertEqual(published['plan']['steps'][1]['depends_on'], ['draft'])
        self.assertEqual(published['plan']['final_response'], binding('summary'))

    def test_revision_publication_cannot_change_contract_versions(self):
        held = self.hold(self.save())
        legacy = self.legacy_plan()
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.publish(held, legacy, {'planner_contract_version': 1})
        current = self.read()
        self.assertEqual(current['plan'], held['plan'])
        self.assertEqual(current['result_aliases'], self.wire_aliases)
        self.assertEqual(len(self.runs.items), 1)

    def test_restore_reauthorizes_source_context_and_preserves_v2_outputs(self):
        original = self.hold(self.save(profile=True))
        newer = self.publish(original)
        outcome = self.editor.build_plan_edit_outcome(
            newer, {'action': 'restore', 'source_run_id': original['id']}, 'owner', self.settings,
            identity={}, conversation_context=self.snapshot, conversation={},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
        )
        checked = self.editor.validate_edited_plan(
            outcome['document'], outcome['turn_context'], 'owner', self.settings, {},
            result_alias_resolver=self.resolve_aliases, composition_profiles=self.profiles,
        )
        restored = self.publish(newer, checked, outcome['turn_context'], origin='restore')
        self.assertEqual(restored['plan']['planner_contract_version'], 2)
        self.assertEqual(restored['planner_contract_version'], 2)
        self.assertEqual(restored['result_aliases'], original['result_aliases'])
        self.assertEqual(restored['plan']['steps'], original['plan']['steps'])
        self.assertEqual(restored['revision_origin'], 'restore')
        self.assertEqual(self.model_calls, [])

    def test_restore_refuses_revoked_aliases_without_mutating_the_current_plan(self):
        original = self.hold(self.save())
        newer = self.publish(original)
        self.fixture.denied.add('document-1')
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.editor.build_plan_edit_outcome(
                newer, {'action': 'restore', 'source_run_id': original['id']}, 'owner', self.settings,
                identity={}, conversation_context=self.snapshot, conversation={},
                result_alias_resolver=self.resolve_aliases,
            )
        current = self.read(newer['id'])
        self.assertEqual(current, newer)
        self.assertEqual(self.model_calls, [])

    def test_v2_claim_reauthorizes_aliases_without_changing_execution_lease_semantics(self):
        record = self.save()
        claimed = self.revisions.claim_plan_run(
            record['id'], 'owner', 'conversation-1',
            result_alias_resolver=self.resolve_aliases,
        )
        self.assertEqual(claimed['status'], 'running')
        self.assertEqual(claimed['plan']['steps'], record['plan']['steps'])
        self.assertEqual(claimed['result_aliases'], self.wire_aliases)
        self.assertTrue(claimed['started_at'])
        self.assertTrue(claimed['execution_lease'])
        self.assertTrue(claimed['recovery_version'])
        self.assertEqual(claimed['attempt_index'], 1)
        with self.assertRaises(self.revisions.PlanRevisionError) as failure:
            self.revisions.claim_plan_run(
                record['id'], 'owner', 'conversation-1',
                result_alias_resolver=self.resolve_aliases,
            )
        self.assertEqual(failure.exception.code, 'already_run')
        self.assertEqual(self.resolve_aliases.call_count, 1)

    def test_claim_missing_alias_resolver_does_not_create_a_lease(self):
        record = self.save()
        with self.assertRaises(self.revisions.PlanRevisionError):
            self.revisions.claim_plan_run(record['id'], 'owner', 'conversation-1')
        current = self.read()
        self.assertEqual(current, record)
        self.assertNotIn('execution_lease', current)

    def test_pending_edit_answer_preserves_private_admission_context_with_flag_off(self):
        record = self.save()
        question = {
            'kind': 'elicitation', 'message': 'Which emphasis should the report use?',
            'requested_schema': {
                'type': 'object', 'properties': {'emphasis': {'type': 'string'}},
                'required': ['emphasis'], 'additionalProperties': False,
            },
        }
        asked = self.edit(record, question)
        self.assertEqual(asked['kind'], 'elicitation')
        self.assertEqual(asked['pending']['turn_context']['planner_contract_version'], 2)
        self.assertEqual(asked['pending']['turn_context']['result_aliases'], self.wire_aliases)
        record['edit_pending'] = asked['pending']
        outcome = self.edit(record, self.reply(record), data={
            'action': 'answer', 'elicitation_response': {
                'action': 'accept', 'content': {'emphasis': 'Risks'},
            },
        })
        self.assertEqual(outcome['document']['planner_contract_version'], 2)
        self.assertEqual(outcome['turn_context']['result_aliases'], self.wire_aliases)
        self.assertEqual(outcome['turn_context']['planner_contract_version'], 2)

    def test_discard_still_works_after_source_revocation(self):
        record = self.save()
        self.fixture.denied.add('document-1')
        outcome = self.editor.build_plan_edit_outcome(
            record, {'action': 'discard'}, 'owner', self.settings, identity={},
            conversation_context=self.snapshot, conversation={},
        )
        self.assertEqual(outcome['kind'], 'discard')
        self.assertEqual(self.model_calls, [])
        self.resolve_aliases.assert_not_called()

    def test_saved_legacy_plan_is_refused_before_validation_editing_claiming_or_discovery(self):
        record = self.save_legacy()
        before = deepcopy(self.runs.items)
        callbacks = self.make_external_callbacks()
        native = Mock(side_effect=AssertionError('A legacy plan must not reach native discovery'))
        rendering = self.make_rendering_service()
        forbidden = Mock(side_effect=AssertionError('A legacy plan must not be rediscovered or replanned'))
        operations = {
            'read': lambda: self.read(),
            'validate': lambda: self.validate(
                record, native_bridge_for_step=native, rendering_service=rendering, **callbacks,
            ),
            'edit': lambda: self.edit(
                record, {'kind': 'plan'}, export_catalog=[], native_bridge_for_step=native,
                rendering_service=rendering, **callbacks,
            ),
            'claim': lambda: self.revisions.claim_plan_run(
                record['id'], 'owner', 'conversation-1',
                export_catalog={'not': 'a catalog'}, composition_profiles={'not': object()},
            ),
            'hold': lambda: self.hold(record),
        }
        with patch.object(self.editor, 'resolve_available_capabilities', forbidden), \
                patch.object(self.editor, 'plan_request', forbidden):
            for name, operation in operations.items():
                with self.subTest(operation=name):
                    with self.assertRaises(self.revisions.PlanRevisionError) as refused:
                        operation()
                    self.assertEqual(refused.exception.code, 'legacy_plan')
                    self.assertEqual(refused.exception.status_code, 409)
                    self.assertEqual(str(refused.exception), self.schema.LEGACY_PLAN_MESSAGE)
        forbidden.assert_not_called()
        native.assert_not_called()
        for callback in callbacks.values():
            callback.assert_not_called()
        self.assertEqual(self.runs.items, before)
        self.assertEqual(self.model_calls, [])


if __name__ == '__main__':
    unittest.main()
