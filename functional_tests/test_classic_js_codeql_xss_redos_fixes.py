# test_classic_js_codeql_xss_redos_fixes.py
"""
Functional test for the classic UI CodeQL XSS and ReDoS fixes.
Version: 0.261.486
Implemented in: 0.261.485
Read-aloud, message loading, and plugin field merge follow-ups added in: 0.261.486

This test ensures the chat table unwrapping keeps the previous fence matching
without exponential backtracking, that conversation IDs, inline export labels,
directory search terms, and directory users are rendered as inert text in the
classic UI, that read-aloud never parses message text as HTML, that message
loading encodes the conversation ID, and that plugin field merges skip
prototype keys.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = ROOT / "application" / "single_app" / "static" / "js"
CHAT_MESSAGES_JS = STATIC_JS / "chat" / "chat-messages.js"
CHAT_EXPORT_JS = STATIC_JS / "chat" / "chat-export.js"
CHAT_TTS_JS = STATIC_JS / "chat" / "chat-tts.js"
PLUGIN_MODAL_STEPPER_JS = STATIC_JS / "plugin_modal_stepper.js"
WORKSPACE_MANAGER_JS = STATIC_JS / "workspace-manager.js"
CONTROL_CENTER_TEMPLATE = ROOT / "application" / "single_app" / "templates" / "control_center.html"

sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.485"

# The removed implementation, kept verbatim as the behavioral reference.
PREVIOUS_UNWRAP = r"""
function previousUnwrap(content) {
  const codeBlockTablePattern = /```(?:\w+)?\n((?:[^\n]*\|[^\n]*\n)+(?:\|[-\s|:]+\|\n)?(?:[^\n]*\|[^\n]*\n)*)\n?```/g;
  return content.replace(codeBlockTablePattern, (match, tableContent) => {
    const lines = tableContent.trim().split('\n');
    if (lines.length >= 2) {
      const hasTableStructure = lines.every(line => line.includes('|'));
      const hasSeparatorLine = lines.some(line => /^[\s|:-]+$/.test(line));
      if (hasTableStructure && (hasSeparatorLine || lines.length >= 3)) {
        return '\n\n' + tableContent.trim() + '\n\n';
      }
    }
    return match;
  });
}
"""

UNWRAP_PROBE = r"""
const unwrap = new Function('console', process.argv[1] + '\nreturn unwrapTablesFromCodeBlocks;')({ log() {} });
""" + PREVIOUS_UNWRAP + r"""
let seed = 20261125;
const random = n => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
const tokenSets = [
  ['```', '```js', '`', '|', '| a | b |', '|---|---|', '|-|', '||', '-', ':', ' ', 'a', '\n', '\n', '\r\n', 'x|y'],
  ['```', '```\n', '\n```', '|', '||', '|-|', '|---|', '---', ':', ' ', '\t', '\n', '\n\n', '| a |', '|```'],
];
const mismatches = [];
let transformed = 0;
for (const tokens of tokenSets) {
  for (let i = 0; i < 40000; i += 1) {
    let text = '';
    for (let t = 1 + random(28); t > 0; t -= 1) text += tokens[random(tokens.length)];
    const expected = previousUnwrap(text);
    if (expected !== text) transformed += 1;
    if (unwrap(text) !== expected && mismatches.length < 3) mismatches.push(text);
  }
}
const cases = {
  table: 'Intro\n```markdown\n| A | B |\n|---|---|\n| 1 | 2 |\n```\nOutro',
  separatorBridge: '```\n|a|\n|---|\n\n|---|\n|b|\n```\n|x|y|\n|---|---|\n|1|2|\n```js\ncode\n```',
  code: '```python\nprint(1)\n```',
};
for (const [name, text] of Object.entries(cases)) {
  if (unwrap(text) !== previousUnwrap(text)) mismatches.push(name);
}
const started = Date.now();
unwrap('```\n' + '||\n'.repeat(40000));
unwrap('|```\n'.repeat(100000));
console.log(JSON.stringify({ mismatches, transformed, pathologicalMs: Date.now() - started }));
"""


def _node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to run the classic chat helpers")
    return node


def _unwrap_source():
    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")
    start = source.index("function unwrapTablesFromCodeBlocks(content) {")
    end = source.index("\n/**\n * Converts Unicode box-drawing tables", start)
    return source[start:end]


def test_table_unwrapping_matches_the_previous_pattern_in_linear_time():
    """The scanner must transform exactly what the old regex did, without its backtracking."""
    print("Testing table unwrapping against the previous pattern...")
    source = _unwrap_source()
    assert "codeBlockTablePattern" not in source

    result = subprocess.run(
        [_node(), "-e", UNWRAP_PROBE, source],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["mismatches"] == [], outcome["mismatches"]
    assert outcome["transformed"] > 1000, "the fuzz corpus must exercise real unwrapping"
    # The previous pattern needed seconds for 22 such lines; 40,000 must stay fast.
    assert outcome["pathologicalMs"] < 5000, outcome
    print(f"  {outcome}")
    print("Table unwrapping passed!")


def test_export_selection_escapes_conversation_ids_in_attributes():
    """Conversation IDs from the URL or DOM must not break out of data-id attributes."""
    print("Testing export wizard ID escaping...")
    source = CHAT_EXPORT_JS.read_text(encoding="utf-8")
    assert 'data-id="${id}"' not in source
    assert source.count('data-id="${safeId}"') == 2
    assert "const safeId = _escapeHtml(id);" in source

    match = re.search(r"function _escapeHtml\(text\) \{.*?\n\}\n", source, re.S)
    assert match, "_escapeHtml was not found"
    script = match.group(0) + (
        "const value = '\"><img src=x onerror=alert(1)>\\'&';\n"
        "console.log(JSON.stringify([_escapeHtml(value), _escapeHtml(null), _escapeHtml(undefined)]));\n"
    )
    result = subprocess.run([_node(), "-e", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    escaped, empty_null, empty_undefined = json.loads(result.stdout)
    assert escaped == "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;&#39;&amp;"
    assert empty_null == "" and empty_undefined == ""
    print("Export wizard ID escaping passed!")


def test_text_to_speech_never_parses_message_text_as_html():
    """Read-aloud speaks the rendered message or the given text as plain text, never parsed as HTML."""
    print("Testing read-aloud text selection...")
    source = CHAT_TTS_JS.read_text(encoding="utf-8")
    assert "DOMParser" not in source
    assert "tempDiv.innerHTML" not in source
    assert "const plainText = getSpeakableMessageText(messageId, text);" in source
    start = source.index("function getSpeakableMessageText(messageId, text) {")
    helper = source[start:source.index("\n/**", start)]
    assert "innerHTML" not in helper

    script = helper + r"""
