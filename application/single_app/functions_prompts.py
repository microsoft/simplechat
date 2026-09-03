# functions_prompts.py

from config import *
from functions_chat_bootstrap_cache import (
    bump_chat_bootstrap_global_cache_version,
    bump_chat_bootstrap_user_cache_version,
)


def _invalidate_prompt_chat_bootstrap_cache(user_id, group_id=None, public_workspace_id=None, reason="prompt_changed"):
    if group_id is not None or public_workspace_id is not None:
        bump_chat_bootstrap_global_cache_version(reason=reason)
    else:
        bump_chat_bootstrap_user_cache_version(user_id, reason=reason)


# A description is the one line shown beside a prompt's name in the workbench list. Capped
# because it is rendered on a single line: anything longer is truncated on display, so storing
# the remainder achieves nothing but a larger document.
PROMPT_DESCRIPTION_MAX_LENGTH = 200


def normalize_prompt_description(value):
    """Trim a description to what the interface can actually show."""
    return str(value or '').strip()[:PROMPT_DESCRIPTION_MAX_LENGTH]


def serialize_prompt_summary(doc):
    """The shape a write returns to the client.

    Deliberately one function rather than a dict literal at each call site. The client applies
    this optimistically to its list, so a create that omits a field the update returns would
    make a newly created prompt render differently from the same prompt after an edit.

    ``description`` and ``is_favorite`` are read defensively: prompts created before those
    fields existed do not carry them, and neither does a prompt last saved by the classic
    interface, which sends only ``name`` and ``content``.
    """
    doc = doc or {}
    return {
        "id": doc.get("id"),
        "name": doc.get("name", ""),
        "description": doc.get("description", "") or "",
        "is_favorite": bool(doc.get("is_favorite", False)),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def build_prompt_updates(data, require_fields=True):
    """Validate a PATCH body into the fields a prompt document may carry.

    Shared by the personal, group and public prompt routes, which previously repeated the same
    name and content checks three times over. Repeating them once more for every new field is
    how the three drift apart, and a field accepted on a personal prompt but silently dropped
    on a group one reads to a user as a save that did not work.

    ``require_fields=False`` is for the create routes, which validate name and content
    themselves and use this only for the optional fields. An empty result is legitimate there:
    it means the caller supplied none of them.

    Returns ``(updates, error)``. ``error`` is a message suitable for a 400 response and is
    ``None`` when ``updates`` is usable.
    """
    data = data or {}
    updates = {}

    if "name" in data:
        if not isinstance(data["name"], str) or not data["name"].strip():
            return None, "Invalid 'name' provided"
        updates["name"] = data["name"].strip()

    if "content" in data:
        if not isinstance(data["content"], str):
            return None, "Invalid 'content' provided"
        updates["content"] = data["content"]

    if "description" in data:
        # None is accepted as "clear it", which is what the editor sends when the field is
        # emptied. Any other non-string is a client bug rather than an intention.
        if data["description"] is not None and not isinstance(data["description"], str):
            return None, "Invalid 'description' provided"
        updates["description"] = normalize_prompt_description(data["description"])

    if "is_favorite" in data:
        if not isinstance(data["is_favorite"], bool):
            return None, "Invalid 'is_favorite' provided"
        updates["is_favorite"] = data["is_favorite"]

    if require_fields and not updates:
        return None, "No fields provided for update"

    return updates, None


# The fields a create accepts beyond name and content. Validated through the same function the
# updates use, so the two paths cannot disagree about what a valid description is.
PROMPT_OPTIONAL_CREATE_FIELDS = ("description", "is_favorite")


def build_prompt_create_options(data):
    """Validate the optional fields of a create body.

    Returns ``(options, error)`` where ``options`` is ready to splat into ``create_prompt_doc``.
    """
    data = data or {}
    supplied = {key: data[key] for key in PROMPT_OPTIONAL_CREATE_FIELDS if key in data}
    options, error = build_prompt_updates(supplied, require_fields=False)
    if error:
        return None, error
    return {
        "description": options.get("description", ""),
        "is_favorite": options.get("is_favorite", False),
    }, None

def get_pagination_params(args):
    try:
        page = int(args.get('page', 1))
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1

    try:
        page_size = int(args.get('page_size', 10))
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100
    except (ValueError, TypeError):
        page_size = 10

    return page, page_size


def _query_prompt_items(cosmos_container, query, parameters):
    return list(
        cosmos_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
    )


def _filter_prompt_items(items, search_term):
    if not search_term:
        return items

    normalized_search = search_term[:100].lower()
    return [
        item for item in items
        if normalized_search in (item.get('name') or '').lower()
        or normalized_search in (item.get('description') or '').lower()
    ]


def _sort_prompt_items(items):
    return sorted(
        items,
        key=lambda item: (
            item.get('updated_at') or '',
            item.get('name') or '',
            item.get('id') or '',
        ),
        reverse=True,
    )


def _read_prompt_from_container(cosmos_container, *, prompt_id, prompt_type, id_field, id_value):
    try:
        item = cosmos_container.read_item(item=prompt_id, partition_key=prompt_id)
        if item.get('type') == prompt_type and item.get(id_field) == id_value:
            return item
    except CosmosResourceNotFoundError:
        pass

    query = f"SELECT * FROM c WHERE c.id=@pid AND c.{id_field}=@id AND c.type=@type"
    parameters = [
        {"name": "@pid", "value": prompt_id},
        {"name": "@id", "value": id_value},
        {"name": "@type", "value": prompt_type},
    ]

    items = _query_prompt_items(cosmos_container, query, parameters)
    return items[0] if items else None


def _get_public_prompt_items(prompt_type, public_workspace_id):
    parameters = [
        {"name": "@id_value", "value": public_workspace_id},
        {"name": "@prompt_type", "value": prompt_type},
    ]

    primary_items = _query_prompt_items(
        cosmos_public_prompts_container,
        "SELECT * FROM c WHERE c.public_id = @id_value AND c.type = @prompt_type",
        parameters,
    )
    legacy_items = _query_prompt_items(
        cosmos_group_prompts_container,
        "SELECT * FROM c WHERE c.group_id = @id_value AND c.type = @prompt_type",
        parameters,
    )

    combined_items = {}
    for item in primary_items + legacy_items:
        prompt_id = item.get('id')
        if prompt_id and prompt_id not in combined_items:
            combined_items[prompt_id] = item

    return _sort_prompt_items(list(combined_items.values()))


def _get_prompt_doc_with_container(user_id, prompt_id, prompt_type, group_id=None, public_workspace_id=None):
    if public_workspace_id is not None:
        item = _read_prompt_from_container(
            cosmos_public_prompts_container,
            prompt_id=prompt_id,
            prompt_type=prompt_type,
            id_field='public_id',
            id_value=public_workspace_id,
        )
        if item:
            return item, cosmos_public_prompts_container

        legacy_item = _read_prompt_from_container(
            cosmos_group_prompts_container,
            prompt_id=prompt_id,
            prompt_type=prompt_type,
            id_field='group_id',
            id_value=public_workspace_id,
        )
        if legacy_item:
            return legacy_item, cosmos_group_prompts_container

        return None, None

    if group_id is not None:
        item = _read_prompt_from_container(
            cosmos_group_prompts_container,
            prompt_id=prompt_id,
            prompt_type=prompt_type,
            id_field='group_id',
            id_value=group_id,
        )
        return item, cosmos_group_prompts_container if item else None

    item = _read_prompt_from_container(
        cosmos_user_prompts_container,
        prompt_id=prompt_id,
        prompt_type=prompt_type,
        id_field='user_id',
        id_value=user_id,
    )
    return item, cosmos_user_prompts_container if item else None


def count_public_prompts_for_workspace(public_workspace_id):
    return len(_get_public_prompt_items('public_prompt', public_workspace_id))

def list_prompts(user_id, prompt_type, args, group_id=None, public_workspace_id=None):
    """
    List prompts for a user or a group with pagination and optional search.
    Returns: (items, total_count, page, page_size)
    """
    is_group = group_id is not None
    is_public_workspace = public_workspace_id is not None
    
    # Determine container
    if is_public_workspace:
        cosmos_container = cosmos_public_prompts_container
    elif is_group:
        cosmos_container = cosmos_group_prompts_container
    else:
        cosmos_container = cosmos_user_prompts_container

    # Determine filter field and value
    if is_public_workspace:
        id_field = 'public_id'
        id_value = public_workspace_id
    elif is_group:
        id_field = 'group_id'
        id_value = group_id
    else:
        id_field = 'user_id'
        id_value = user_id

    page, page_size = get_pagination_params(args)
    search_term = args.get('search')

    if is_public_workspace:
        all_items = _get_public_prompt_items(prompt_type, public_workspace_id)
        filtered_items = _filter_prompt_items(all_items, search_term)
        total_count = len(filtered_items)
        offset = (page - 1) * page_size
        items = filtered_items[offset:offset + page_size]
        return items, total_count, page, page_size

    base_filter = f"c.{id_field} = @id_value AND c.type = @prompt_type"
    parameters = [
        {"name": "@id_value", "value": id_value},
        {"name": "@prompt_type", "value": prompt_type}
    ]

    # Build count and select queries
    count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {base_filter}"
    select_query = f"SELECT * FROM c WHERE {base_filter}"

    if search_term:
        st = search_term[:100]
        # `IS_DEFINED` guards the description arm rather than relying on Cosmos three-valued
        # logic: prompts created before the field existed have no `description` at all, and an
        # unguarded CONTAINS against a missing property is the kind of thing that quietly
        # changes which rows come back.
        match_clause = (
            " AND (CONTAINS(c.name, @search, true)"
            " OR (IS_DEFINED(c.description) AND CONTAINS(c.description, @search, true)))"
        )
        select_query += match_clause
        count_query += match_clause
        parameters.append({"name": "@search", "value": st})

    select_query += " ORDER BY c.updated_at DESC"
    offset = (page - 1) * page_size
    select_query += f" OFFSET {offset} LIMIT {page_size}"

    # Execute count
    total_count = _query_prompt_items(cosmos_container, count_query, parameters)
    total_count = total_count[0] if total_count else 0

    # Execute select
    items = _query_prompt_items(cosmos_container, select_query, parameters)

    return items, total_count, page, page_size


def list_all_prompts_for_scope(user_id, prompt_type, group_id=None, public_workspace_id=None):
    """
    List all prompts for a user, group, or public workspace without pagination.
    Returns a full list of prompt documents for chat bootstrap scenarios.
    """
    is_group = group_id is not None
    is_public_workspace = public_workspace_id is not None

    if is_public_workspace:
        cosmos_container = cosmos_public_prompts_container
        id_field = 'public_id'
        id_value = public_workspace_id
    elif is_group:
        cosmos_container = cosmos_group_prompts_container
        id_field = 'group_id'
        id_value = group_id
    else:
        cosmos_container = cosmos_user_prompts_container
        id_field = 'user_id'
        id_value = user_id

    if is_public_workspace:
        return _get_public_prompt_items(prompt_type, public_workspace_id)

    query = f"SELECT * FROM c WHERE c.{id_field} = @id_value AND c.type = @prompt_type"
    parameters = [
        {"name": "@id_value", "value": id_value},
        {"name": "@prompt_type", "value": prompt_type}
    ]

    return _query_prompt_items(cosmos_container, query, parameters)

def create_prompt_doc(name, content, prompt_type, user_id, group_id=None, public_workspace_id=None,
                      description=None, is_favorite=False):
    """
    Create a new prompt for a user or a group.
    Returns minimal created doc.
    """
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    prompt_id = str(uuid.uuid4())
    is_group = group_id is not None
    is_public_workspace = public_workspace_id is not None

    # Determine container
    if is_public_workspace:
        cosmos_container = cosmos_public_prompts_container
    elif is_group:
        cosmos_container = cosmos_group_prompts_container
    else:
        cosmos_container = cosmos_user_prompts_container

    # Build the document
    doc = {
        "id": prompt_id,
        "name": name.strip(),
        "content": content,
        "description": normalize_prompt_description(description),
        "is_favorite": bool(is_favorite),
        "type": prompt_type,
        "created_at": now,
        "updated_at": now
    }
    
    # Set the appropriate ID field
    if is_public_workspace:
        doc["public_id"] = public_workspace_id
    elif is_group:
        doc["group_id"] = group_id
    else:
        doc["user_id"] = user_id

    created = cosmos_container.create_item(body=doc)
    _invalidate_prompt_chat_bootstrap_cache(
        user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        reason="prompt_created",
    )
    return serialize_prompt_summary(created)

def get_prompt_doc(user_id, prompt_id, prompt_type, group_id=None, public_workspace_id=None):
    """
    Retrieve a prompt by ID for a user or group.
    Returns the item dict or None.
    """
    item, _ = _get_prompt_doc_with_container(
        user_id,
        prompt_id,
        prompt_type,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    return item

def update_prompt_doc(user_id, prompt_id, prompt_type, updates, group_id=None, public_workspace_id=None):
    """
    Update an existing prompt for a user or a group.
    Returns minimal updated doc or None if not found.
    """
    item, cosmos_container = _get_prompt_doc_with_container(
        user_id,
        prompt_id,
        prompt_type,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    if not item:
        return None

    # Apply updates
    for k, v in updates.items():
        item[k] = v
    item["updated_at"] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    updated = cosmos_container.replace_item(item=prompt_id, body=item)
    _invalidate_prompt_chat_bootstrap_cache(
        user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        reason="prompt_updated",
    )

    return serialize_prompt_summary(updated)

def delete_prompt_doc(user_id, prompt_id, group_id=None, public_workspace_id=None):
    """
    Delete a prompt for a user or a group.
    Returns True if deleted, False if not found.
    """
    prompt_type = 'public_prompt' if public_workspace_id is not None else 'group_prompt' if group_id is not None else 'user_prompt'
    item, cosmos_container = _get_prompt_doc_with_container(
        user_id,
        prompt_id,
        prompt_type,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    if not item:
        return False

    cosmos_container.delete_item(item=prompt_id, partition_key=prompt_id)
    _invalidate_prompt_chat_bootstrap_cache(
        user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        reason="prompt_deleted",
    )
    return True