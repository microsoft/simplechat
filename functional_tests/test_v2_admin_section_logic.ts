// test_v2_admin_section_logic.ts
//
// Runtime test for the Admin Settings section shell's presentation decisions.
// Version: 0.261.093
// Implemented in: 0.261.084
// Agents-only visual hierarchy coverage added in: 0.261.093
//
// The V2 admin surface used to render a section as a flat run of controls in declaration
// order. That is fine for Appearance. It is not fine for Knowledge, where Document
// Intelligence alone is around forty controls and the credential the rest depend on was
// simply the last one in the list.
//
// The replacement makes two judgements per section: what status to show, and which groups
// to open. Both are invisible in review and in a screenshot -- a wrong status is a plain
// green chip on a broken connection, and a wrong disclosure rule either buries the next
// step or defeats the point by opening everything. So both are executed here.
//
// Run by test_v2_admin_section_shell.py, which bundles this with the esbuild Vite already
// brings in and executes it under node, skipping when the front-end toolchain is absent.
// Bundling rather than running directly is what resolves the extensionless import between
// adminSections and adminFields.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
    SettingsSection,
    type SettingsSectionProps,
} from '../application/v2_ui/src/components/admin/SettingsSection';
import { agentSectionAppearances } from '../application/v2_ui/src/components/admin/agentSectionAppearance';
import {
    collectRequirements,
    deriveSectionStatus,
    findCapabilityField,
    hasValue,
    shouldGroupStartOpen,
} from '../application/v2_ui/src/lib/adminSections';
import {
    groupFields,
    evaluateDependency,
    type AdminField,
    type AdminFieldDependency,
    type RenderedFieldGroup,
} from '../application/v2_ui/src/lib/adminFields';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

/** The capability switch a section hangs off. */
function capability(key: string, overrides: Partial<AdminField> = {}): AdminField {
    return { key, type: 'switch', label: key, role: 'capability', ...overrides };
}

/** A connection field that must hold a value for the section to be configured. */
function required(key: string, overrides: Partial<AdminField> = {}): AdminField {
    return {
        key,
        type: 'text',
        label: key,
        required: true,
        group: { id: 'connection', label: 'Connection', variant: 'connection' },
        ...overrides,
    };
}

/** A collapsible group, with only the fields the disclosure rule reads. */
function renderedGroup(
    id: string,
    variant?: RenderedFieldGroup['variant'],
): RenderedFieldGroup {
    return { id, variant, fields: [] };
}

check('a section with no capability and nothing required claims no status', () => {
    const fields = [{ key: 'a', type: 'switch', label: 'A' }];
    assert.equal(deriveSectionStatus(fields, {}, {}), 'none');
});

check('a capability that is off reads as off', () => {
    const fields = [capability('enable_thing'), required('thing_endpoint')];
    assert.equal(deriveSectionStatus(fields, { enable_thing: false }, {}), 'off');
});

check('an enabled capability with an empty required field needs configuration', () => {
    const fields = [capability('enable_thing'), required('thing_endpoint')];
    assert.equal(
        deriveSectionStatus(fields, { enable_thing: true, thing_endpoint: '' }, {}),
        'incomplete',
    );
});

check('an enabled capability with every required field filled is ready', () => {
    const fields = [capability('enable_thing'), required('thing_endpoint')];
    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_thing: true, thing_endpoint: 'https://example.invalid' },
            {},
        ),
        'ready',
    );
});

check('a stored credential still reads as configured', () => {
    // The browser is never sent the real secret, only the placeholder. Reading that as
    // missing would tell an administrator to re-enter a key that is already stored.
    const fields = [
        capability('enable_thing'),
        required('thing_endpoint'),
        required('thing_key', { type: 'secret' }),
    ];
    assert.equal(
        deriveSectionStatus(
            fields,
            {
                enable_thing: true,
                thing_endpoint: 'https://example.invalid',
                thing_key: '***REDACTED***',
            },
            {},
        ),
        'ready',
    );
});

check('an unsaved edit is what the status reflects', () => {
    const fields = [capability('enable_thing'), required('thing_endpoint')];
    // Typing an endpoint should clear the warning immediately, not after saving.
    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_thing: true, thing_endpoint: '' },
            { thing_endpoint: 'https://example.invalid' },
        ),
        'ready',
    );
    // And clearing one should raise it immediately.
    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_thing: true, thing_endpoint: 'https://example.invalid' },
            { thing_endpoint: '' },
        ),
        'incomplete',
    );
});

check('an unmet prerequisite outranks every other status', () => {
    // Nothing else the administrator does here takes effect until it is met, so saying
    // "needs configuration" would send them to fix the wrong thing.
    const fields = [
        capability('enable_file_sync'),
        {
            key: 'file_sync_limit',
            type: 'number',
            label: 'Limit',
            requires: { key: 'enable_redis_cache', label: 'Redis Cache', mode: 'warn' },
        },
        required('file_sync_endpoint'),
    ];
    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_file_sync: true, enable_redis_cache: false, file_sync_endpoint: '' },
            {},
        ),
        'blocked',
    );
    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_file_sync: false, enable_redis_cache: false },
            {},
        ),
        'blocked',
    );
});

