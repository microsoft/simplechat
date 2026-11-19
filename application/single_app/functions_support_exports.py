# functions_support_exports.py
"""Operation-time wiring for support exports; no resource initialization on import."""

import logging
import uuid

from azure.identity import AzureAuthorityHosts, DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError

import config
from content_screening.access import public_history_messages
from content_screening.contracts import ScreeningConfigurationError
from content_screening.model import evaluate_model_units, validate_scanner_model_configuration
from cosmos_document_utils import normalize_cosmos_document
from functions_ai_connections import AIConnectionError, CHAT_CAPABILITY, resolve_capability_binding
from functions_appinsights import log_event
from functions_collaboration import assert_user_can_view_collaboration_conversation
from functions_model_capabilities import ModelTokenBudgetError, resolve_model_token_budget
from functions_notifications import create_notification
from functions_orchestration_attempts import exclude_superseded_orchestration_attempts
from functions_saved_analysis import sanitize_saved_analysis_messages
from functions_settings import get_settings
from support_export_contracts import SupportExportError, digest, fail, iso, normalize_configuration, utc_now
from support_export_service import SupportExportService
from support_export_sources import SupportExportSources, build_support_monitor_client
from support_export_store import SupportExportStore


def audit_support_export(operation, **details):
    log_event(
        "[SUPPORT_EXPORT] Support export state changed.",
        extra={"operation": operation, **details},
        level=logging.ERROR if "error_type" in details else logging.INFO,
    )
    actor = details.pop("actor", None) or "system"
    config.cosmos_activity_logs_container.create_item(body={
        "id": uuid.uuid4().hex, "user_id": actor, "activity_type": "support_export",
        "timestamp": iso(utc_now()), "operation": operation, "additional_context": details,
    })


def _binding_fingerprint(binding):
    return digest({
        "selection": binding.selection, "provider": binding.selection["provider"],
        "connection": binding.endpoint.get("connection", {}), "model": binding.model,
        "operation_settings": binding.operation_settings,
    })


def _model_info():
    try:
        response = config.cosmos_settings_container.read_item(item="app_settings", partition_key="app_settings")
        settings = normalize_cosmos_document(response)
        binding = resolve_capability_binding(settings, CHAT_CAPABILITY)
        validate_scanner_model_configuration(settings, binding.selection)
        output_limit = min(binding.model.get("responseLength") or 8192, 8192)
        budget = resolve_model_token_budget(
            binding.model, binding.endpoint, provider=binding.selection["provider"], request_output_limit=output_limit,
        )
        allowance = budget.remaining_input()
        if allowance < 1024:
            fail("model_context_small", "The default text model has too little configured input context.", 503)
        return {
            "available": True, "label": binding.model.get("displayName") or binding.model.get("deploymentName") or binding.selection["model_id"],
            "provider": binding.selection["provider"], "selection": dict(binding.selection),
            "fingerprint": _binding_fingerprint(binding), "input_ceiling": allowance + output_limit,
            "message": "Uses the configured default text model; only already-scrubbed data is sent.",
        }
    except (AIConnectionError, ModelTokenBudgetError, SupportExportError, ScreeningConfigurationError, ResourceNotFoundError) as exc:
        log_event("[SUPPORT_EXPORT] Default privacy model is unavailable.", extra={"error_type": type(exc).__name__}, level=logging.WARNING)
        return {
            "available": False,
            "message": "Configure a supported default text model in AI Connections, including its context and total-generation token limits.",
        }


