# functions_document_analysis_checkpoints.py
"""Analyze work-unit references bound to the existing shared result transport.

Version: 0.261.109
Implemented in: 0.261.109

The caller supplies a currently authorized real producer and, for a retry, its
server-verified previous attempt. This adapter does not schedule work or acquire
execution leases. The existing runner owns execution and cancellation.
"""

import hashlib
import json
import uuid
from copy import deepcopy

from functions_analysis_access import (
    AnalysisResultUnavailable,
    analysis_source_snapshot,
    authorize_analysis_sources,
)
from functions_workflow_result_store import (
    AnalysisWorkUnitConflictError,
    WorkflowResultIntegrityError,
    _chat_identity,
    _configured_result_store,
    _identity,
    _orchestration_identity,
)


class AnalysisWorkUnitCheckpoints:
    """Small pointer/claim adapter; payload bytes never get a second backend."""

    def __init__(
        self, store, binding, *, user_id, authorize, resume_from=None,
        attempt_token=None, source_authorizer=None, operation_request=None, operation_sources=None,
        recover_running_unit=None,
    ):
        if not callable(authorize):
            raise ValueError('Analysis checkpoints require current producer authorization.')
        if (operation_request is None) != (operation_sources is None):
            raise ValueError('Per-document analysis checkpoints require both the full operation request and sources.')
        self.store = store
        self.binding = deepcopy(binding)
        self.user_id = user_id
        self.authorize = authorize
        self.resume_from = deepcopy(resume_from)
        self.token = attempt_token or uuid.uuid4().hex
        self.recover_running_unit = recover_running_unit
        self.source_authorizer = source_authorizer or authorize_analysis_sources
        self.operation_request = deepcopy(operation_request)
        self.operation_sources = (
            analysis_source_snapshot(operation_sources) if operation_sources is not None else None
        )
        self.sources = []
        self.reference = None
        self.request_key = ''
        self._prepared = False

    def prepare(self):
        """Register the real producer before extraction or byte-only result saving."""
        self._authorize()
        reference = self.store.prepare_analysis_attempt(
            self.binding, token=self.token, resume_from=self.resume_from,
        )
        self._prepared = True
        try:
            self._authorize()
        except Exception:
            try:
                self.cancel(reason='failed')
            except Exception as exc:
                raise AnalysisWorkUnitConflictError('analysis_cancellation_unconfirmed') from exc
            raise
        return reference

    def cancel(self, reason='cancelled'):
        """Revoke this server-owned worker token without discarding completed units."""
        if not self._prepared and self.reference is None:
            self._authorize()
        return self.store.cancel_analysis_attempt(self.binding, token=self.token, reason=reason)

    def _authorize(self):
        if self.authorize() is False:
            raise AnalysisResultUnavailable('analysis_producer_unavailable')

    def validate_sources(self, sources=None):
        self._authorize()
        if self.reference is not None:
            self.store._analysis_guard(self.binding, required=True, writable=True, token=self.token)
        allowed = self.source_authorizer(
            self.user_id, self.sources if sources is None else analysis_source_snapshot(sources),
            require_snapshot=True,
        )
        if allowed is False:
            raise AnalysisResultUnavailable()

    def initialize(self, request, sources):
        assigned = analysis_source_snapshot(sources)
        self.sources = self.operation_sources if self.operation_sources is not None else assigned
        if any(source not in self.sources for source in assigned):
            raise AnalysisWorkUnitConflictError('analysis_source_manifest_changed')
        self.validate_sources()
        self.reference = self.store.begin_analysis_attempt(
            self.binding, self.operation_request if self.operation_request is not None else request,
            self.sources, token=self.token, resume_from=self.resume_from,
        )
        self.request_key = hashlib.sha256(self.store._serialize({
            'request': request, 'sources': assigned,
        })).hexdigest()
        self.reference['unit_request_digest'] = self.request_key
        # Close the authorization/initialization gap before admitting any payload.
        self.validate_sources()
        return deepcopy(self.reference)

    def _lineage(self):
        binding = self.binding
        seen = set()
        expected_child = None
        while binding is not None:
            identity = tuple((key, json.dumps(value, sort_keys=True, separators=(',', ':')))
                             for key, value in sorted(binding.items()))
            if identity in seen or len(seen) >= 128:
                raise WorkflowResultIntegrityError('Analysis checkpoint retry lineage is invalid.')
            seen.add(identity)
            guard = self.store._analysis_guard(binding, required=True)
            if guard.get('deleted'):
                raise AnalysisWorkUnitConflictError('analysis_work_deleted')
            registered = guard.get('request_registered', bool(guard.get('request_digest')))
            if guard.get('request_digest') != (self.reference or {}).get('request_digest') and not (
                guard.get('prepared') and not registered and guard.get('request_digest') is None
            ):
                raise AnalysisWorkUnitConflictError('analysis_resume_changed')
            if expected_child is not None and guard.get('successor') != expected_child:
                raise AnalysisWorkUnitConflictError('analysis_resume_binding_invalid')
            if registered:
                yield binding
            expected_child, binding = binding, guard.get('resume_from')

    def source_loaded(self, source):
        """Recheck the current source before accepting any original-window checkpoint."""
        self.validate_sources([source])
        for binding in self._lineage():
            previous = self.store.read_analysis_checkpoint(binding, 'source', source['document_id'])
            if previous is not None and previous.get('source') != source:
                raise AnalysisWorkUnitConflictError('analysis_source_content_changed')
        self.store.write_analysis_checkpoint(
            self.binding, 'source', source['document_id'], {'source': deepcopy(source)}, token=self.token,
        )

    def load_unit(self, unit):
        self.validate_sources([unit['source']])
        for binding in self._lineage():
            row = self.store.read_analysis_checkpoint(binding, 'unit', unit['work_unit_id'])
            if row is None or row.get('status') != 'completed':
                if binding == self.binding and row is not None and row.get('status') == 'running':
                    if self.recover_running_unit is None or not self.recover_running_unit():
                        raise AnalysisWorkUnitConflictError('analysis_unit_already_claimed')
                    self.fail_unit(row)
                continue
            payload = self.store._load(binding, row['reference'])
            saved_unit = payload.get('work_unit') or {}
            if (
                payload.get('version') != 'analysis-work-unit-v1'
                or saved_unit.get('work_unit_id') != unit['work_unit_id']
                or saved_unit.get('source') != unit['source']
                or saved_unit.get('status') != 'completed'
                or not isinstance(payload.get('candidate_result'), dict)
                or not isinstance(payload.get('analysis_text'), str)
            ):
                raise WorkflowResultIntegrityError('A completed analysis work unit is invalid.')
            return payload
        return None

    def claim_unit(self, unit):
        self._authorize()
        return self.store.claim_analysis_unit(self.binding, unit['work_unit_id'], token=self.token)

    def commit_unit(self, claim, unit, candidate_result, analysis_text, *, metrics=None):
        if claim.get('key') != unit.get('work_unit_id') or unit.get('status') != 'completed':
            raise WorkflowResultIntegrityError('The analysis claim does not match its completed work unit.')
        self.validate_sources([unit['source']])
        return self.store.finish_analysis_unit(
            self.binding, claim, {
                'version': 'analysis-work-unit-v1', 'work_unit': deepcopy(unit),
                'candidate_result': deepcopy(candidate_result), 'analysis_text': analysis_text,
                'metrics': deepcopy(metrics or {}),
            },
            token=self.token,
        )

    def fail_unit(self, claim):
        self._authorize()
        self.store.fail_analysis_unit(self.binding, claim, token=self.token)

    def load_final_result(self):
        self.validate_sources()
        for binding in self._lineage():
            row = self.store.read_analysis_checkpoint(binding, 'final', self.request_key)
            if row is not None:
                saved = self.store._load(binding, row['reference'])
                result = saved.get('result') or {}
                if saved.get('version') != 'analysis-final-checkpoint-v1' or result.get('analysis_result_version') != 'analyze-final-v1':
                    raise WorkflowResultIntegrityError('The final analysis checkpoint is invalid.')
                coverage = (result.get('analysis_validation') or {}).get('coverage') or {}
                if coverage.get('failed_work_units') or coverage.get('pending_work_units'):
                    continue
                return saved
        return None

    def save_final_result(self, result, *, coverage, metrics):
        self.validate_sources()
        reference = self.store._save(
            self.binding, {
                'version': 'analysis-final-checkpoint-v1', 'result': result,
                'coverage': coverage, 'metrics': metrics,
            },
            guard_token=self.token, require_analysis_guard=True,
        )
        self.store.write_analysis_checkpoint(
            self.binding, 'final', self.request_key, {'reference': reference}, token=self.token,
        )
        return reference


