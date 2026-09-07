#!/usr/bin/env python3
# test_chat_citation_whitespace_preservation.py
"""
Functional test for inline citation whitespace preservation.
Version: 0.250.229
Implemented in: 0.250.229

This test ensures that parseCitations() in chat-citations.js no longer deletes the
whitespace that follows an inline document citation. The citation regex captures the
whitespace after the trailing [#citation-id] marker, and before this fix that
whitespace was dropped, collapsing the following paragraph onto the end of the
citation and, inside lists, absorbing it into the preceding list item.

parseCitations() runs on raw markdown before marked.parse(), so the harness below
executes the real production function and then renders the result with the vendored
marked bundle to assert the user-visible block structure.

Refs: #1289
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_JS_DIR = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat')
CITATIONS_FILE = os.path.join(CHAT_JS_DIR, 'chat-citations.js')
MARKED_FILE = os.path.join(CHAT_JS_DIR, 'marked.min.js')

CITATION_ONE = '181b54f7-fcf9-479b-a58b-81a5da3ba251_1'
CITATION_TWO = '159255fa-79d6-4619-9131-819813ae7997_1'
CITATION_THREE = '5e583e44-ea82-4569-bda8-e545bf12dca4_1'
CITATION_GENERIC = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

REPORTED_MESSAGE = (
    'Simple Chat processes uploaded images as part of its document-ingestion pipeline:\n'
    '\n'
    '5. **Grounded chat:** Once processing completes, the image-derived content can be '
    'found through hybrid keyword and vector search and used to support cited answers in '
    f'chat. (Source: application_workflows.md, Page: 1) [#{CITATION_ONE}]\n'
    '\n'
    'Admins can configure the extraction approach for images and PDFs under '
    '**Admin Settings > Search & Extract**. The available modes are:\n'
    '\n'
    '- **Auto:** Samples the content and chooses the richer path when the document '
    f'structure warrants it (Source: document-intelligence.md, Page: 1) [#{CITATION_TWO}]\n'
    '\n'
    'For best results, upload clear, readable images. '
    f'(Source: uploading_documents.md, Page: 1) [#{CITATION_THREE}]\n'
    '\n'
    'Thank you, Paul.'
)

TEST_CASES = {
    'reported': REPORTED_MESSAGE,
    'inline_space': (
        f'See the policy (Source: Policy.pdf, Page: 12) [#{CITATION_GENERIC}_12] and then act.'
    ),
    'trailing_punctuation': (
        f'See the policy (Source: Policy.pdf, Page: 12) [#{CITATION_GENERIC}_12].'
    ),
    'back_to_back': (
        f'Both agree (Source: A.pdf, Page: 1) [#{CITATION_GENERIC}_1] '
        f'(Source: B.pdf, Page: 2) [#{CITATION_GENERIC}_2] end.'
    ),
    'citation_id_on_next_line': (
        'Findings are consistent. (Source: Report.pdf, Page: 4)\n'
        f'[#{CITATION_GENERIC}_4]\n'
        '\n'
        'The next section explains why.'
    ),
    'stray_bracket_own_line': (
        'Model used passim style.\n'
        '\n'
        f'[#{CITATION_GENERIC}_3]\n'
        '\n'
        'Next paragraph.'
    ),
    'stray_bracket_starts_paragraph': (
        'Model used passim style.\n'
        '\n'
        f'[#{CITATION_GENERIC}_3] Next paragraph.'
    ),
    'stray_bracket_inline': (
        f'Model used passim style [#{CITATION_GENERIC}_3] mid sentence.'
    ),
    'stray_bracket_consecutive': (
        f'Model used passim style [#{CITATION_GENERIC}_3] [#{CITATION_GENERIC}_4] mid sentence.'
    ),
}

NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };

function escapeText(value) {
    return String(value).replace(/[&<>]/g, character => ESCAPE_MAP[character]);
}

function escapeAttribute(value) {
    return String(value).replace(/[&<>"]/g, character => ESCAPE_MAP[character]);
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.childNodes = [];
        this.dataset = {};
        this.attributes = {};
        this.textValue = '';
    }
    set textContent(value) {
        this.textValue = value === null || value === undefined ? '' : String(value);
        this.childNodes = [];
    }
    get textContent() { return this.textValue; }
    set href(value) { this.attributes.href = value; }
    set className(value) { this.attributes.class = value; }
    set target(value) { this.attributes.target = value; }
    set rel(value) { this.attributes.rel = value; }
    appendChild(child) { this.childNodes.push(child); return child; }
    get innerHTML() {
        if (this.childNodes.length) {
            return this.childNodes.map(child => child.outerHTML).join('');
        }
        return escapeText(this.textValue);
    }
    get outerHTML() {
        const parts = [];
        Object.keys(this.attributes).forEach(name => {
            parts.push(`${name}="${escapeAttribute(this.attributes[name])}"`);
        });
        Object.keys(this.dataset).forEach(name => {
            const attributeName = 'data-' + name.replace(/[A-Z]/g, match => '-' + match.toLowerCase());
            parts.push(`${attributeName}="${escapeAttribute(this.dataset[name])}"`);
        });
        const attributeText = parts.length ? ' ' + parts.join(' ') : '';
        return `<${this.tagName}${attributeText}>${this.innerHTML}</${this.tagName}>`;
    }
}

const documentStub = {
    getElementById: () => null,
    createElement: tagName => new FakeElement(tagName),
    addEventListener: () => {},
};

const citationSource = fs.readFileSync(process.argv[2], 'utf8')
    .replace(/^\s*import\s[^;]*;\s*$/gm, '')
    .replace(/^export /gm, '');

const citationSandbox = {
    module: { exports: {} },
    console,
    document: documentStub,
    window: { addEventListener: () => {} },
};
vm.runInNewContext(citationSource + '\nmodule.exports = { parseCitations };', citationSandbox);
const { parseCitations } = citationSandbox.module.exports;

const markedSandbox = { module: { exports: {} }, console };
markedSandbox.exports = markedSandbox.module.exports;
vm.runInNewContext(fs.readFileSync(process.argv[4], 'utf8'), markedSandbox);
const markedParse = markedSandbox.module.exports.parse;

const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const results = {};
Object.keys(cases).forEach(name => {
    const citationMarkdown = parseCitations(cases[name]);
    results[name] = {
        markdown: citationMarkdown,
        html: markedParse(citationMarkdown),
    };
});
process.stdout.write(JSON.stringify(results));
"""


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def run_citation_harness():
    """Execute the production parseCitations() and return markdown/HTML per case."""
    node_executable = shutil.which('node')
    if not node_executable:
        return None

    with tempfile.TemporaryDirectory() as temp_dir:
        harness_path = os.path.join(temp_dir, 'citation_harness.cjs')
        cases_path = os.path.join(temp_dir, 'cases.json')

        with open(harness_path, 'w', encoding='utf-8') as harness_file:
            harness_file.write(NODE_HARNESS)
        with open(cases_path, 'w', encoding='utf-8') as cases_file:
            json.dump(TEST_CASES, cases_file)

        completed = subprocess.run(
            [node_executable, harness_path, CITATIONS_FILE, cases_path, MARKED_FILE],
            capture_output=True,
            text=True,
            timeout=60,
        )

    assert completed.returncode == 0, f'Citation harness failed: {completed.stderr}'
    return json.loads(completed.stdout)