def _inspect_ai(units, selection, progress, token_budget, *, expected_fingerprint):
    info = _model_info()
    if not info.get("available") or info["selection"] != selection or info["fingerprint"] != expected_fingerprint:
        fail("model_changed", "The default privacy model changed. Create a new export.", 409)

    def on_progress(_result):
        if progress:
            progress()
        current = _model_info()
        return current.get("fingerprint") == info["fingerprint"]

    return evaluate_model_units(
        units, {
            "id": "support-privacy", "enabled": True,
            "model_selection": {key: selection[key] for key in ("endpoint_id", "model_id")},
            "instructions": (
                "Identify sensitive personal or confidential information remaining in these diagnostic fields, "
                "including personal names, street addresses, credentials, and private business content. "
                "Do not infer facts or alter diagnostic codes. Return grounded exact spans only."
            ),
            "severity": "high", "category": "sensitive_information",
            "window_unit": "chunks", "window_size": 1, "max_characters": 12000, "overlap_characters": 500,
            "limits": {
                "max_units": 100000, "max_total_characters": 20000000, "max_windows": 100000,
                "max_findings": 1000, "max_runtime_seconds": 300,
            },
        },
        on_progress=on_progress, token_ceiling=token_budget, input_ceiling=info["input_ceiling"],
        binding_validator=lambda binding: _binding_fingerprint(binding) == expected_fingerprint,
    )


def _notify(owner_id, job_id):
    create_notification(
        user_id=owner_id, notification_type="system_announcement",
        title="A support export needs your approval",
        message="An administrator requested whole personal conversation snapshots. Review the exact scope before approving.",
        link_url="/approvals?support_export=" + job_id,
        idempotency_key="support-export:" + job_id, strict=True,
    )


def _visible_messages(messages, owner_id):
    active = []
    for message in messages:
        metadata = message.get("metadata") or {}
        if metadata.get("is_deleted") is True or (metadata.get("thread_info") or {}).get("active_thread") is False:
            continue
        active.append(message)
    active = sanitize_saved_analysis_messages(active, owner_id)
    active = public_history_messages(active, owner_id)
    return exclude_superseded_orchestration_attempts(active)


def get_support_export_service():
    settings = get_settings()
    blobs = None
    blob_service = None
    if settings.get("office_docs_storage_account_url") or settings.get("office_docs_storage_account_blob_endpoint"):
        blob_service = config.build_enhanced_citations_blob_service_client(settings)
        blobs = blob_service.get_container_client("support-exports")
    store = SupportExportStore(config.cosmos_support_exports_container, blobs)
    configuration = normalize_configuration(store.configuration() or {
        "cloud": "public", "app_resource_id": "", "site_resource_id": "",
    })
    monitor = None
    credential = None
    if configuration["app_resource_id"] or configuration["site_resource_id"]:
        government = configuration.get("cloud") == "usgovernment"
        authority = AzureAuthorityHosts.AZURE_GOVERNMENT if government else AzureAuthorityHosts.AZURE_PUBLIC_CLOUD
        credential = DefaultAzureCredential(authority=authority)
        monitor = build_support_monitor_client(configuration, credential)
    sources = SupportExportSources({
        "users": config.cosmos_user_settings_container,
        "conversations": config.cosmos_conversations_container, "messages": config.cosmos_messages_container,
        "group_conversations": config.cosmos_group_conversations_container, "group_messages": config.cosmos_group_messages_container,
        "collaboration": config.cosmos_collaboration_conversations_container,
        "collaboration_messages": config.cosmos_collaboration_messages_container,
        "collaboration_states": config.cosmos_collaboration_user_state_container,
        "activity": config.cosmos_activity_logs_container, "file_processing": config.cosmos_file_processing_container,
    }, monitor=monitor, authorize_shared=lambda user_id, document: assert_user_can_view_collaboration_conversation(
        user_id, document, read_only=True,
    ), filter_messages=_visible_messages)
    def close_resources():
        try:
            if monitor is not None:
                monitor.close()
        finally:
            try:
                if credential is not None:
                    credential.close()
            finally:
                if blob_service is not None:
                    blob_service.close()

    return SupportExportService(
        store, sources, version=config.VERSION, model_info=_model_info, inspect_ai=_inspect_ai,
        notify=_notify, audit=audit_support_export,
        storage_binding=digest({"container": blobs.url if blobs is not None else ""}),
        close_resources=close_resources,
    )


def check_due_support_exports_once():
    metadata = SupportExportStore(config.cosmos_support_exports_container, None)
    jobs = metadata.query("SELECT TOP 1 c.id FROM c WHERE c.record_kind = 'export'", [], limit=1)
    if not jobs and metadata.read("blob-cleanup", "configuration") is None:
        return
    service = get_support_export_service()
    try:
        service.tick()
    finally:
        service.close()
