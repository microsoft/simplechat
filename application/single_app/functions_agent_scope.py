# functions_agent_scope.py
"""Helpers for resolving agent selection scope."""


def find_agent_by_scope(agents_cfg, selected_agent_data):
    """Return the agent matching the requested name/id within its declared scope."""
    if not isinstance(selected_agent_data, dict) or not agents_cfg:
        return None

    selected_agent_name = selected_agent_data.get("name")
    selected_agent_id = selected_agent_data.get("id")
    is_global_flag = selected_agent_data.get("is_global", False)
    is_group_flag = selected_agent_data.get("is_group", False)
    selected_agent_group_id = selected_agent_data.get("group_id")

    def scope_matches(candidate):
        if is_group_flag:
            if not candidate.get("is_group", False):
                return False
            return selected_agent_group_id is None or candidate.get("group_id") == selected_agent_group_id
        if is_global_flag:
            return candidate.get("is_global", False) and not candidate.get("is_group", False)
        return not candidate.get("is_global", False) and not candidate.get("is_group", False)

    if selected_agent_id:
        found = next((agent for agent in agents_cfg if agent.get("id") == selected_agent_id and scope_matches(agent)), None)
        if found:
            return found

    if selected_agent_name:
        return next((agent for agent in agents_cfg if agent.get("name") == selected_agent_name and scope_matches(agent)), None)

    return None