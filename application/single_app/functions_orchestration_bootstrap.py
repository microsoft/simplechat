# functions_orchestration_bootstrap.py
"""Application-owned factories shared by web requests and scheduler continuations.

Version: 0.261.127

Unlike the result/rendering services, this is an application composition root.
Import it only after config has initialized the existing clients. Registering the
artifact factory performs no I/O; each use rebuilds current actor/source access.
"""

import hashlib
import hmac
from copy import deepcopy
from urllib.parse import urlsplit

import requests

import config
import functions_authentication as authentication
from agent_execution_context import capture_execution_identity
from functions_generated_export_contracts import GeneratedFileExportRequest
from functions_generated_export_registry import resolve_generated_file_export_format
from functions_orchestration_artifacts import (
    OrchestrationArtifactTransport,
    OrchestrationOutputCleanupService,
    configure_orchestration_artifact_service,
)
from functions_orchestration_external_configuration import (
    OrchestrationExternalConfigurationAttestor, _read_metadata,
)
from functions_orchestration_external_metadata import build_external_metadata_reader
from functions_orchestration_external_sources import OrchestrationExternalSourceProvider
from functions_orchestration_output_store import (
    OrchestrationOutputStore, OutputError, OutputUnavailableError,
)
from functions_orchestration_registry import resolve_available_capability_ids
from functions_orchestration_result_contracts import InputBinding, ResultContractError, ResultRef, TaskResult
from functions_orchestration_results import ResultUnavailableError
from functions_orchestration_runs import get_orchestration_run
from functions_orchestration_services import OrchestrationServices
from functions_orchestration_source_access import (
    read_orchestration_source_metadata,
    resolve_orchestration_source_manifest,
)
from functions_settings import get_settings, get_user_settings
from functions_simplechat_operations import (
    delete_staged_orchestration_chat_artifact_for_user,
    open_generated_chat_artifact_stream,
    upload_generated_file_artifact_stream_for_user,
)
from functions_workflow_result_store import WorkflowResultStore, _quota_bytes


def read_owned_conversation(user_id, conversation_id, *, request_timeout=None):
    options = {} if request_timeout is None else {
        "connection_timeout": request_timeout, "read_timeout": request_timeout, "retry_total": 0,
    }
    conversation = config.cosmos_conversations_container.read_item(
        item=conversation_id, partition_key=conversation_id, **options,
    )
    if (
        conversation.get("id") != conversation_id or conversation.get("user_id") != user_id
        or conversation.get("orchestration_deleted") or conversation.get("deleted")
    ):
        raise OutputUnavailableError("output_conversation_unavailable")
    return conversation


def private_external_configuration_digest(value):
    """Bind private configuration revisions to the existing stable backend key."""
    if type(value) is not bytes:
        raise ResultContractError("external_configuration_payload_invalid")
    key = config.SECRET_KEY
    if type(key) is str:
        try:
            key = key.encode("utf-8")
        except UnicodeError:
            raise ResultUnavailableError("external_configuration_private_digest_required") from None
    if (
        type(key) is not bytes or len(key) < 32 or not key.strip()
        or key == b"dev-secret-key-change-in-production"
    ):
        raise ResultUnavailableError("external_configuration_private_digest_required")
    digest = hmac.new(
        key, b"SimpleChat:orchestration-external-configuration:v1\x00", hashlib.sha256,
    )
    digest.update(value)
    return digest.hexdigest()


