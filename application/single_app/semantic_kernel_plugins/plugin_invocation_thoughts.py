# plugin_invocation_thoughts.py
"""Helpers for turning plugin invocations into thought records."""


EXCLUDED_PARAMETER_NAMES = {
    'conversation_id',
    'group_id',
    'public_workspace_id',
    'scope_id',
    'thread_id',
    'user_id',
}


def _get_parameter_value(parameters, *names):
    for name in names:
        if name in parameters:
            return parameters[name]
    return None


def _format_value(value, max_length=60):
    if value is None:
        return None

    rendered_value = str(value)
    if len(rendered_value) > max_length:
        return f"{rendered_value[: max_length - 3]}..."
    return rendered_value


def _format_duration_suffix(invocation):
    duration_ms = getattr(invocation, 'duration_ms', None)
    return f" ({int(duration_ms)}ms)" if duration_ms else ""


def _format_success_suffix(invocation):
    return " failed" if not getattr(invocation, 'success', True) else ""


def _format_generic_parameter_summary(parameters):
    rendered_items = []
    for parameter_name, parameter_value in (parameters or {}).items():
        if parameter_name in EXCLUDED_PARAMETER_NAMES:
            continue

        rendered_value = _format_value(parameter_value, max_length=24)
        if rendered_value is None:
            continue

        rendered_items.append(f"{parameter_name}={rendered_value}")
        if len(rendered_items) == 2:
            break

    if not rendered_items:
        return ""
    return f" [{', '.join(rendered_items)}]"


def _format_wait_content(invocation, actor_label, parameters):
    seconds = _get_parameter_value(parameters, 'input', 'seconds', 'arg_0')
    rendered_seconds = _format_value(seconds, max_length=20) or 'the requested interval'
    return f"{actor_label} invoked wait for {rendered_seconds} seconds{_format_duration_suffix(invocation)}{_format_success_suffix(invocation)}"


def _format_math_content(invocation, actor_label, parameters):
    function_name = getattr(invocation, 'function_name', '')
    result = getattr(invocation, 'result', None)
    input_value = _format_value(_get_parameter_value(parameters, 'input', 'arg_0'), max_length=20)
    amount_value = _format_value(_get_parameter_value(parameters, 'amount', 'arg_1'), max_length=20)
    exponent_value = _format_value(_get_parameter_value(parameters, 'exponent', 'arg_1'), max_length=20)
    symbol_map = {
        'Add': ('+', amount_value),
        'Subtract': ('-', amount_value),
        'Multiply': ('*', amount_value),
        'Divide': ('/', amount_value),
        'Modulus': ('%', amount_value),
        'Power': ('^', exponent_value),
    }

    if function_name == 'SquareRoot':
        math_summary = f"sqrt({input_value})"
    elif function_name in symbol_map and input_value is not None and symbol_map[function_name][1] is not None:
        operator_symbol, right_hand_value = symbol_map[function_name]
        math_summary = f"{input_value} {operator_symbol} {right_hand_value}"
    else:
        math_summary = function_name

    rendered_result = _format_value(result, max_length=30)
    result_suffix = f" = {rendered_result}" if rendered_result is not None and getattr(invocation, 'success', True) else ""
    return f"{actor_label} performed math: {math_summary}{result_suffix}{_format_duration_suffix(invocation)}{_format_success_suffix(invocation)}"


def _format_plugin_content(invocation, actor_label, parameters):
    plugin_name = getattr(invocation, 'plugin_name', '')
    function_name = getattr(invocation, 'function_name', '')

    if plugin_name == 'WaitPlugin' and function_name == 'wait':
        return _format_wait_content(invocation, actor_label, parameters)

    if plugin_name == 'MathPlugin':
        return _format_math_content(invocation, actor_label, parameters)

    parameter_summary = _format_generic_parameter_summary(parameters)
    return (
        f"{actor_label} executed {plugin_name}.{function_name}"
        f"{parameter_summary}{_format_duration_suffix(invocation)}{_format_success_suffix(invocation)}"
    )


def _format_plugin_detail(invocation, parameters):
    detail_parts = []

    for parameter_name, parameter_value in (parameters or {}).items():
        if parameter_name in EXCLUDED_PARAMETER_NAMES:
            continue

        rendered_value = _format_value(parameter_value, max_length=80)
        if rendered_value is None:
            continue

        detail_parts.append(f"{parameter_name}={rendered_value}")

    result = getattr(invocation, 'result', None)
    rendered_result = _format_value(result, max_length=120)
    if rendered_result is not None and getattr(invocation, 'success', True):
        detail_parts.append(f"result={rendered_result}")

    error_message = getattr(invocation, 'error_message', None)
    if error_message:
        detail_parts.append(f"error={_format_value(error_message, max_length=120)}")

    detail_parts.append(f"success={getattr(invocation, 'success', True)}")
    return '; '.join(detail_parts)


def format_plugin_invocation_start_thought(invocation_start):
    """Build a concise thought payload for an in-flight plugin invocation."""
    plugin_name = getattr(invocation_start, 'plugin_name', 'Plugin')
    function_name = getattr(invocation_start, 'function_name', 'function')
    parameters = getattr(invocation_start, 'parameters', {}) or {}
    detail = '; '.join(
        f"{parameter_name}={_format_value(parameter_value, max_length=80)}"
        for parameter_name, parameter_value in parameters.items()
        if parameter_name not in EXCLUDED_PARAMETER_NAMES and _format_value(parameter_value, max_length=80) is not None
    )
    return {
        'step_type': 'agent_tool_call',
        'content': f"Invoking {plugin_name}.{function_name}",
        'detail': detail or None,
    }


def format_plugin_invocation_thought(invocation, actor_label='Agent'):
    """Build a thought payload from a logged plugin invocation."""
    parameters = getattr(invocation, 'parameters', {}) or {}
    return {
        'step_type': 'agent_tool_call',
        'content': _format_plugin_content(invocation, actor_label, parameters),
        'detail': _format_plugin_detail(invocation, parameters),
    }


def register_plugin_invocation_thought_callback(plugin_logger, thought_tracker, user_id, conversation_id, actor_label='Agent'):
    """Register a logger callback that writes plugin invocation thoughts."""
    callback_key = f"{user_id}:{conversation_id}"

    def on_plugin_invocation_start(invocation_start):
        thought_payload = format_plugin_invocation_start_thought(invocation_start)
        thought_tracker.add_thought(
            thought_payload['step_type'],
            thought_payload['content'],
            detail=thought_payload['detail']
        )

    def on_plugin_invocation(invocation):
        thought_payload = format_plugin_invocation_thought(invocation, actor_label=actor_label)
        thought_tracker.add_thought(
            thought_payload['step_type'],
            thought_payload['content'],
            detail=thought_payload['detail']
        )

    plugin_logger.register_start_callback(callback_key, on_plugin_invocation_start)
    plugin_logger.register_callback(callback_key, on_plugin_invocation)
    return callback_key