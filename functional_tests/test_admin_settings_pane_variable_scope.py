#!/usr/bin/env python3
# test_admin_settings_pane_variable_scope.py
"""
Functional test for the Admin Settings pane variable scope contract.
Version: 0.260.019
Implemented in: 0.260.019

Admin Settings renders its tabs as sibling {% include %} partials. Jinja gives
each include its own context copy, so a value assigned with {% set %} inside one
pane is invisible to the next pane. When the Document Action Capabilities card
moved into actions.html and its two {% set %} statements stayed behind in
agents.html, every /admin/settings request began raising

    jinja2.exceptions.UndefinedError: 'analyze_capability' is undefined

The composed-template helpers cannot catch this: they inline every include into
one flat string, which makes a sibling pane's {% set %} look reachable. These
tests therefore read each pane on its own and assert that every variable a pane
uses is either declared in that same pane or supplied by the route.
"""

import ast
import re
import sys
from pathlib import Path

import jinja2
from jinja2 import meta

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
TEMPLATE_DIR = APP_DIR / "templates"
PANES_DIR = TEMPLATE_DIR / "admin" / "_panes"
ADMIN_SETTINGS_TEMPLATE = TEMPLATE_DIR / "admin_settings.html"
ADMIN_ROUTE_FILE = APP_DIR / "route_frontend_admin_settings.py"
APP_FILE = APP_DIR / "app.py"

# Names Jinja and Flask resolve on their own, so no template has to declare them.
TEMPLATE_RUNTIME_NAMES = frozenset({
    "config",
    "csrf_token",
    "cycler",
    "dict",
    "g",
    "get_flashed_messages",
    "joiner",
    "lipsum",
    "namespace",
    "range",
    "request",
    "session",
    "url_for",
})

SET_ASSIGNMENT_RE = re.compile(r"\{%-?\s*set\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _render_template_keywords(source, template_name):
    """Return the keyword argument names of a render_template call for a template."""
    module = ast.parse(source)
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        function_name = getattr(function, "id", None) or getattr(function, "attr", None)
        if function_name != "render_template":
            continue
        if not node.args:
            continue
        first_argument = node.args[0]
        if not isinstance(first_argument, ast.Constant) or first_argument.value != template_name:
            continue
        return {keyword.arg for keyword in node.keywords if keyword.arg}
    raise AssertionError(f"No render_template('{template_name}', ...) call found.")


def _context_processor_keywords(source, function_name):
    """Return the keyword names of the dict(...) returned by a context processor."""
    module = ast.parse(source)
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return) or not isinstance(inner.value, ast.Call):
                continue
            call = inner.value
            if getattr(call.func, "id", None) != "dict":
                continue
            return {keyword.arg for keyword in call.keywords if keyword.arg}
    raise AssertionError(f"No dict(...) return found in {function_name}().")


def get_provided_template_names():
    """Return every name the Admin Settings template can rely on from Python.

    The names are parsed out of the route and the context processor instead of
    being listed here, so adding or removing a template variable cannot leave
    this test asserting against a stale allowlist.
    """
    route_names = _render_template_keywords(
        ADMIN_ROUTE_FILE.read_text(encoding="utf-8"),
        "admin_settings.html",
    )
    context_names = _context_processor_keywords(
        APP_FILE.read_text(encoding="utf-8"),
        "inject_settings",
    )
    return route_names | context_names | TEMPLATE_RUNTIME_NAMES


def get_unresolved_template_names(source):
    """Return names a template uses without declaring, ignoring provided names.

    Names assigned anywhere in the same file are treated as declared. Jinja's
    meta helper reports a {% set %} inside a {% for %} body as undeclared even
    though it resolves correctly at render time, and those loop-local names are
    not the failure mode being guarded here.
    """
    environment = jinja2.Environment()
    undeclared = meta.find_undeclared_variables(environment.parse(source))
    locally_assigned = set(SET_ASSIGNMENT_RE.findall(source))
    provided = get_provided_template_names()
    return sorted(undeclared - locally_assigned - provided)


def test_provided_names_are_discoverable():
    """The allowlist has to come from the real route, or the test proves nothing."""
    print("Testing Admin Settings template context discovery...")

    provided = get_provided_template_names()
    for expected_name in ("settings", "app_settings", "admin_landing_tab", "admin_nav"):
        assert expected_name in provided, (
            f"'{expected_name}' was not discovered in the Admin Settings template context. "
            "The route or context processor parsing in this test is out of date."
        )

    print(f"Discovered {len(provided)} template context names.")


