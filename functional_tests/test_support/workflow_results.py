# workflow_results.py
"""
Isolated workflow result dependencies for existing sequence unit tests.
Version: 0.261.122
Implemented in: 0.261.106
"""

import hashlib
import json
import logging

from azure.core.exceptions import AzureError
from functions_m365_approvals import M365ApprovalRequired
from functions_m365_workflow_checkpoints import (
    m365_workflow_task_context,
    read_m365_task_checkpoint,
    save_m365_task_checkpoint,
)
from m365_interaction import M365SignInRequired
from functions_workflow_result_store import WorkflowResultStorageUnavailableError, WorkflowResultTooLargeError
from functions_workflow_context import (
    WorkflowContextBudgetError,
    WorkflowModelClient,
    invoke_workflow_agent,
    raise_if_workflow_context_blocked,
    workflow_context_budget_scope,
    wrap_workflow_chat_service,
    wrap_workflow_model_client,
)
from functions_workflow_results import (
    WorkflowResultNotReadyError,
    build_workflow_task_result,
    get_workflow_result_text,
    load_workflow_task_input,
    persist_workflow_task_result,
    workflow_result_summary,
    authorize_workflow_task_result_read,
)
from functions_saved_analysis import SavedAnalysisInput, explain_saved_analysis
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_bindings import (
    WorkflowInputError,
    attach_workflow_reference_sources,
    load_workflow_reference,
    resolve_workflow_task_inputs,
)
from functions_workflow_validation import (
    validate_workflow_task_output,
    workflow_output_contract_instruction,
    workflow_run_outcome,
)
from functions_saved_analysis import SavedAnalysisInput, explain_saved_analysis
from functions_workflow_execution import (
    WorkflowSuspended,
    assert_workflow_execution_owned,
    current_workflow_execution,
    workflow_checkpoint_scope_guard,
    workflow_unit,
)
from functions_workflow_readiness import (
    WorkflowOutputUnavailable,
    pending_workflow_output_references,
    reconcile_workflow_pending_output,
    reconcile_workflow_publication_output,
)
from functions_workflow_runtime_store import WorkflowRuntimeConflict


def workflow_result_helpers():
    stored = {}

    def save_result(workflow, run_id, task_id, result, **kwargs):
        data = json.dumps(result, allow_nan=False)
        digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
        key = (workflow["id"], run_id, task_id, digest)
        stored[key] = data
        return {"task_id": task_id, "size_bytes": len(data), "sha256": digest}

    def load_result(workflow, run_id, task_id, reference):
        assert reference["task_id"] == task_id
        return json.loads(stored[(workflow["id"], run_id, task_id, reference["sha256"])])

    return {
        "M365ApprovalRequired": M365ApprovalRequired,
        "M365SignInRequired": M365SignInRequired,
        "m365_workflow_task_context": m365_workflow_task_context,
        "read_m365_task_checkpoint": read_m365_task_checkpoint,
        "save_m365_task_checkpoint": save_m365_task_checkpoint,
        "AzureError": AzureError,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "WorkflowResultTooLargeError": WorkflowResultTooLargeError,
        "WorkflowContextBudgetError": WorkflowContextBudgetError,
        "WorkflowResultNotReadyError": WorkflowResultNotReadyError,
        "AnalysisResultUnavailable": AnalysisResultUnavailable,
        "WorkflowInputError": WorkflowInputError,
        "WorkflowSuspended": WorkflowSuspended,
        "WorkflowRuntimeConflict": WorkflowRuntimeConflict,
        "assert_workflow_execution_owned": assert_workflow_execution_owned,
        "current_workflow_execution": current_workflow_execution,
        "workflow_checkpoint_scope_guard": workflow_checkpoint_scope_guard,
        "workflow_unit": workflow_unit,
        "WorkflowOutputUnavailable": WorkflowOutputUnavailable,
        "pending_workflow_output_references": pending_workflow_output_references,
        "reconcile_workflow_pending_output": reconcile_workflow_pending_output,
        "reconcile_workflow_publication_output": reconcile_workflow_publication_output,
        "attach_workflow_reference_sources": attach_workflow_reference_sources,
        "load_workflow_reference": load_workflow_reference,
        "resolve_workflow_task_inputs": resolve_workflow_task_inputs,
        "validate_workflow_task_output": validate_workflow_task_output,
        "workflow_output_contract_instruction": workflow_output_contract_instruction,
        "workflow_run_outcome": workflow_run_outcome,
        "WorkflowModelClient": WorkflowModelClient,
        "SavedAnalysisInput": SavedAnalysisInput,
        "explain_saved_analysis": explain_saved_analysis,
        "invoke_workflow_agent": invoke_workflow_agent,
        "raise_if_workflow_context_blocked": raise_if_workflow_context_blocked,
        "workflow_context_budget_scope": workflow_context_budget_scope,
        "wrap_workflow_chat_service": wrap_workflow_chat_service,
        "wrap_workflow_model_client": wrap_workflow_model_client,
        "build_workflow_task_result": build_workflow_task_result,
        "get_workflow_result_text": get_workflow_result_text,
        "load_workflow_task_input": lambda workflow, run_id, task_id, reference, **kwargs: load_workflow_task_input(
            workflow, run_id, task_id, reference, load_result=load_result, **kwargs,
        ),
        "persist_workflow_task_result": lambda envelope, **kwargs: persist_workflow_task_result(
            envelope, save_result=save_result, **kwargs,
        ),
        "workflow_result_summary": workflow_result_summary,
        "authorize_workflow_task_result_read": lambda *args, **kwargs: authorize_workflow_task_result_read(
            *args, load_result=load_result, **kwargs,
        ),
        "save_workflow_task_result": save_result,
        "load_workflow_task_result": load_result,
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
    }
