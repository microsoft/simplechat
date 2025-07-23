# functions_prompts.py

from config import *

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
        select_query += " AND CONTAINS(c.name, @search, true)"
        count_query  += " AND CONTAINS(c.name, @search, true)"
        parameters.append({"name": "@search", "value": st})

    select_query += " ORDER BY c.updated_at DESC"
    offset = (page - 1) * page_size
    select_query += f" OFFSET {offset} LIMIT {page_size}"

    # Execute count
    total_count = list(
        cosmos_container.query_items(
            query=count_query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
    )
    total_count = total_count[0] if total_count else 0

    # Execute select
    items = list(
        cosmos_container.query_items(
            query=select_query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
    )

    return items, total_count, page, page_size

def create_prompt_doc(name, content, prompt_type, user_id, group_id=None, public_workspace_id=None):
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
    return {
        "id": created["id"],
        "name": created["name"],
        "updated_at": created["updated_at"]
    }

def get_prompt_doc(user_id, prompt_id, prompt_type, group_id=None, public_workspace_id=None):
    """
    Retrieve a prompt by ID for a user or group.
    Returns the item dict or None.
    """
    is_public_workspace = prompt_type == 'public_prompt'
    is_group = group_id is not None and not is_public_workspace

    # Determine container
    if is_public_workspace:
        cosmos_container = cosmos_public_prompts_container
    elif is_group:
        cosmos_container = cosmos_group_prompts_container
    else:
        cosmos_container = cosmos_user_prompts_container

    # Try direct read
    try:
        item = cosmos_container.read_item(item=prompt_id, partition_key=prompt_id)
        if item.get("type") == prompt_type:
            # Check ownership based on prompt type
            if is_public_workspace and item.get("public_id") == public_workspace_id:
                return item
            elif is_group and item.get("group_id") == group_id:
                return item
            elif not is_public_workspace and not is_group and item.get("user_id") == user_id:
                return item
    except CosmosResourceNotFoundError:
        pass

    # Fallback to query
    if is_public_workspace:
        id_field = 'public_id'
        id_value = public_workspace_id
    elif is_group:
        id_field = 'group_id'
        id_value = group_id
    else:
        id_field = 'user_id'
        id_value = user_id
        
    query = (
        "SELECT * FROM c WHERE c.id=@pid AND c.{0}=@id AND c.type=@type"
    ).format(id_field)
    parameters = [
        {"name": "@pid",   "value": prompt_id},
        {"name": "@id",    "value": id_value},
        {"name": "@type",  "value": prompt_type}
    ]

    items = list(
        cosmos_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
    )
    return items[0] if items else None

def update_prompt_doc(user_id, prompt_id, prompt_type, updates, group_id=None, public_workspace_id=None):
    """
    Update an existing prompt for a user or a group.
    Returns minimal updated doc or None if not found.
    """
    item = get_prompt_doc(user_id, prompt_id, prompt_type, group_id, public_workspace_id)
    if not item:
        return None

    # Apply updates
    for k, v in updates.items():
        item[k] = v
    item["updated_at"] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    is_group = group_id is not None
    is_public_workspace = public_workspace_id is not None

    # Determine container
    if is_public_workspace:
        cosmos_container = cosmos_public_prompts_container
    elif is_group:
        cosmos_container = cosmos_group_prompts_container
    else:
        cosmos_container = cosmos_user_prompts_container
        
    updated = cosmos_container.replace_item(item=prompt_id, body=item)

    return {
        "id":         updated["id"],
        "name":       updated["name"],
        "updated_at": updated["updated_at"]
    }

def delete_prompt_doc(user_id, prompt_id, group_id=None, public_workspace_id=None):
    """
    Delete a prompt for a user or a group.
    Returns True if deleted, False if not found.
    """
    is_group = group_id is not None
    is_public_workspace = public_workspace_id is not None

    if is_public_workspace:
        cosmos_container = cosmos_public_prompts_container
    elif is_group:
        cosmos_container = cosmos_group_prompts_container
    else:
        cosmos_container = cosmos_user_prompts_container

    cosmos_container.delete_item(item=prompt_id, partition_key=prompt_id)
    return True