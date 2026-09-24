# test_group_document_write_inventory.py
"""
Functional test for the group document write inventory.
Version: 0.261.156
Implemented in: 0.261.156

A write that stores an outdated copy of a group document can put back membership,
roles or settings that have since changed. A write to a group deleted since it was
read recreates it. So every writer of the group document goes through
``update_group_document_with_etag_guard`` in ``functions_group``, apart from a short,
reviewed allowlist.

This test reads every module of the application, statically, and finds every call to
a write method of ``cosmos_groups_container``: ``upsert_item``, ``replace_item``,
``create_item``, ``patch_item``, ``delete_item``, ``execute_item_batch`` and
``delete_all_items_by_partition_key``. It follows the container:

- under its own name, however it was imported;
- under an import alias, or assigned to another name, in the scope that assigned it
  and the functions nested inside it;
- as ``<module>.cosmos_groups_container``, or through
  ``getattr(<object>, "cosmos_groups_container"[, default])``;
- passed, positionally or by keyword, into a function of the same module, whose
  parameter then names it.

Every other use of the container fails unless it's reviewed. That covers returning
it, storing it in a collection or attribute, passing it to another module's function,
and calling a method this test doesn't know. The text ``"cosmos_groups_container"``
anywhere but ``config.py`` fails the same way, since a registry can reach the
container by name.

Limits: this test can't see a container reached through a name computed at run
time, or one held in a class or closure and fetched from another module. It also
can't see writes through another SDK client or the REST API.

``PENDING_RAW_WRITES`` is a ratchet. It lists the unconditional writers still being
moved onto the guard in this series, and each conversion removes its own entries.
A pending entry that no longer matches the code fails, so the list can only shrink.
"""

import ast
from collections import Counter
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
CONTAINER = "cosmos_groups_container"
WRITE_METHODS = frozenset({
    "upsert_item", "replace_item", "create_item", "patch_item", "delete_item",
    "execute_item_batch", "delete_all_items_by_partition_key",
})
READ_METHODS = frozenset({"read_item", "query_items", "read_all_items", "query_items_change_feed", "read"})

