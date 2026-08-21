#!/usr/bin/env python3
"""
Functional test for the agent instruction "#" reference tokens.
Version: 0.250.214
Implemented in: 0.250.214

This test ensures that the agent instructions autocomplete produces the
namespaced #action: / #knowledge: token grammar, resolves only the actions and
knowledge selected in the earlier modal steps, and follows the SimpleChat
local-asset and XSS-prevention rules.

Refs: https://github.com/microsoft/simplechat/issues/1257
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = REPO_ROOT / "application" / "single_app" / "static" / "js"
MENTIONS_JS = STATIC_JS / "agent_instruction_mentions.js"
STEPPER_JS = STATIC_JS / "agent_modal_stepper.js"
MODAL_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"

NODE_HARNESS = r"""
import {
    AgentInstructionMentions,
    formatMentionValue,
    buildActionToken,
    buildKnowledgeToken,
    splitTokenSegments,
    locateMentionTrigger
} from %(module_url)s;

const actions = [
    {
        display_name: 'Simple Chat', name: 'simplechat', type: 'simplechat', description: 'SimpleChat operations',
        capabilities: [
            { key: 'create_group', label: 'Create groups' },
            { key: 'add_group_member', label: 'Add users to groups' }
        ]
    },
    { display_name: 'Chart', name: 'chart', type: 'chart', description: 'Charts', capabilities: [{ key: 'bar', label: 'Bar charts' }] },
    { display_name: 'Weather API', name: 'weather', type: 'openapi', description: 'Weather', capabilities: [] }
];

const knowledge = {
    enabled: true,
    sources: [{ scope: 'personal', id: 'personal', name: 'Personal workspace' }],
    documents: [
        { id: '1', title: 'Employee Handbook.pdf', file_name: 'Employee Handbook.pdf', source_name: 'Personal workspace' },
        { id: '2', title: 'Benefits.pdf', file_name: 'Benefits.pdf', source_name: 'Personal workspace' }
    ],
    tags: ['policy'],
    web_sources: [{ url: 'https://example.com/a', mode: 'url_review', mode_label: 'Review URL' }]
};

const mentions = new AgentInstructionMentions({ getActions: () => actions, getKnowledge: () => knowledge });
const emptyMentions = new AgentInstructionMentions({ getActions: () => [], getKnowledge: () => ({ enabled: false }) });
const tokensOf = items => items.map(item => item.token);
const triggerOf = trigger => trigger && {
    level: trigger.level,
    query: trigger.query,
    allowsSpaces: Boolean(trigger.allowsSpaces),
    triggerLength: trigger.triggerLength
};

// The trigger scan runs on every keystroke. A regex able to describe optional
// quoted runs backtracks exponentially, so measure the shapes that used to
// blow up and confirm they stay linear.
function worstTriggerMilliseconds() {
    const samples = [];
    for (const count of [3, 7, 20, 40]) {
        samples.push('Search #knowledge:doc:"Employee Handbook.pdf" ' + '"quoted phrase" '.repeat(count) + 'then #action:"Simple Chat"');
    }
    for (const count of [10, 100, 200]) {
        samples.push('#' + '"x"'.repeat(count) + '#');
    }
    for (const shape of ['"x" ', '"', '#', 'a"b ', '#a:"b" ']) {
        samples.push(shape.repeat(Math.ceil(600 / shape.length)).slice(0, 600));
    }

    let worst = 0;
    for (const sample of samples) {
        const started = process.hrtime.bigint();
        for (let iteration = 0; iteration < 50; iteration += 1) {
            mentions.parseTrigger(sample);
        }
        worst = Math.max(worst, Number(process.hrtime.bigint() - started) / 1e6 / 50);
    }
    return worst;
}

