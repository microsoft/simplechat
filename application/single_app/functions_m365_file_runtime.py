# functions_m365_file_runtime.py
"""Application-owned request budgeting for retained Microsoft 365 evidence."""

import json
from collections.abc import Mapping

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError
from flask import g

from config import cosmos_m365_execution_runs_container
from conversation_memory_runtime import resolve_m365_memory
from functions_m365_retrieval import configure_m365_retrieval, create_m365_request_budget
from functions_m365_agent_continuation import configure_m365_agent_continuation
from functions_m365_analysis_runtime import analyze_m365_memory
from functions_m365_workflow_checkpoints import configure_m365_workflow_checkpoints
from functions_m365_transport import M365ProviderError
from functions_model_capabilities import resolve_model_token_limits


def _message_text(message):
    if isinstance(message, Mapping):
        return json.dumps(dict(message), ensure_ascii=False, default=str)
    return str(message)


def configure_m365_model_context(model, messages, *, instructions=""):
    """Reserve declared model output and conservatively count the input envelope."""
    context_limit, output_limit = resolve_model_token_limits(model)
    g.m365_model_context_limit = context_limit
    g.m365_model_output_limit = output_limit
    g.m365_model_base_bytes = sum(
        len(_message_text(message).encode("utf-8")) + 256 for message in messages
    ) + len(str(instructions or "").encode("utf-8")) + 4096


def resolve_m365_model_room(context):
    context_limit = getattr(g, "m365_model_context_limit", None)
    output_limit = getattr(g, "m365_model_output_limit", None)
    if not context_limit or not output_limit:
        raise M365ProviderError(
            "model_context_unavailable",
            "This model needs declared context and output limits before file evidence can be added.",
        )
    return max(0, context_limit - output_limit - g.m365_model_base_bytes)


def count_m365_context_tokens(text, context):
    # A UTF-8 byte bound is conservative across the supported model tokenizers.
    return len(text.encode("utf-8"))


def resolve_m365_budget_run(context) -> str:
    container = cosmos_m365_execution_runs_container
    try:
        record = container.read_item(context.request_id, partition_key=context.data_user_id)
    except CosmosResourceNotFoundError:
        body = {
            "id": context.request_id,
            "user_id": context.data_user_id,
            "actor_user_id": context.actor_user_id,
            "type": "m365_execution_request",
            "status": "running",
            "conversation_id": context.conversation_id,
            "workflow_id": context.workflow_id,
            "run_id": context.run_id,
        }
        try:
            record = container.create_item(body=body)
        except CosmosResourceExistsError:
            record = container.read_item(context.request_id, partition_key=context.data_user_id)
    if (
        record.get("conversation_id") != context.conversation_id
        or record.get("actor_user_id") != context.actor_user_id
    ):
        raise M365ProviderError("request_memory_mismatch", "The file budget belongs to a different request.")
    if record.get("memory_budget_run_id"):
        g.m365_has_pending_record = True
        return record["memory_budget_run_id"]
    store, memory_context = resolve_m365_memory(context)
    run_id = create_m365_request_budget(store, memory_context, context)
    for attempt in range(4):
        completed = {**record, "memory_budget_run_id": run_id}
        completed.pop("memory_budget_initializing", None)
        try:
            container.replace_item(
                record["id"], body=completed,
                etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            g.m365_has_pending_record = True
            return run_id
        except CosmosHttpResponseError as error:
            if error.status_code != 412 or attempt == 3:
                raise
            record = container.read_item(context.request_id, partition_key=context.data_user_id)
            if record.get("memory_budget_run_id") not in (None, run_id):
                raise M365ProviderError("request_memory_mismatch", "The request budget changed unexpectedly.") from error
    raise M365ProviderError("request_memory_busy", "The request budget could not be saved. Review the request before retrying.")


def configure_m365_file_runtime():
    configure_m365_workflow_checkpoints(
        memory_resolver=resolve_m365_memory,
        jobs_factory=lambda: cosmos_m365_execution_runs_container,
    )
    configure_m365_agent_continuation(
        memory_resolver=resolve_m365_memory,
        jobs_factory=lambda: cosmos_m365_execution_runs_container,
        model_context_setter=configure_m365_model_context,
    )
    configure_m365_retrieval(
        memory_resolver=resolve_m365_memory,
        request_run_resolver=resolve_m365_budget_run,
        model_budget_resolver=resolve_m365_model_room,
        token_counter=count_m365_context_tokens,
        analysis_callback=analyze_m365_memory,
    )
