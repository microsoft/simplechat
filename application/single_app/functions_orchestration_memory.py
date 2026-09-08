# functions_orchestration_memory.py
"""Read-only, audience-bound saved memory for orchestration.

Version: 0.261.104
"""

from azure.core.exceptions import AzureError

from collaboration_models import (
    COLLABORATION_KIND,
    COLLABORATION_SOURCE_KIND,
    GROUP_MULTI_USER_CHAT_TYPE,
    PERSONAL_MULTI_USER_CHAT_TYPE,
)
from functions_appinsights import log_event


class OrchestrationMemoryError(ValueError):
    """A safe memory-context failure, distinct from an empty or disabled memory."""

    def __init__(self, message, *, code='memory_context_unavailable'):
        super().__init__(message)
        self.message = message
        self.code = code


def validate_memory_audience(conversation, user_id, expected=None):
    """Ownership does not make a collaboration backing conversation private."""
    if not isinstance(conversation, dict) or not user_id or conversation.get('user_id') != user_id:
        raise OrchestrationMemoryError('The memory context could not be authorized.')
    collaboration_id = str(conversation.get('collaboration_conversation_id') or '').strip()
    shared = bool(
        collaboration_id
        or conversation.get('is_hidden') is True
        or conversation.get('conversation_kind') in (COLLABORATION_KIND, COLLABORATION_SOURCE_KIND)
        or conversation.get('chat_type') in (GROUP_MULTI_USER_CHAT_TYPE, PERSONAL_MULTI_USER_CHAT_TYPE)
    )
    audience = {
        'kind': 'shared' if shared else 'personal',
        'owner_id': user_id,
        'collaboration_id': collaboration_id,
    }
    if expected is not None and expected != audience:
        raise OrchestrationMemoryError(
            'The conversation audience changed. Create a new plan before using saved memory.',
            code='memory_audience_changed',
        )
    return audience


def validate_memory_context(conversation, user_id, expected_audience=None, scope=None):
    """Reauthorize the scope actually recalled, without rereading or changing its facts."""
    audience = validate_memory_audience(conversation, user_id, expected_audience)
    if scope is None:
        return
    if (
        audience['kind'] != 'personal'
        or not isinstance(scope, dict)
        or scope.get('type') not in ('user', 'group')
        or not isinstance(scope.get('id'), str) or not scope['id'].strip()
    ):
        raise OrchestrationMemoryError('The saved memory context is no longer valid.')
    if scope['type'] == 'user':
        if scope['id'] != user_id:
            raise OrchestrationMemoryError('The memory context could not be authorized.')
        return

    # Disabled/unscoped paths must not initialize group or memory dependencies.
    from functions_group import assert_group_role

    try:
        assert_group_role(
            user_id, scope['id'], allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
    except PermissionError as exc:
        raise OrchestrationMemoryError(
            'The selected memory scope is no longer available. Update the sources and plan again.',
            code='memory_scope_unavailable',
        ) from exc
    except AzureError as exc:
        raise OrchestrationMemoryError('Saved memory access could not be checked. Please retry.') from exc


def load_orchestration_memory(
    user_id, conversation, query_text, *, settings, seeds=None, expected_audience=None,
):
    """Recall existing instructions/facts without autosave, backfill, or new privileges."""
    audience = validate_memory_audience(conversation, user_id, expected_audience)
    result = {
        'audience': audience, 'status': 'disabled', 'scope_type': None, 'scope': None,
        'context_messages': [], 'citations': [], 'notices': [],
    }
    if not settings.get('enable_fact_memory_plugin', False):
        return result
    if audience['kind'] == 'shared':
        # The owner-only orchestration route does not establish a shared memory audience.
        result.update(status='unavailable', notices=[
            'Saved memory is not used in shared conversations; no personal or group memory was read.',
        ])
        log_event('[ORCHESTRATION] Withheld saved memory from a shared conversation.', debug_only=True)
        return result

    seeds = seeds or {}
    group_ids = seeds.get('active_group_ids') or []
    group_id = group_ids[0] if group_ids and seeds.get('doc_scope', 'all') in ('all', 'group') else None
    if group_id and not settings.get('enable_group_workspaces', False):
        raise OrchestrationMemoryError(
            'The selected group memory scope is not enabled.', code='memory_scope_unavailable',
        )
    scope_type = 'group' if group_id else 'user'
    scope_id = group_id or user_id

    # The disabled path must not initialize memory storage or embedding dependencies.
    from functions_fact_memory_context import build_fact_memory_prompt_payload

    try:
        payload = build_fact_memory_prompt_payload(
            scope_id=scope_id, scope_type=scope_type, query_text=query_text,
            conversation_id=conversation['id'], agent_id=None,
            enabled=True, read_only=True, authorized_user_id=user_id,
        )
    except PermissionError as exc:
        raise OrchestrationMemoryError(
            'The selected memory scope is no longer available. Update the sources and plan again.',
            code='memory_scope_unavailable',
        ) from exc
    except AzureError as exc:
        raise OrchestrationMemoryError('Saved memory could not be loaded. Please retry.') from exc

    messages = payload['context_messages']
    result.update(
        status='available' if messages else 'empty', scope_type=scope_type,
        scope={'type': scope_type, 'id': scope_id},
        context_messages=messages, citations=payload['citations'],
    )
    if payload['recall_payload']['search_mode'] == 'embedding_unavailable':
        result.update(
            status='partial' if messages else 'unavailable',
            notices=['Saved facts could not be searched. Any available instruction memories are still included.'],
        )
    return result
