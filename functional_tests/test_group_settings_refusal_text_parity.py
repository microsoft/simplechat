# test_group_settings_refusal_text_parity.py
"""
Functional test for V2 group settings refusal text parity.
Version: 0.261.165
Implemented in: 0.261.165

This test ensures the browser's REFUSAL_TEXT table stays byte-for-byte aligned
with functions_group_settings.REFUSAL_MESSAGES, including the plural
create_groups_role_required code used by the server.

It also pins the ImportError fallback literal in functions_workspace_context.py
(the copy exercised by the seam and context harnesses that stub functions_group)
against the real functions_group_settings.REFUSAL_MESSAGES[GROUP_MANAGER_REQUIRED],
so the S9 manage-section reason can never drift from the server's own sentence.
"""

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
V2_GROUP_SETTINGS = ROOT / "application" / "v2_ui" / "src" / "lib" / "groupSettings.ts"

CONTEXT_MODULE = APP_ROOT / "functions_workspace_context.py"
GROUP_SETTINGS_POLICY = APP_ROOT / "functions_group_settings_policy.py"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _group_manager_required_code():
    """The GROUP_MANAGER_REQUIRED code value, from the real module when it imports, else by AST."""
    try:
        from functions_group_settings_policy import GROUP_MANAGER_REQUIRED  # noqa: PLC0415
        return GROUP_MANAGER_REQUIRED
    except ModuleNotFoundError:
        tree = ast.parse(GROUP_SETTINGS_POLICY.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "GROUP_MANAGER_REQUIRED" for target in node.targets
            ):
                return ast.literal_eval(node.value)
        raise AssertionError("GROUP_MANAGER_REQUIRED not found in functions_group_settings_policy.py")


def _context_import_fallback_text():
    """The literal REFUSAL_MESSAGES[GROUP_MANAGER_REQUIRED] the context module falls back to on ImportError."""
    tree = ast.parse(CONTEXT_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not any(isinstance(handler.type, ast.Name) and handler.type.id == "ImportError" for handler in node.handlers):
            continue
        for handler in node.handlers:
            for stmt in ast.walk(handler):
                if (
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "REFUSAL_MESSAGES" for target in stmt.targets)
                    and isinstance(stmt.value, ast.Dict)
                ):
                    values = [ast.literal_eval(value) for value in stmt.value.values]
                    assert len(values) == 1, f"Expected one fallback message, found {len(values)}"
                    return values[0]
    raise AssertionError("ImportError fallback for REFUSAL_MESSAGES not found in functions_workspace_context.py")


def _server_refusal_messages():
    """Import the server table when dependencies are present; otherwise read the constants by AST."""
    try:
        from functions_group_settings import REFUSAL_MESSAGES  # noqa: PLC0415
        return REFUSAL_MESSAGES
    except ModuleNotFoundError:
        constants = {}
        for path in (
            APP_ROOT / "functions_group_directory_policy.py",
            APP_ROOT / "functions_group_settings_policy.py",
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    try:
                        constants[node.targets[0].id] = ast.literal_eval(node.value)
                    except ValueError:
                        pass

        tree = ast.parse((APP_ROOT / "functions_group_settings.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "REFUSAL_MESSAGES" for target in node.targets
            ):
                messages = {}
                for key, value in zip(node.value.keys, node.value.values):
                    key_name = key.id if isinstance(key, ast.Name) else ast.literal_eval(key)
                    messages[constants[key_name]] = ast.literal_eval(value)
                return messages
        raise AssertionError("Could not read REFUSAL_MESSAGES from functions_group_settings.py")


def _decode_js_string(quote, value):
    if quote in ("'", '"'):
        return ast.literal_eval(f"{quote}{value}{quote}")
    return bytes(value, "utf-8").decode("unicode_escape")


def _typescript_refusal_texts():
    source = V2_GROUP_SETTINGS.read_text(encoding="utf-8")
    block = re.search(
        r"const\s+REFUSAL_TEXT:\s*Record<string,\s*string>\s*=\s*\{(?P<body>.*?)\};",
        source,
        flags=re.S,
    )
    assert block, "Could not find REFUSAL_TEXT in groupSettings.ts"
    entries = {}
    for match in re.finditer(
        r"(?P<key>[A-Za-z0-9_]+)\s*:\s*(?P<quote>['\"`])(?P<value>(?:\\.|(?!\2).)*)(?P=quote)\s*,?",
        block.group("body"),
        flags=re.S,
    ):
        entries[match.group("key")] = _decode_js_string(match.group("quote"), match.group("value"))
    assert len(entries) == 6, f"Expected 6 refusal texts, found {len(entries)}: {sorted(entries)}"
    return entries


def test_v2_refusal_texts_match_the_server():
    browser_texts = _typescript_refusal_texts()
    refusal_messages = _server_refusal_messages()
    for key, text in browser_texts.items():
        assert key in refusal_messages, f"{key} is not a server refusal code"
        assert text == refusal_messages[key], (
            f"{key} refusal text drifted:\n"
            f"  browser: {text!r}\n"
            f"  server:  {refusal_messages[key]!r}"
        )
    assert browser_texts["create_groups_role_required"] == refusal_messages["create_groups_role_required"]


def test_context_import_fallback_matches_the_server():
    """The S9 manage-section reason falls back to a literal on ImportError; pin it to the server text."""
    fallback = _context_import_fallback_text()
    code = _group_manager_required_code()
    refusal_messages = _server_refusal_messages()
    assert code in refusal_messages, f"{code!r} is not a server refusal code"
    assert fallback == refusal_messages[code], (
        "functions_workspace_context.py ImportError fallback drifted from the server text:\n"
        f"  fallback: {fallback!r}\n"
        f"  server:   {refusal_messages[code]!r}"
    )


if __name__ == "__main__":
    test_v2_refusal_texts_match_the_server()
    test_context_import_fallback_matches_the_server()
    print("Test passed!")
