#!/usr/bin/env python3
# test_v2_scope_lock_edit.py
"""
Functional test for editing a conversation's workspace scope lock from the V2 chat.
Version: 0.261.445
Implemented in: 0.261.445

V2 drew a conversation's scope lock in the chat header and gave no way to change it, while
classic locks and unlocks it through ``PATCH /api/conversations/<id>/scope_lock``. The V2 control
opens a dialog from the header, the conversation details and the Documents picker.

These checks pin what that control relies on, derived from the route source rather than from
memory of it:

- the route's method, decorators, body field, strict boolean check and response fields;
- the unlock refusal while ``enforce_workspace_scope_lock`` is on, and that locking is never
  refused, which is why the V2 control offers a lock even under enforcement;
- that a shared conversation is changed through the same route by anyone who can participate, and
  that the shared conversation's serialized form carries the fields V2 reads;
- that the setting reaches the browser through the sanitized bootstrap ``settings`` block;
- that the client sends exactly what the route reads, and that every surface is wired;
- the TypeScript logic (visibility rules, wording, optimistic write and rollback).
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
CONVERSATIONS_ROUTE = APP_ROOT / "route_backend_conversations.py"
COLLABORATION_FUNCTIONS = APP_ROOT / "functions_collaboration.py"
SETTINGS_FUNCTIONS = APP_ROOT / "functions_settings.py"
ADMIN_FIELDS = APP_ROOT / "admin_settings_fields.py"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_scope_lock_logic.ts"

NEW_SOURCES = [
    V2_SRC / "lib" / "scopeLock.ts",
    V2_SRC / "stores" / "scopeLockStore.ts",
    V2_SRC / "components" / "chat" / "ScopeLockControl.tsx",
    V2_SRC / "components" / "chat" / "ScopeLockDialog.tsx",
]


def _read(path):
    assert Path(path).is_file(), f"Missing expected file: {path}"
    return Path(path).read_text(encoding="utf-8")


def _normalize(source):
    return re.sub(r"\s+", " ", source)


def _route_source():
    source = _read(CONVERSATIONS_ROUTE)
    match = re.search(
        r"@bp\.route\('/api/conversations/<conversation_id>/scope_lock', methods=\['PATCH'\]\)"
        r"(?P<decorators>(?:\s*@[^\n]+\n)+)\s*def (?P<name>\w+)\(conversation_id\):"
        r"(?P<body>.*?)(?=\n    @bp\.route|\Z)",
        source,
        re.S,
    )
    assert match, "Could not find PATCH /api/conversations/<conversation_id>/scope_lock"
    return match


def test_version_is_at_least_the_implementing_release():
    """The application carries at least the version scope lock editing arrived in."""
    print("Testing the application version...")
    assert_app_version_at_least("0.261.445")


def test_the_route_is_what_the_client_expects():
    """Method, decorators, body field and strict boolean check all match the V2 client."""
    print("Testing the scope lock route contract...")

    route = _route_source()
    decorators = route.group("decorators")
    for decorator in ("@swagger_route(security=get_auth_security())", "@login_required", "@user_required"):
        assert decorator in decorators, f"The scope lock route should carry {decorator}"

    body = route.group("body")
    assert "'scope_locked' not in data" in body, "The route reads a `scope_locked` field"
    assert "return jsonify({'error': 'Missing scope_locked field'}), 400" in body
    # The client sends `locked === true`, a real boolean, because anything else is a 400.
    assert "new_value is not True and new_value is not False" in body, (
        "The route accepts only real booleans, so the client must never send a string or number"
    )
    assert "'scope_locked must be true or false'" in body

    for field in ('"success": True', '"scope_locked": new_value', '"locked_contexts"'):
        assert field in body, f"The route answers with {field}, which V2 reads back"
    assert "conversation_item.get('locked_contexts', [])" in body, (
        "Unlocking preserves locked_contexts so locking again returns to the same workspaces"
    )

    print("  ok  the scope lock route is what the V2 client calls")


def test_unlock_is_refused_under_enforcement_and_locking_never_is():
    """The V2 control offers Lock under enforcement but never Unlock."""
    print("Testing enforcement...")

    body = _route_source().group("body")
    guard = re.search(
        r"if new_value is False:\s*settings = get_settings\(\)\s*"
        r"if settings\.get\('enforce_workspace_scope_lock', True\):\s*"
        r"return jsonify\(\{'error': 'Scope unlock is disabled by administrator'\}\), 403",
        body,
    )
    assert guard, (
        "Unlocking must be refused with a 403 while enforce_workspace_scope_lock is on, defaulting "
        "to on. The V2 control mirrors this, and treats an absent setting as enforced."
    )
    # The refusal is scoped to unlocking: locking has no such branch, so a conversation that was
    # unlocked before the setting was turned on can still be locked again.
    assert body.count("enforce_workspace_scope_lock") == 1

    print("  ok  unlock is refused while enforced; locking is not")


def test_shared_conversations_use_the_same_route_for_anyone_who_can_participate():
    """V2 gates a shared conversation on `can_post_messages`, which is the participation check."""
    print("Testing shared-conversation rules...")

    routes = _read(CONVERSATIONS_ROUTE)
    loader = re.search(r"def _load_scope_lock_conversation\(conversation_id, user_id\):(?P<body>.*?)\ndef ", routes, re.S)
    assert loader, "Could not find _load_scope_lock_conversation"
    body = loader.group("body")
    assert "if conversation_item.get('user_id') != user_id:" in body and "raise PermissionError('Forbidden')" in body, (
        "A personal conversation is changed by its owner only"
    )
    assert "assert_user_can_participate_in_collaboration_conversation(user_id, conversation_item)" in body, (
        "A shared conversation is changed by anyone who can participate in it"
    )

    functions = _read(COLLABORATION_FUNCTIONS)
    serialize = re.search(r"def serialize_collaboration_conversation\(.*?\n    return \{(?P<body>.*?)\n    \}\n", functions, re.S)
    assert serialize, "Could not find serialize_collaboration_conversation"
    for field in ("'can_post_messages': can_post_messages", "'scope_locked': conversation_doc.get('scope_locked', True)", "'locked_contexts':"):
        assert field in serialize.group("body"), f"A shared conversation reports {field}, which V2 reads"

    metadata_route = re.search(r'"scope_locked": conversation_item.get\(.scope_locked.\),\s*"locked_contexts"', routes)
    assert metadata_route, "The personal metadata response carries scope_locked and locked_contexts"
    assert '"user_id": conversation_item.get(\'user_id\', \'\')' in routes, (
        "The personal metadata response carries the owner, which V2 compares with the signed-in user"
    )

    print("  ok  shared conversations are gated on participation")


def test_the_administrator_setting_reaches_the_browser_with_the_server_default():
    """The setting is not an enable_* flag, so V2 reads it from the sanitized settings block."""
    print("Testing how the enforcement setting reaches V2...")

    functions = _read(SETTINGS_FUNCTIONS)
    tree = ast.parse(functions)
    sanitize = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "sanitize_settings_for_user"
    )
    terms = next(
        ast.literal_eval(node.value)
        for node in ast.walk(sanitize)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "sensitive_terms" for target in node.targets)
    )
    key = "enforce_workspace_scope_lock"
    assert not any(term in key for term in terms), (
        f"{key} must survive sanitize_settings_for_user, or the bootstrap payload cannot carry it"
    )

    backend_only = re.search(r"TABULAR_GENERATION_BACKEND_SETTING_KEYS = \{(?P<body>.*?)\}", functions, re.S)
    assert backend_only and key not in backend_only.group("body")

    assert f"'{key}': True," in functions, "The stored default is enforced"
    assert "settings.get('enforce_workspace_scope_lock', True)" in _read(CONVERSATIONS_ROUTE)

    admin = _normalize(_read(ADMIN_FIELDS))
    assert re.search(
        r'"workspace-scope-lock-section": \[ \{ "key": "enforce_workspace_scope_lock", "type": "switch",', admin
    ), "The administrator controls it with a switch in the Workspace Scope Lock section"

    features = _read(APP_ROOT / "route_backend_v2.py")
    assert 'if key.startswith("enable_") and isinstance(value, bool)' in features, (
        "Only enable_* keys reach `features`; this one is read from `settings` instead"
    )

    logic = _read(V2_SRC / "lib" / "scopeLock.ts")
    assert "settings.enforce_workspace_scope_lock === false" in logic, (
        "Only an explicit false lifts the lock in V2, matching the server's default of enforced"
    )

    print("  ok  the setting reaches V2 through bootstrap settings, defaulting to enforced")


def test_the_client_sends_what_the_route_reads():
    """PATCH, the encoded conversation id, and a real boolean under `scope_locked`."""
    print("Testing the client request...")

    endpoints = _normalize(_read(V2_SRC / "lib" / "endpoints.ts"))
    assert (
        "export const setConversationScopeLock = (conversationId: string, locked: boolean) => "
        "api.patch<ScopeLockResponse>( "
        "`/api/conversations/${encodeURIComponent(conversationId)}/scope_lock`, "
        "{ scope_locked: locked === true }, );"
    ) in endpoints, "The client must PATCH /api/conversations/<id>/scope_lock with { scope_locked: <boolean> }"

    store = _read(V2_SRC / "stores" / "scopeLockStore.ts")
    assert "setConversationScopeLock(conversationId, locked)" in store
    assert "loadMetadata(conversationId)" in store, (
        "After a change the conversation is read again so every surface agrees with the server"
    )

    print("  ok  the client sends what the route reads")


def test_every_surface_is_wired_to_the_same_dialog():
    """Header, details and picker all ask the store for one dialog that is hosted once."""
    print("Testing wiring...")

    badges = _read(V2_SRC / "components" / "chat" / "ConversationBadges.tsx")
    assert '<ScopeLockControl variant="badge" />' in badges, "The header lock is a button that opens the dialog"
    assert badges.count("<ScopeLockDialogHost />") == 1, "The dialog is hosted once, beside the header lock"

    details = _read(V2_SRC / "components" / "chat" / "ConversationDetails.tsx")
    assert '<ScopeLockControl variant="row" />' in details, "The details show the lock and offer the change"
    assert "!scopeLockOpen" in details, (
        "Escape in the scope lock dialog must not also close the details underneath it"
    )

    picker = _read(V2_SRC / "components" / "chat" / "WorkspaceDocumentPicker.tsx")
    assert '<ScopeLockControl variant="notice" onActivate={onClose} />' in picker, (
        "The Documents picker explains why its list is narrowed and closes before the dialog opens"
    )

    control = _read(V2_SRC / "components" / "chat" / "ScopeLockControl.tsx")
    assert "view.state === 'hidden'" in control, "A conversation with no lock state draws no control"
    assert "aria-haspopup=\"dialog\"" in control and "aria-label={label}" in control, (
        "The control names itself and says it opens a dialog"
    )

    dialog = _read(V2_SRC / "components" / "chat" / "ScopeLockDialog.tsx")
    assert "useState<ScopeLockAction | null>(view.action)" in dialog, (
        "The dialog fixes its intent when it opens, so it cannot flip while the change is running"
    )
    assert 'role="alert"' in dialog, "A refusal is announced inside the dialog that made the request"
    assert "Workspace scope lock is enforced" not in dialog, "Wording lives in lib/scopeLock.ts, where it is tested"

    print("  ok  every surface asks one dialog, hosted once")


def test_nothing_unsafe_or_remote_is_added():
    """Text from the server is React text, and no remote asset or inline display rule appears."""
    print("Testing markup and assets...")

    offenders = []
    for path in NEW_SOURCES:
        source = _read(path)
        for pattern, why in (
            (r"dangerouslySetInnerHTML", "raw HTML"),
            (r"innerHTML", "raw HTML"),
            (r"https?://", "a remote URL"),
            (r"display\s*:\s*none", "an inline display rule"),
            (r"\balert\(", "alert()"),
        ):
            if re.search(pattern, source):
                offenders.append(f"{path.name}: {why}")
    assert not offenders, offenders

    print("  ok  no raw HTML, remote URLs, inline display rules or alert()")


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("Testing scope lock logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node can
    # resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-scope-lock-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 10, result.stdout
    print(f"  ok  {passed} TypeScript logic checks passed")


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_the_route_is_what_the_client_expects,
        test_unlock_is_refused_under_enforcement_and_locking_never_is,
        test_shared_conversations_use_the_same_route_for_anyone_who_can_participate,
        test_the_administrator_setting_reaches_the_browser_with_the_server_default,
        test_the_client_sends_what_the_route_reads,
        test_every_surface_is_wired_to_the_same_dialog,
        test_nothing_unsafe_or_remote_is_added,
        test_the_typescript_logic_checks_pass,
    ]
    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\n{sum(1 for result in results if result)}/{len(results)} test(s) passed")
    sys.exit(0 if all(results) else 1)