const CSS = { escape: value => value.replace(/["\\]/g, '\\$&') };
const selectors = [];
let rendered = null;
const document = { querySelector(selector) { selectors.push(selector); return rendered; } };
const markup = '<img src=x onerror=alert(1)> read <b>this</b>';
const fallback = getSpeakableMessageText('a"b', markup);
rendered = { innerText: 'Rendered reply', textContent: 'ignored' };
const shown = getSpeakableMessageText('m1', markup);
rendered = { innerText: '   ', textContent: '' };
const blank = getSpeakableMessageText('m1', 'Given text');
console.log(JSON.stringify({ fallback, shown, blank, selectors }));
"""
    result = subprocess.run([_node(), "-e", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["fallback"] == "<img src=x onerror=alert(1)> read <b>this</b>"
    assert outcome["shown"] == "Rendered reply"
    assert outcome["blank"] == "Given text"
    assert outcome["selectors"][0] == '[data-message-id="a\\"b"] .message-text'
    print("Read-aloud text selection passed!")


def test_message_loading_encodes_the_conversation_id():
    """A conversation ID from the page URL must stay one path segment when messages load."""
    print("Testing message loading URL...")
    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")
    assert "fetch(`/conversation/${encodeURIComponent(conversationId)}/messages?ts=${Date.now()}`, {" in source
    assert "fetch(`/conversation/${conversationId}/messages" not in source
    print("Message loading URL passed!")


def test_plugin_field_merge_skips_prototype_keys():
    """Merging parsed additional-field JSON must not reach Object.prototype."""
    print("Testing plugin field merge...")
    source = PLUGIN_MODAL_STEPPER_JS.read_text(encoding="utf-8")
    match = re.search(r"  deepMerge\(target, source\) \{.*?\n    return target;\n  \}\n", source, re.S)
    assert match, "deepMerge was not found"
    script = "const merger = {\n" + match.group(0) + "};\n" + r"""
const parsed = JSON.parse('{"__proto__": {"polluted": "yes"}, "constructor": {"prototype": {"polluted": "yes"}},'
  + ' "nested": {"__proto__": {"polluted": "yes"}, "keep": 1}, "plain": 2}');
const merged = merger.deepMerge({ nested: { existing: true } }, parsed);
console.log(JSON.stringify({ merged, polluted: ({}).polluted ?? null }));
"""
    result = subprocess.run([_node(), "-e", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["polluted"] is None
    assert outcome["merged"] == {"nested": {"existing": True, "keep": 1}, "plain": 2}
    print("Plugin field merge passed!")


def test_inline_export_buttons_render_labels_as_text():
    """Export button labels and icon classes must not be interpreted as markup."""
    print("Testing inline export button rendering...")
    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")
    start = source.index("function renderInlineExportButtonContent(")
    helper = source[start:source.index("function waitForUiPaint()", start)]
    assert "innerHTML" not in helper
    assert "button.replaceChildren(...(icon ? [icon] : []), String(labelText ?? ''));" in helper
    assert "icon.className = `${iconClass} me-1`;" in helper
    print("Inline export button rendering passed!")


@pytest.mark.parametrize("path,manager,prefix", [
    (CONTROL_CENTER_TEMPLATE, "GroupManager", "cc"),
    (WORKSPACE_MANAGER_JS, "WorkspaceManager", "ws"),
])
def test_user_search_renders_directory_text_inert(path, manager, prefix):
    """Search terms and directory names must never become markup or inline script."""
    print(f"Testing {manager} user search rendering...")
    source = path.read_text(encoding="utf-8")
    assert f'No users found matching "${{{manager}.escapeHtml(searchTerm)}}"' in source
    assert 'No users found matching "${searchTerm}"' not in source
    assert f'onclick="{manager}.selectUserForAdd(' not in source
    assert "escapeJsString" not in source
    assert f'class="btn btn-sm btn-primary {prefix}-select-user-btn" data-user-index="${{index}}"' in source
    assert f"{manager}.selectUserForAdd(user.id || '', user.displayName || '', user.email || '');" in source
    print(f"{manager} user search rendering passed!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
