# functions_fact_memory_autosave.py
"""
Agent-free fact memory writes for the standard chat experience.

Memory recall already works without agents, but creating, updating, and deleting
memories previously required the Semantic Kernel agent path because that was the only
place `FactMemoryPlugin` was attached to a kernel with automatic function calling.

This module closes that gap with a small, self-contained kernel that carries only the
fact-memory plugin. It runs after the assistant response is already finalized, so it can
never alter or delay the answer the user sees, and it is gated by a cheap intent
pre-filter so ordinary turns pay no extra model call.

The pass must run inside the originating Flask request: `FactMemoryPlugin` resolves its
authorization boundary from `g.authorized_chat_context`, which is what keeps a tool call
from writing outside the caller's own user or group scope.
"""

import logging
import re

from functions_appinsights import log_event
from functions_model_endpoint_runtime import build_semantic_kernel_chat_service_for_model
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import (
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel_plugins.fact_memory_plugin import FactMemoryPlugin
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger

FACT_MEMORY_PLUGIN_NAME = 'fact_memory'
FACT_MEMORY_AUTOSAVE_SERVICE_ID = 'fact-memory-autosave'
FACT_MEMORY_WRITE_FUNCTIONS = ('set_fact', 'update_fact', 'delete_fact')
FACT_MEMORY_MAX_AUTO_INVOKE_ATTEMPTS = 5
FACT_MEMORY_ASSISTANT_CONTEXT_CHARS = 2000
FACT_MEMORY_THOUGHT_STEP_TYPE = 'fact_memory'

# Recall questions ("do you remember...", "what do you know about me") read memory rather
# than change it, and the recall path already handles them. Screening them out first keeps
# the broad `remember` pattern below from firing a pointless write pass on every such turn.
_MEMORY_RECALL_QUESTION_PATTERNS = (
    r'^(?:do|does|did|can|could|would|will)\s+you\b[^?]*\b(?:remember|recall|know)\b',
    r'\bwhat\s+do\s+you\s+(?:remember|recall|know)\b',
    r'\b(?:what|which|how\s+many)\b[^?]*\b(?:memories|memory)\b[^?]*\?',
)

_MEMORY_WRITE_PATTERNS = (
    # Explicit memory vocabulary.
    r'\bremember\b',
    r'\bmemoriz(?:e|ing)\b',
    r"\bdon'?t\s+forget\b",
    r'\bforget\s+(?:that|about|what|my|this|it)\b',
    r'\bkeep\s+(?:this|that|it)\s+in\s+mind\b',
    r'\b(?:make|take)\s+a\s+note\b',
    r'\bnote\s+that\b',
    r'\b(?:my|saved)\s+memor(?:y|ies)\b',
    r'\bto\s+memory\b',
    # Durable behavior instructions.
    r'\bfrom\s+now\s+on\b',
    r'\b(?:going|moving)\s+forward\b',
    r'\bin\s+the\s+future\b',
    r'\bevery\s+time\s+(?:i|we|you)\b',
    r'\bno\s+longer\b',
    r'\b(?:you\s+should\s+|please\s+)?(?:always|never)\s+'
    r'(?:use|say|call|include|show|add|start|stop|respond|reply|answer|format|write|give|mention|assume|treat|refer)\b',
    r'\b(?:stop|quit)\s+\w+ing\b',
    r'\bi\s+want\s+you\s+to\s+(?:always|never|start|stop)\b',
    # Identity and durable preferences.
    r'\bmy\s+name\s+is\b',
    r'\bcall\s+me\b',
    r'\bi\s+go\s+by\b',
    r"\bi\s+(?:prefer|dislike|hate|don'?t\s+like|do\s+not\s+like)\b",
)

_MEMORY_RECALL_QUESTION_REGEXES = tuple(
    re.compile(pattern) for pattern in _MEMORY_RECALL_QUESTION_PATTERNS
)
_MEMORY_WRITE_REGEXES = tuple(re.compile(pattern) for pattern in _MEMORY_WRITE_PATTERNS)

_AUTOSAVE_SYSTEM_PROMPT = """You maintain the saved memories for one specific user.

You are not answering the user. The assistant has already replied. Your only job is to decide
whether the latest exchange contains something the user wants remembered, changed, or removed,
and to make that change with the available tools.

Call a tool only when the user explicitly asks for a durable change, such as asking you to
remember something, telling you how they want you to behave from now on, correcting a detail
about themselves, or asking you to forget or stop something. Do not save passing details,
one-off task instructions, or anything the user did not ask you to retain.

Use memory_type='instruction' for durable rules about how to respond, and memory_type='fact'
for details about the user that should only surface when relevant.

To change or remove an existing memory, call get_facts first so you have the correct fact id.

If nothing should change, reply with exactly NO_MEMORY_CHANGE and call no tools."""


def user_requested_memory_update(user_message):
    """Return True when the user is explicitly asking to save, change, or remove a memory."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    if any(regex.search(normalized_message) for regex in _MEMORY_RECALL_QUESTION_REGEXES):
        return False

    return any(regex.search(normalized_message) for regex in _MEMORY_WRITE_REGEXES)


def should_run_fact_memory_autosave(user_message, fact_memory_enabled, selected_agent=None):
    """Return True when the agent-free memory pass should run for this turn.

    An agent run already had the fact-memory tool attached inline, so re-running the pass
    afterwards would risk duplicate writes for the same request.
    """
    if not fact_memory_enabled:
        return False
    if selected_agent is not None:
        return False
    return user_requested_memory_update(user_message)


def _truncate(value, limit=160):
    text = re.sub(r'\s+', ' ', str(value or '').strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def _describe_invocation(invocation):
    """Build a user-facing description for one fact-memory tool call."""
    function_name = getattr(invocation, 'function_name', '') or ''
    parameters = getattr(invocation, 'parameters', {}) or {}
    if not isinstance(parameters, dict):
        parameters = {}

    memory_type = str(parameters.get('memory_type') or 'fact').strip().lower()
    type_label = 'instruction' if memory_type == 'instruction' else 'fact'
    value_preview = _truncate(parameters.get('value'))

    if function_name == 'set_fact':
        content = f'Saved a new {type_label} memory'
        detail = value_preview or None
    elif function_name == 'update_fact':
        content = 'Updated a saved memory'
        detail = value_preview or None
    elif function_name == 'delete_fact':
        content = 'Removed a saved memory'
        detail = None
    else:
        return None

    if not getattr(invocation, 'success', True):
        return {
            'function_name': function_name,
            'success': False,
            'content': 'Could not update saved memories',
            'detail': _truncate(getattr(invocation, 'error_message', '')) or None,
        }

    return {
        'function_name': function_name,
        'success': True,
        'content': content,
        'detail': detail,
    }


def _collect_memory_changes(plugin_logger, user_id, conversation_id, baseline_count):
    """Return descriptions of the fact-memory writes performed since the baseline."""
    try:
        invocations = plugin_logger.get_invocations_for_conversation(
            user_id,
            conversation_id,
            limit=1000,
        )
    except Exception as exc:
        log_event(
            f'[FACT_MEMORY_AUTOSAVE] Unable to read plugin invocations: {exc}',
            level=logging.WARNING,
        )
        return []

    new_invocations = list(invocations or [])[baseline_count:]
    changes = []
    for invocation in new_invocations:
        if getattr(invocation, 'function_name', '') not in FACT_MEMORY_WRITE_FUNCTIONS:
            continue
        described = _describe_invocation(invocation)
        if described:
            changes.append(described)
    return changes


def _build_autosave_chat_history(user_message, assistant_message, scope_id, scope_type, conversation_id):
    chat_history = ChatHistory()
    chat_history.add_system_message(_AUTOSAVE_SYSTEM_PROMPT)
    chat_history.add_system_message(
        'When calling a tool use these argument values: '
        f"scope_type='{scope_type}', scope_id='{scope_id}', "
        f"conversation_id='{conversation_id or ''}', agent_id=''."
    )
    chat_history.add_user_message(
        'Latest exchange to evaluate.\n\n'
        f'User said:\n{str(user_message or "").strip()}\n\n'
        f'Assistant replied:\n{_truncate(assistant_message, FACT_MEMORY_ASSISTANT_CONTEXT_CHARS)}'
    )
    return chat_history


async def run_fact_memory_autosave(
    user_message,
    assistant_message,
    settings,
    gpt_model,
    scope_id,
    scope_type,
    conversation_id,
    user_id,
    model_context=None,
):
    """Let the model persist explicit memory changes without requiring agents or actions.

    Returns a payload of `{'changes': [...], 'thoughts': [...], 'error': str | None}`.
    Every failure is contained here: a memory problem must never break a chat response.
    """
    payload = {'changes': [], 'thoughts': [], 'error': None}

    try:
        kernel = Kernel()
        kernel.add_plugin(FactMemoryPlugin(), plugin_name=FACT_MEMORY_PLUGIN_NAME)

        chat_service, _runtime_protocol = build_semantic_kernel_chat_service_for_model(
            gpt_model,
            settings,
            service_id=FACT_MEMORY_AUTOSAVE_SERVICE_ID,
            model_context=model_context,
        )
        kernel.add_service(chat_service)

        plugin_logger = get_plugin_logger()
        try:
            baseline_count = len(
                plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000) or []
            )
        except Exception:
            baseline_count = 0

        chat_history = _build_autosave_chat_history(
            user_message,
            assistant_message,
            scope_id,
            scope_type,
            conversation_id,
        )

        execution_settings = AzureChatPromptExecutionSettings(
            service_id=FACT_MEMORY_AUTOSAVE_SERVICE_ID,
            function_choice_behavior=FunctionChoiceBehavior.Auto(
                maximum_auto_invoke_attempts=FACT_MEMORY_MAX_AUTO_INVOKE_ATTEMPTS,
                filters={'included_plugins': [FACT_MEMORY_PLUGIN_NAME]},
            ),
        )

        await chat_service.get_chat_message_contents(
            chat_history,
            execution_settings,
            kernel=kernel,
        )

        payload['changes'] = _collect_memory_changes(
            plugin_logger,
            user_id,
            conversation_id,
            baseline_count,
        )
        payload['thoughts'] = [
            {
                'step_type': FACT_MEMORY_THOUGHT_STEP_TYPE,
                'content': change['content'],
                'detail': change.get('detail'),
            }
            for change in payload['changes']
        ]

        log_event(
            f'[FACT_MEMORY_AUTOSAVE] Completed memory pass with {len(payload["changes"])} change(s).',
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'scope_type': scope_type,
                'change_count': len(payload['changes']),
            },
            level=logging.INFO,
        )
    except Exception as exc:
        payload['error'] = str(exc)
        log_event(
            f'[FACT_MEMORY_AUTOSAVE] Memory pass failed and was skipped: {exc}',
            extra={'user_id': user_id, 'conversation_id': conversation_id},
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    return payload
