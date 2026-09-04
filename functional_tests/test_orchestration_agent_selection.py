#!/usr/bin/env python3
"""
Functional test for orchestration agent selection.
Version: 0.261.089
Implemented in: 0.261.087

An agent's configuration is not all equally safe to show a planner. Its naming fields are
what a planner needs to choose sensibly; its ``instructions`` are a full system prompt, and
putting one in front of the planner would both waste the context and let one agent's
instructions influence a plan it was never chosen for.

So the catalog is projected before it is shown, and the projection is checked here. Also
checked: that a user-seeded agent is treated as a hard constraint rather than a suggestion,
and that the projection is applied at the single point the planner context is built, so a
caller passing raw records cannot leak through it.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT, stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

CONTEXT = 'functions_orchestration_context.py'
ROUTE = 'route_backend_orchestration.py'

# Everything an agent record can hold that the planner must never be shown. These are not
# arbitrary: instructions is the system prompt, and the rest name internal wiring.
WITHHELD = (
    'instructions',
    'actions_to_load',
    'assigned_knowledge',
    'model_endpoint_id',
    'scope_id',
    'azure_openai_gpt_key',
)

FULL_AGENT = {
    'name': 'research_helper',
    'display_name': 'Research Helper',
    'description': 'Looks things up in the research corpus.',
    'tags': ['research'],
    'action_labels': ['search_corpus'],
    'instructions': 'You are a research assistant. SECRET SYSTEM PROMPT.',
    'actions_to_load': ['corpus_plugin'],
    'assigned_knowledge': {'workspace': 'w1'},
    'model_endpoint_id': 'endpoint-123',
    'scope_id': 'group-9',
    'azure_openai_gpt_key': 'sk-do-not-leak',
}


def _tree(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return ast.parse(handle.read())


def test_projection_withholds_agent_internals():
    """The planner sees an agent's naming fields and nothing else."""
    print("Testing the agent planner projection...")
    try:
        assert_app_version_at_least('0.261.087')

        with stubbed_app_imports():
            from functions_orchestration_registry import (
                AGENT_PLANNER_FIELDS,
                build_agent_planner_projection,
            )

            projected = build_agent_planner_projection([FULL_AGENT])
            assert len(projected) == 1, f"expected one agent, got {projected}"
            entry = projected[0]

            for field in WITHHELD:
                assert field not in entry, (
                    f"{field} reached the planner projection. The planner chooses an agent "
                    f"by name and purpose; it has no use for internals and every reason "
                    f"not to see them."
                )

            # And the whole record must be inside the allow-list, so a field added to an
            # agent record later cannot appear here by default.
            unexpected = set(entry) - set(AGENT_PLANNER_FIELDS)
            assert not unexpected, (
                f"projection emitted fields outside AGENT_PLANNER_FIELDS: {sorted(unexpected)}"
            )

            assert entry['name'] == 'research_helper'
            assert entry['description'], 'the planner needs a description to choose sensibly'

        print("  ok  only naming fields reach the planner")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_nameless_agents_are_dropped():
    """An agent with no name cannot be referenced by a plan, so it is not offered."""
    print("Testing that nameless agents are dropped...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_registry import build_agent_planner_projection

            projected = build_agent_planner_projection([
                {'display_name': 'No Name', 'description': 'x'},
                {'name': '   '},
                {'name': 'usable', 'description': 'y'},
                'not a dict',
                None,
            ])

            names = [a['name'] for a in projected]
            assert names == ['usable'], (
                f"only referenceable agents should be offered, got {names}. A plan names an "
                f"agent by its name; offering one without a name invites a plan that cannot "
                f"be validated."
            )

        print("  ok  unreferenceable agents are not offered")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_projection_is_applied_where_the_context_is_built():
    """Raw records passed to build_planner_context are projected, not trusted."""
    print("Testing that the context builder projects rather than trusts...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_context import build_planner_context

            context = build_planner_context('a question', agents=[FULL_AGENT])
            agents = context.get('agents') or []
            assert agents, 'the catalog did not reach the planner context'

            blob = repr(agents)
            for field in WITHHELD:
                assert field not in blob, (
                    f"{field} survived into the planner context. Projecting at the one "
                    f"place the context is built is what makes this safe regardless of what "
                    f"a caller passes."
                )
            assert 'SECRET SYSTEM PROMPT' not in blob, (
                "an agent's instructions reached the planner context"
            )

        print("  ok  raw records are projected at the context boundary")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_seeded_agent_is_a_hard_constraint():
    """Choosing an agent by hand narrows the plan rather than suggesting to it."""
    print("Testing that a seeded agent wins...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_context import resolve_agent_catalog

            source = ast.dump(_tree(CONTEXT))
            assert 'resolve_agent_catalog' in source

            # A seeded agent must narrow the catalog. The user has already made the choice
            # this catalog exists to inform, so offering alternatives invites the planner to
            # overrule them -- the same reason a seeded document turns off the candidate probe.
            catalog = resolve_agent_catalog(
                'user-1',
                seeds={'agent': {'name': 'chosen_one', 'display_name': 'Chosen One'}},
            )
            names = [a.get('name') for a in (catalog or [])]
            assert names == ['chosen_one'], (
                f"a seeded agent must be the only one offered, got {names}. A user who "
                f"picked an agent has stated a constraint, not a preference."
            )

        print("  ok  a user-selected agent is the only one offered")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_catalog_resolution_fails_soft():
    """A catalog lookup that raises degrades to 'no agents', never breaks planning."""
    print("Testing that catalog resolution fails soft...")
    try:
        tree = _tree(CONTEXT)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'resolve_agent_catalog':
                target = node
        assert target is not None, 'resolve_agent_catalog not found'

        handlers = [n for n in ast.walk(target) if isinstance(n, ast.ExceptHandler)]
        assert handlers, (
            'resolve_agent_catalog must handle a failing lookup. It is a multi-query Cosmos '
            'traversal; a transient failure there must cost the plan its agents, not the '
            'user their answer.'
        )
        for handler in handlers:
            raises = [n for n in ast.walk(handler) if isinstance(n, ast.Raise)]
            assert not raises, (
                'the catalog handler re-raises; planning must continue without agents'
            )

        print("  ok  a failed lookup degrades to no agents")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_route_resolves_the_catalog_once_per_plan():
    """Resolution happens per plan and per run -- never inside a loop over steps."""
    print("Testing catalog resolution placement...")
    try:
        tree = _tree(ROUTE)

        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'resolve_agent_catalog'
        ]
        assert len(calls) == 2, (
            f"expected exactly two resolutions (one when planning, one when running), "
            f"found {len(calls)}. Planning and running are separate requests and access "
            f"can be revoked between them, so the run must not reuse the plan's snapshot -- "
            f"but neither may resolve more than once."
        )

        # And none of them inside a loop, which would make it per-step.
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == 'resolve_agent_catalog'
                    ):
                        raise AssertionError(
                            'the agent catalog is resolved inside a loop; it is a '
                            'multi-query Cosmos operation with no cache'
                        )

        print("  ok  resolved once when planning and once when running")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_projection_withholds_agent_internals,
        test_nameless_agents_are_dropped,
        test_projection_is_applied_where_the_context_is_built,
        test_a_seeded_agent_is_a_hard_constraint,
        test_catalog_resolution_fails_soft,
        test_route_resolves_the_catalog_once_per_plan,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
