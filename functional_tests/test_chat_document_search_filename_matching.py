#!/usr/bin/env python3
# test_chat_document_search_filename_matching.py
"""
Functional test for chat document search file-name matching and dropdown divider cleanup.
Version: 0.250.210
Implemented in: 0.250.210

This test ensures that the chat grounded-search document picker matches on both the
document title and its file name (anywhere in the string, including multi-word queries
where `_`, `-`, and `.` act as word breaks), renders the file name as muted secondary
text when it differs from the title, and that filtering never leaves orphaned section
separator lines behind in the document, scope, or tags dropdowns.

Refs: https://github.com/microsoft/simplechat/issues/1256
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

CHAT_DOCUMENTS_FILE = os.path.join(
    ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-documents.js',
)
CHAT_SEARCHABLE_SELECT_FILE = os.path.join(
    ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-searchable-select.js',
)
CHAT_ONLOAD_FILE = os.path.join(
    ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-onload.js',
)
CHAT_CSS_FILE = os.path.join(
    ROOT_DIR, 'application', 'single_app', 'static', 'css', 'chats.css',
)

# Runs the production searchable-select logic against a minimal DOM shim so the divider
# and token-matching rules are exercised for real instead of only asserted as source text.
NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(process.argv[2], 'utf8').replace(/^export /gm, '');
const sandbox = { module: { exports: {} }, console };
vm.runInNewContext(
    source + '\nmodule.exports = { updateDropdownStructure, matchesSearchTokens };',
    sandbox
);
const { updateDropdownStructure, matchesSearchTokens } = sandbox.module.exports;

class El {
    constructor(classes, role, label) {
        this.classes = new Set(classes);
        this.role = role || null;
        this.label = label || '';
        this.parent = null;
        this.classList = {
            contains: c => this.classes.has(c),
            add: c => this.classes.add(c),
            remove: c => this.classes.delete(c),
            toggle: (c, force) => { if (force) { this.classes.add(c); } else { this.classes.delete(c); } },
        };
    }
    getAttribute(name) { return name === 'data-search-role' ? this.role : null; }
    get index() { return this.parent.kids.indexOf(this); }
    get nextElementSibling() { return this.parent.kids[this.index + 1] || null; }
    get previousElementSibling() { return this.parent.kids[this.index - 1] || null; }
}

class Container {
    constructor() { this.kids = []; }
    add(el) { el.parent = this; this.kids.push(el); return el; }
    get children() { return this.kids; }
}

function applyFilter(container, term) {
    container.kids
        .filter(kid => kid.classList.contains('dropdown-item'))
        .forEach(item => {
            const alwaysVisible = item.role === 'action';
            const matches = alwaysVisible || matchesSearchTokens(item.label, term);
            item.classList.toggle('d-none', !matches);
        });
    updateDropdownStructure(container);
}

function render(container) {
    return container.kids
        .filter(kid => !kid.classList.contains('d-none'))
        .map(kid => {
            if (kid.classList.contains('dropdown-divider')) { return '---'; }
            if (kid.classList.contains('dropdown-header')) { return '#' + kid.label; }
            return kid.label;
        });
}

const TITLED_DOC = 'Fiscal Overview Quarterly_Report_200_final.pdf [Public] Beta';

function buildDocumentDropdown() {
    const c = new Container();
    c.add(new El(['dropdown-item'], 'action', 'Select All'));
    c.add(new El(['dropdown-header'], null, 'Personal'));
    c.add(new El(['dropdown-item'], 'item', 'Budget Notes Budget_Notes.docx Personal'));
    c.add(new El(['dropdown-divider'], null, ''));
    c.add(new El(['dropdown-header'], null, '[Group] Alpha'));
    c.add(new El(['dropdown-item'], 'item', 'Alpha Charter Alpha_Charter.pdf [Group] Alpha'));
    c.add(new El(['dropdown-divider'], null, ''));
    c.add(new El(['dropdown-header'], null, '[Public] Beta'));
    c.add(new El(['dropdown-item'], 'item', TITLED_DOC));
    return c;
}

function buildTagsDropdown() {
    const c = new Container();
    c.add(new El(['dropdown-item'], 'action', 'Clear All'));
    c.add(new El(['dropdown-divider'], null, ''));
    c.add(new El(['dropdown-item'], 'item', 'finance'));
    c.add(new El(['dropdown-item'], 'item', 'hr'));
    c.add(new El(['dropdown-divider'], null, ''));
    c.add(new El(['dropdown-header'], null, 'Classifications'));
    c.add(new El(['dropdown-item'], 'item', 'Confidential'));
    return c;
}

function buildScopeDropdown() {
    const c = new Container();
    c.add(new El(['dropdown-item'], 'action', 'All'));
    c.add(new El(['dropdown-divider'], null, ''));
    c.add(new El(['dropdown-item'], 'item', 'Personal'));
    c.add(new El(['dropdown-header'], null, 'Groups'));
    c.add(new El(['dropdown-item'], 'item', 'Engineering'));
    c.add(new El(['dropdown-header'], null, 'Public Workspaces'));
    c.add(new El(['dropdown-item'], 'item', 'Marketing WS'));
    return c;
}

const builders = {
    document: buildDocumentDropdown,
    tags: buildTagsDropdown,
    scope: buildScopeDropdown,
};

const cases = [
    ['document', ''],
    ['document', '200'],
    ['document', 'report 200'],
    ['document', 'charter'],
    ['document', 'budget'],
    ['document', 'zzzz'],
    ['tags', ''],
    ['tags', 'confidential'],
    ['tags', 'finance'],
    ['scope', ''],
    ['scope', 'marketing'],
    ['scope', 'zzzz'],
];

const results = {};
cases.forEach(([dropdown, term]) => {
    const container = builders[dropdown]();
    applyFilter(container, term);
    results[dropdown + '|' + term] = render(container);
});

process.stdout.write(JSON.stringify(results));
"""


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_document_descriptor_includes_file_name():
    """Verify the document descriptor carries the file name for search and display."""
    print('🔍 Testing document descriptor file-name wiring...')

    try:
        content = read_file(CHAT_DOCUMENTS_FILE)

        required_snippets = [
            'function getDocumentFileName(documentItem) {',
            "return String((documentItem || {}).file_name || '').trim();",
            'const fileName = getDocumentFileName(documentItem);',
            "const showsFileName = Boolean(fileName) && fileName.toLowerCase() !== displayName.toLowerCase();",
            "searchLabel: [displayName, fileName, sectionLabel].filter(Boolean).join(' '),",
            "secondaryLabel: showsFileName ? fileName : '',",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing document descriptor file-name wiring: {missing}'

        legacy_search_label = "searchLabel: `${getDocumentDisplayName(documentItem)} ${sectionLabel}`"
        assert legacy_search_label not in content, \
            'Document search label must no longer be built from the display name alone'

        print('✅ Document descriptor file-name wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_document_row_renders_file_name_safely():
    """Verify the document row renders a muted file name using textContent."""
    print('🔍 Testing document row file-name rendering...')

    try:
        content = read_file(CHAT_DOCUMENTS_FILE)

        required_snippets = [
            "labelWrapper.classList.add('chat-document-option-text');",
            "primaryLabel.classList.add('chat-document-option-title');",
            'primaryLabel.textContent = doc.label;',
            'if (doc.secondaryLabel) {',
            "secondaryLabel.classList.add('chat-document-option-filename', 'text-muted');",
            'secondaryLabel.textContent = doc.secondaryLabel;',
            "dropdownItem.setAttribute('title', doc.secondaryLabel ? `${doc.label}\\n${doc.secondaryLabel}` : doc.label);",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing document row file-name rendering: {missing}'

        assert 'secondaryLabel.innerHTML' not in content, 'File name must be rendered with textContent'
        assert 'primaryLabel.innerHTML' not in content, 'Document title must be rendered with textContent'

        print('✅ Document row file-name rendering passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_selected_document_label_reads_the_title_span():
    """Verify the button label reads the title span, not the stacked wrapper."""
    print('🔍 Testing selected document button label wiring...')

    try:
        documents_content = read_file(CHAT_DOCUMENTS_FILE)
        onload_content = read_file(CHAT_ONLOAD_FILE)

        for label, content in (('chat-documents.js', documents_content), ('chat-onload.js', onload_content)):
            assert ".querySelector('.chat-document-option-title')" in content, \
                f'{label} must read the document title span for the dropdown button label'
            assert '[data-document-id="${selectedDocumentId}"] span' not in content, \
                f'{label} must not read the first descendant span of a document row'
            assert '[data-document-id="${docIdsToSelect[0]}"] span' not in content, \
                f'{label} must not read the first descendant span of a document row'

        print('✅ Selected document button label wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_shared_search_helper_uses_token_matching():
    """Verify the shared helper exposes and uses normalized token matching."""
    print('🔍 Testing shared search helper token matching...')

    try:
        content = read_file(CHAT_SEARCHABLE_SELECT_FILE)

        required_snippets = [
            'export function normalizeSearchText(value) {',
            'export function matchesSearchTokens(searchText, searchTerm) {',
            'const SEARCH_SEPARATOR_PATTERN = /[_\\-.]+/g;',
            "return normalizedTerm.split(' ').every(token => normalizedText.includes(token));",
            'const matches = keepVisible || matchesSearchTokens(readSearchText(item), searchTerm);',
            'const matches = matchesSearchTokens(optionSearchText, searchTerm);',
            'const searchTerm = normalizeSearchText(rawSearchTerm);',
            'const searchTerm = normalizeSearchText(searchInputEl.value);',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing shared token matching wiring: {missing}'

        assert 'searchText.includes(searchTerm)' not in content, \
            'Filterable dropdown search must not use raw substring matching'
        assert 'optionSearchText.includes(searchTerm)' not in content, \
            'Searchable single select must not use raw substring matching'

        print('✅ Shared search helper token matching passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_divider_visibility_is_section_aware():
    """Verify divider visibility follows section content instead of nearest sibling."""
    print('🔍 Testing section-aware divider visibility...')

    try:
        content = read_file(CHAT_SEARCHABLE_SELECT_FILE)

        required_snippets = [
            "const SEARCH_ROLE_ACTION = 'action';",
            'function isVisibleSectionContent(el) {',
            "&& el.getAttribute('data-search-role') !== SEARCH_ROLE_ACTION;",
            'function findDividerBoundHeader(children, dividerIndex) {',
            'function collapseRedundantDividers(children) {',
            'const boundHeader = findDividerBoundHeader(children, index);',
            'keepDivider = !isHiddenElement(boundHeader) && hasSectionContentBefore;',
            'keepDivider = hasVisibleContentBefore && hasSectionContentAfter;',
            'collapseRedundantDividers(children);',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing section-aware divider wiring: {missing}'

        assert 'let previousVisible = null;' not in content, \
            'Divider visibility must no longer be resolved by scanning for the nearest visible sibling'
        assert 'let nextVisible = null;' not in content, \
            'Divider visibility must no longer be resolved by scanning for the nearest visible sibling'

        print('✅ Section-aware divider visibility passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_document_row_styles_are_defined():
    """Verify the stacked document row styles exist in the chat stylesheet."""
    print('🔍 Testing document row stylesheet rules...')

    try:
        content = read_file(CHAT_CSS_FILE)

        required_snippets = [
            '#document-dropdown-items .dropdown-item .chat-document-option-text {',
            '#document-dropdown-items .dropdown-item .chat-document-option-title,',
            '#document-dropdown-items .dropdown-item .chat-document-option-filename {',
            'flex-direction: column;',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing document row stylesheet rules: {missing}'

        print('✅ Document row stylesheet rules passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_filtered_dropdown_output_has_no_orphaned_dividers():
    """Execute the production filter logic and verify filtered dropdown output."""
    print('🔍 Testing filtered dropdown output against the production logic...')

    node_executable = shutil.which('node')
    if not node_executable:
        print('⚠️  Node.js not available, skipping executable dropdown filter check')
        return True

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness_path = os.path.join(temp_dir, 'dropdown_filter_harness.cjs')
            with open(harness_path, 'w', encoding='utf-8') as harness_file:
                harness_file.write(NODE_HARNESS)

            completed = subprocess.run(
                [node_executable, harness_path, CHAT_SEARCHABLE_SELECT_FILE],
                capture_output=True,
                text=True,
                timeout=60,
            )

        assert completed.returncode == 0, f'Dropdown harness failed: {completed.stderr}'
        results = json.loads(completed.stdout)

        titled_document = 'Fiscal Overview Quarterly_Report_200_final.pdf [Public] Beta'
        expected = {
            'document|': [
                'Select All',
                '#Personal', 'Budget Notes Budget_Notes.docx Personal',
                '---',
                '#[Group] Alpha', 'Alpha Charter Alpha_Charter.pdf [Group] Alpha',
                '---',
                '#[Public] Beta', titled_document,
            ],
            'document|200': ['Select All', '#[Public] Beta', titled_document],
            'document|report 200': ['Select All', '#[Public] Beta', titled_document],
            'document|charter': ['Select All', '#[Group] Alpha', 'Alpha Charter Alpha_Charter.pdf [Group] Alpha'],
            'document|budget': ['Select All', '#Personal', 'Budget Notes Budget_Notes.docx Personal'],
            'document|zzzz': ['Select All'],
            'tags|': ['Clear All', '---', 'finance', 'hr', '---', '#Classifications', 'Confidential'],
            'tags|confidential': ['Clear All', '---', '#Classifications', 'Confidential'],
            'tags|finance': ['Clear All', '---', 'finance'],
            'scope|': ['All', '---', 'Personal', '#Groups', 'Engineering', '#Public Workspaces', 'Marketing WS'],
            'scope|marketing': ['All', '---', '#Public Workspaces', 'Marketing WS'],
            'scope|zzzz': ['All'],
        }

        for key, expected_rows in expected.items():
            assert results.get(key) == expected_rows, \
                f'Unexpected dropdown output for "{key}": {results.get(key)} != {expected_rows}'

        for key, rows in results.items():
            for index in range(1, len(rows)):
                assert not (rows[index] == '---' and rows[index - 1] == '---'), \
                    f'Adjacent separator lines survived filtering for "{key}": {rows}'
            assert rows[0] != '---', f'Leading separator line survived filtering for "{key}": {rows}'
            assert rows[-1] != '---', f'Trailing separator line survived filtering for "{key}": {rows}'

        print('✅ Filtered dropdown output passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_version_bumped_for_chat_document_search_change():
    """Verify config version covers the chat document search change."""
    print('🔍 Testing config version bump...')

    try:
        assert_app_version_at_least("0.250.210")

        print('✅ Config version bump passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_document_descriptor_includes_file_name,
        test_document_row_renders_file_name_safely,
        test_selected_document_label_reads_the_title_span,
        test_shared_search_helper_uses_token_matching,
        test_divider_visibility_is_section_aware,
        test_document_row_styles_are_defined,
        test_filtered_dropdown_output_has_no_orphaned_dividers,
        test_version_bumped_for_chat_document_search_change,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