def analysis_checkpoints_for_chat(
    user_id, conversation_id, message_id, *, authorize, resume_message_id=None,
    attempt_token=None, settings=None, store=None, source_authorizer=None,
    operation_request=None, operation_sources=None, actor_user_id=None,
):
    binding = _chat_identity(user_id, conversation_id, message_id)
    return AnalysisWorkUnitCheckpoints(
        store or _configured_result_store(binding, settings=settings, for_write=True),
        binding, user_id=user_id if actor_user_id is None else actor_user_id,
        authorize=authorize, attempt_token=attempt_token,
        resume_from=_chat_identity(user_id, conversation_id, resume_message_id) if resume_message_id else None,
        source_authorizer=source_authorizer,
        operation_request=operation_request, operation_sources=operation_sources,
    )


def analysis_checkpoints_for_workflow(
    workflow, run_id, task_id, *, user_id, authorize, resume_run_id=None,
    attempt_token=None, settings=None, store=None, source_authorizer=None,
    operation_request=None, operation_sources=None,
    recover_running_unit=None,
    execution_id=None, node_id=None, attempt=None, iteration_path=None,
):
    selectors = {}
    if execution_id is not None:
        selectors = {"execution_id": execution_id, "node_id": node_id, "attempt": attempt,
                     "iteration_path": [] if iteration_path is None else iteration_path}
    binding = _identity(workflow, run_id, task_id, **selectors)
    result_store = store or _configured_result_store(binding, settings=settings, for_write=True)
    resume_from = _identity(workflow, resume_run_id, task_id) if resume_run_id else None
    if selectors and attempt > 1:
        prior_binding = _identity(workflow, run_id, task_id, **{**selectors, "attempt": attempt - 1})
        if result_store._analysis_guard(prior_binding) is not None:
            resume_from = prior_binding
    return AnalysisWorkUnitCheckpoints(
        result_store,
        binding, user_id=user_id, authorize=authorize, attempt_token=attempt_token,
        resume_from=resume_from,
        source_authorizer=source_authorizer,
        operation_request=operation_request, operation_sources=operation_sources,
        recover_running_unit=recover_running_unit,
    )


def analysis_checkpoints_for_orchestration(
    user_id, conversation_id, run_id, step_id, *, authorize, resume_run_id=None,
    attempt_token=None, settings=None, store=None, source_authorizer=None,
    operation_request=None, operation_sources=None, actor_user_id=None,
):
    binding = _orchestration_identity(user_id, conversation_id, run_id, step_id)
    return AnalysisWorkUnitCheckpoints(
        store or _configured_result_store(binding, settings=settings, for_write=True),
        binding, user_id=user_id if actor_user_id is None else actor_user_id,
        authorize=authorize, attempt_token=attempt_token,
        resume_from=(
            _orchestration_identity(user_id, conversation_id, resume_run_id, step_id)
            if resume_run_id else None
        ),
        source_authorizer=source_authorizer,
        operation_request=operation_request, operation_sources=operation_sources,
    )