console.log(JSON.stringify({
    quoting: {
        bare: formatMentionValue('create_group'),
        spaced: formatMentionValue('Employee Handbook.pdf'),
        colon: formatMentionValue('https://example.com/a'),
        empty: formatMentionValue('   '),
        innerQuote: formatMentionValue('say "hi"')
    },
    tokens: {
        action: buildActionToken('Chart'),
        actionCapability: buildActionToken('Simple Chat', 'create_group'),
        knowledgeDoc: buildKnowledgeToken('doc', 'Employee Handbook.pdf'),
        knowledgeTag: buildKnowledgeToken('tag', 'policy'),
        emptyValue: buildKnowledgeToken('doc', '')
    },
    segments: {
        quotedColon: splitTokenSegments('knowledge:doc:"Q3: Results.pdf"'),
        plain: splitTokenSegments('action:Chart:bar')
    },
    locate: {
        plain: locateMentionTrigger('hello #act'),
        midWord: locateMentionTrigger('abc#act'),
        previousLine: locateMentionTrigger('#action:Chart\nnow writing prose'),
        quotedSpace: locateMentionTrigger('use #action:"Simple Chat"')
    },
    triggers: {
        namespace: triggerOf(mentions.parseTrigger('hello #')),
        namespaceQuery: triggerOf(mentions.parseTrigger('hello #act')),
        namespaceWithSpace: triggerOf(mentions.parseTrigger('hello # world')),
        midWord: triggerOf(mentions.parseTrigger('abc#act')),
        action: triggerOf(mentions.parseTrigger('use #action:Sim')),
        actionSpaced: triggerOf(mentions.parseTrigger('use #action:Weather AP')),
        capability: triggerOf(mentions.parseTrigger('use #action:"Simple Chat":cre')),
        capabilityEmpty: triggerOf(mentions.parseTrigger('use #action:"Simple Chat":')),
        knowledge: triggerOf(mentions.parseTrigger('see #knowledge:Emp')),
        knowledgeSpaced: triggerOf(mentions.parseTrigger('see #knowledge:Employee Hand')),
        completedDoc: triggerOf(mentions.parseTrigger('see #knowledge:doc:"Employee Handbook.pdf"')),
        completedDocProse: triggerOf(mentions.parseTrigger('see #knowledge:doc:"Employee Handbook.pdf" and then')),
        afterNewline: triggerOf(mentions.parseTrigger('line one\n#')),
        previousLine: triggerOf(mentions.parseTrigger('#action:Chart\nnow writing prose')),
        longLookbehind: triggerOf(mentions.parseTrigger('x'.repeat(2000) + ' #knowledge:Emp')),
        outsideLookbehind: triggerOf(mentions.parseTrigger('#knowledge:' + 'x'.repeat(2000)))
    },
    // Inserting a finished token must not leave an empty menu behind.
    completedTokens: {
        capability: triggerOf(mentions.parseTrigger('Use #action:"Simple Chat":create_group ')),
        capabilityItems: (() => {
            const trigger = mentions.parseTrigger('Use #action:"Simple Chat":create_group ');
            return trigger ? tokensOf(mentions.buildItems(trigger)) : null;
        })(),
        actionNoCapabilities: triggerOf(mentions.parseTrigger('Use #action:"Weather API" ')),
        actionNoCapabilitiesItems: (() => {
            const trigger = mentions.parseTrigger('Use #action:"Weather API" ');
            return trigger ? tokensOf(mentions.buildItems(trigger)) : null;
        })(),
        partialQuotedAction: tokensOf(mentions.buildActionItems('"Simple Ch'))
    },
    worstTriggerMilliseconds: worstTriggerMilliseconds(),
    items: {
        namespaces: tokensOf(mentions.buildNamespaceItems('')),
        actions: tokensOf(mentions.buildActionItems('')),
        actionKeepOpen: mentions.buildActionItems('').map(item => Boolean(item.keepOpen)),
        actionsSpacedQuery: tokensOf(mentions.buildActionItems('Weather AP')),
        capabilities: tokensOf(mentions.buildCapabilityItems('"Simple Chat"', '')),
        capabilitiesUnquotedLookup: tokensOf(mentions.buildCapabilityItems('Simple Chat', 'add')),
        capabilitiesUnknownAction: tokensOf(mentions.buildCapabilityItems('Nope', '')),
        knowledge: tokensOf(mentions.buildKnowledgeItems('')),
        knowledgeBadges: mentions.buildKnowledgeItems('').map(item => item.badge),
        knowledgeSpacedQuery: tokensOf(mentions.buildKnowledgeItems('Employee Hand')),
        knowledgeProseQuery: tokensOf(mentions.buildKnowledgeItems('Employee Handbook.pdf is the policy doc')),
        knowledgeDisabled: tokensOf(emptyMentions.buildKnowledgeItems('')),
        actionsEmpty: tokensOf(emptyMentions.buildActionItems(''))
    }
}));
"""


def read_text(path):
    return path.read_text(encoding="utf-8")


def run_node_harness():
    """Execute the mention module in Node and return its JSON report."""
    node_path = shutil.which("node")
    if not node_path:
        return None

    module_url = json.dumps(MENTIONS_JS.resolve().as_uri())
    harness_source = NODE_HARNESS % {"module_url": module_url}

    with tempfile.TemporaryDirectory() as temp_dir:
        harness_path = Path(temp_dir) / "agent_mentions_harness.mjs"
        harness_path.write_text(harness_source, encoding="utf-8")
        result = subprocess.run(
            [node_path, str(harness_path)],
            capture_output=True,
            check=False,
            text=True,
        )

    if result.returncode != 0:
        raise AssertionError(
            "Expected the mention harness to run cleanly.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    return json.loads(result.stdout.strip().splitlines()[-1])


def test_token_grammar_and_quoting():
    """Tokens must be namespaced and quoted only when the value needs it."""
    print("Testing agent instruction token grammar...")
    try:
        report = run_node_harness()
        if report is None:
            print("Node.js was not found; skipping runtime token grammar checks.")
            return True

        quoting = report["quoting"]
        assert quoting["bare"] == "create_group", quoting
        assert quoting["spaced"] == '"Employee Handbook.pdf"', quoting
        assert quoting["colon"] == '"https://example.com/a"', quoting
        assert quoting["empty"] == "", quoting
        assert quoting["innerQuote"] == '"say \'hi\'"', quoting

        tokens = report["tokens"]
        assert tokens["action"] == "#action:Chart", tokens
        assert tokens["actionCapability"] == '#action:"Simple Chat":create_group', tokens
        assert tokens["knowledgeDoc"] == '#knowledge:doc:"Employee Handbook.pdf"', tokens
        assert tokens["knowledgeTag"] == "#knowledge:tag:policy", tokens
        assert tokens["emptyValue"] == "", tokens

        segments = report["segments"]
        assert segments["quotedColon"] == ["knowledge", "doc", '"Q3: Results.pdf"'], segments
        assert segments["plain"] == ["action", "Chart", "bar"], segments

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trigger_parsing():
    """The "#" trigger must open at word boundaries and close on completed tokens."""
    print("Testing agent instruction trigger parsing...")
    try:
        report = run_node_harness()
        if report is None:
            print("Node.js was not found; skipping runtime trigger parsing checks.")
            return True

        triggers = report["triggers"]

        assert triggers["namespace"] == {
            "level": "namespace", "query": "", "allowsSpaces": False, "triggerLength": 1
        }, triggers["namespace"]
        assert triggers["namespaceQuery"]["level"] == "namespace", triggers["namespaceQuery"]
        assert triggers["midWord"] is None, "A '#' inside a word must not trigger the menu."
        assert triggers["afterNewline"]["level"] == "namespace", triggers["afterNewline"]

        assert triggers["action"] == {
            "level": "action", "query": "Sim", "allowsSpaces": False, "triggerLength": 11
        }, triggers["action"]
        assert triggers["capability"]["level"] == "capability", triggers["capability"]
        assert triggers["capability"]["query"] == "cre", triggers["capability"]
        assert triggers["capabilityEmpty"]["level"] == "capability", triggers["capabilityEmpty"]
        assert triggers["knowledge"] == {
            "level": "knowledge", "query": "Emp", "allowsSpaces": False, "triggerLength": 14
        }, triggers["knowledge"]

        # Document titles and workspace names contain spaces, so the query must
        # be able to span them once a namespace has been typed.
        assert triggers["knowledgeSpaced"]["level"] == "knowledge", triggers["knowledgeSpaced"]
        assert triggers["knowledgeSpaced"]["query"] == "Employee Hand", triggers["knowledgeSpaced"]
        assert triggers["knowledgeSpaced"]["allowsSpaces"] is True, triggers["knowledgeSpaced"]
        assert triggers["actionSpaced"]["query"] == "Weather AP", triggers["actionSpaced"]

        # A completed token is not a query.
        assert triggers["completedDoc"] is None, triggers["completedDoc"]
        assert triggers["completedDocProse"] is None, triggers["completedDocProse"]

        # The lookbehind window keeps typing cheap in long instructions.
        assert triggers["longLookbehind"]["level"] == "knowledge", triggers["longLookbehind"]
        assert triggers["outsideLookbehind"] is None, triggers["outsideLookbehind"]

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_menu_items_resolve_selected_context():
    """The menu must only offer actions and knowledge from the earlier steps."""
    print("Testing agent instruction menu items...")
    try:
        report = run_node_harness()
        if report is None:
            print("Node.js was not found; skipping runtime menu item checks.")
            return True

        items = report["items"]

        assert items["namespaces"] == ["#action:", "#knowledge:"], items["namespaces"]

        assert items["actions"] == [
            "#action:Chart:",
            '#action:"Simple Chat":',
            '#action:"Weather API"',
        ], items["actions"]
        # Only actions with sub-capabilities keep the menu open for a third level.
        assert items["actionKeepOpen"] == [True, True, False], items["actionKeepOpen"]
        assert items["actionsSpacedQuery"] == ['#action:"Weather API"'], items["actionsSpacedQuery"]

        assert items["capabilities"] == [
            '#action:"Simple Chat":create_group',
            '#action:"Simple Chat":add_group_member',
        ], items["capabilities"]
        assert items["capabilitiesUnquotedLookup"] == [
            '#action:"Simple Chat":add_group_member'
        ], items["capabilitiesUnquotedLookup"]
        assert items["capabilitiesUnknownAction"] == [], items["capabilitiesUnknownAction"]

        assert items["knowledge"] == [
            "#knowledge:doc:Benefits.pdf",
            '#knowledge:doc:"Employee Handbook.pdf"',
            '#knowledge:workspace:"Personal workspace"',
            "#knowledge:tag:policy",
            '#knowledge:web:"https://example.com/a"',
        ], items["knowledge"]
        assert items["knowledgeBadges"] == [
            "document", "document", "workspace", "tag", "web"
        ], items["knowledgeBadges"]
        assert items["knowledgeSpacedQuery"] == [
            '#knowledge:doc:"Employee Handbook.pdf"'
        ], items["knowledgeSpacedQuery"]
        # Prose typed after a token must stop resolving so the menu can close.
        assert items["knowledgeProseQuery"] == [], items["knowledgeProseQuery"]

        assert items["knowledgeDisabled"] == [], items["knowledgeDisabled"]
        assert items["actionsEmpty"] == [], items["actionsEmpty"]

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_module_follows_frontend_asset_rules():
    """The autocomplete must be a local asset wired in through a static import."""
    print("Testing agent instruction mention asset rules...")
    try:
        assert MENTIONS_JS.exists(), "Expected static/js/agent_instruction_mentions.js to exist."

        mentions_source = read_text(MENTIONS_JS)
        stepper_source = read_text(STEPPER_JS)

        assert mentions_source.startswith("// agent_instruction_mentions.js"), (
            "JavaScript files must start with a filename comment."
        )

        assert 'import { AgentInstructionMentions, buildActionToken, buildKnowledgeToken } from "./agent_instruction_mentions.js";' in stepper_source, (
            "agent_modal_stepper.js should statically import the local mentions module."
        )

        for forbidden in ("http://", "https://cdn", "unpkg.com", "jsdelivr", "cdnjs", "import("):
            assert forbidden not in mentions_source, (
                f"Found forbidden remote/dynamic asset reference {forbidden!r} in the mentions module."
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_menu_rendering_is_xss_safe():
    """Untrusted labels must never reach innerHTML, and visibility must use d-none."""
    print("Testing agent instruction menu rendering safety...")
    try:
        mentions_source = read_text(MENTIONS_JS)
        stepper_source = read_text(STEPPER_JS)
        template_source = read_text(MODAL_TEMPLATE)

        assert "innerHTML" not in mentions_source, (
            "The mentions module must build DOM nodes with textContent, not innerHTML."
        )
        assert ".textContent = item.label" in mentions_source, (
            "Menu item labels should be assigned with textContent."
        )

        assert "display:none" not in mentions_source.replace(" ", ""), (
            "Use Bootstrap's d-none class instead of display:none."
        )
        assert "classList.add('d-none')" in mentions_source, (
            "The menu should be hidden with the d-none class."
        )

        # The reference panel renders action and document names supplied by users.
        panel_start = stepper_source.index("renderInstructionsContextPanel()")
        panel_source = stepper_source[panel_start:panel_start + 5000]
        assert "innerHTML" not in panel_source, (
            "The Selected Actions & Knowledge panel must not use innerHTML."
        )

        assert ".agent-mention-menu {" in template_source, (
            "Expected local menu styles in the agent modal template."
        )
        assert ".agent-instructions-context-item {" in template_source, (
            "Expected local reference panel styles in the agent modal template."
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_drilldown_is_synchronous():
    """Selecting a namespace or action must advance the menu without a timer.

    Deferring the next level behind setTimeout made the menu blink and left the
    previous level rendered until the timer fired.
    """
    print("Testing agent instruction menu drill-down...")
    try:
        mentions_source = read_text(MENTIONS_JS)

        select_start = mentions_source.index("    select(index) {")
        select_end = mentions_source.index("    handleKeydown(", select_start)
        select_source = mentions_source[select_start:select_end]

        assert "setTimeout" not in select_source, (
            "select() should advance the menu synchronously, not behind a timer."
        )
        assert "this.handleInput(adapter, { allowOpen: true });" in select_source, (
            "select() should re-evaluate the trigger immediately after inserting a partial token."
        )
        assert "if (item.keepOpen) {" in select_source, (
            "Only namespace and action rows should keep the menu open."
        )
        assert "this.close();" in select_source, (
            "Selecting a leaf item should close the menu."
        )

        # Caret moves must not pop the menu open over previously written text.
        assert "{ name: 'cursorActivity', allowOpen: false }" in mentions_source, (
            "CodeMirror cursor movement should only refresh an already open menu."
        )
        assert "{ name: 'changes', allowOpen: true }" in mentions_source, (
            "CodeMirror edits should be able to open the menu, including deletions."
        )
        assert "{ name: 'input', allowOpen: true }" in mentions_source, (
            "Textarea edits should be able to open the menu."
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trigger_scan_is_linear():
    """The trigger scan runs per keystroke and must not backtrack exponentially.

    An earlier regex used `(?:[^\\s#"]|"[^"#]*"?)*`. The optional closing quote
    made a quoted run ambiguous, so ordinary prose containing several quoted
    phrases took seconds per keystroke and froze the tab.
    """
    print("Testing agent instruction trigger scan performance...")
    try:
        mentions_source = read_text(MENTIONS_JS)

        assert 'MENTION_TRIGGER_PATTERN' not in mentions_source, (
            "The ambiguous regex trigger must not come back; use the linear scan."
        )
        assert '"[^"#]*"?' not in mentions_source, (
            "An optional closing quote inside a repeated group causes catastrophic backtracking."
        )
        assert "export function locateMentionTrigger(" in mentions_source, (
            "Expected the linear reverse scan that replaced the trigger regexes."
        )

        report = run_node_harness()
        if report is None:
            print("Node.js was not found; skipping the runtime performance check.")
            return True

        worst_ms = report["worstTriggerMilliseconds"]
        print(f"  worst parseTrigger call: {worst_ms:.4f} ms")
        assert worst_ms < 5.0, (
            f"parseTrigger took {worst_ms:.2f} ms on an adversarial input; expected sub-millisecond."
        )

        locate = report["locate"]
        assert locate["plain"]["body"] == "act", locate["plain"]
        assert locate["midWord"] is None, "A '#' inside a word is not a reference."
        assert locate["previousLine"] is None, "A reference must not span lines."
        assert locate["quotedSpace"]["body"] == 'action:"Simple Chat"', locate["quotedSpace"]
        assert locate["quotedSpace"]["hasUnquotedWhitespace"] is False, locate["quotedSpace"]

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_completed_token_does_not_reopen_empty_menu():
    """Finishing a token must close the menu, not re-render it with no items."""
    print("Testing agent instruction completed-token handling...")
    try:
        report = run_node_harness()
        if report is None:
            print("Node.js was not found; skipping the completed-token checks.")
            return True

        completed = report["completedTokens"]

        # A quoted action name used to make the strict pattern swallow the
        # trailing space, so the menu reopened showing "no capabilities".
        assert completed["capability"] is None or completed["capabilityItems"] == [], (
            f"Inserting a capability token should not leave an open menu: {completed}"
        )
        assert completed["actionNoCapabilities"] is None or completed["actionNoCapabilitiesItems"] == [], (
            f"Inserting an action token should not leave an open menu: {completed}"
        )
        if completed["capability"] is not None:
            assert completed["capability"]["allowsSpaces"] is True, (
                "A trailing space must be recognised so the empty-result guard can close the menu."
            )

        # Partially typed quoted names must still resolve while the author types.
        assert completed["partialQuotedAction"] == ['#action:"Simple Chat":'], (
            completed["partialQuotedAction"]
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cleanup_and_open_gating():
    """destroy() must fully unwind, and caret-only events must not open the menu."""
    print("Testing agent instruction cleanup and open gating...")
    try:
        mentions_source = read_text(MENTIONS_JS)

        # handleInput must actually accept the flag every caller passes.
        assert "handleInput(adapter, { allowOpen = true } = {})" in mentions_source, (
            "handleInput must accept the allowOpen option, or caret-only events will open the menu."
        )
        assert "if (!allowOpen && !isOpenForAdapter) {" in mentions_source, (
            "handleInput should skip opening when only the caret moved."
        )

        # destroy() destructured names that attachAdapter never stored, so it
        # threw and left every listener bound.
        destroy_start = mentions_source.index("    destroy() {\n        this.close();")
        destroy_source = mentions_source[destroy_start:destroy_start + 900]
        assert "inputHandlers.forEach(({ name, handler }) => adapter.off(name, handler));" in destroy_source, (
            "destroy() must unbind the handlers attachAdapter actually stored."
        )
        assert "inputEvents" not in destroy_source, (
            "destroy() must not reference a field attachAdapter never stores."
        )
        assert "releaseAttachmentFlag()" in destroy_source, (
            "destroy() must clear the attach guard so the module can be re-attached."
        )
        assert "inputHandlers" in mentions_source[mentions_source.index("attachAdapter(adapter"):], (
            "attachAdapter must store the input handlers it binds."
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_module_parses_with_node():
    """Verify Node can parse the mentions module."""
    print("Testing agent instruction mentions module syntax with Node.js...")
    try:
        node_path = shutil.which("node")
        if not node_path:
            print("Node.js was not found; skipping the syntax check.")
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            module_copy = Path(temp_dir) / "agent_instruction_mentions.mjs"
            module_copy.write_text(read_text(MENTIONS_JS), encoding="utf-8")
            result = subprocess.run(
                [node_path, "--check", str(module_copy)],
                capture_output=True,
                check=False,
                text=True,
            )

        if result.returncode != 0:
            raise AssertionError(
                "Expected agent_instruction_mentions.js to parse cleanly. "
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least(
        "0.250.214",
        reason="Agent instruction reference tokens landed in 0.250.214.",
    )

    tests = [
        test_token_grammar_and_quoting,
        test_trigger_parsing,
        test_menu_items_resolve_selected_context,
        test_module_follows_frontend_asset_rules,
        test_menu_rendering_is_xss_safe,
        test_drilldown_is_synchronous,
        test_trigger_scan_is_linear,
        test_completed_token_does_not_reopen_empty_menu,
        test_cleanup_and_open_gating,
        test_module_parses_with_node,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
