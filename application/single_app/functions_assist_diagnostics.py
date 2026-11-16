# functions_assist_diagnostics.py
"""Content-free diagnostics shared by the editor and workflow Ask AI cores."""

import hashlib
import math
import time


ASSIST_DIAGNOSTIC_LIMIT = 12
ASSIST_DIAGNOSTIC_TEXT = {
    'assist_surface': frozenset({'agent', 'action', 'workflow'}),
    'assist_scope': frozenset({'personal', 'group', 'global'}),
    'assist_event': frozenset({
        'model_started', 'model_finished', 'provider_finished', 'provider_failed', 'json_mode_fallback',
        'validation_rejected', 'correction_started', 'request_finished',
    }),
    'assist_stage': frozenset({
        'request', 'limit', 'base', 'projection', 'references', 'options', 'handles', 'excerpts',
        'envelope', 'model', 'evaluate', 'warnings', 'response', 'parse', 'shape', 'length',
        'operations', 'schema', 'apply', 'violation', 'validation',
    }),
    'assist_outcome': frozenset({'changed', 'explained', 'question', 'failed'}),
    'assist_code': frozenset({
        'invalid_request', 'instruction_invalid', 'conversation_invalid', 'draft_invalid', 'focus_invalid',
        'time_zone_invalid', 'tags_unsupported', 'reference_limit', 'reference_unavailable',
        'group_workflow_unsupported', 'workflow_read_only', 'assistant_input_too_large', 'request_too_large',
        'workflow_not_found', 'workflow_definition_conflict', 'workflow_deleted', 'assistant_busy',
        'assistant_rate_limited', 'assistant_output_invalid', 'assistant_refused', 'assistant_unavailable',
        'assistant_timeout', 'assistant_limit_unavailable', 'reference_check_failed', 'assistant_failed',
        'agent_assistant_disabled', 'action_assistant_disabled', 'scope_forbidden', 'scope_not_found',
    }),
    'assist_finish_reason': frozenset({'stop', 'length', 'content_filter', 'tool_calls', 'function_call', 'missing', 'other'}),
    'assist_validation_code': frozenset({
        'invalid_workflow', 'invalid_workflow_definition', 'invalid_workflow_settings', 'invalid_workflow_alerts',
        'blueprint_invalid', 'unsupported_field', 'too_many_tasks', 'trigger_invalid', 'cadence_below_minimum',
        'quota_exceeded', 'agent_unavailable', 'reference_unknown', 'reference_unauthorized',
        'file_sync_source_unavailable', 'workflow_conflict', 'workflows_unavailable', 'scope_unavailable',
        'merge_unavailable', 'merge_inputs_required', 'merge_trigger_required', 'merge_runner_invalid',
        'merge_options_invalid', 'merge_format_invalid',
    }),
    'assist_field_kind': frozenset({'text', 'textarea', 'number', 'boolean', 'select', 'choices', 'lines', 'web_sources'}),
    'assist_rule': frozenset({
        'empty_reply', 'invalid_json', 'invalid_json_value', 'reply_not_object',
        'unexpected_reply_field', 'reply_required', 'operations_not_array', 'too_many_operations',
        'operation_shape', 'output_truncated', 'create_unavailable', 'create_shape',
        'new_handle_invalid', 'too_many_new_items', 'new_type_invalid', 'new_values_not_object',
        'new_field_unknown', 'new_required_field', 'field_unknown', 'field_read_only',
        'field_repeated', 'text_invalid', 'text_multiline', 'text_too_long', 'required_value',
        'number_invalid', 'number_below_minimum', 'number_above_maximum', 'boolean_invalid',
        'select_invalid', 'choices_not_array', 'choice_handle_invalid', 'too_many_items',
        'lines_not_array', 'line_invalid', 'line_too_long', 'web_sources_not_array',
        'web_source_shape', 'web_source_url', 'web_source_mode', 'field_kind_invalid',
        'created_item_unassigned', 'operation_invalid', 'handle_invalid', 'schedule_invalid',
        'protected_workflow', 'projection_invalid', 'save_validation', 'candidate_invalid',
        'task_limit', 'task_required', 'task_self_reference', 'new_task_key_repeated',
        'document_scope_unknown', 'reference_not_bound', 'alert_scope_invalid',
        'chat_execution_invalid', 'chat_mode_unavailable', 'chat_capability_unavailable', 'chat_output_unavailable',
        'schema_required', 'schema_additional_properties', 'schema_not', 'schema_enum',
        'schema_const', 'schema_type', 'schema_pattern', 'schema_min_length', 'schema_max_length',
        'schema_min_items', 'schema_max_items', 'schema_unique_items', 'schema_minimum',
        'schema_maximum', 'schema_one_of', 'schema_invalid',
    }),
    'assist_operation': frozenset({
        'set', 'create_item', 'set_name', 'set_description', 'set_trigger_manual',
        'set_schedule_interval', 'set_schedule_calendar', 'set_alert_mode', 'add_alert_rule',
        'update_alert_rule', 'remove_alert_rule', 'set_workflow_runner', 'set_task_runner',
        'add_task', 'remove_task', 'move_task', 'set_task_name', 'set_task_instructions',
        'set_task_inputs', 'bind_reference', 'set_task_references', 'unbind_reference',
        'set_task_document_target', 'clear_task_document_target',
        'set_workflow_chat_execution', 'set_task_chat_execution', 'inherit_task_chat_execution',
        'set_results_delivery', 'set_results_recipients', 'set_results_all_group_members',
        'set_task_document_scope', 'set_task_document_selection', 'set_task_merge_options',
        'update_task_document_window', 'replace_task_document_filter',
    }),
    'assist_field': frozenset({
        '/display_name', '/displayName', '/description', '/instructions', '/actions', '/model',
        '/type', '/agent_type', '/reasoning_effort', '/max_completion_tokens',
        '/endpoint', '/deployment', '/api_version', '/auth/type',
        '/knowledge/enabled', '/knowledge/sources', '/knowledge/documents', '/knowledge/tags',
        '/knowledge/web_sources', '/additionalFields/database_type', '/additionalFields/server',
        '/additionalFields/database', '/additionalFields/port', '/additionalFields/driver',
        '/additionalFields/read_only', '/additionalFields/max_rows', '/additionalFields/timeout',
    }),
}
ASSIST_DIAGNOSTIC_NUMBERS = frozenset({
    'attempt', 'provider_attempt', 'operation_index', 'reason_index', 'reason_count', 'elapsed_ms', 'remaining_ms',
    'provider_duration_ms', 'provider_status', 'output_length', 'operation_count', 'model_calls',
    'correction_count', 'status', 'change_count', 'new_item_count',
})
ASSIST_DIAGNOSTIC_FLAGS = frozenset({'output_present', 'json_mode', 'field_known'})


