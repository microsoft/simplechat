#!/usr/bin/env python3
"""
Functional test for Admin Settings pane template variable scope.
Version: 0.260.019
Implemented in: 0.260.019

Jinja `{% set %}` scope does not cross an `{% include %}` boundary. While Admin
Settings was one template that never mattered, because a variable derived near
the top was visible everywhere below it. Splitting the template into per-tab
partials made it matter a great deal: a card can move to a new pane and leave
the variable it depends on behind in its old one.

That happened three times, and the two failure modes are very different:

  Attribute access on the missing name raises UndefinedError and takes the whole
  Admin Settings page down. Loud, obvious, found immediately.

  A boolean test on the missing name silently evaluates false, because Jinja's
  default Undefined is falsy. Nothing errors. The controls it guards simply
  never appear, and no one notices.

The second kind is why this test exists rather than relying on a page load.

This test ensures every variable a pane uses is either declared in that pane or
supplied by the render context, and never borrowed from a sibling pane.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from jinja2 import Environment, FileSystemLoader, meta  # noqa: E402

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
TEMPLATE_DIR = os.path.join(APP_ROOT, "templates")
PANES_DIR = os.path.join(TEMPLATE_DIR, "admin", "_panes")
ROUTE_FILE = os.path.join(APP_ROOT, "route_frontend_admin_settings.py")
APP_FILE = os.path.join(APP_ROOT, "app.py")

SET_PATTERN = re.compile(r"{%-?\s*set\s+([A-Za-z_][A-Za-z0-9_]*)\s*[=,]")

# Provided by Flask and Jinja to every template.
FRAMEWORK_GLOBALS = {
    "config",
    "request",
    "session",
    "g",
    "url_for",
    "get_flashed_messages",
    "current_user",
    "csrf_token",
    "range",
    "dict",
    "lipsum",
    "cycler",
    "joiner",
    "namespace",
}


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _route_context_keys():
    """Keyword arguments the Admin Settings route passes to render_template."""
    source = _read(ROUTE_FILE)
    anchor = source.index("render_template(\n                'admin_settings.html'")
    block = source[anchor:source.index("\n            )", anchor)]
    return set(re.findall(r"^\s+([a-z_][a-z0-9_]*)=", block, re.M))


def _context_processor_keys():
    """Names injected into every template by an app context processor."""
    source = _read(APP_FILE)
    keys = set()
    for match in re.finditer(r"@app\.context_processor", source):
        block = source[match.start():match.start() + 6000]
        end = block.find("\n@")
        if end != -1:
            block = block[:end]
        keys.update(re.findall(r"^\s+([a-z_][a-z0-9_]*)=", block, re.M))
    return keys


def _pane_files():
    return sorted(
        os.path.join(PANES_DIR, name)
        for name in os.listdir(PANES_DIR)
        if name.endswith(".html")
    )


def _analyse():
    """Return (external_needs, declared) per pane.

    external_needs excludes names the pane declares itself. A `{% set %}` inside
    a `{% for %}` is block scoped, so Jinja reports it as undeclared even though
    it is perfectly valid and local; those are filtered out by checking whether
    the pane declares the name anywhere.
    """
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    external, declared = {}, {}
    for path in _pane_files():
        pane = os.path.basename(path)[: -len(".html")]
        source = _read(path)
        local = set(SET_PATTERN.findall(source))
        declared[pane] = local
        external[pane] = set(meta.find_undeclared_variables(env.parse(source))) - local
    return external, declared


def test_no_pane_borrows_a_variable_from_a_sibling():
    """The exact bug: a card moved tabs and left its `{% set %}` behind."""
    print("Testing panes do not borrow variables from sibling panes...")

    external, declared = _analyse()
    owner = {}
    for pane, names in declared.items():
        for name in names:
            owner.setdefault(name, set()).add(pane)

    borrowed = []
    for pane, names in sorted(external.items()):
        for name in sorted(names):
            elsewhere = owner.get(name, set()) - {pane}
            if elsewhere:
                borrowed.append(
                    f"'{name}' is used in '{pane}' but only declared in {sorted(elsewhere)}"
                )

    assert not borrowed, (
        "Panes borrowing a variable across an include boundary, which Jinja does "
        "not support. Declare it in the pane that uses it:\n  " + "\n  ".join(borrowed)
    )

    print(f"No pane borrows a variable from a sibling ({len(external)} panes checked).")
    return True


def test_every_pane_variable_is_supplied():
    """Anything not declared locally must come from the render context."""
    print("Testing every pane variable is supplied by the render context...")

    available = _route_context_keys() | _context_processor_keys() | FRAMEWORK_GLOBALS
    assert "settings" in available, "Sanity check failed: route context not parsed"
    assert "admin_landing_tab" in available, "Sanity check failed: context processors not parsed"

    external, _ = _analyse()
    missing = []
    for pane, names in sorted(external.items()):
        for name in sorted(names - available):
            missing.append(f"{pane}: '{name}'")

    assert not missing, (
        "Pane variables that are neither declared locally nor supplied by the "
        "Admin Settings render context:\n  " + "\n  ".join(missing)
    )

    print(f"All pane variables are supplied ({len(available)} names available).")
    return True


def test_analyser_detects_a_planted_leak():
    """A guard that cannot fail is worthless, so prove it catches the real bug."""
    print("Testing the scope analyser detects a planted leak...")

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    source = _read(os.path.join(PANES_DIR, "actions.html"))
    assert "{% set analyze_capability" in source, (
        "Expected actions.html to declare analyze_capability locally"
    )

    # Reproduce the original bug: remove the local declaration and confirm the
    # analyser reports the name as needed from outside.
    planted = re.sub(r"{%-?\s*set\s+analyze_capability\s*=.*?%}", "", source)
    needs = meta.find_undeclared_variables(env.parse(planted))
    assert "analyze_capability" in needs, (
        "The analyser failed to detect a removed declaration, so it would not "
        "have caught the original bug"
    )

    print("The analyser detects a planted leak.")
    return True


if __name__ == "__main__":
    tests = [
        test_no_pane_borrows_a_variable_from_a_sibling,
        test_every_pane_variable_is_supplied,
        test_analyser_detects_a_planted_leak,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
