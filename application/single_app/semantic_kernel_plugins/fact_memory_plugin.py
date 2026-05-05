# fact_memory_plugin.py
"""
FactMemoryPlugin for Semantic Kernel: provides write/update/delete operations for fact memory.
- Uses FactMemoryStore for persistence.
- Exposes methods for use as a Semantic Kernel plugin (does not need to derive from BasePlugin).
- Read/inject logic is handled separately by orchestration utility.
"""
import logging
from flask import g, has_request_context
from typing import Optional, List

from functions_appinsights import log_event
from functions_authentication import get_current_user_id
from semantic_kernel.functions import kernel_function
from semantic_kernel_fact_memory_store import FactMemoryStore

from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions


class FactMemoryPlugin:
    def __init__(self, store: Optional[FactMemoryStore] = None):
        self.store = store or FactMemoryStore()
        auto_wrap_plugin_functions(self, self.__class__.__name__)

    def _get_authorized_fact_memory_scope(self) -> dict:
        """Return the canonical request-scoped fact-memory authorization boundary."""
        if not has_request_context():
            raise PermissionError('Fact memory requires an active request context.')

        current_user_id = str(get_current_user_id() or '').strip()
        if not current_user_id:
            raise PermissionError('User not authenticated.')

        authorized_context = dict(getattr(g, 'authorized_chat_context', {}) or {})
        authorized_user_id = str(authorized_context.get('user_id') or current_user_id).strip()
        if authorized_user_id != current_user_id:
            authorized_user_id = current_user_id

        authorized_scope_id = str(
            authorized_context.get('fact_memory_scope_id')
            or authorized_context.get('active_group_id')
            or current_user_id
        ).strip()
        authorized_scope_type = str(
            authorized_context.get('fact_memory_scope_type')
            or ('group' if authorized_context.get('active_group_id') else 'user')
        ).strip().lower()
        if authorized_scope_type not in {'user', 'group'}:
            authorized_scope_type = 'user'

        authorized_conversation_id = str(
            authorized_context.get('conversation_id') or getattr(g, 'conversation_id', '') or ''
        ).strip() or None

        return {
            'user_id': authorized_user_id,
            'scope_id': authorized_scope_id,
            'scope_type': authorized_scope_type,
            'conversation_id': authorized_conversation_id,
        }

    def _resolve_authorized_fact_memory_call(
        self,
        scope_type: str = '',
        scope_id: str = '',
        conversation_id: str = '',
    ) -> dict:
        """Normalize tool-call scope arguments against the authorized request scope."""
        authorized_scope = self._get_authorized_fact_memory_scope()
        requested_scope_type = str(scope_type or '').strip().lower()
        requested_scope_id = str(scope_id or '').strip()
        requested_conversation_id = str(conversation_id or '').strip()

        if (
            (requested_scope_type and requested_scope_type != authorized_scope['scope_type'])
            or (requested_scope_id and requested_scope_id != authorized_scope['scope_id'])
        ):
            log_event(
                '[FactMemoryPlugin] Overriding mismatched fact-memory scope in tool call.',
                extra={
                    'requested_scope_type': requested_scope_type,
                    'requested_scope_id': requested_scope_id,
                    'authorized_scope_type': authorized_scope['scope_type'],
                    'authorized_scope_id': authorized_scope['scope_id'],
                },
                level=logging.WARNING,
            )

        if requested_conversation_id and requested_conversation_id != authorized_scope['conversation_id']:
            log_event(
                '[FactMemoryPlugin] Overriding mismatched fact-memory conversation_id in tool call.',
                extra={
                    'requested_conversation_id': requested_conversation_id,
                    'authorized_conversation_id': authorized_scope['conversation_id'],
                },
                level=logging.WARNING,
            )

        return authorized_scope

    @kernel_function(
        description="""
        Store a fact for the given agent, scope, and conversation.

        Args:
            scope_type (str): The type of scope, either 'user' or 'group'.
            scope_id (str): The id of the user or group, depending on scope_type.
            value (str): The value to be stored in memory.
            conversation_id (str): The id of the conversation.
            agent_id (str): The id of the agent, as specified in the agent's manifest.
            memory_type (str): Either 'instruction' or 'fact'. Use 'instruction' for durable response rules or user preferences that should be applied to every future prompt. Use 'fact' for profile/context details that should only be recalled when relevant to the current request.

        Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent.
        Let the model decide the memory_type when saving a new memory.
        """,
        name="set_fact"
    )
    def set_fact(self, scope_type: str, scope_id: str, value: str, conversation_id: str, agent_id: str, memory_type: str = 'fact') -> dict:
        """
        Store a fact for the given agent, scope, and conversation.
        """
        authorized_scope = self._resolve_authorized_fact_memory_call(
            scope_type=scope_type,
            scope_id=scope_id,
            conversation_id=conversation_id,
        )
        return self.store.set_fact(
            scope_type=authorized_scope['scope_type'],
            scope_id=authorized_scope['scope_id'],
            value=value,
            conversation_id=authorized_scope['conversation_id'],
            agent_id=agent_id,
            memory_type=memory_type,
        )

    @kernel_function(
        description="Update an existing fact by its unique id. Provide memory_type only when you want to change it between 'instruction' and 'fact'.",
        name="update_fact"
    )
    def update_fact(self, scope_id: str, fact_id: str, value: str, memory_type: str = '') -> dict:
        """
        Update a fact value by its unique id and scope_id partition key.
        """
        authorized_scope = self._resolve_authorized_fact_memory_call(scope_id=scope_id)
        update_kwargs = {
            'scope_id': authorized_scope['scope_id'],
            'fact_id': fact_id,
            'value': value,
        }
        if str(memory_type or '').strip():
            update_kwargs['memory_type'] = memory_type

        updated_fact = self.store.update_fact(
            **update_kwargs,
        )
        return updated_fact or {}

    @kernel_function(
        description="Delete a fact by its unique id.",
        name="delete_fact"
    )
    def delete_fact(self, scope_id: str, fact_id: str) -> bool:
        """
        Delete a fact by its unique id and the scope_id which is the partition key.
        """
        authorized_scope = self._resolve_authorized_fact_memory_call(scope_id=scope_id)
        return self.store.delete_fact(
            scope_id=authorized_scope['scope_id'],
            fact_id=fact_id
        )

    @kernel_function(
        description="""
        Retrieve all facts for the given user or group. Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent. Use this to get all facts that will be injected as context for the agent.
        Allows the agent to remember important information about the user or group that they designate.
        
        Args:
            scope_type (str): The type of scope, either 'user' or 'group'.
            scope_id (str): The id of the user or group, depending on scope_type.

        Returns:
            List[dict]: A list of fact objects, each representing a persistent fact relevant to the agent and context.
        """,
        name="get_facts"
    )
    def get_facts(self, scope_type: str, scope_id: str,) -> List[dict]:
        """
        Retrieve all facts for the user. Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent. Use this to get all facts that will be injected as context for the agent.
        """
        authorized_scope = self._resolve_authorized_fact_memory_call(
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return self.store.get_facts(
            scope_type=authorized_scope['scope_type'],
            scope_id=authorized_scope['scope_id'],
        )
