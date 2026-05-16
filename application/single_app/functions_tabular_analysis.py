# functions_tabular_analysis.py
"""
Reusable tabular analysis helpers for chat and workflow execution.

This module is the non-route import surface for tabular analysis behavior that
is still implemented in route_backend_chats.py. Keeping workflow code pointed at
this module lets the implementation move out of the chat route incrementally
without changing workflow callers again.
"""


def _load_chat_helper(helper_name):
    # Import lazily because route_backend_chats imports functions_workflow_runner during app startup.
    from route_backend_chats import (
        augment_tabular_invocations_with_related_document_evidence,
        build_tabular_computed_results_system_message,
        build_tabular_related_document_evidence_summary,
        get_new_plugin_invocations,
        maybe_create_tabular_generated_output,
        run_tabular_analysis_with_thought_tracking,
    )

    helpers = {
        'augment_tabular_invocations_with_related_document_evidence': augment_tabular_invocations_with_related_document_evidence,
        'build_tabular_computed_results_system_message': build_tabular_computed_results_system_message,
        'build_tabular_related_document_evidence_summary': build_tabular_related_document_evidence_summary,
        'get_new_plugin_invocations': get_new_plugin_invocations,
        'maybe_create_tabular_generated_output': maybe_create_tabular_generated_output,
        'run_tabular_analysis_with_thought_tracking': run_tabular_analysis_with_thought_tracking,
    }
    return helpers[helper_name]


def augment_tabular_invocations_with_related_document_evidence(*args, **kwargs):
    return _load_chat_helper('augment_tabular_invocations_with_related_document_evidence')(*args, **kwargs)


def build_tabular_computed_results_system_message(*args, **kwargs):
    return _load_chat_helper('build_tabular_computed_results_system_message')(*args, **kwargs)


def build_tabular_related_document_evidence_summary(*args, **kwargs):
    return _load_chat_helper('build_tabular_related_document_evidence_summary')(*args, **kwargs)


def get_new_plugin_invocations(*args, **kwargs):
    return _load_chat_helper('get_new_plugin_invocations')(*args, **kwargs)


async def maybe_create_tabular_generated_output(*args, **kwargs):
    helper = _load_chat_helper('maybe_create_tabular_generated_output')
    return await helper(*args, **kwargs)


async def run_tabular_analysis_with_thought_tracking(*args, **kwargs):
    helper = _load_chat_helper('run_tabular_analysis_with_thought_tracking')
    return await helper(*args, **kwargs)
