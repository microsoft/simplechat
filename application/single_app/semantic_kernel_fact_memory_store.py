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
from functions_content import generate_embedding


MEMORY_TYPE_FACT = 'fact'
MEMORY_TYPE_INSTRUCTION = 'instruction'
MEMORY_TYPE_LEGACY_DESCRIBER = 'describer'
VALID_MEMORY_TYPES = {MEMORY_TYPE_FACT, MEMORY_TYPE_INSTRUCTION, MEMORY_TYPE_LEGACY_DESCRIBER}
UNSET = object()

class FactMemoryStore:
    def __init__(self, container=cosmos_agent_facts_container):
        self.container = container

    def get_partition_key(self, scope_id):
        return f"{scope_id}"

    def normalize_memory_type(self, memory_type):
        normalized = str(memory_type or '').strip().lower()
        if normalized == MEMORY_TYPE_LEGACY_DESCRIBER:
            return MEMORY_TYPE_FACT
        if normalized in VALID_MEMORY_TYPES:
            return normalized
        return MEMORY_TYPE_FACT

    def normalize_fact_item(self, item):
        normalized_item = dict(item or {})
        normalized_item['memory_type'] = self.normalize_memory_type(normalized_item.get('memory_type'))
        return normalized_item

    def _build_embedding_fields(self, value, memory_type):
        if self.normalize_memory_type(memory_type) != MEMORY_TYPE_FACT:
            return {
                'value_embedding': None,
                'embedding_model': None,
                'embedding_updated_at': None,
            }

        try:
            embedding_result = generate_embedding(str(value or '').strip())
        except Exception:
            return {
                'value_embedding': None,
                'embedding_model': None,
                'embedding_updated_at': None,
            }

        if not embedding_result:
            return {
                'value_embedding': None,
                'embedding_model': None,
                'embedding_updated_at': None,
            }

        if isinstance(embedding_result, tuple):
            embedding_vector, token_usage = embedding_result
        else:
            embedding_vector = embedding_result
            token_usage = None

        if not embedding_vector:
            return {
                'value_embedding': None,
                'embedding_model': None,
                'embedding_updated_at': None,
            }

        return {
            'value_embedding': embedding_vector,
            'embedding_model': (token_usage or {}).get('model_deployment_name') if isinstance(token_usage, dict) else None,
            'embedding_updated_at': datetime.now(timezone.utc).isoformat(),
        }

    def get_fact_item(self, scope_id, fact_id):
        partition_key = self.get_partition_key(scope_id)
        try:
            return self.normalize_fact_item(self.container.read_item(item=fact_id, partition_key=partition_key))
        except exceptions.CosmosResourceNotFoundError:
            return None

    def set_fact(self, scope_type, scope_id, value, conversation_id=None, agent_id=None, memory_type=MEMORY_TYPE_FACT):
        now = datetime.now(timezone.utc).isoformat()
        doc_id = str(uuid.uuid4())
        normalized_memory_type = self.normalize_memory_type(memory_type)
        item = {
            "id": doc_id,
            "agent_id": agent_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "conversation_id": conversation_id,
            "memory_type": normalized_memory_type,
            "value": value,
            "created_at": now,
            "updated_at": now
        }
        item.update(self._build_embedding_fields(value, normalized_memory_type))
        self.container.upsert_item(item)
        return self.normalize_fact_item(item)


    def get_fact(self, scope_id, fact_id):
        item = self.get_fact_item(scope_id, fact_id)
        if item is None:
            return None
        return item.get("value")


    def get_facts(self, scope_type, scope_id, conversation_id=None, agent_id=None, memory_type=None):
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
        items = [
            self.normalize_fact_item(item)
            for item in self.container.query_items(query=query, parameters=params, partition_key=partition_key)
        ]

        normalized_memory_type = None
        if memory_type is not None:
            normalized_memory_type = self.normalize_memory_type(memory_type)

        filtered_items = []
        for item in items:
            if normalized_memory_type and item.get('memory_type') != normalized_memory_type:
                continue
            filtered_items.append(item)

        return filtered_items

    def list_facts(self, scope_type, scope_id, conversation_id=None, agent_id=None, memory_type=None):
        items = self.get_facts(
            scope_type=scope_type,
            scope_id=scope_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            memory_type=memory_type,
        )
        return sorted(
            items,
            key=lambda item: item.get("updated_at") or item.get("created_at") or "",
            reverse=True,
        )

    def update_fact(self, scope_id, fact_id, value=UNSET, memory_type=UNSET):
        item = self.get_fact_item(scope_id, fact_id)
        if item is None:
            return None

        value_changed = value is not UNSET and item.get('value') != value
        memory_type_changed = memory_type is not UNSET and self.normalize_memory_type(memory_type) != item.get('memory_type')

        if value is not UNSET:
            item["value"] = value
        if memory_type is not UNSET:
            item['memory_type'] = self.normalize_memory_type(memory_type)

        if value_changed or memory_type_changed:
            item.update(self._build_embedding_fields(item.get('value'), item.get('memory_type')))

        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.container.upsert_item(item)
        return self.normalize_fact_item(item)

    def update_fact_embedding(self, scope_id, fact_id, value_embedding, embedding_model=None):
        item = self.get_fact_item(scope_id, fact_id)
        if item is None:
            return None

        item['value_embedding'] = value_embedding
        item['embedding_model'] = embedding_model
        item['embedding_updated_at'] = datetime.now(timezone.utc).isoformat()
        item['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.container.upsert_item(item)
        return self.normalize_fact_item(item)

    def delete_fact(self, scope_id, fact_id):
        partition_key = self.get_partition_key(scope_id)
        try:
            self.container.delete_item(item=fact_id, partition_key=partition_key)
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False
