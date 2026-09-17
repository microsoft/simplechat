# workflow_results.py
"""
Isolated workflow result dependencies for existing sequence unit tests.
Version: 0.261.109
Implemented in: 0.261.106
"""

import hashlib
import json
import logging

from azure.core.exceptions import AzureError
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
)
from functions_saved_analysis import SavedAnalysisInput, explain_saved_analysis


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
        "AzureError": AzureError,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "WorkflowResultTooLargeError": WorkflowResultTooLargeError,
        "WorkflowContextBudgetError": WorkflowContextBudgetError,
        "WorkflowResultNotReadyError": WorkflowResultNotReadyError,
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
        "save_workflow_task_result": save_result,
        "load_workflow_task_result": load_result,
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
    }
