# app_source.py
"""Run application definitions unchanged from their source, and stub whole modules.

Version: 0.261.160
Implemented in: 0.261.160

``definitions`` selects top-level functions, classes and assignments from an
application file, plus functions nested in a registrar such as
``register_route_backend_group_documents``, and ``run_definitions`` executes them in
a namespace the test provides. A name the code uses that the namespace doesn't
provide fails with a ``NameError`` where it is used.

``refusing_module_stub`` stands in for a whole module: every top-level name its file
defines is present, and each one refuses when called unless the test provides it.
Code a test doesn't model then fails where it is used, not at import, so a module
that later imports another name from the stub still loads.
"""

import ast

from test_support.agent_delegation import APP_ROOT, module_stub


def definitions(file_name, names, register=None, nested=()):
    """The named top-level definitions of ``file_name`` and those nested in ``register``."""
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    selected, found = [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            selected.append(node)
            found.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.FunctionDef) and node.name == register:
            for inner in node.body:
                if isinstance(inner, ast.FunctionDef) and inner.name in nested:
                    selected.append(inner)
                    found.add(inner.name)
    missing = (set(names) | set(nested)) - found
    assert not missing, f"Missing definitions in {file_name}: {missing}"
    return ast.Module(body=selected, type_ignores=[])


def run_definitions(file_name, names, namespace, register=None, nested=()):
    """Execute the selected definitions of ``file_name`` in ``namespace`` and return it."""
    module = definitions(file_name, names, register=register, nested=nested)
    exec(compile(module, file_name, "exec"), namespace)
    return namespace


def defined_names(file_name):
    """Every top-level name ``file_name`` defines: functions, classes and assignments."""
    names = set()
    for node in ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {name for name in names if not name.startswith("__")}


def refusing_module_stub(file_name, module_name, **provided):
    """A stand-in for ``module_name`` with every name ``file_name`` defines.

    The names given are the real ones or the test's models; every other name refuses
    when called.
    """
    defined = defined_names(file_name)
    assert set(provided) <= defined, f"{module_name} does not define {set(provided) - defined}"

    def refusing(name):
        def refused(*args, **kwargs):
            raise AssertionError(f"The code under test called {module_name}.{name}, which this test does not model")

        refused.__name__ = name
        return refused

    attributes = {name: refusing(name) for name in defined}
    attributes.update(provided)
    return module_stub(module_name, **attributes)
