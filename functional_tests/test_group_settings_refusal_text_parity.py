# test_group_settings_refusal_text_parity.py
"""
Functional test for V2 group settings refusal text parity.
Version: 0.261.165
Implemented in: 0.261.165

This test ensures the browser's REFUSAL_TEXT table stays byte-for-byte aligned
with functions_group_settings.REFUSAL_MESSAGES, including the plural
create_groups_role_required code used by the server.
"""

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
V2_GROUP_SETTINGS = ROOT / "application" / "v2_ui" / "src" / "lib" / "groupSettings.ts"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


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


if __name__ == "__main__":
    raise SystemExit(test_v2_refusal_texts_match_the_server())
