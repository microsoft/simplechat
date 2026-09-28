# test_public_settings_refusal_text_parity.py
"""
Functional test for V2 public settings refusal text parity.
Version: 0.261.188
Implemented in: 0.261.185

The V2 public Settings section explains every withheld control with the reviewed text for the reason
code the server's settings_management hint reports. This test holds the browser's REFUSAL_TEXT table
(application/v2_ui/src/lib/publicSettings.ts) byte-for-byte to the server's one table,
functions_public_settings_policy.PUBLIC_SETTINGS_REFUSAL_MESSAGES -- the same table the native routes
refuse with and the public workspace context gives as a closed Manage section's reason -- read from the
real modules through the isolated public settings harness, never a bare import or an AST fallback.
It also holds the browser fixture's copy (ui_tests/fixtures/public_settings.py) to the same table, and the
browser's unrecognized-status sentence and the status reason code it replaces to
functions_public_settings.PUBLIC_STATUS_UNRECOGNIZED_MESSAGE and PUBLIC_STATUS_UNAVAILABLE (0.261.188).
"""

import ast
import re
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_support.public_settings_harness import public_settings_environment  # noqa: E402


V2_PUBLIC_SETTINGS = ROOT / "application" / "v2_ui" / "src" / "lib" / "publicSettings.ts"


@lru_cache(maxsize=None)
def _real_server_table():
    """PUBLIC_SETTINGS_REFUSAL_MESSAGES and the routes' REFUSAL_MESSAGES, from the real modules.

    The harness loads functions_public_settings_policy and functions_public_settings with config
    stubbed and the network refused, so this reads the server's own values in any interpreter.
    """
    with public_settings_environment() as env:
        policy_table = dict(env.modules.policy.PUBLIC_SETTINGS_REFUSAL_MESSAGES)
        route_table = dict(env.modules.settings.REFUSAL_MESSAGES)
        return policy_table, route_table


@lru_cache(maxsize=None)
def _real_status_refusal():
    """The status reason code and the sentence refusal() swaps in for a status the server doesn't recognize."""
    with public_settings_environment() as env:
        return env.modules.policy.PUBLIC_STATUS_UNAVAILABLE, env.modules.settings.PUBLIC_STATUS_UNRECOGNIZED_MESSAGE


def _decode_js_string(quote, value):
    if quote in ("'", '"'):
        return ast.literal_eval(f"{quote}{value}{quote}")
    return bytes(value, "utf-8").decode("unicode_escape")


def _typescript_refusal_texts():
    source = V2_PUBLIC_SETTINGS.read_text(encoding="utf-8")
    block = re.search(
        r"const\s+REFUSAL_TEXT:\s*Record<string,\s*string>\s*=\s*\{(?P<body>.*?)\};",
        source,
        flags=re.S,
    )
    assert block, "Could not find REFUSAL_TEXT in publicSettings.ts"
    entries = {}
    for match in re.finditer(
        r"(?P<key>[A-Za-z0-9_]+)\s*:\s*(?P<quote>['\"`])(?P<value>(?:\\.|(?!(?P=quote)).)*)(?P=quote)\s*,?",
        block.group("body"),
        flags=re.S,
    ):
        entries[match.group("key")] = _decode_js_string(match.group("quote"), match.group("value"))
    return entries


def _typescript_constant(name):
    """An exported string constant from publicSettings.ts, decoded as the browser reads it."""
    source = V2_PUBLIC_SETTINGS.read_text(encoding="utf-8")
    match = re.search(
        rf"export\s+const\s+{name}\s*=\s*(?P<quote>['\"`])(?P<value>(?:\\.|(?!(?P=quote)).)*)(?P=quote)\s*;",
        source,
        flags=re.S,
    )
    assert match, f"Could not find {name} in publicSettings.ts"
    return _decode_js_string(match.group("quote"), match.group("value"))


def test_the_browser_table_is_the_server_table():
    browser = _typescript_refusal_texts()
    policy_table, _route_table = _real_server_table()
    assert browser == policy_table, (
        "publicSettings.ts REFUSAL_TEXT drifted from PUBLIC_SETTINGS_REFUSAL_MESSAGES:\n"
        f"  only in the browser: {sorted(set(browser) - set(policy_table))}\n"
        f"  only on the server:  {sorted(set(policy_table) - set(browser))}\n"
        f"  differing texts:     {sorted(k for k in set(browser) & set(policy_table) if browser[k] != policy_table[k])}"
    )
    assert len(browser) == 6


def test_the_routes_refuse_with_the_same_table():
    policy_table, route_table = _real_server_table()
    assert route_table == policy_table


def test_the_unrecognized_status_sentence_matches_the_server():
    """The Settings section words a status refusal in a workspace of unknown status with the sentence the
    server's refusal() swaps in for that same reason code, never the locked-or-inactive one (M11)."""
    code, sentence = _real_status_refusal()
    policy_table, _route_table = _real_server_table()
    assert _typescript_constant("PUBLIC_STATUS_UNAVAILABLE_REASON") == code
    assert _typescript_constant("PUBLIC_STATUS_UNRECOGNIZED_TEXT") == sentence
    assert sentence != policy_table[code]


def test_the_browser_fixture_serves_the_same_table():
    from ui_tests.fixtures import public_settings as fixture_module

    policy_table, _route_table = _real_server_table()
    assert fixture_module.PUBLIC_SETTINGS_REFUSAL_MESSAGES == policy_table


if __name__ == "__main__":
    test_the_browser_table_is_the_server_table()
    test_the_routes_refuse_with_the_same_table()
    test_the_unrecognized_status_sentence_matches_the_server()
    test_the_browser_fixture_serves_the_same_table()
    print("Test passed!")
