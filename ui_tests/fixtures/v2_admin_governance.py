# v2_admin_governance.py
"""
In-memory governance APIs for V2 Admin Settings browser tests.
Version: 0.261.273
Implemented in: 0.261.273

Extends the schema-backed Admin Settings fixture with the governance endpoints the
Governance group and its tie-ins call: feature policies, delegated item policies,
the principal directory, the MCP destination catalog, and the lookups the item
policy editor offers. Policies live in memory, so a test can create, edit, move,
and delete them and read back exactly what the page sent. Item policy saves can be
held to stand in for a slow save. Unexpected requests still fail the test.
"""

import copy
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import Page, Route

from v2_admin_settings import AdminSettingsFixture

GOVERNANCE_SECTIONS = {
    "ai-models": ["multi-endpoint-configuration"],
    "agents-actions": [
        "agents-config",
        "agent-toggles-card",
        "plugin-feature-toggles",
        "inbound-mcp-configuration",
    ],
    "governance": [
        "governance-feature-toggles-section",
        "governance-feature-policies-section",
        "governance-item-policies-section",
        "governance-mcp-destination-section",
        "governance-inbound-mcp-section",
    ],
}

FEATURE_KEYS = (
    "governance_user_endpoints",
    "governance_group_endpoints",
    "governance_global_endpoints",
    "governance_user_agents",
    "governance_group_agents",
    "governance_global_agents_usage",
    "governance_user_actions",
    "governance_group_actions",
    "governance_global_actions_usage",
)

KNOWN_ENTITY_TYPES = {
    "global_endpoint", "global_agent", "global_action",
    "personal_action_type", "group_action_type", "global_action_type",
    "mcp_personal_destination", "mcp_group_destination", "mcp_global_destination",
    "inbound_mcp_source",
}

USERS = [
    {"id": "u-ada", "displayName": "Ada Lovelace", "email": "ada@contoso.com"},
    {"id": "u-grace", "displayName": "Grace Hopper", "email": "grace@contoso.com"},
]

GROUPS = [
    {"id": "g-pilot", "name": "Personal Agents Pilot", "description": "Pilot cohort", "kind": "group", "member_count": 4},
    {"id": "g-ops", "name": "Operations", "description": "Ops team", "kind": "group", "member_count": 9},
    {"id": "pw-research", "name": "Research Library", "description": "Public research", "kind": "public_workspace", "member_count": None},
]


def _principals(body):
    def ids(name):
        values = body.get(name) or []
        seen = []
        for value in values:
            value = str(value).strip()
            if value and value not in seen:
                seen.append(value)
        return seen

    allowed_users, allowed_groups = ids("allowed_users"), ids("allowed_groups")
    allow_all = bool(body.get("allow_all", True)) and not allowed_users and not allowed_groups
    return {
        "allow_all": allow_all,
        "allowed_users": [] if allow_all else allowed_users,
        "allowed_groups": [] if allow_all else allowed_groups,
        "denied_users": ids("denied_users"),
        "denied_groups": ids("denied_groups"),
    }