def safe_assist_diagnostics(properties):
    """Keep only closed categories, finite measurements, flags, and a submission hash."""
    safe = {}
    for key, value in properties.items():
        if key in ASSIST_DIAGNOSTIC_TEXT:
            if isinstance(value, str) and value in ASSIST_DIAGNOSTIC_TEXT[key]:
                safe[key] = value
        elif key in ASSIST_DIAGNOSTIC_NUMBERS:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and (
                isinstance(value, int) or math.isfinite(value)
            ):
                safe[key] = max(0, min(value, 1_000_000_000))
        elif key in ASSIST_DIAGNOSTIC_FLAGS:
            if isinstance(value, bool):
                safe[key] = value
        elif key == 'turn_id_hash':
            if isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value):
                safe[key] = value
    return safe


class AssistDiagnostics:
    """An injected, best-effort observer; no settings, Azure, or request content dependencies."""

    def __init__(self, emit=None):
        self._emit = emit
        self._context = {}
        self._clock = time.monotonic
        self._started = self._clock()
        self.attempt = 0

    def bind(self, surface, scope, submission_id=None, *, clock=time.monotonic):
        self._clock = clock
        self._started = clock()
        self.attempt = 0
        self._context = safe_assist_diagnostics({'assist_surface': surface, 'assist_scope': scope})
        if isinstance(submission_id, str) and submission_id:
            self._context['turn_id_hash'] = hashlib.sha256(submission_id.encode('utf-8')).hexdigest()

    def emit(self, event, **properties):
        if self._emit is None or 'assist_surface' not in self._context:
            return
        safe = safe_assist_diagnostics({
            **properties, **self._context, 'assist_event': event, 'attempt': self.attempt,
            'elapsed_ms': int((self._clock() - self._started) * 1000),
        })
        try:
            self._emit(safe)
        except Exception:
            # An observer must not replace the proposal, rejection, or limiter cleanup.
            pass


def assist_finish_reason(value):
    """A provider finish reason is diagnostic data, not an arbitrary log string."""
    if value is None:
        return 'missing'
    if isinstance(value, str) and value in ASSIST_DIAGNOSTIC_TEXT['assist_finish_reason']:
        return value
    return 'other'