def test_reported_message_keeps_its_paragraph_breaks():
    """The reported message must keep every block separate after citation parsing."""
    print('🔍 Testing reported citation message keeps paragraph breaks...')

    try:
        results = run_citation_harness()
        if results is None:
            print('⚠️  Node.js not available, skipping executable citation parsing check')
            return True

        markdown = results['reported']['markdown']
        html = results['reported']['html']

        collapsed_forms = [
            ')Admins can configure',
            ')For best results',
            ')Thank you, Paul.',
        ]
        for collapsed in collapsed_forms:
            assert collapsed not in markdown, \
                f'Citation swallowed the whitespace before "{collapsed.lstrip(")")}"'

        assert '</a>)\n\nAdmins can configure' in markdown, \
            'Blank line between the citation and the following paragraph was not preserved'
        assert '</a>)\n\nFor best results' in markdown, \
            'Blank line before "For best results" was not preserved'
        assert '</a>)\n\nThank you, Paul.' in markdown, \
            'Blank line before the closing sentence was not preserved'

        assert '<p>Admins can configure the extraction approach' in html, \
            'Follow-on paragraph must render as its own block, not inside the numbered list item'
        assert '<p>For best results, upload clear, readable images.' in html, \
            'Follow-on paragraph must render as its own block, not inside the bullet list item'
        assert '<p>Thank you, Paul.</p>' in html, \
            'Closing sentence must render as its own paragraph'

        assert '<li><strong>Grounded chat:</strong>' in html, \
            'The numbered list item should still render'
        assert 'Admins can configure' not in html.split('</ol>')[0], \
            'The paragraph after the citation must not be absorbed into the numbered list'

        print('✅ Reported citation message paragraph breaks passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_inline_citation_spacing_is_preserved():
    """Inline spacing around citations must survive parsing unchanged."""
    print('🔍 Testing inline citation spacing...')

    try:
        results = run_citation_harness()
        if results is None:
            print('⚠️  Node.js not available, skipping inline citation spacing check')
            return True

        inline_space = results['inline_space']['markdown']
        assert '</a>) and then act.' in inline_space, \
            'A citation followed by more text on the same line must keep its separating space'

        trailing_punctuation = results['trailing_punctuation']['markdown']
        assert trailing_punctuation.endswith('</a>).'), \
            'A citation followed immediately by punctuation must not gain whitespace'

        back_to_back = results['back_to_back']['markdown']
        assert '</a>) (Source: B.pdf' in back_to_back, \
            'Back-to-back citations must keep the space between them'
        assert '</a>)(Source: B.pdf' not in back_to_back, \
            'Back-to-back citations must not collide'

        next_line = results['citation_id_on_next_line']['markdown']
        assert '</a>)\n\nThe next section explains why.' in next_line, \
            'A citation id on the following line must still leave the paragraph break intact'

        print('✅ Inline citation spacing passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_stray_citation_bracket_cleanup_keeps_line_structure():
    """The leftover [#guid] cleanup pass must not consume surrounding newlines."""
    print('🔍 Testing stray citation bracket cleanup...')

    try:
        results = run_citation_harness()
        if results is None:
            print('⚠️  Node.js not available, skipping stray bracket cleanup check')
            return True

        for case_name in (
            'stray_bracket_own_line',
            'stray_bracket_starts_paragraph',
            'stray_bracket_inline',
            'stray_bracket_consecutive',
        ):
            markdown = results[case_name]['markdown']
            assert '[#' not in markdown, \
                f'Leftover citation bracket survived cleanup in {case_name}: {markdown!r}'

        own_line_html = results['stray_bracket_own_line']['html']
        assert '<p>Model used passim style.</p>' in own_line_html, \
            'A bracket alone on its own line must not merge the paragraphs around it'
        assert '<p>Next paragraph.</p>' in own_line_html, \
            'The paragraph after a whole-line bracket must stay separate'

        starts_paragraph = results['stray_bracket_starts_paragraph']
        assert 'Model used passim style. Next paragraph.' not in starts_paragraph['markdown'], \
            'Cleanup must not pull the following paragraph onto the previous line'
        assert '<p>Next paragraph.</p>' in starts_paragraph['html'], \
            'A bracket that starts a paragraph must not destroy the paragraph break'

        inline_markdown = results['stray_bracket_inline']['markdown']
        assert inline_markdown == 'Model used passim style mid sentence.', \
            f'Inline bracket cleanup should leave a single space: {inline_markdown!r}'

        consecutive_markdown = results['stray_bracket_consecutive']['markdown']
        assert consecutive_markdown == 'Model used passim style mid sentence.', \
            f'Consecutive inline brackets should collapse cleanly: {consecutive_markdown!r}'

        print('✅ Stray citation bracket cleanup passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_citation_source_restores_trailing_whitespace():
    """Guard the mechanism in source so the fix cannot be silently reverted."""
    print('🔍 Testing chat-citations.js source guards...')

    try:
        assert_app_version_at_least(
            '0.250.229',
            reason='Inline citation whitespace preservation shipped in 0.250.229.',
        )

        source = read_file_text(CITATIONS_FILE)

        assert 'const trailingWhitespaceMatch = /\\s*$/.exec(bracketSection);' in source, \
            'parseCitations must capture the whitespace consumed by the citation bracket group'
        assert '${linkedPagesText})${trailingWhitespace}`' in source, \
            'parseCitations must re-emit the captured trailing whitespace'

        assert '/\\s*\\[#?[0-9a-f]{8}-' not in source, \
            'The stray bracket cleanup must not consume leading newlines'
        assert 'guidBracketRunPattern' in source, \
            'Stray bracket runs should be cleaned up as a unit'
        assert "`^[ \\\\t]*${guidBracketRunPattern}\\\\r?\\\\n`" in source, \
            'A whole-line stray bracket run should be removed as a complete line'
        assert "`(?:[ \\\\t]*${guidBracketPattern})+`" in source, \
            'The inline stray bracket cleanup should only consume spaces and tabs'

        print('✅ chat-citations.js source guards passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_reported_message_keeps_its_paragraph_breaks,
        test_inline_citation_spacing_is_preserved,
        test_stray_citation_bracket_cleanup_keeps_line_structure,
        test_citation_source_restores_trailing_whitespace,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