class GovernanceSettingsFixture(AdminSettingsFixture):
    """The Admin Settings fixture with governance, connections, and inbound MCP."""

    def __init__(self, page: Page, *, sections=None):
        super().__init__(page, validate_updates=True, sections=sections or GOVERNANCE_SECTIONS)
        self.payload["runtime_flags"] = {"mcp_ui_enabled": True}
        self.payload["status_readouts"] = {
            "mcp_destination_environment_policy": {
                "ok": True,
                "message": "The deployment environment adds no destination restrictions, "
                "so the switches above decide enforcement.",
            },
        }
        # Governance enforced for personal agents, and kept but waiting for group agents.
        self.settings.update({
            "governance_user_agents": True,
            "governance_group_agents": True,
            "allow_group_agents": False,
        })
        self.endpoints = [{
            "id": "conn-east",
            "name": "East US OpenAI",
            "provider": "aoai",
            "enabled": True,
            "connection": {"endpoint": "https://east.openai.azure.com/"},
            "auth": {"type": "managed_identity"},
            "models": [],
        }]
        self.feature_policies = {
            key: {
                "id": f"feature:{key}", "feature_key": key, "allow_all": True,
                "allowed_users": [], "allowed_groups": [], "denied_users": [], "denied_groups": [],
            }
            for key in FEATURE_KEYS
        }
        self.item_policies = []
        self.feature_writes = []
        self.item_writes = []
        self.item_deletes = []
        # Set to hold item policy saves, standing in for a slow save, until
        # release_item_writes answers them.
        self.hold_item_writes = False
        self.held_item_writes = []

    # -- helpers -----------------------------------------------------------------

    def release_item_writes(self):
        """Answer saves held by `hold_item_writes`, as a slow save finishing would."""
        self.hold_item_writes = False
        while self.held_item_writes:
            route, body = self.held_item_writes.pop(0)
            status, response = self._upsert_item(body)
            route.fulfill(status=status, json=response)

    def assert_clean(self):
        assert not self.held_item_writes, "A held item policy save was never answered."
        super().assert_clean()

    def _review(self, query):
        types = [value for value in (query.get("entity_type", [""])[0] or "").split(",") if value]
        if any(value not in KNOWN_ENTITY_TYPES for value in types):
            return 400, {"error": "Unknown delegated item entity type."}
        item_id = (query.get("item_id", [""])[0] or "").strip()
        search = (query.get("search", [""])[0] or "").strip().lower()
        page = max(1, int(query.get("page", ["1"])[0] or 1))
        per_page = max(1, min(100, int(query.get("per_page", ["25"])[0] or 25)))

        policies = [
            policy for policy in self.item_policies
            if (not types or policy["entity_type"] in types)
            and (not item_id or policy["item_id"] == item_id)
            and (not search or search in " ".join(
                str(value) for value in policy.values() if not isinstance(value, list)
            ).lower() + " ".join(
                " ".join(policy[name]) for name in ("allowed_users", "allowed_groups", "denied_users", "denied_groups")
            ).lower())
        ]
        total = len(policies)
        total_pages = max(1, -(-total // per_page))
        page = min(page, total_pages)
        start = (page - 1) * per_page
        return 200, {
            "item_policies": policies[start:start + per_page],
            "pagination": {
                "page": page, "per_page": per_page, "total_items": total, "total_pages": total_pages,
                "has_prev": page > 1, "has_next": page < total_pages,
            },
        }

    def _upsert_item(self, body):
        entity_type = str(body.get("entity_type") or "").strip()
        item_id = str(body.get("item_id") or "").strip()
        if entity_type not in KNOWN_ENTITY_TYPES or not item_id:
            return 400, {"error": "entity_type and item_id are required."}
        policy_id = str(body.get("policy_id") or "").strip()
        original = (str(body.get("original_entity_type") or ""), str(body.get("original_item_id") or ""))
        if policy_id and any(
            policy["policy_id"] == policy_id
            and (policy["entity_type"], policy["item_id"]) not in {(entity_type, item_id), original}
            for policy in self.item_policies
        ):
            return 409, {"error": "This item governance policy ID is already assigned to another delegated item."}
        policy_id = policy_id or str(uuid.uuid4())
        self.item_policies = [policy for policy in self.item_policies if policy["policy_id"] != policy_id]
        stored = {
            "entity_type": entity_type,
            "item_id": item_id,
            "policy_id": policy_id,
            "policy_name": str(body.get("policy_name") or "").strip() or f"{item_id} Policy",
            "resource_label": str(body.get("resource_label") or "").strip(),
            "system_managed": False,
            "managed_reason": "",
            **_principals(body),
        }
        self.item_policies.append(stored)
        self.item_policies.sort(key=lambda policy: (policy["entity_type"], policy["resource_label"] or policy["item_id"]))
        return 200, {"policy": stored}

    def _principal_groups(self, query):
        ids = [value for value in (query.get("ids", [""])[0] or "").split(",") if value]
        if ids:
            return [group for group in GROUPS if group["id"] in ids]
        search = (query.get("search", [""])[0] or "").strip().lower()
        return [
            group for group in GROUPS
            if not search or search in f"{group['name']} {group['description']} {group['id']}".lower()
        ]

    # -- routing -----------------------------------------------------------------

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path, method = parsed.path, request.method
        query = parse_qs(parsed.query)

        if path == "/api/admin/governance/policies" and method == "GET":
            route.fulfill(json={"features": list(self.feature_policies.values()), "feature_keys": list(FEATURE_KEYS)})
        elif path.startswith("/api/admin/governance/policies/") and method == "PUT":
            key = unquote(path.rsplit("/", 1)[-1])
            body = request.post_data_json or {}
            self.feature_writes.append({"feature_key": key, **copy.deepcopy(body)})
            stored = {"id": f"feature:{key}", "feature_key": key, **_principals(body)}
            self.feature_policies[key] = stored
            route.fulfill(json={"policy": stored})
        elif path == "/api/admin/governance/item-policies/review" and method == "GET":
            status, body = self._review(query)
            route.fulfill(status=status, json=body)
        elif path == "/api/admin/governance/item-policies" and method == "POST":
            body = request.post_data_json or {}
            self.item_writes.append(copy.deepcopy(body))
            if self.hold_item_writes:
                self.held_item_writes.append((route, body))
                return
            status, response = self._upsert_item(body)
            route.fulfill(status=status, json=response)
        elif path == "/api/admin/governance/item-policies/delete" and method == "POST":
            body = request.post_data_json or {}
            self.item_deletes.append(copy.deepcopy(body))
            before = len(self.item_policies)
            self.item_policies = [
                policy for policy in self.item_policies
                if not (
                    policy["entity_type"] == body.get("entity_type")
                    and policy["item_id"] == body.get("item_id")
                    and policy["policy_id"] == body.get("policy_id")
                )
            ]
            if len(self.item_policies) == before:
                route.fulfill(status=404, json={"error": "Item governance policy not found."})
            else:
                route.fulfill(json={"deleted": True})
        elif path == "/api/admin/governance/principal-groups" and method == "GET":
            route.fulfill(json={"groups": self._principal_groups(query), "truncated": False})
        elif path == "/api/admin/governance/mcp-destination-catalog" and method == "GET":
            route.fulfill(json={
                "preconfigurations": [
                    {"id": "microsoft_learn", "label": "Microsoft Learn Documentation", "catalog_tier": "public",
                     "scopes": [], "requires_explicit_policy": False, "requires_endpoint_review": False},
                    {"id": "github", "label": "GitHub", "catalog_tier": "enterprise", "scopes": [],
                     "requires_explicit_policy": True, "requires_endpoint_review": False},
                ],
                "presets": [{"id": "generic", "label": "Generic MCP server"}],
                "transports": ["sse", "streamable_http", "websocket"],
            })
        elif path == "/api/userSearch" and method == "GET":
            term = (query.get("query", [""])[0] or "").strip().lower()
            route.fulfill(json=[
                user for user in USERS
                if term and (user["displayName"].lower().startswith(term) or user["email"].startswith(term))
            ])
        elif path.startswith("/api/user/info/") and method == "GET":
            user_id = unquote(path.rsplit("/", 1)[-1])
            user = next((entry for entry in USERS if entry["id"] == user_id), None)
            if user:
                route.fulfill(json={**user, "display_name": user["displayName"]})
            else:
                route.fulfill(status=404, json={"error": "User not found or access denied"})
        elif path == "/api/admin/agents" and method == "GET":
            route.fulfill(json=[{"id": "agent-research", "name": "researcher", "display_name": "Research Assistant"}])
        elif path == "/api/admin/plugins" and method == "GET":
            route.fulfill(json=[{"id": "action-search", "name": "Contoso Search", "type": "openapi"}])
        elif path == "/api/admin/plugins/types" and method == "GET":
            route.fulfill(json=[
                {"type": "openapi", "display": "OpenAPI", "description": "Call an OpenAPI service."},
                {"type": "mcp", "display": "MCP", "description": "Connect to a remote MCP server."},
            ])
        elif path == "/api/plugins/agent-targets" and method == "GET":
            # Read by the Call agent settings that share the Agents & Actions group.
            scope = (query.get("scope", ["global"])[0] or "global")
            route.fulfill(json={"targets": [], "can_manage": True, "scope_type": scope, "scope_id": "global"})
        else:
            super()._route(route)