def build_external_identity_reader(actor_user_id, actor_conversation_id, *, execution_check=None):
    """Create a lazy current-directory reader, never a saved-session role fallback."""
    reader = None
    timeout = 10.0

    def authorize_conversation(*, user_id, conversation_id):
        if user_id != actor_user_id or conversation_id != actor_conversation_id:
            raise ResultUnavailableError("external_identity_access_denied")
        try:
            return read_owned_conversation(user_id, conversation_id, request_timeout=timeout)
        except OutputUnavailableError:
            raise ResultUnavailableError("external_identity_access_denied") from None

    def read_user_settings(user_id):
        authorize_conversation(user_id=user_id, conversation_id=actor_conversation_id)
        return config.cosmos_user_settings_container.read_item(
            item=user_id, partition_key=user_id,
            connection_timeout=timeout, read_timeout=timeout, retry_total=0,
        )

    def read_identity(*, user_id, conversation_id):
        nonlocal reader
        if user_id != actor_user_id or conversation_id != actor_conversation_id:
            raise ResultUnavailableError("external_identity_access_denied")
        if reader is None:
            # Optional directory authorization is initialized only when external data is accessed.
            from functions_orchestration_external_identity import (
                ExternalIdentityServiceError,
                GraphExternalIdentityReader,
            )

            graph_base = authentication.get_graph_base_url()
            graph_origin = urlsplit(graph_base)
            graph_scope = f"{graph_origin.scheme}://{graph_origin.netloc}/.default"
            app_client_id = authentication.CLIENT_ID
            application = None

            def get_access_token(scope):
                nonlocal application
                if scope != graph_scope or authentication.CLIENT_ID != app_client_id:
                    raise ResultUnavailableError("external_identity_access_denied")
                if application is None:
                    application = authentication._build_msal_app(
                        authority_override=authentication.get_graph_authority(), timeout=timeout,
                    )
                result = application.acquire_token_for_client(scopes=[scope])
                if type(result) is not dict:
                    raise ExternalIdentityServiceError("external_identity_response_invalid")
                token = result.get("access_token")
                if type(token) is str and token:
                    return token
                error = result.get("error")
                if error in ("server_error", "temporarily_unavailable"):
                    raise ExternalIdentityServiceError()
                if error == "too_many_requests":
                    raise ExternalIdentityServiceError("external_identity_throttled")
                if error in (
                    "invalid_client", "invalid_grant", "unauthorized_client", "invalid_scope",
                    "access_denied", "consent_required", "interaction_required",
                ):
                    raise ResultUnavailableError("external_identity_access_denied")
                raise ExternalIdentityServiceError("external_identity_response_invalid")

            reader = GraphExternalIdentityReader(
                user_id=actor_user_id, conversation_id=actor_conversation_id,
                app_client_id=app_client_id, graph_base_url=graph_base, graph_scope=graph_scope,
                get_access_token=get_access_token, http_get=requests.get,
                authorize_conversation=authorize_conversation, read_user_settings=read_user_settings,
                execution_check=execution_check, request_timeout=timeout,
            )
        return reader(user_id=user_id, conversation_id=conversation_id)

    return read_identity


def current_execution_identity(user_id, conversation_id, *, seeded_agent=None):
    """Use authenticated claims only for their actor; background role gates fail closed."""
    read_owned_conversation(user_id, conversation_id)
    identity = capture_execution_identity(user_id, conversation_id)
    preference = (get_user_settings(user_id) or {}).get("settings") or {}
    return {
        "user_roles": list(identity.roles),
        "user_email": identity.email,
        "user_enable_agents": (
            True if isinstance(seeded_agent, dict) and seeded_agent.get("name")
            else preference.get("enable_agents", True) is True
        ),
    }


def native_bridge_for_step(step, context):
    """Bind the real compute-only bridge; discovery never submits a native job."""
    del context
    # Native execution dependencies are loaded only for an explicitly bound native step.
    from functions_orchestration_native_results import (
        build_native_orchestration_bridge,
        validate_native_orchestration_arguments,
    )

    arguments = validate_native_orchestration_arguments(step["arguments"])
    return build_native_orchestration_bridge(
        native_operation=arguments["native_operation"],
        task_type=arguments["task_type"],
        source_policy="current",
    )


