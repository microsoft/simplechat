// test_v2_admin_agents_logic.mjs
//
// Runtime test for the Admin Settings logic the Agents & Actions rework depends on.
// Version: 0.261.059
// Implemented in: 0.261.059
//
// The companion test, test_v2_admin_agents_parity.py, proves the schema describes the same
// settings the V1 pane submits. That is a source assertion; it says nothing about whether
// the browser then draws them correctly.
//
// These checks execute the decisions that determine what an administrator actually sees,
// each of which fails silently in a way that looks like the feature simply not existing:
//
//   - A dependency chain judged one link at a time puts a control back on screen when an
//     intermediate gate is off. The merge toggle only means something in Workspace Mode,
//     which itself only means something when agents are on.
//   - A section condition read from the settings document alone cannot see mcp_ui_enabled,
//     because that flag comes from an App Service application setting and is never stored.
//   - Orchestration must draw nothing while the server offers a single type. Getting that
//     backwards shows a select with one option and a Max Rounds field the server discards.
//   - A promotion has to carry the exact fields the server keeps, or it is silently
//     rewritten on save.
//
// Run directly with `node functional_tests/test_v2_admin_agents_logic.mjs`. Requires Node
// 22.6 or newer, which strips the TypeScript types so the real modules are imported.

import assert from 'node:assert/strict';
import {
    buildSectionBlocks,
    isFieldVisible,
    isSectionVisible,
} from '../application/v2_ui/src/lib/adminFields.ts';
import {
    agentScopeLabel,
    agentScopeType,
    orchestrationIsSelectable,
    promotableAgents,
    readOrchestrationTypes,
    readPromotedAgents,
    roundsApply,
    toPromotedAgent,
} from '../application/v2_ui/src/lib/adminAgents.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

const field = (key, extra = {}) => ({ key, type: 'switch', label: key, ...extra });

/* ------------------------------ section layout ------------------------------- */

check('ungrouped fields keep their declared order', () => {
    const blocks = buildSectionBlocks([field('a'), field('b')]);
    assert.deepEqual(
        blocks.map((block) => block.field.key),
        ['a', 'b'],
    );
});

check('a group is collected at the position of its first field', () => {
    const blocks = buildSectionBlocks([
        field('gate'),
        field('title', { group: 'Hero' }),
        field('promoted', { group: 'Promoted agents' }),
        field('subtitle', { group: 'Hero' }),
    ]);

    assert.deepEqual(
        blocks.map((block) => (block.kind === 'group' ? block.name : block.field.key)),
        ['gate', 'Hero', 'Promoted agents'],
    );
    assert.deepEqual(
        blocks[1].fields.map((item) => item.key),
        ['title', 'subtitle'],
    );
});

check('only the first field of a group decides whether it starts closed', () => {
    const blocks = buildSectionBlocks([
        field('one', { group: 'Promoted agents', collapsed: true }),
        field('two', { group: 'Promoted agents' }),
    ]);
    assert.equal(blocks[0].collapsed, true);
});

check('a group with no collapsed marker starts open', () => {
    const blocks = buildSectionBlocks([field('one', { group: 'Hero' })]);
    assert.equal(blocks[0].collapsed, false);
});

/* -------------------------------- visibility --------------------------------- */

const AGENTS_ON = { enable_semantic_kernel: true, per_user_semantic_kernel: true };

check('a field with no dependency is always visible', () => {
    assert.equal(isFieldVisible(field('a'), {}, {}), true);
});

check('a chain hides the field when any link is unmet', () => {
    const merge = field('merge', {
        depends_on: [
            { key: 'enable_semantic_kernel', equals: true },
            { key: 'per_user_semantic_kernel', equals: true },
        ],
    });

    assert.equal(isFieldVisible(merge, AGENTS_ON, {}), true);
    assert.equal(
        isFieldVisible(merge, { ...AGENTS_ON, per_user_semantic_kernel: false }, {}),
        false,
        'workspace mode off must hide the merge toggle',
    );
    assert.equal(
        isFieldVisible(merge, { ...AGENTS_ON, enable_semantic_kernel: false }, {}),
        false,
        'agents off must hide it even while workspace mode is on',
    );
});

check('an unsaved edit decides visibility before the stored value does', () => {
    const dependent = field('child', {
        depends_on: { key: 'enable_semantic_kernel', equals: true },
    });
    assert.equal(
        isFieldVisible(dependent, { enable_semantic_kernel: false }, { enable_semantic_kernel: true }),
        true,
    );
});

check('a string dependency compares against a select value', () => {
    const secondary = field('secondary', {
        depends_on: { key: 'agents_page_hero_color_mode', equals: 'two_tone' },
    });
    assert.equal(isFieldVisible(secondary, { agents_page_hero_color_mode: 'two_tone' }, {}), true);
    assert.equal(isFieldVisible(secondary, { agents_page_hero_color_mode: 'single' }, {}), false);
});

check('a string dependency is not satisfied by a truthy non-match', () => {
    const secondary = field('secondary', {
        depends_on: { key: 'mode', equals: 'two_tone' },
    });
    assert.equal(isFieldVisible(secondary, { mode: 'anything' }, {}), false);
});

/* ---------------------------- section conditions ----------------------------- */

check('a section with no condition always applies', () => {
    assert.equal(isSectionVisible(undefined, {}, {}, {}), true);
});