# The writes allowed to stay outside the guard, with the reason each is safe.
ALLOWED_WRITES = {
    ("functions_group.py", "create_group", "create_item"): "creates a new group document",
    ("functions_group.py", "update_group_document_with_etag_guard", "replace_item"):
        "the guard itself: conditional on the _etag of the copy it just read",
    ("functions_group.py", "delete_group", "delete_item"): "removes the whole group",
    ("functions_group_document_management.py", "_patch_tag_definitions", "patch_item"):
        "a partial patch of /tag_definitions, conditional on an _etag filter predicate",
}
# Modules that reach the container through registries, and why that's reviewed.
ALLOWED_DYNAMIC_MODULES = {
    "functions_data_management.py": (
        "migration to another environment and the Cosmos editor replace conditionally; restore with "
        "overwrite replaces whole documents from a backup by design"
    ),
}
# The ratchet: raw writers this series still moves onto the guard. Each conversion removes its own.
PENDING_RAW_WRITES = Counter({
    ("route_backend_group_documents.py", "api_create_group_tag", "upsert_item"): 1,
    ("route_backend_group_documents.py", "api_update_group_tag", "upsert_item"): 2,
    ("route_backend_group_documents.py", "api_delete_group_tag", "upsert_item"): 1,
    ("functions_documents.py", "get_or_create_tag_definition", "upsert_item"): 1,
    ("functions_simplechat_operations.py", "make_group_inactive_for_current_user", "upsert_item"): 1,
    ("functions_group.py", "update_group_model_endpoints", "upsert_item"): 1,
})

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class Inventory:
    """Every use of the groups container in one module's source."""

    def __init__(self, name, source):
        self.name = name
        self.tree = ast.parse(source)
        self.parents = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parents[child] = node
        self.functions = {}
        for node in ast.walk(self.tree):
            if isinstance(node, _FUNCTIONS):
                self.functions.setdefault(node.name, []).append(node)
        self.scope_of = {}
        self._index_scopes(self.tree, self.tree)
        self.aliases = {self.tree: {CONTAINER}}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == CONTAINER and alias.asname:
                        self.aliases[self.tree].add(alias.asname)
        self.writes, self.escapes = [], []
        self.registry_lines = [
            node.lineno for node in ast.walk(self.tree)
            if isinstance(node, ast.Constant) and node.value == CONTAINER
        ]
        self._resolve()
        self._classify()

    # --- scopes -------------------------------------------------------------

    def _index_scopes(self, node, scope):
        for child in ast.iter_child_nodes(node):
            self.scope_of[child] = scope
            self._index_scopes(child, child if isinstance(child, _FUNCTIONS) else scope)

    def _enclosing(self, scope):
        chain = []
        while scope is not None:
            chain.append(scope)
            scope = None if scope is self.tree else self.scope_of.get(scope)
        return chain

    def names_in_scope(self, scope):
        names = set()
        for owner in self._enclosing(scope):
            names |= self.aliases.get(owner, set())
        return names

    def is_container(self, node):
        scope = self.scope_of.get(node, self.tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            return node.id in self.names_in_scope(scope)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            return node.attr == CONTAINER
        return (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == CONTAINER
        )

    def _resolve(self):
        """Grow the alias sets to a fixed point: assignments and same-module parameters."""
        changed = True
        while changed:
            changed = False
            for node in ast.walk(self.tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    if not self.is_container(node.value):
                        continue
                    targets = [node.target] if isinstance(node, (ast.AnnAssign, ast.NamedExpr)) else node.targets
                    scope = self.scope_of.get(node, self.tree)
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in self.aliases.setdefault(scope, set()):
                            self.aliases[scope].add(target.id)
                            changed = True
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.functions:
                    for key, value in [*enumerate(node.args), *((kw.arg, kw.value) for kw in node.keywords)]:
                        if key is None or not self.is_container(value):
                            continue
                        for function in self.functions[node.func.id]:
                            parameters = [a.arg for a in (*function.args.posonlyargs, *function.args.args)]
                            name = parameters[key] if isinstance(key, int) and key < len(parameters) else key
                            if isinstance(name, str) and name not in self.aliases.setdefault(function, set()):
                                self.aliases[function].add(name)
                                changed = True

    # --- classification -------------------------------------------------------

    def _function_name(self, node):
        scope = self.scope_of.get(node, self.tree)
        return scope.name if isinstance(scope, _FUNCTIONS) else "<module>"

    def _classify(self):
        for node in ast.walk(self.tree):
            if not self.is_container(node):
                continue
            parent = self.parents.get(node)
            owner = self._function_name(node)
            if isinstance(parent, ast.Attribute) and parent.value is node:
                call = self.parents.get(parent)
                if isinstance(call, ast.Call) and call.func is parent and parent.attr in WRITE_METHODS:
                    self.writes.append((owner, parent.attr, call))
                elif not (isinstance(call, ast.Call) and call.func is parent and parent.attr in READ_METHODS):
                    self.escapes.append((owner, f"uses .{parent.attr}", node.lineno))
                continue
            if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and parent.value is node:
                targets = [parent.target] if isinstance(parent, (ast.AnnAssign, ast.NamedExpr)) else parent.targets
                if all(isinstance(target, ast.Name) for target in targets):
                    continue
            if isinstance(parent, ast.keyword):
                parent = self.parents.get(parent)
            if (
                isinstance(parent, ast.Call) and parent.func is not node and isinstance(parent.func, ast.Name)
                and parent.func.id in self.functions
            ):
                continue
            callee = ast.unparse(parent.func) if isinstance(parent, ast.Call) else type(parent).__name__
            self.escapes.append((owner, f"escapes into {callee}", node.lineno))


def application_modules():
    return sorted(path for path in APP_ROOT.rglob("*.py") if path.name != "config.py")


@pytest.fixture(scope="module")
def inventories():
    return {path.relative_to(APP_ROOT).as_posix(): Inventory(path.name, path.read_text(encoding="utf-8"))
            for path in application_modules()}


def found_writes(inventories):
    return Counter(
        (name, owner, method)
        for name, inventory in inventories.items()
        for owner, method, _call in inventory.writes
    )


def test_the_inventory_reads_the_whole_application(inventories):
    assert len(inventories) > 100
    assert found_writes(inventories)[("functions_group.py", "update_group_document_with_etag_guard", "replace_item")] == 1


def test_every_group_document_write_is_allowed_or_pending(inventories):
    unexpected = {
        key: count for key, count in found_writes(inventories).items()
        if key not in ALLOWED_WRITES and key not in PENDING_RAW_WRITES
    }
    assert unexpected == {}, "A new unconditional write of the group document: use update_group_document_with_etag_guard"


def test_the_allowlist_and_the_ratchet_match_the_code_exactly(inventories):
    writes = found_writes(inventories)
    assert {key: writes[key] for key in ALLOWED_WRITES} == {key: 1 for key in ALLOWED_WRITES}
    assert {key: writes[key] for key in PENDING_RAW_WRITES} == dict(PENDING_RAW_WRITES), (
        "A pending writer changed: remove the entries of every writer moved onto the guard"
    )


def test_the_container_never_escapes_unreviewed(inventories):
    escapes = {
        name: inventory.escapes for name, inventory in inventories.items()
        if inventory.escapes and name not in ALLOWED_DYNAMIC_MODULES
    }
    assert escapes == {}


def test_only_reviewed_modules_name_the_container_as_text(inventories):
    named = {name for name, inventory in inventories.items() if inventory.registry_lines}
    assert named == set(ALLOWED_DYNAMIC_MODULES)


def test_the_tag_definition_patch_is_conditional_on_the_etag(inventories):
    [(_owner, _method, call)] = [
        write for write in inventories["functions_group_document_management.py"].writes
        if write[0] == "_patch_tag_definitions"
    ]
    predicate = {keyword.arg: keyword.value for keyword in call.keywords}.get("filter_predicate")
    assert predicate is not None and "_etag" in ast.unparse(predicate)


SYNTHETIC = {
    "direct": ("from config import cosmos_groups_container\n"
               "def f(g):\n    cosmos_groups_container.upsert_item(g)\n", [("f", "upsert_item")], []),
    "star_import": ("from config import *\n"
                    "def f(g):\n    cosmos_groups_container.replace_item(item=g['id'], body=g)\n",
                    [("f", "replace_item")], []),
    "import_alias": ("from config import cosmos_groups_container as groups\n"
                     "def f(g):\n    groups.create_item(g)\n", [("f", "create_item")], []),
    "alias_chain": ("from config import *\n"
                    "def f(g):\n    c = cosmos_groups_container\n    other = c\n    other.upsert_item(g)\n",
                    [("f", "upsert_item")], []),
    "closure": ("from config import *\n"
                "def f(g):\n    c = cosmos_groups_container\n    def apply():\n        c.patch_item(g, g, [])\n"
                "    apply()\n", [("apply", "patch_item")], []),
    "module_attribute": ("import config\n"
                         "def f(g):\n    config.cosmos_groups_container.delete_item(g, g)\n",
                         [("f", "delete_item")], []),
    "getattr": ("import config\n"
                "def f(g):\n    container = getattr(config, 'cosmos_groups_container', None)\n"
                "    container.upsert_item(g)\n", [("f", "upsert_item")], []),
    "positional_parameter": ("from config import cosmos_groups_container\n"
                             "def save(container, g):\n    container.upsert_item(g)\n"
                             "def f(g):\n    save(cosmos_groups_container, g)\n", [("save", "upsert_item")], []),
    "keyword_parameter": ("from config import cosmos_groups_container\n"
                          "def save(g, *, target=None):\n    target.execute_item_batch([])\n"
                          "def f(g):\n    save(g, target=cosmos_groups_container)\n",
                          [("save", "execute_item_batch")], []),
    "another_module": ("from config import cosmos_groups_container\nfrom helpers import save\n"
                       "def f(g):\n    save(cosmos_groups_container, g)\n", [], ["escapes into save"]),
    "returned": ("from config import cosmos_groups_container\n"
                 "def get():\n    return cosmos_groups_container\n", [], ["escapes into Return"]),
    "registry": ("from config import cosmos_groups_container\n"
                 "REGISTRY = {'groups': cosmos_groups_container}\n", [], ["escapes into Dict"]),
    "attribute_store": ("from config import cosmos_groups_container\n"
                        "class Holder:\n    def __init__(self):\n        self.container = cosmos_groups_container\n",
                        [], ["escapes into Assign"]),
    "method_by_name": ("from config import cosmos_groups_container\n"
                       "def f(g):\n    getattr(cosmos_groups_container, 'upsert_item')(g)\n",
                       [], ["escapes into getattr"]),
    "unknown_method": ("from config import cosmos_groups_container\n"
                       "def f():\n    cosmos_groups_container.replace_throughput(400)\n",
                       [], ["uses .replace_throughput"]),
    "reads_only": ("from config import cosmos_groups_container\n"
                   "def f(g):\n    cosmos_groups_container.read_item(item=g, partition_key=g)\n"
                   "    list(cosmos_groups_container.query_items('SELECT * FROM c'))\n", [], []),
    "other_container": ("from config import cosmos_user_settings_container\n"
                        "def f(g):\n    cosmos_user_settings_container.upsert_item(g)\n", [], []),
    "same_name_other_scope": ("from config import *\n"
                              "def f(g):\n    c = cosmos_groups_container\n    c.read_item(g, g)\n"
                              "def h(g):\n    c = cosmos_user_settings_container\n    c.upsert_item(g)\n", [], []),
}


@pytest.mark.parametrize("case", SYNTHETIC)
def test_the_inventory_follows_every_supported_form(case):
    source, writes, escapes = SYNTHETIC[case]
    inventory = Inventory(f"{case}.py", source)
    assert [(owner, method) for owner, method, _call in inventory.writes] == writes
    assert [reason for _owner, reason, _line in inventory.escapes] == escapes


def test_the_registry_text_is_found_wherever_it_appears():
    inventory = Inventory("registry_text.py", "NAMES = ('cosmos_groups_container', 'other')\n")
    assert inventory.registry_lines == [1]
