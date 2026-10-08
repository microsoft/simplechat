# functions_v2_agents_catalog.py
"""The Agents catalogue, shaped for the V2 interface.

The classic ``/agents`` page reads ``GET /api/agents/catalog``, which lists every
agent the user can reach in their personal, group and global scopes. The V2 page
lists only the agents the user may start a chat with. Governance can block a whole
scope or a single agent, and the chat picker already leaves those out, so the
catalogue does too rather than offering a Chat button that cannot work.

The classic endpoint keeps its behaviour because the admin Promoted Agents editor
reads it, and governance has no administrator bypass: filtering it there would
hide agents from the very control that promotes them.

Only the fields the page draws are sent. Assigned knowledge and the model
endpoint, deployment and provider stay on the server; the page shows the model
label. Instructions are sent only when the administrator shows them in the
details dialog, the same rule the classic endpoint applies.

It imports no Flask and no Azure client, so it can be exercised directly: the
route passes in the catalogue loader, the governance check, the usage and
promotion annotators, and the page configuration.
"""


# Every field the V2 page reads, and nothing else. ``instructions`` is handled
# separately because it depends on an administrator setting.
V2_CATALOG_AGENT_FIELDS = (
    "id",
    "name",
    "display_name",
    "description",
    "agent_type",
    "is_global",
    "is_group",
    "scope_type",
    "scope_id",
    "scope_name",
    "group_id",
    "group_name",
    "tags",
    "icon",
    "model_label",
    "actions_to_load",
    "action_labels",
    "catalog_key",
    "usage_count",
    "usage_count_30_days",
    "usage_count_all_time",
    "is_promoted_popular",
    "promoted_popular_window",
    "promoted_popular_rank",
    "promoted_popular_order",
    "promoted_popular_tag_enabled",
    "promoted_popular_tag_label",
)

V2_CATALOG_INSTRUCTIONS_FIELD = "instructions"


def catalog_agent_governance_scope(agent):
    """Return the governance scope of a catalogue record, read as the bootstrap reads it."""
    return str(agent.get("scope_type") or "").strip().lower() or "personal"


def project_v2_catalog_agent(agent, *, include_instructions):
    """Copy only the fields the V2 page draws from one catalogue record."""
    projected = {field: agent[field] for field in V2_CATALOG_AGENT_FIELDS if field in agent}
    if include_instructions and V2_CATALOG_INSTRUCTIONS_FIELD in agent:
        projected[V2_CATALOG_INSTRUCTIONS_FIELD] = agent[V2_CATALOG_INSTRUCTIONS_FIELD]
    return projected


def build_v2_agents_catalog_payload(
    *,
    load_catalog,
    is_allowed,
    apply_usage_counts,
    apply_promotions,
    page_config,
):
    """Return ``{"page": ..., "agents": [...]}`` for the V2 Agents page.

    ``load_catalog()``
        Returns the accessible catalogue records.
    ``is_allowed(agent, scope)``
        Whether governance lets the user chat with the agent. An error it raises
        propagates, so the page fails closed rather than listing agents that were
        never checked.
    ``apply_usage_counts(records)`` and ``apply_promotions(records)``
        Annotate the records and return them.
    ``page_config``
        The normalised display configuration from ``build_agents_page_config``. Its
        ``show_instructions_in_details`` decides whether instructions are sent, so the
        flag the page reads and the redaction cannot disagree.

    Governance runs first, so usage is counted and promotions are applied only to
    agents the user can see: an administrator promoting an agent this user is
    blocked from cannot put it back on this user's Popular tab.
    """
    page = dict(page_config or {})
    include_instructions = bool(page.get("show_instructions_in_details"))

    allowed = [
        agent
        for agent in load_catalog() or []
        if isinstance(agent, dict) and is_allowed(agent, catalog_agent_governance_scope(agent))
    ]
    allowed = apply_usage_counts(allowed)
    allowed = apply_promotions(allowed)

    return {
        "page": page,
        "agents": [
            project_v2_catalog_agent(agent, include_instructions=include_instructions)
            for agent in allowed
        ],
    }
