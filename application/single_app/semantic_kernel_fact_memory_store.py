# semantic_kernel_fact_memory_store.py
"""
FactMemoryStore abstraction for agent fact memory in CosmosDB.
- Scopes facts by agent, scope_type (user/group), scope_id, and conversation_id
- Uses the 'agent_facts' CosmosDB container
"""

import uuid
from datetime import datetime, timezone
from azure.cosmos import exceptions
from config import cosmos_agent_facts_container

class FactMemoryStore:
    def __init__(self, container=cosmos_agent_facts_container):
        self.container = container

    def get_partition_key(self, scope_id):
        return f"{scope_id}"

    def set_fact(self, scope_type, scope_id, value, conversation_id=None, agent_id=None):
        now = datetime.now(timezone.utc).isoformat()
        doc_id = str(uuid.uuid4())
        item = {
            "id": doc_id,
            "agent_id": agent_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "conversation_id": conversation_id,
            "value": value,
            "created_at": now,
            "updated_at": now
        }
        self.container.upsert_item(item)
        return item


    def get_fact(self, scope_id, fact_id):
        partition_key = self.get_partition_key(scope_id)
        try:
            item = self.container.read_item(item=fact_id, scope_id=partition_key)
            return item.get("value")
        except exceptions.CosmosResourceNotFoundError:
            return None


    def get_facts(self, scope_type, scope_id, conversation_id=None, agent_id=None):
        partition_key = self.get_partition_key(scope_id)
        query = "SELECT * FROM c WHERE c.scope_id=@scope_id AND c.scope_type=@scope_type"
        params = [
            {"name": "@scope_id", "value": scope_id},
            {"name": "@scope_type", "value": scope_type}
        ]
        useOptionalFilters = False
        if useOptionalFilters and agent_id is not None:
            query += " AND c.agent_id=@agent_id"
            params.append({"name": "@agent_id", "value": agent_id})
        if useOptionalFilters and conversation_id is not None:
            query += " AND c.conversation_id=@conversation_id"
            params.append({"name": "@conversation_id", "value": conversation_id})
        items = list(self.container.query_items(query=query, parameters=params, partition_key=partition_key))
        return items

    def delete_fact(self, scope_id, fact_id):
        partition_key = self.get_partition_key(scope_id)
        try:
            self.container.delete_item(item=fact_id, partition_key=partition_key)
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False
