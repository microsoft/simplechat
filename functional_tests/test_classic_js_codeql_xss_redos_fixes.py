# test_classic_js_codeql_xss_redos_fixes.py
"""
Functional test for the classic UI CodeQL XSS and ReDoS fixes.
Version: 0.261.485
Implemented in: 0.261.485

This test ensures the chat table unwrapping keeps the previous fence matching
without exponential backtracking, and that conversation IDs, text-to-speech
text, inline export labels, directory search terms, and directory users are
rendered as inert text in the classic UI.
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


def test_text_to_speech_strips_markup_with_an_inert_parser():
    """Message text that looks like HTML must not be parsed into a live element."""
    print("Testing text-to-speech markup stripping...")
    source = CHAT_TTS_JS.read_text(encoding="utf-8")
    assert "tempDiv.innerHTML = text" not in source
    assert "new DOMParser().parseFromString(text, 'text/html')" in source
    assert "const plainText = parsed.body.textContent || '';" in source
    print("Text-to-speech markup stripping passed!")


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