check('a hidden required field is not counted as missing', () => {
    // The APIM endpoint is required only while APIM is selected. Demanding it while
    // direct access is in use would leave a status nobody can clear.
    const fields = [
        capability('enable_search'),
        required('direct_endpoint', {
            depends_on: { key: 'use_apim', equals: false },
        }),
        required('apim_endpoint', {
            depends_on: { key: 'use_apim', equals: true },
        }),
    ];

    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_search: true, use_apim: false, direct_endpoint: 'https://d.invalid' },
            {},
        ),
        'ready',
    );

    assert.equal(
        deriveSectionStatus(
            fields,
            { enable_search: true, use_apim: true, direct_endpoint: 'https://d.invalid' },
            {},
        ),
        'incomplete',
    );
});

check('a numeric zero counts as a value', () => {
    // A limit of 0 is a deliberate setting, not a blank field.
    assert.equal(hasValue(0), true);
    assert.equal(hasValue(''), false);
    assert.equal(hasValue('   '), false);
    assert.equal(hasValue([]), false);
    assert.equal(hasValue(['a']), true);
    assert.equal(hasValue(null), false);
    assert.equal(hasValue(undefined), false);
});

check('the capability field is found by role, not by position', () => {
    const fields = [
        { key: 'notes', type: 'text', label: 'Notes' },
        capability('enable_thing'),
    ];
    assert.equal(findCapabilityField(fields)?.key, 'enable_thing');
    assert.equal(findCapabilityField([{ key: 'a', type: 'text', label: 'A' }]), undefined);
});

check('a prerequisite shared by several fields is stated once', () => {
    const requirement = { key: 'enable_redis_cache', label: 'Redis Cache' };
    const fields = [
        { key: 'a', type: 'text', label: 'A', requires: requirement },
        { key: 'b', type: 'text', label: 'B', requires: requirement },
        { key: 'c', type: 'text', label: 'C' },
    ];
    assert.equal(collectRequirements(fields).length, 1);
    assert.equal(collectRequirements(fields)[0].key, 'enable_redis_cache');
});

check('fields cluster into declared groups in declared order', () => {
    const fields = [
        { key: 'lead', type: 'switch', label: 'Lead' },
        required('endpoint'),
        {
            key: 'tuning',
            type: 'number',
            label: 'Tuning',
            group: { id: 'behavior', label: 'Behaviour', variant: 'behavior' },
        },
        required('key_value'),
    ];

    const groups = groupFields(fields);
    assert.deepEqual(
        groups.map((group) => group.id),
        ['', 'connection', 'behavior'],
    );
    // A field is filed with its group even when another group intervenes, so the schema
    // can read in the order the section should be worked through.
    assert.deepEqual(
        groups[1].fields.map((field) => field.key),
        ['endpoint', 'key_value'],
    );
    assert.equal(groups[0].fields.length, 1);
});

check('ungrouped fields never collapse', () => {
    const group = renderedGroup('');
    assert.equal(shouldGroupStartOpen(group, 'off', false), true);
    assert.equal(shouldGroupStartOpen(group, 'ready', true), true);
});

check('a group under a disabled capability stays shut', () => {
    assert.equal(shouldGroupStartOpen(renderedGroup('connection', 'connection'), 'off', false), false);
});

check('the connection group opens when it is what needs attention', () => {
    const connection = renderedGroup('connection', 'connection');
    assert.equal(shouldGroupStartOpen(connection, 'incomplete', true), true);
    // Already configured: the section should read as a summary, not a wall of inputs.
    assert.equal(shouldGroupStartOpen(connection, 'ready', true), false);
});

check('non-connection groups stay shut even when the section is incomplete', () => {
    // Tuning knobs are never the next step when the connection is not yet made.
    const variants: RenderedFieldGroup['variant'][] = [
        'behavior',
        'limits',
        'access',
        'advanced',
    ];
    for (const variant of variants) {
        assert.equal(
            shouldGroupStartOpen(renderedGroup(String(variant), variant), 'incomplete', true),
            false,
            `${variant} should not open`,
        );
    }
});

