// test_v2_admin_agents_logic.mjs
//
// Runtime test for the Admin Settings logic the Agents & Actions rework depends on.
// Version: 0.261.063
// Implemented in: 0.261.061 (agents), 0.261.062 (nested values and mirrored fields),
//                 0.261.063 (runtime flag gates and allowlists)
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
    buildFieldIndex,
    buildSectionBlocks,
    isFieldVisible,
    isSectionVisible,
    readFieldValue,
    readNestedValue,
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
import {
    effectiveEntries,
    readEntryList,
} from '../application/v2_ui/src/lib/adminEntries.ts';

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

/* --------------------------- nested settings values --------------------------- */

const ANALYZE_ENABLED = field('document_action_analyze_enabled', {
    settings_path: ['document_action_capabilities', 'analyze', 'enabled'],
});
const ANALYZE_CHAT_LIMIT = {
    key: 'document_action_analyze_chat_max_documents',
    type: 'number',
    label: 'limit',
    default: 3,
    settings_path: ['document_action_capabilities', 'analyze', 'chat_max_documents'],
    depends_on: { key: 'document_action_analyze_enabled', equals: true },
};

const CAPABILITIES = {
    document_action_capabilities: {
        analyze: { enabled: true, chat_max_documents: 25 },
        comparison: { enabled: false },
    },
};

check('a nested path is walked, and a missing branch reads as undefined', () => {
    assert.equal(
        readNestedValue(CAPABILITIES, ['document_action_capabilities', 'analyze', 'chat_max_documents']),
        25,
    );
    assert.equal(readNestedValue(CAPABILITIES, ['document_action_capabilities', 'missing', 'x']), undefined);
    assert.equal(readNestedValue({ a: 'text' }, ['a', 'b']), undefined);
    assert.equal(readNestedValue({ a: [1] }, ['a', 'b']), undefined);
});

check('a settings_path field reads its stored value, not its flat key', () => {
    assert.equal(readFieldValue(ANALYZE_CHAT_LIMIT, CAPABILITIES, {}), 25);
});

check('a settings_path field falls back to its declared default', () => {
    assert.equal(readFieldValue(ANALYZE_CHAT_LIMIT, {}, {}), 3);
});

check('an unsaved edit is keyed by the flat name even for a nested field', () => {
    assert.equal(
        readFieldValue(ANALYZE_CHAT_LIMIT, CAPABILITIES, {
            document_action_analyze_chat_max_documents: 9,
        }),
        9,
    );
});

check('a gate stored inside a container is resolved through the field index', () => {
    const index = buildFieldIndex({ 'document-action-capabilities-card': [ANALYZE_ENABLED] });

    assert.equal(
        isFieldVisible(ANALYZE_CHAT_LIMIT, CAPABILITIES, {}, index),
        true,
        'the limit must be visible while its container flag is on',
    );
    assert.equal(
        isFieldVisible(
            ANALYZE_CHAT_LIMIT,
            { document_action_capabilities: { analyze: { enabled: false } } },
            {},
            index,
        ),
        false,
    );
});

check('without the index a nested gate cannot be found, which is why it is passed', () => {
    assert.equal(
        isFieldVisible(ANALYZE_CHAT_LIMIT, CAPABILITIES, {}),
        false,
        'this is the failure the field index exists to prevent',
    );
});

/* ------------------------------ runtime flag gates ---------------------------- */

const MCP_FIELD = field('enable_inbound_mcp_server', {
    depends_on: { flag: 'mcp_ui_enabled', equals: true },
});
const MCP_NOTICE = field('notice', {
    depends_on: { flag: 'mcp_ui_enabled', equals: false },
});

check('a runtime flag gate cannot be satisfied from the settings document', () => {
    assert.equal(
        isFieldVisible(MCP_FIELD, { mcp_ui_enabled: true }, {}, undefined, {}),
        false,
        'the flag comes from the App Service, so a settings key of the same name must not count',
    );
    assert.equal(isFieldVisible(MCP_FIELD, {}, {}, undefined, { mcp_ui_enabled: true }), true);
});