check('a settings-key condition follows the setting', () => {
    assert.equal(isSectionVisible('per_user_semantic_kernel', AGENTS_ON, {}, {}), true);
    assert.equal(isSectionVisible('per_user_semantic_kernel', {}, {}, {}), false);
});

check('a runtime flag is used even though it is absent from settings', () => {
    assert.equal(isSectionVisible('mcp_ui_enabled', {}, {}, { mcp_ui_enabled: true }), true);
    assert.equal(isSectionVisible('mcp_ui_enabled', {}, {}, { mcp_ui_enabled: false }), false);
});

check('a runtime flag wins over a settings key of the same name', () => {
    assert.equal(
        isSectionVisible('mcp_ui_enabled', { mcp_ui_enabled: true }, {}, { mcp_ui_enabled: false }),
        false,
    );
});

check('a section reveals itself from the draft before the save lands', () => {
    assert.equal(
        isSectionVisible('per_user_semantic_kernel', {}, { per_user_semantic_kernel: true }, {}),
        true,
    );
});

/* ------------------------------- orchestration -------------------------------- */

const SINGLE = [{ value: 'default_agent', label: 'Selected Agent', agent_mode: 'single' }];
const MULTI = [...SINGLE, { value: 'group_chat', label: 'Group Chat', agent_mode: 'multi' }];

check('orchestration types drop entries with no value', () => {
    const parsed = readOrchestrationTypes([
        { value: 'default_agent', label: 'Selected Agent' },
        { label: 'nameless' },
        null,
        'not an object',
    ]);
    assert.deepEqual(
        parsed.map((type) => type.value),
        ['default_agent'],
    );
});

check('a non-array orchestration payload yields no types', () => {
    assert.deepEqual(readOrchestrationTypes(undefined), []);
    assert.deepEqual(readOrchestrationTypes({ value: 'default_agent' }), []);
});

check('a label falls back to the value so an option is never blank', () => {
    assert.equal(readOrchestrationTypes([{ value: 'default_agent' }])[0].label, 'default_agent');
});

check('one orchestration type is not a choice, so nothing is drawn', () => {
    assert.equal(orchestrationIsSelectable([]), false);
    assert.equal(
        orchestrationIsSelectable(SINGLE),
        false,
        'today the server returns exactly one type and the card must stay hidden',
    );
    assert.equal(orchestrationIsSelectable(MULTI), true);
});

check('max rounds applies only to a multi-agent type', () => {
    assert.equal(roundsApply(MULTI, 'group_chat'), true);
    assert.equal(roundsApply(MULTI, 'default_agent'), false);
    assert.equal(roundsApply(MULTI, 'unknown'), false);
});

/* --------------------------------- promotions --------------------------------- */

check('scope is classified the same way the classic admin classifies it', () => {
    assert.equal(agentScopeType({ is_group: true }), 'group');
    assert.equal(agentScopeType({ is_global: true }), 'global');
    assert.equal(agentScopeType({ scope_type: 'enterprise' }), 'global');
    assert.equal(agentScopeType({}), 'personal');

    assert.equal(agentScopeLabel({ is_global: true }), 'Enterprise');
    assert.equal(agentScopeLabel({ is_group: true, scope_name: 'Finance' }), 'Finance');
    assert.equal(agentScopeLabel({ is_group: true }), 'Group');
    assert.equal(agentScopeLabel({}), 'Personal');
});

check('a catalog entry without a catalog key cannot be promoted', () => {
    assert.equal(toPromotedAgent({ display_name: 'Nameless' }), null);
});

check('a promotion carries every field the server keeps', () => {
    const promoted = toPromotedAgent({
        catalog_key: 'global:researcher',
        name: 'researcher',
        is_global: true,
    });
    assert.deepEqual(promoted, {
        catalog_key: 'global:researcher',
        display_name: 'researcher',
        scope_label: 'Enterprise',
        scope_type: 'global',
        window: 'both',
    });
});

check('stored promotions drop junk and duplicates and default the window', () => {
    const promoted = readPromotedAgents([
        { catalog_key: 'a', display_name: 'A' },
        { catalog_key: 'a', display_name: 'A again' },
        { display_name: 'no key' },
        null,
        { catalog_key: 'b', display_name: 'B', window: '30_days' },
    ]);

    assert.deepEqual(
        promoted.map((agent) => [agent.catalog_key, agent.window]),
        [
            ['a', 'both'],
            ['b', '30_days'],
        ],
    );
});

check('a non-array stored value reads as no promotions', () => {
    assert.deepEqual(readPromotedAgents(null), []);
    assert.deepEqual(readPromotedAgents('[]'), []);
});

check('an already promoted agent is not offered a second time', () => {
    const candidates = [
        { catalog_key: 'a', display_name: 'A' },
        { catalog_key: 'b', display_name: 'B' },
        { display_name: 'unusable' },
    ];
    const available = promotableAgents(candidates, readPromotedAgents([{ catalog_key: 'a' }]));
    assert.deepEqual(
        available.map((agent) => agent.catalog_key),
        ['b'],
    );
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`ok   ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL ${name}`);
        console.log(`     ${error.message}`);
        failed += 1;
    }
}

console.log(`\n${passed}/${passed + failed} runtime checks passed`);

// Set the code rather than calling process.exit, which can truncate piped stdout
// on Windows and abort the process before this summary is flushed.
process.exitCode = failed > 0 ? 1 : 0;