def _bound_render_reference(run, step, user_id):
    inputs = step.get("inputs")
    if type(inputs) is not dict or len(inputs) != 1:
        raise OutputUnavailableError("output_binding_invalid")
    value = next(iter(inputs.values()))
    if type(value) is not dict or value.get("allow_partial", False) is not False:
        raise OutputUnavailableError("output_binding_invalid")
    binding = InputBinding.from_dict(value.get("binding"))
    if binding.existing_result is not None:
        aliases = run.get("result_aliases") or {}
        if binding.existing_result not in aliases:
            raise OutputUnavailableError("output_binding_invalid")
        return ResultRef.from_dict(aliases[binding.existing_result])
    # Recovery owns chained checkpoint provenance; don't guess a result digest or
    # substitute the latest result for a different execution attempt.
    from functions_orchestration_recovery import _completed_checkpoint

    checkpoint = _completed_checkpoint(
        run, binding.step_id,
        lambda: read_owned_conversation(user_id, run["conversation_id"]),
    )
    task = TaskResult.from_dict(checkpoint["result"]["task_result"])
    return task.output(binding.output_name)


def _authorize_render_output(record, *, operation, rendering_service):
    user_id, conversation_id = record["user_id"], record["conversation_id"]
    access = rendering_service.results.access
    if user_id != access.user_id or conversation_id != access.conversation_id:
        raise OutputUnavailableError("output_binding_invalid")
    read_owned_conversation(user_id, conversation_id)
    run = get_orchestration_run(record["run_id"], user_id, conversation_id, strict=True)
    if not run or (run.get("plan") or {}).get("planner_contract_version") != 2:
        raise OutputUnavailableError("output_run_unavailable")
    step = next((
        value for value in run["plan"]["steps"]
        if value["step_id"] == record["producer"]["step_id"]
    ), None)
    if step is None or step["capability_id"] != "render_file" or step.get("enabled", True) is not True:
        raise OutputUnavailableError("output_plan_changed")
    settings = get_settings()
    available = resolve_available_capability_ids(
        settings, allowed_ids=settings.get("chat_orchestration_enabled_capabilities"),
        candidate_ids={"render_file"}, contract_version=2,
        request_context={"rendering_service": rendering_service},
    )
    if "render_file" not in available:
        raise OutputUnavailableError("output_capability_disabled")
    reference = _bound_render_reference(run, step, user_id)
    if reference.to_dict() != record["source_ref"]:
        raise OutputUnavailableError("output_binding_invalid")
    arguments = step["arguments"]
    options = deepcopy(arguments.get("options") or {})
    if "columns" in options:
        options["columns"] = tuple(options["columns"])
    request = GeneratedFileExportRequest(
        arguments["output_format"], arguments["profile"], **options,
    )
    source_kind = {
        "records-v1": "records", "structured-v1": "structured_value",
        "comparison-v1": "structured_value", "text-v1": "text", "markdown-v1": "markdown",
    }.get(reference.kind)
    entry = resolve_generated_file_export_format(request, source_kind)
    spec = record["render_spec"]
    if (
        spec["output_format"] != entry.format_id or spec["profile"] != request.profile
        or spec["columns"] != (list(request.columns) if request.columns is not None else None)
        or spec["title"] != request.title or spec["sheet_name"] != request.sheet_name
    ):
        raise OutputUnavailableError("output_plan_changed")
    return True


