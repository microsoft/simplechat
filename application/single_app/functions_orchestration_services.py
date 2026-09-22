# functions_orchestration_services.py
"""Bind initialized application resources to the retained-result harness.

Version: 0.261.127

The web and scheduler owners supply storage, current access callbacks and private
artifact transport. This module never discovers configuration, credentials or
Flask request state, and never initializes a client as an import side effect.
"""

from copy import deepcopy

from content_screening.contracts import DocumentHeldError
from functions_document_analysis_checkpoints import AnalysisWorkUnitCheckpoints
from functions_generated_export_registry import (
    PREPARED_SLIDE_DECK_VERSION,
    get_generated_file_export_catalog,
    get_prepared_slide_deck_schema,
)
from functions_orchestration_output_store import OrchestrationOutputStore, OutputError
from functions_orchestration_rendering import OrchestrationRenderingService
from functions_orchestration_result_contracts import (
    InputBinding, ResultContractError, ResultRef, TaskResult, canonical_digest,
)
from functions_orchestration_results import OrchestrationResultAccess, OrchestrationResults
from functions_workflow_result_store import _orchestration_identity


MAX_RESULT_ALIASES = 64


def composition_profiles():
    """Use the renderer's exact prepared-content schema, not a second slide grammar."""
    return {PREPARED_SLIDE_DECK_VERSION: get_prepared_slide_deck_schema()}


def validate_composition_profile(profile, value):
    if profile != PREPARED_SLIDE_DECK_VERSION:
        raise ResultContractError("result_profile_unavailable")
    # Office libraries are execution dependencies, not registry/bootstrap dependencies.
    from functions_generated_office_adapters import prepare_generated_slide_deck

    prepare_generated_slide_deck(value)
    return True


def admitted_result_aliases(record, results):
    """Reopen server-stored aliases; browser descriptors never enter this boundary."""
    values = record.get("result_aliases", {})
    if type(values) is not dict or len(values) > MAX_RESULT_ALIASES:
        raise ResultContractError("result_reference_untrusted")
    aliases = {}
    for alias, value in values.items():
        InputBinding(existing_result=alias)
        reference = ResultRef.from_dict(value)
        results.open_result(reference, require_current_sources=True).recheck()
        aliases[alias] = reference
    return aliases


def discover_result_aliases(runs, results):
    """Return admitted refs and an explicit count of currently inaccessible results."""
    if type(runs) is not list or len(runs) > 10:
        raise ResultContractError("result_reference_untrusted")
    aliases, unavailable_count = {}, 0
    for run in runs:
        if (
            type(run) is not dict or run.get("user_id") != results.access.user_id
            or run.get("conversation_id") != results.access.conversation_id
        ):
            raise ResultContractError("result_reference_untrusted")
        if (
            (run.get("plan") or {}).get("planner_contract_version") != 2
            or run.get("checkpoints_deleted")
        ):
            continue
        tasks = run.get("task_results") or {}
        if type(tasks) is not dict:
            raise ResultContractError("result_reference_untrusted")
        for step_id, value in tasks.items():
            task = TaskResult.from_dict(value)
            if task.producer.step_id != step_id:
                raise ResultContractError("result_producer_mismatch")
            for reference in task.outputs:
                if reference.completeness.status != "complete":
                    continue
                try:
                    results.open_result(reference, require_current_sources=True).recheck()
                except (PermissionError, DocumentHeldError):
                    unavailable_count += 1
                    continue
                alias = f"saved_{canonical_digest(reference.to_dict())[:48]}"
                aliases[alias] = reference
                if len(aliases) == MAX_RESULT_ALIASES:
                    return {"aliases": aliases, "unavailable_count": unavailable_count}
    return {"aliases": aliases, "unavailable_count": unavailable_count}


