# functions_tabular_analysis.py
"""
Reusable tabular analysis helpers for chat and workflow execution.

This module owns extracted tabular coordination helpers and provides the
non-route import surface for behavior still implemented in
route_backend_chats.py. Keeping workflow code pointed here lets the remaining
implementation move incrementally without changing workflow callers again.
"""

def _load_chat_helper(helper_name):
    # Import lazily because route_backend_chats imports functions_workflow_runner during app startup.
    from route_backend_chats import (
        _execute_mixed_source_tabular_evidence,
        augment_tabular_invocations_with_related_document_evidence,
        build_tabular_computed_results_system_message,
        build_tabular_related_document_evidence_summary,
        maybe_create_tabular_generated_output,
        maybe_queue_direct_tabular_generated_output,
        run_tabular_analysis_with_thought_tracking,
    )

    helpers = {
        'execute_mixed_source_tabular_evidence': _execute_mixed_source_tabular_evidence,
        'augment_tabular_invocations_with_related_document_evidence': augment_tabular_invocations_with_related_document_evidence,
        'build_tabular_computed_results_system_message': build_tabular_computed_results_system_message,
        'build_tabular_related_document_evidence_summary': build_tabular_related_document_evidence_summary,
        'maybe_create_tabular_generated_output': maybe_create_tabular_generated_output,
        'maybe_queue_direct_tabular_generated_output': maybe_queue_direct_tabular_generated_output,
        'run_tabular_analysis_with_thought_tracking': run_tabular_analysis_with_thought_tracking,
    }
    return helpers[helper_name]


def _load_orchestration_helper(helper_name):
    from functions_tabular_orchestration import (
        execute_tabular_plan,
        orchestrate_tabular_request,
        plan_tabular_request,
    )

    helpers = {
        'execute_tabular_plan': execute_tabular_plan,
        'orchestrate_tabular_request': orchestrate_tabular_request,
        'plan_tabular_request': plan_tabular_request,
    }
    return helpers[helper_name]


def plan_tabular_request(*args, **kwargs):
    return _load_orchestration_helper('plan_tabular_request')(*args, **kwargs)


def execute_tabular_plan(*args, **kwargs):
    return _load_orchestration_helper('execute_tabular_plan')(*args, **kwargs)


def orchestrate_tabular_request(*args, **kwargs):
    return _load_orchestration_helper('orchestrate_tabular_request')(*args, **kwargs)


def queue_direct_tabular_generated_output_from_plan(
    plan,
    user_question,
    file_contexts,
    user_id,
    conversation_id,
    gpt_model,
    settings,
    thought_callback=None,
    model_context=None,
    cancel_requested=None,
    request_correlation_id=None,
):
    """Invoke the existing source-backed durable preflight for an accepted plan."""
    if not isinstance(plan, dict):
        return None
    if plan.get('execution_contract') == 'foreground_aggregate':
        return None
    if plan.get('reason_code') != 'durable_intent' or not plan.get('durable_task_type'):
        return None

    helper = _load_chat_helper('maybe_queue_direct_tabular_generated_output')
    return helper(
        user_question=user_question,
        file_contexts=file_contexts,
        user_id=user_id,
        conversation_id=conversation_id,
        gpt_model=gpt_model,
        settings=settings,
        thought_callback=thought_callback,
        model_context=model_context,
        cancel_requested=cancel_requested,
        request_correlation_id=request_correlation_id,
        planner_metadata=plan,
    )


def execute_mixed_source_tabular_evidence(*args, **kwargs):
    return _load_chat_helper('execute_mixed_source_tabular_evidence')(*args, **kwargs)


def augment_tabular_invocations_with_related_document_evidence(*args, **kwargs):
    return _load_chat_helper('augment_tabular_invocations_with_related_document_evidence')(*args, **kwargs)


def build_tabular_computed_results_system_message(*args, **kwargs):
    return _load_chat_helper('build_tabular_computed_results_system_message')(*args, **kwargs)


def build_tabular_related_document_evidence_summary(*args, **kwargs):
    return _load_chat_helper('build_tabular_related_document_evidence_summary')(*args, **kwargs)


def get_new_plugin_invocations(invocations, baseline_count):
    """Return only the plugin invocations created after the baseline count."""
    if not invocations:
        return []

    if baseline_count <= 0:
        return list(invocations)

    if baseline_count >= len(invocations):
        return []

    return list(invocations[baseline_count:])


async def maybe_create_tabular_generated_output(*args, **kwargs):
    helper = _load_chat_helper('maybe_create_tabular_generated_output')
    return await helper(*args, **kwargs)


def maybe_queue_direct_tabular_generated_output(*args, **kwargs):
    helper = _load_chat_helper('maybe_queue_direct_tabular_generated_output')
    return helper(*args, **kwargs)


async def run_tabular_analysis_with_thought_tracking(*args, **kwargs):
    helper = _load_chat_helper('run_tabular_analysis_with_thought_tracking')
    return await helper(*args, **kwargs)