def build_orchestration_services(user_id, conversation_id, *, settings=None):
    """Supply the initialized private result, run and chat-artifact resources."""
    read_owned_conversation(user_id, conversation_id)
    settings = get_settings() if settings is None else settings
    maximum_mb = settings.get("max_generated_chat_artifact_size_mb", 500)
    if type(maximum_mb) is not int or maximum_mb < 1:
        raise OutputError("output_limit_invalid")
    result_store = WorkflowResultStore(
        config.cosmos_personal_workflow_run_items_container,
        config.CLIENTS.get("storage_account_office_docs_client"),
        config.storage_account_personal_chat_container_name,
        max_size_bytes=_quota_bytes(settings),
    )
    transport = OrchestrationArtifactTransport(
        upload=upload_generated_file_artifact_stream_for_user,
        read_message=lambda cid, mid: config.cosmos_messages_container.read_item(
            item=mid, partition_key=cid,
        ),
        open_stream=open_generated_chat_artifact_stream,
        delete=delete_staged_orchestration_chat_artifact_for_user,
        blob_container=config.storage_account_personal_chat_container_name,
    )
    def read_conversation(cid):
        return read_owned_conversation(user_id, cid)

    def read_run(rid):
        return get_orchestration_run(rid, user_id, conversation_id, strict=True)

    def read_external_conversation(cid):
        try:
            return _read_metadata(read_conversation, cid)
        except OutputUnavailableError:
            raise ResultUnavailableError("result_external_context_unavailable") from None

    attestor = OrchestrationExternalConfigurationAttestor(
        user_id=user_id, conversation_id=conversation_id,
        read_current_source=build_external_metadata_reader(
            user_id, conversation_id, read_conversation=read_external_conversation,
        ),
        private_digest=private_external_configuration_digest,
    )
    provider = OrchestrationExternalSourceProvider(
        user_id=user_id, conversation_id=conversation_id,
        read_identity=build_external_identity_reader(user_id, conversation_id),
        read_settings=lambda: _read_metadata(get_settings),
        read_conversation=read_external_conversation,
        read_run=lambda rid: _read_metadata(read_run, rid),
        read_configuration=attestor.current,
        configuration_admitter=attestor.for_admission,
        acquisition_validator=attestor.validate_acquisition,
    )

    def capture(source_type, *, producer, settings, source=None, selector=None):
        provider.preflight_gather_acquisition(
            source_type, producer=producer, settings=settings, source=source, selector=selector,
        )
        if source is None and (source_type, producer.capability_id) in (
            ("agent", "agent_invoke"), ("action", "action_invoke"),
        ):
            return
        attestor.capture(
            source_type, producer=producer, settings=settings, source=source, selector=selector,
        )

    def admit(*, producer, prepared):
        # The runtime validates and installs these aliases in the facade's copied catalog.
        return provider.admit_gather_result(
            producer=producer, prepared=prepared, selector=attestor.selector_for(producer),
        )

    def authorize_output(record, *, operation):
        return _authorize_render_output(
            record, operation=operation, rendering_service=services.rendering,
        )

    services = OrchestrationServices(
        user_id=user_id, conversation_id=conversation_id, result_store=result_store,
        run_container=config.cosmos_orchestration_runs_container,
        read_conversation=read_conversation, read_run=read_run,
        source_resolver=resolve_orchestration_source_manifest,
        source_metadata_reader=read_orchestration_source_metadata,
        external_source_catalog={}, external_source_authorizer=provider.authorize,
        external_source_preflight=provider.preflight_gather_invocation,
        external_source_admission=admit, capture_external_source_configuration=capture,
        transport=transport, authorize_execution=authorize_output,
        max_output_bytes=min(maximum_mb, 500) * 1024 * 1024,
        native_bridge_for_step=native_bridge_for_step,
    )
    return services


def initialize_orchestration_artifact_access():
    """Register live history/download access; deletion-only cleanup is separate."""
    configure_orchestration_artifact_service(
        lambda user_id, conversation_id: build_orchestration_services(user_id, conversation_id).rendering,
    )


def build_orchestration_cleanup_service(user_id, conversation_id):
    """Bind deletion-only cleanup to real records without making them readable."""
    store = OrchestrationOutputStore(
        config.cosmos_orchestration_runs_container,
        user_id=user_id, conversation_id=conversation_id,
        read_conversation=lambda cid: config.cosmos_conversations_container.read_item(
            item=cid, partition_key=cid,
        ),
        read_run_tombstone=lambda rid: config.cosmos_orchestration_run_steps_container.read_item(
            item="checkpoint:lifecycle", partition_key=rid,
        ),
    )
    return OrchestrationOutputCleanupService(
        store, config.cosmos_messages_container,
        config.CLIENTS.get("storage_account_office_docs_client"),
        blob_container=config.storage_account_personal_chat_container_name,
    )