check('the disabled notice is the complement of the gated fields', () => {
    const off = { mcp_ui_enabled: false };
    const on = { mcp_ui_enabled: true };

    assert.equal(isFieldVisible(MCP_FIELD, {}, {}, undefined, off), false);
    assert.equal(isFieldVisible(MCP_NOTICE, {}, {}, undefined, off), true);
    assert.equal(isFieldVisible(MCP_FIELD, {}, {}, undefined, on), true);
    assert.equal(isFieldVisible(MCP_NOTICE, {}, {}, undefined, on), false);
});

check('a missing flag reads as off rather than as satisfied', () => {
    assert.equal(isFieldVisible(MCP_FIELD, {}, {}, undefined, undefined), false);
    assert.equal(isFieldVisible(MCP_NOTICE, {}, {}, undefined, undefined), true);
});

check('a flag gate combines with an ordinary key gate', () => {
    const throttle = field('inbound_mcp_rate_limit_window_seconds', {
        depends_on: [
            { flag: 'mcp_ui_enabled', equals: true },
            { key: 'enable_inbound_mcp_rate_limits', equals: true },
        ],
    });
    const flags = { mcp_ui_enabled: true };

    assert.equal(
        isFieldVisible(throttle, { enable_inbound_mcp_rate_limits: true }, {}, undefined, flags),
        true,
    );
    assert.equal(
        isFieldVisible(throttle, { enable_inbound_mcp_rate_limits: false }, {}, undefined, flags),
        false,
    );
    assert.equal(
        isFieldVisible(
            throttle,
            { enable_inbound_mcp_rate_limits: true },
            {},
            undefined,
            { mcp_ui_enabled: false },
        ),
        false,
    );
});

/* -------------------------------- allowlists ---------------------------------- */

check('a stored allowlist reads rows, and a bare string is still accepted', () => {
    assert.deepEqual(readEntryList([{ value: 'a', description: 'A' }, 'b', null]), [
        { value: 'a', description: 'A' },
        { value: 'b', description: '' },
        { value: '', description: '' },
    ]);
    assert.deepEqual(readEntryList(undefined), []);
});

check('the effective allowlist drops blanks and repeats, keeping the first', () => {
    const entries = [
        { value: '  ABC  ', description: ' VS Code ' },
        { value: '', description: 'blank' },
        { value: 'abc', description: 'duplicate' },
        { value: 'def', description: '' },
    ];

    assert.deepEqual(effectiveEntries(entries, true), [
        { value: 'abc', description: 'VS Code' },
        { value: 'def', description: '' },
    ]);
});

check('case is only folded where the server folds it', () => {
    const entries = [{ value: 'VSCode', description: '' }];
    assert.equal(effectiveEntries(entries, false)[0].value, 'VSCode');
    assert.equal(effectiveEntries(entries, true)[0].value, 'vscode');
});

/* ------------------------------ mirrored fields ------------------------------- */
const MIRROR = field('enable_fact_memory_plugin', {
    readonly: true,
    managed_by: 'Chat',
});
const OWNER = field('enable_fact_memory_plugin');

check('the writable declaration owns a key however the sections are ordered', () => {
    const mirrorFirst = buildFieldIndex({ actions: [MIRROR], chat: [OWNER] });
    const ownerFirst = buildFieldIndex({ chat: [OWNER], actions: [MIRROR] });

    assert.equal(mirrorFirst.get('enable_fact_memory_plugin').readonly, undefined);
    assert.equal(ownerFirst.get('enable_fact_memory_plugin').readonly, undefined);
});

check('a key that is only ever mirrored still resolves to the mirror', () => {
    const index = buildFieldIndex({ actions: [field('enable_tabular_processing_plugin', { readonly: true })] });
    assert.equal(index.get('enable_tabular_processing_plugin').readonly, true);
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