check('dependency evaluation agrees with the server rules', () => {
    // The server enforces min_selected against the same conditions the browser uses to
    // decide what to draw, so a disagreement rejects a save for an invisible control.
    const values: Record<string, unknown> = {
        on: true,
        off: false,
        auth: 'key',
        formCheckbox: 'on',
    };
    const read = (key: string) => values[key];

    assert.equal(evaluateDependency(undefined, read), true);
    assert.equal(evaluateDependency({ key: 'on', equals: true }, read), true);
    assert.equal(evaluateDependency({ key: 'off', equals: true }, read), false);
    assert.equal(evaluateDependency({ key: 'formCheckbox', equals: true }, read), true);
    assert.equal(evaluateDependency({ key: 'auth', equals: 'key' }, read), true);
    assert.equal(evaluateDependency({ key: 'auth', not_equals: 'key' }, read), false);

    const anyOf: AdminFieldDependency = {
        any_of: [
            { key: 'off', equals: true },
            { key: 'on', equals: true },
        ],
    };
    assert.equal(evaluateDependency(anyOf, read), true);

    const allOf: AdminFieldDependency = {
        all_of: [
            { key: 'off', equals: true },
            { key: 'on', equals: true },
        ],
    };
    assert.equal(evaluateDependency(allOf, read), false);
    assert.equal(evaluateDependency({ key: 'missing', equals: false }, read), true);
});

check('distinct presentation is limited to the four Agents sections', () => {
    assert.deepEqual(Object.keys(agentSectionAppearances), [
        'agents-config',
        'agent-toggles-card',
        'agents-page-customization-card',
        'agent-template-approvals-section',
    ]);
    for (const id of ['core-plugin-toggles', 'inbound-mcp-configuration', 'unknown-section']) {
        assert.equal(agentSectionAppearances[id], undefined);
    }
});

function renderSection(
    appearance: SettingsSectionProps['appearance'],
    fields: AdminField[],
    settings: Record<string, unknown>,
    calls: string[],
) {
    return renderToStaticMarkup(createElement(SettingsSection, {
        sectionId: 'agents-config',
        label: 'Agent Runtime',
        groupLabel: 'Agents & Actions',
        tabLabel: 'Agents',
        fields,
        settings,
        draft: {},
        appearance,
        renderField: (field) => {
            calls.push(`field:${field.key}`);
            return createElement('span', { key: field.key }, field.label);
        },
        renderCapability: (field) => {
            calls.push(`capability:${field.key}`);
            return createElement('span', { key: field.key }, field.label);
        },
    }));
}

check('presentation keeps rendering order, capability callbacks, and visibility intact', () => {
    const fields: AdminField[] = [
        capability('enable_semantic_kernel'),
        { key: 'per_user_semantic_kernel', type: 'switch', label: 'Workspace Mode' },
        {
            key: 'merge_global_semantic_kernel_with_workspace',
            type: 'switch',
            label: 'Include global agents',
            depends_on: { key: 'per_user_semantic_kernel', equals: true },
        },
    ];
    const values = { enable_semantic_kernel: true, per_user_semantic_kernel: false };
    const plainCalls: string[] = [];
    const distinctCalls: string[] = [];
    const plain = renderSection(undefined, fields, values, plainCalls);
    const distinct = renderSection(
        agentSectionAppearances['agents-config'], fields, values, distinctCalls,
    );

    assert.deepEqual(distinctCalls, plainCalls);
    assert.deepEqual(distinctCalls, [
        'capability:enable_semantic_kernel',
        'field:per_user_semantic_kernel',
    ]);
    assert.doesNotMatch(plain, /admin-settings-distinct|role="region"/);
    assert.match(distinct, /role="region" aria-labelledby="agents-config-title"/);
    assert.match(distinct, /data-setting-emphasis="primary"/);
    assert.match(distinct, /data-setting-emphasis="dependent"/);
    assert.equal(distinct.includes('Configured'), plain.includes('Configured'));
    assert.doesNotMatch(distinct, /Include global agents/);
});

check('runtime emphasis does not turn an ordinary switch into a capability status', () => {
    const fields = [{ key: 'enable_semantic_kernel', type: 'switch', label: 'Enable Agents' }];
    const calls: string[] = [];
    const markup = renderSection(
        agentSectionAppearances['agents-config'], fields, { enable_semantic_kernel: true }, calls,
    );
    assert.deepEqual(calls, ['field:enable_semantic_kernel']);
    assert.match(markup, /data-setting-emphasis="primary"/);
    assert.doesNotMatch(markup, /Configured|Needs configuration/);
});

check('distinct subsection presentation preserves collapsed defaults and counts', () => {
    const fields = [
        { key: 'agents_page_title', type: 'text', label: 'Hero Title', group: 'Hero' },
        { key: 'agents_page_subtitle', type: 'text', label: 'Hero Subtitle', group: 'Hero' },
    ];
    const calls: string[] = [];
    const markup = renderSection(
        agentSectionAppearances['agents-page-customization-card'], fields, {}, calls,
    );
    assert.match(markup, /aria-expanded="false"/);
    assert.match(markup, /2 settings/);
    assert.doesNotMatch(markup, /Hero Title|Hero Subtitle/);
    assert.deepEqual(calls, []);
});

let passed = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${error.message}`);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
