"""
FactMemoryPlugin for Semantic Kernel: provides write/update/delete operations for fact memory.
- Uses FactMemoryStore for persistence.
- Exposes methods for use as a Semantic Kernel plugin (does not need to derive from BasePlugin).
- Read/inject logic is handled separately by orchestration utility.
"""
from semantic_kernel_fact_memory_store import FactMemoryStore
from typing import Optional, List
from semantic_kernel.functions import kernel_function


class FactMemoryPlugin:
    def __init__(self, store: Optional[FactMemoryStore] = None):
        self.store = store or FactMemoryStore()

    @kernel_function(
        description="""
        Store a fact for the given agent, scope, and conversation.

        Args:
            scope_type (str): The type of scope, either 'user' or 'group'.
            scope_id (str): The id of the user or group, depending on scope_type.
            value (str): The value to be stored in memory.
            conversation_id (str): The id of the conversation.
            agent_id (str): The id of the agent, as specified in the agent's manifest.

        Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent.
        Use facts to remember things that should always be available as context for this agent.
        """,
        name="set_fact"
    )
    def set_fact(self, scope_type: str, scope_id: str, value: str, conversation_id: str, agent_id: str) -> dict:
        """
        Store a fact for the given agent, scope, and conversation.
        """
        return self.store.set_fact(
            scope_type=scope_type,
            scope_id=scope_id,
            value=value,
            conversation_id=conversation_id,
            agent_id=agent_id
        )

    @kernel_function(
        description="Delete a fact by its unique id.",
        name="delete_fact"
    )
    def delete_fact(self, scope_id: str, fact_id: str) -> bool:
        """
        Delete a fact by its unique id and the scope_id which is the partition key.
        """
        return self.store.delete_fact(
            scope_id=scope_id,
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
        return self.store.get_facts(
            scope_type=scope_type,
            scope_id=scope_id,
        )
