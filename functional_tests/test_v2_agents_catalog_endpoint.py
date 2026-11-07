# test_v2_agents_catalog_endpoint.py
"""
Functional test for the agent catalogue served to the V2 Agents page.
Version: 0.261.305
Implemented in: 0.261.305

The classic ``/agents`` page reads ``GET /api/agents/catalog``, which lists every
agent the user can reach. The V2 page reads ``GET /api/v2/agents/catalog``,
built by ``functions_v2_agents_catalog``, which lists only the agents the user
may chat with.

These checks pin what that endpoint promises:

- agents governance blocks are left out, and each is checked against the scope
  the bootstrap uses, so the page and the chat picker agree;
- governance runs before usage counts and promotions, so a promotion cannot
  put a blocked agent back on the Popular tab;
- a governance error propagates rather than listing unchecked agents;
- only the fields the page draws are sent, never assigned knowledge or the
  model endpoint, deployment or provider;
- instructions follow the administrator's details setting;
- every field the TypeScript page reads is one the endpoint sends;
- the route sits on the user blueprint behind the Semantic Kernel gate and
  never returns exception text.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTE_FILE = APP_ROOT / "route_backend_v2.py"
CATALOG_TS = REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "agentCatalog.ts"
CATALOG_INTERFACE_RE = re.compile(r"export interface CatalogAgent \{(?P<body>.*?)\n\}", re.DOTALL)
INTERFACE_FIELD_RE = re.compile(r"^\s+([a-z_][a-z0-9_]*)\??:", re.MULTILINE)

catalog_module = import_app_module("functions_v2_agents_catalog")

PAGE_CONFIG = {
    "title": "Find your next AI partner",
    "subtitle": "Explore specialized agents built to accelerate how you work.",
    "hero_color_mode": "single",
    "hero_primary_color": "#0f172a",
    "hero_secondary_color": "#1e293b",
    "disclaimer_markdown": "",
    "show_instructions_in_details": True,
}


def make_agent(agent_id, scope_type, **extra):
    record = {
        "id": agent_id,
        "name": agent_id,
        "display_name": agent_id.title(),
        "description": f"{agent_id} description",
        "scope_type": scope_type,
        "catalog_key": f"{scope_type}:{agent_id}",
        "instructions": f"You are {agent_id}.",
        "assigned_knowledge": {"documents": ["secret-plan.docx"]},
        "model_id": "gpt-internal",
        "model_endpoint_id": "endpoint-123",
        "model_provider": "aoai",
        "model_label": "GPT",
    }
    record.update(extra)
    return record


def build(catalog, *, is_allowed=None, page_config=None, calls=None):
    calls = calls if calls is not None else {}

    def apply_usage_counts(records):
        calls["usage"] = [record["id"] for record in records]
        for record in records:
            record["usage_count"] = 3
        return records

    def apply_promotions(records):
        calls["promotions"] = [record["id"] for record in records]
        for record in records:
            if record["id"] == "promoted":
                record["is_promoted_popular"] = True
                record["promoted_popular_rank"] = 0
        return records

    return catalog_module.build_v2_agents_catalog_payload(
        load_catalog=lambda: catalog,
        is_allowed=is_allowed or (lambda agent, scope: True),
        apply_usage_counts=apply_usage_counts,
        apply_promotions=apply_promotions,
        page_config=PAGE_CONFIG if page_config is None else page_config,
    )


def test_blocked_agents_are_left_out():
    """Agents governance blocks never reach the page, checked by their bootstrap scope."""
    print("\nTesting the governance filter...")
    assert_app_version_at_least("0.261.305")

    seen = []

    def is_allowed(agent, scope):
        seen.append((agent["id"], scope))
        return agent["id"] != "blocked"

    catalog = [
        make_agent("personal-one", "personal"),
        make_agent("blocked", "global"),
        make_agent("group-one", "group", group_id="g1", group_name="Research"),
        make_agent("unscoped", ""),
        make_agent("shouty", " GLOBAL "),
    ]
    payload = build(catalog, is_allowed=is_allowed)

    assert [agent["id"] for agent in payload["agents"]] == [
        "personal-one",
        "group-one",
        "unscoped",
        "shouty",
    ], payload["agents"]
    assert seen == [
        ("personal-one", "personal"),
        ("blocked", "global"),
        ("group-one", "group"),
        ("unscoped", "personal"),
        ("shouty", "global"),
    ], seen

    print("  Blocked agents are dropped and scopes are read as the bootstrap reads them.")
    return True


def test_governance_runs_before_usage_and_promotions():
    """Usage and promotions only see agents the user may chat with."""
    print("\nTesting the order of filtering and annotation...")

    calls = {}
    catalog = [make_agent("allowed", "personal"), make_agent("promoted", "global")]
    payload = build(
        catalog,
        is_allowed=lambda agent, scope: agent["id"] != "promoted",
        calls=calls,
    )

    assert calls["usage"] == ["allowed"], calls
    assert calls["promotions"] == ["allowed"], calls
    assert [agent["id"] for agent in payload["agents"]] == ["allowed"], payload["agents"]
    assert not any(agent.get("is_promoted_popular") for agent in payload["agents"])

    print("  A promoted agent the user is blocked from stays off the page.")
    return True


def test_governance_errors_fail_closed():
    """An unexpected governance error propagates instead of listing unchecked agents."""
    print("\nTesting that governance errors propagate...")

    def is_allowed(agent, scope):
        raise RuntimeError("governance store unavailable")

    try:
        build([make_agent("anyone", "personal")], is_allowed=is_allowed)
    except RuntimeError as exc:
        assert "governance store unavailable" in str(exc)
    else:
        raise AssertionError("A governance error was swallowed and the catalogue was returned.")

    print("  The builder raises, so the route answers 500 and lists nothing.")
    return True


def test_only_drawn_fields_are_sent():
    """Assigned knowledge and model wiring stay on the server."""
    print("\nTesting the field allowlist...")

    agent = make_agent(
        "promoted",
        "group",
        group_id="g1",
        group_name="Research",
        tags=["finance"],
        icon="bi-robot",
        actions_to_load=["weather"],
        action_labels=["Weather"],
        future_internal_field="should not leak",
    )
    payload = build([agent])
    projected = payload["agents"][0]

    for hidden in (
        "assigned_knowledge",
        "model_id",
        "model_endpoint_id",
        "model_provider",
        "future_internal_field",
    ):
        assert hidden not in projected, f"{hidden} reached the browser."

    for kept in (
        "id",
        "display_name",
        "scope_type",
        "group_id",
        "group_name",
        "tags",
        "icon",
        "model_label",
        "action_labels",
        "catalog_key",
        "usage_count",
        "is_promoted_popular",
        "promoted_popular_rank",
    ):
        assert kept in projected, f"{kept} was dropped."

    assert set(projected) <= set(catalog_module.V2_CATALOG_AGENT_FIELDS) | {"instructions"}, projected

    print("  Only the allowlisted fields are sent.")
    return True


def test_instructions_follow_the_details_setting():
    """Instructions are sent only when the details dialog shows them."""
    print("\nTesting the instructions setting...")

    shown = build([make_agent("helper", "personal")])
    assert shown["agents"][0]["instructions"] == "You are helper.", shown
    assert shown["page"] == PAGE_CONFIG, shown["page"]

    hidden_config = dict(PAGE_CONFIG, show_instructions_in_details=False)
    hidden = build([make_agent("helper", "personal")], page_config=hidden_config)
    assert "instructions" not in hidden["agents"][0], hidden
    assert hidden["page"]["show_instructions_in_details"] is False, hidden["page"]

    print("  The flag the page reads and the redaction agree.")
    return True


def test_empty_and_malformed_catalogues():
    """An empty or partly malformed catalogue still returns a usable payload."""
    print("\nTesting empty and malformed catalogues...")

    empty = build([])
    assert empty == {"page": PAGE_CONFIG, "agents": []}, empty

    missing = catalog_module.build_v2_agents_catalog_payload(
        load_catalog=lambda: None,
        is_allowed=lambda agent, scope: True,
        apply_usage_counts=lambda records: records,
        apply_promotions=lambda records: records,
        page_config=PAGE_CONFIG,
    )
    assert missing["agents"] == [], missing

    mixed = build(["not-an-agent", None, make_agent("real", "personal")])
    assert [agent["id"] for agent in mixed["agents"]] == ["real"], mixed

    print("  Non-dict records are skipped and nothing raises.")
    return True


def test_page_reads_only_served_fields():
    """Every field the TypeScript page declares is one the endpoint sends."""
    print("\nTesting the TypeScript contract...")

    match = CATALOG_INTERFACE_RE.search(CATALOG_TS.read_text(encoding="utf-8"))
    assert match, "CatalogAgent interface not found in lib/agentCatalog.ts."
    declared = set(INTERFACE_FIELD_RE.findall(match.group("body")))
    assert declared, "No fields were read from the CatalogAgent interface."

    served = set(catalog_module.V2_CATALOG_AGENT_FIELDS) | {"instructions"}
    unserved = sorted(declared - served)
    assert not unserved, f"The page reads fields the endpoint never sends: {unserved}"

    print(f"  {len(declared)} declared field(s) are all served.")
    return True


def test_route_is_user_guarded_and_gated():
    """The route sits on the user blueprint behind the Semantic Kernel gate."""
    print("\nTesting the route registration...")

    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8"))
    registrar = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_v2"
    )
    route = next(
        (
            node
            for node in ast.walk(registrar)
            if isinstance(node, ast.FunctionDef) and node.name == "v2_agents_catalog"
        ),
        None,
    )
    assert route, "v2_agents_catalog is not registered on the user blueprint."

    decorators = [ast.unparse(decorator) for decorator in route.decorator_list]
    assert decorators[0] == "bp.route('/api/v2/agents/catalog', methods=['GET'])", decorators
    assert decorators[1] == "swagger_route(security=get_auth_security())", decorators
    assert decorators[2:] == [
        "login_required",
        "user_required",
        "enabled_required('enable_semantic_kernel')",
    ], decorators

    source = ast.unparse(route)
    assert "build_v2_agents_catalog_payload" in source, source
    assert "_is_chat_agent_allowed_by_governance" in source, source
    assert "build_agents_page_config(sanitize_settings_for_user(settings))" in source, source
    assert "log_event(" in source and "exceptionTraceback=True" in source, source
    assert "level=logging.ERROR" in source, source
    assert "return (jsonify({'error': 'Failed to load agents.'}), 500)" in source, source
    assert "str(exc)" not in source, "Exception text must not reach the client."

    print("  The route is user guarded, gated, governance filtered and returns no exception text.")
    return True


if __name__ == "__main__":
    tests = [
        test_blocked_agents_are_left_out,
        test_governance_runs_before_usage_and_promotions,
        test_governance_errors_fail_closed,
        test_only_drawn_fields_are_sent,
        test_instructions_follow_the_details_setting,
        test_empty_and_malformed_catalogues,
        test_page_reads_only_served_fields,
        test_route_is_user_guarded_and_gated,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