class OrchestrationServices:
    """Actor/conversation-scoped result and file services over existing containers."""

    def __init__(
        self, *, user_id, conversation_id, result_store, run_container,
        read_conversation, read_run, source_resolver, source_metadata_reader,
        transport, authorize_execution, max_output_bytes,
        external_source_catalog=None, external_source_authorizer=None,
        external_source_admission=None, external_source_preflight=None, native_bridge_for_step=None,
        capture_external_source_configuration=None,
    ):
        if external_source_preflight is not None and not callable(external_source_preflight):
            raise ResultContractError("result_external_reader_required")
        if external_source_admission is not None and (
            not callable(external_source_admission) or not callable(external_source_authorizer)
        ):
            raise ResultContractError("result_external_reader_required")
        if native_bridge_for_step is not None and not callable(native_bridge_for_step):
            raise ResultContractError("result_native_reader_required")
        if capture_external_source_configuration is not None and (
            not callable(capture_external_source_configuration)
            or not callable(external_source_admission) or not callable(external_source_authorizer)
        ):
            raise ResultContractError("result_external_reader_required")
        self.external_source_admission = external_source_admission
        self.external_source_preflight = external_source_preflight
        self.native_bridge_for_step = native_bridge_for_step
        self.capture_external_source_configuration = capture_external_source_configuration
        external = {}
        if external_source_catalog is not None or external_source_authorizer is not None:
            external = {
                "external_source_catalog": external_source_catalog,
                "external_source_authorizer": external_source_authorizer,
            }
        access = OrchestrationResultAccess(
            user_id=user_id, conversation_id=conversation_id,
            read_conversation=read_conversation, read_run=read_run,
            source_resolver=source_resolver, source_metadata_reader=source_metadata_reader,
            **external,
        )
        self.results = OrchestrationResults(result_store, access)
        self.outputs = OrchestrationOutputStore(
            run_container, user_id=user_id, conversation_id=conversation_id,
            read_conversation=read_conversation,
        )
        self.rendering = OrchestrationRenderingService(
            self.outputs, self.results, transport,
            authorize_execution=authorize_execution, max_output_bytes=max_output_bytes,
        )

    @property
    def user_id(self):
        return self.results.access.user_id

    @property
    def conversation_id(self):
        return self.results.access.conversation_id

    def export_catalog(self):
        return get_generated_file_export_catalog()

    def capability_request_bindings(self):
        """Expose initialized runtime dependencies only to server-side discovery."""
        bindings = {
            "native_bridge_for_step": self.native_bridge_for_step,
            "rendering_service": self.rendering,
        }
        external = {
            "external_source_preflight": self.external_source_preflight,
            "external_source_admission": self.external_source_admission,
            "external_source_authorizer": self.results.access.external_source_authorizer,
            "capture_external_source_configuration": self.capture_external_source_configuration,
        }
        if all(callable(callback) for callback in external.values()):
            bindings.update(external)
        return bindings

    def bind_context(
        self, context, record, *, checkpoint_factory, guard_token, execution_check,
    ):
        """Share the real owning attempt's store and guard with every producer."""
        if (
            getattr(context, "plan_contract_version", None) != 2
            or (record.get("plan") or {}).get("planner_contract_version") != 2
            or context.user_id != self.user_id or record.get("user_id") != self.user_id
            or context.conversation_id != self.conversation_id
            or record.get("conversation_id") != self.conversation_id
            or context.run_id != record.get("id")
            or context.attempt_index != record.get("attempt_index", 1)
            or not callable(checkpoint_factory) or not callable(execution_check)
            or type(guard_token) is not str or not guard_token
        ):
            raise ResultContractError("result_producer_mismatch")
        steps = {
            step["step_id"]: deepcopy(step) for step in record["plan"]["steps"]
            if step.get("enabled", True)
        }
        checkpoints = {}

        def checked_checkpoint(step_id):
            if step_id not in steps:
                raise ResultContractError("result_producer_mismatch")
            if execution_check() is False:
                raise ResultContractError("result_guard_required")
            producer = context.result_producer(steps[step_id])
            self.results.access.authorize_producer(producer, for_write=True)
            if step_id not in checkpoints:
                checkpoints[step_id] = checkpoint_factory(step_id)
            checkpoint = checkpoints[step_id]
            if (
                not isinstance(checkpoint, AnalysisWorkUnitCheckpoints)
                or checkpoint.store is not self.results.store
                or checkpoint.token != guard_token
                or checkpoint.binding != _orchestration_identity(
                    self.user_id, self.conversation_id, context.run_id, step_id,
                )
            ):
                raise ResultContractError("result_guard_required")
            return checkpoint

        aliases = admitted_result_aliases(record, self.results)
        context.result_service = self.results
        context.result_aliases = aliases
        context.external_source_admission = self.external_source_admission
        context.external_source_preflight = self.external_source_preflight
        context.native_bridge_for_step = self.native_bridge_for_step
        context.capture_external_source_configuration = self.capture_external_source_configuration
        context._result_guard_token_for_step = lambda step_id: checked_checkpoint(step_id).token
        context.analysis_checkpoint_factory = checked_checkpoint
        context.export_catalog = self.export_catalog()
        context.composition_profiles = composition_profiles()
        context.composition_profile_validator = validate_composition_profile
        context.execution_deadline_at = record.get("execution_deadline_at")
        context.rendering_service = self.rendering
        context.approved_work_id = record.get("attempt_root_run_id") or record["id"]
        return context

    def rendering_for_context(self, context, *, settings, user_id):
        """Adapter callback; do not let an incidental context select another actor."""
        del settings
        if (
            user_id != self.user_id or context.user_id != self.user_id
            or context.conversation_id != self.conversation_id
            or context.result_service is not self.results
        ):
            raise OutputError("output_binding_invalid")
        return self.rendering
