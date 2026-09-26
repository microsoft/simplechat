# test_group_settings_refusal_text_parity.py
"""
Functional test for V2 group settings refusal text parity.
Version: 0.261.187
Implemented in: 0.261.165

This test ensures the browser's REFUSAL_TEXT table stays byte-for-byte aligned
with functions_group_settings.REFUSAL_MESSAGES, including the plural
create_groups_role_required code used by the server.

It also holds the browser's unrecognized-status sentence and the status reason code it
replaces to functions_group_settings.GROUP_STATUS_UNRECOGNIZED_MESSAGE and
functions_group_settings_policy.GROUP_STATUS_UNAVAILABLE (0.261.187).

It also pins the ImportError fallback literal in functions_workspace_context.py
(the copy exercised by the seam and context harnesses that stub functions_group)
against the real functions_group_settings.REFUSAL_MESSAGES[GROUP_MANAGER_REQUIRED],
so the S9 manage-section reason can never drift from the server's own sentence.
"""

import ast
import re
from functools import lru_cache
from pathlib import Path

from test_support.group_settings_harness import group_settings_environment


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
V2_GROUP_SETTINGS = ROOT / "application" / "v2_ui" / "src" / "lib" / "groupSettings.ts"

CONTEXT_MODULE = APP_ROOT / "functions_workspace_context.py"


@lru_cache(maxsize=None)
def _real_server_table():
    """GROUP_MANAGER_REQUIRED and REFUSAL_MESSAGES, read from the real modules.

    The group settings harness loads functions_group_settings_policy and functions_group_settings
    with config stubbed and the network refused, so this reads the server's own values in any
    interpreter. A bare import would reach config.py's Cosmos client once the app's dependencies
    are installed, and an AST fallback would only run where they aren't.
    """
    with group_settings_environment() as env:
        return env.modules.policy.GROUP_MANAGER_REQUIRED, dict(env.modules.settings.REFUSAL_MESSAGES)


@lru_cache(maxsize=None)
def _real_status_refusal():
    """The status reason code and the sentence refusal() swaps in for a status the server doesn't recognize."""
    with group_settings_environment() as env:
        return env.modules.policy.GROUP_STATUS_UNAVAILABLE, env.modules.settings.GROUP_STATUS_UNRECOGNIZED_MESSAGE


def _group_manager_required_code():
    """The GROUP_MANAGER_REQUIRED code value, from the real policy module."""
    return _real_server_table()[0]


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
    """The server's refusal table, from the real functions_group_settings module."""
    return _real_server_table()[1]


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


def _typescript_constant(name):
    """An exported string constant from groupSettings.ts, decoded as the browser reads it."""
    source = V2_GROUP_SETTINGS.read_text(encoding="utf-8")
    match = re.search(
        rf"export\s+const\s+{name}\s*=\s*(?P<quote>['\"`])(?P<value>(?:\\.|(?!(?P=quote)).)*)(?P=quote)\s*;",
        source,
        flags=re.S,
    )
    assert match, f"Could not find {name} in groupSettings.ts"
    return _decode_js_string(match.group("quote"), match.group("value"))


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


def test_the_unrecognized_status_sentence_matches_the_server():
    """The Settings section words a status refusal in a group of unknown status with the sentence the
    server's refusal() swaps in for that same reason code, never the locked-or-inactive one (M11)."""
    code, sentence = _real_status_refusal()
    assert _typescript_constant("GROUP_STATUS_UNAVAILABLE_REASON") == code
    assert _typescript_constant("GROUP_STATUS_UNRECOGNIZED_TEXT") == sentence
    assert sentence != _server_refusal_messages()[code]


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
    test_the_unrecognized_status_sentence_matches_the_server()
    test_context_import_fallback_matches_the_server()
    print("Test passed!")
