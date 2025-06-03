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
            agent_id (str): The id of the agent, as specified in the agent's manifest.
            scope_type (str): The type of scope, either 'user' or 'group'.
            scope_id (str): The id of the user or group, depending on scope_type.
            conversation_id (str): The id of the conversation.
            value (str): The value to be stored in memory.

        Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent.
        Use facts to remember things that should always be available as context for this agent.
        """,
        name="set_fact"
    )
    def set_fact(self, agent_id: str, scope_type: str, scope_id: str, conversation_id: str, value: str) -> dict:
        """
        Store a fact for the given agent, scope, and conversation.

        Args:
            agent_id (str): The id of the agent, as specified in the agent's manifest.
            scope_type (str): The type of scope, either 'user' or 'group'.
            scope_id (str): The id of the user or group, depending on scope_type.
            conversation_id (str): The id of the conversation.
            value (str): The value to be stored in memory.

        Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent.
        Use facts to remember things that should always be available as context for this agent.
        """
        return self.store.set_fact(agent_id, scope_type, scope_id, conversation_id, value)

    @kernel_function(
        description="Delete a fact by its unique id.",
        name="delete_fact"
    )
    def delete_fact(self, agent_id: str, fact_id: str) -> bool:
        """
        Delete a fact by its unique id.
        """
        return self.store.delete_fact(agent_id, fact_id)

    @kernel_function(
        description="Retrieve all facts for the given agent, scope, and conversation. Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent. Use this to get all facts that will be injected as context for the agent.",
        name="get_facts"
    )
    def get_facts(self, agent_id: str, scope_type: str, scope_id: str, conversation_id: str) -> List[dict]:
        """
        Retrieve all facts for the given agent, scope, and conversation. Facts are persistent values that provide important context, background knowledge, or user preferences to the AI agent. Use this to get all facts that will be injected as context for the agent.
        """
        return self.store.get_facts(agent_id, scope_type, scope_id, conversation_id)