def test_every_pane_declares_the_values_it_uses():
    """A pane may not depend on a value another pane happens to set.

    Sibling includes do not share scope, so any such dependency renders as
    Undefined and takes the whole page down with a 500 the moment the value is
    used for attribute access.
    """
    print("Testing Admin Settings panes declare their own values...")

    pane_paths = sorted(PANES_DIR.glob("*.html"))
    assert pane_paths, f"No Admin Settings panes found under {PANES_DIR}"

    offenders = []
    for pane_path in pane_paths:
        unresolved = get_unresolved_template_names(pane_path.read_text(encoding="utf-8"))
        if unresolved:
            offenders.append(f"admin/_panes/{pane_path.name} -> {', '.join(unresolved)}")

    assert not offenders, (
        "These panes use values that are neither declared in the pane nor passed by "
        "the Admin Settings route. Sibling {% include %} panes each render in their "
        "own scope, so a value set in another pane is Undefined here:\n  "
        + "\n  ".join(offenders)
    )

    print(f"All {len(pane_paths)} panes declare or receive every value they use.")


def test_parent_template_declares_the_values_it_uses():
    """The parent shell is subject to the same rule as the panes."""
    print("Testing admin_settings.html declares the values it uses...")

    unresolved = get_unresolved_template_names(
        ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    )

    assert not unresolved, (
        "admin_settings.html uses values the route does not pass, which render as "
        f"empty strings or raise on attribute access: {', '.join(unresolved)}"
    )

    print("Parent template declares or receives every value it uses.")


def test_document_action_capabilities_resolve_in_the_actions_pane():
    """Regression guard for the 500 this test was written for."""
    print("Testing document action capability values resolve in the Actions pane...")

    actions_markup = (PANES_DIR / "actions.html").read_text(encoding="utf-8")
    agents_markup = (PANES_DIR / "agents.html").read_text(encoding="utf-8")

    for capability_name in ("analyze_capability", "comparison_capability"):
        assert re.search(rf"\{{%-?\s*set\s+{capability_name}\s*=", actions_markup), (
            f"actions.html uses {capability_name} but never sets it. It has to be "
            "set in this pane, because a sibling pane's {% set %} is not visible here."
        )
        assert capability_name in actions_markup, (
            f"{capability_name} is set in actions.html but no longer used there."
        )
        assert not re.search(rf"\{{%-?\s*set\s+{capability_name}\s*=", agents_markup), (
            f"agents.html sets {capability_name} again. Only the pane that renders "
            "the Document Action Capabilities card should define it."
        )

    print("Document action capability values are declared where they are used.")


def test_capability_panes_render_as_the_parent_composes_them():
    """Render the two panes together the way admin_settings.html includes them.

    The static checks above describe the contract; this one exercises it. If the
    {% set %} statements ever drift back into a sibling pane, this render raises
    the same UndefinedError that took /admin/settings down.
    """
    print("Testing the Agents and Actions panes render together...")

    environment = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)))
    parent = environment.from_string(
        '{% include "admin/_panes/agents.html" %}{% include "admin/_panes/actions.html" %}'
    )

    settings = {
        "document_action_capabilities": {
            "analyze": {
                "enabled": True,
                "chat_max_documents": 25,
                "workflow_max_documents": 120,
            },
            "comparison": {
                "enabled": False,
                "chat_max_documents": 8,
                "workflow_max_documents": 40,
            },
        },
        "agents_page_promoted_popular_agents": [],
    }

    try:
        markup = parent.render(
            settings=settings,
            app_settings=settings,
            admin_landing_tab="secrets",
            user_settings={},
            mcp_ui_enabled=False,
        )
    except jinja2.exceptions.UndefinedError as render_error:
        raise AssertionError(
            "Rendering the Agents and Actions panes together raised "
            f"UndefinedError: {render_error}. A value used by one pane is being "
            "set in the other, and sibling includes do not share scope."
        ) from render_error

    assert 'id="document-action-capabilities-card"' in markup, (
        "The Document Action Capabilities card did not render."
    )
    for expected_value in ('value="25"', 'value="120"', 'value="8"', 'value="40"'):
        assert expected_value in markup, (
            f"Configured capability limit {expected_value} did not reach the rendered markup."
        )

    print("Both panes render together with their capability limits intact.")


if __name__ == "__main__":
    assert_app_version_at_least(
        "0.260.019",
        reason="Admin Settings pane variable scope fix.",
    )

    tests = [
        test_provided_names_are_discoverable,
        test_every_pane_declares_the_values_it_uses,
        test_parent_template_declares_the_values_it_uses,
        test_document_action_capabilities_resolve_in_the_actions_pane,
        test_capability_panes_render_as_the_parent_composes_them,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
