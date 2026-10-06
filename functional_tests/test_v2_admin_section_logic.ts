// test_v2_admin_section_logic.ts
//
// Runtime test for the Admin Settings section shell's presentation decisions.
// Version: 0.261.260
// Implemented in: 0.261.084
// Agents-only visual hierarchy coverage added in: 0.261.093
// Every-section presentation and schema-derived hierarchy added in: 0.261.258
// Enhanced extraction engine, open_until_set and on_enable coverage added in: 0.261.260
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
import { EnhancedExtractionEngine } from '../application/v2_ui/src/components/admin/EnhancedExtractionEngine';
import { agentSectionAppearances } from '../application/v2_ui/src/components/admin/agentSectionAppearance';
import {
    ADMIN_NAV_ICONS,
    FALLBACK_SECTION_ICON,
    resolveAdminNavIcon,
} from '../application/v2_ui/src/components/admin/adminSectionIcons';
import {
    collectRequirements,
    computeSectionStatus,
    dependencyKeys,
    deriveFieldHierarchy,
    deriveSectionStatus,
    findCapabilityField,
    hasValue,
    shouldGroupStartOpen,
} from '../application/v2_ui/src/lib/adminSections';
import {
    applyEnableEffect,
    groupFields,
    evaluateDependency,
    SECRET_PLACEHOLDER,
    type AdminField,
    type AdminFieldDependency,
    type RenderedFieldGroup,
} from '../application/v2_ui/src/lib/adminFields';
import { resolveEnhancedExtractionEngine } from '../application/v2_ui/src/lib/enhancedExtraction';

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

/** The Agent Runtime fields, shaped as `admin_settings_fields.py` declares them. */
const AGENT_RUNTIME_FIELDS: AdminField[] = [
    { key: 'enable_semantic_kernel', type: 'switch', label: 'Enable Agents' },
    {
        key: 'per_user_semantic_kernel',
        type: 'switch',
        label: 'Workspace Mode',
        depends_on: { key: 'enable_semantic_kernel', equals: true },
    },
    {
        key: 'merge_global_semantic_kernel_with_workspace',
        type: 'switch',
        label: 'Add Global Agents and Actions to Workspaces',
        depends_on: [
            { key: 'enable_semantic_kernel', equals: true },
            { key: 'per_user_semantic_kernel', equals: true },
        ],
    },
    {
        key: 'enable_multi_agent_orchestration',
        type: 'switch',
        label: 'Multi-Agent Orchestration',
        readonly: true,
        depends_on: { key: 'enable_semantic_kernel', equals: true },
    },
    {
        type: 'component',
        component: 'agent-orchestration',
        label: 'Orchestration',
        depends_on: { key: 'enable_semantic_kernel', equals: true },
    },
];

function emphasisOf(fields: AdminField[]): Record<string, string> {
    return Object.fromEntries(deriveFieldHierarchy(fields).emphasis);
}

check('every navigation icon name resolves, and an unknown one falls back', () => {
    for (const [name, icon] of Object.entries(ADMIN_NAV_ICONS)) {
        assert.ok(name.startsWith('bi-'), `${name} is not a Bootstrap icon name`);
        assert.equal(resolveAdminNavIcon(name), icon);
    }
    assert.equal(resolveAdminNavIcon(undefined), FALLBACK_SECTION_ICON);
    assert.equal(resolveAdminNavIcon('bi-not-a-real-icon'), FALLBACK_SECTION_ICON);
});

check('the derived hierarchy reproduces the Agent Runtime presentation', () => {
    // These are exactly the cues the Agents cards were first drawn with by hand.
    assert.deepEqual(emphasisOf(AGENT_RUNTIME_FIELDS), {
        enable_semantic_kernel: 'primary',
        per_user_semantic_kernel: 'dependent',
        merge_global_semantic_kernel_with_workspace: 'dependent',
    });
    assert.deepEqual(
        [...deriveFieldHierarchy(AGENT_RUNTIME_FIELDS).leads].sort(),
        ['enable_semantic_kernel', 'per_user_semantic_kernel'],
    );
});

check('a leading switch nests the settings that only exist while it is on', () => {
    const fields: AdminField[] = [
        { key: 'enable_ai_notice', type: 'switch', label: 'Show notice' },
        { key: 'ai_notice_message', type: 'textarea', label: 'Text', depends_on: { key: 'enable_ai_notice', equals: true } },
        { key: 'ai_notice_frequency', type: 'select', label: 'Frequency', depends_on: { key: 'enable_ai_notice', equals: true } },
    ];
    assert.deepEqual(emphasisOf(fields), {
        enable_ai_notice: 'primary',
        ai_notice_message: 'dependent',
        ai_notice_frequency: 'dependent',
    });
});

check('a switch leading only its own group is nested under, never promoted', () => {
    // Azure AI Search: routing through APIM is a mode of the connection group, and both
    // branches -- shown while it is on and while it is off -- belong to it.
    const connection = { id: 'connection', label: 'Connection', variant: 'connection' as const };
    const fields: AdminField[] = [
        { key: 'enable_ai_search_apim', type: 'switch', label: 'Route through APIM', group: connection },
        { key: 'apim_endpoint', type: 'text', label: 'APIM endpoint', group: connection, depends_on: { key: 'enable_ai_search_apim', equals: true } },
        { key: 'search_endpoint', type: 'text', label: 'Endpoint', group: connection, depends_on: { key: 'enable_ai_search_apim', equals: false } },
    ];
    assert.deepEqual(emphasisOf(fields), {
        apim_endpoint: 'dependent',
        search_endpoint: 'dependent',
    });
});

check('a capability nests its ungrouped settings but not its groups', () => {
    const notice = { id: 'notice', label: 'User notice' };
    const fields: AdminField[] = [
        capability('enable_web_search'),
        { key: 'web_search_max_results', type: 'number', label: 'Results', depends_on: { key: 'enable_web_search', equals: true } },
        { key: 'web_search_endpoint', ...required('web_search_endpoint'), depends_on: { key: 'enable_web_search', equals: true } },
        { key: 'enable_notice', type: 'switch', label: 'Notice', group: notice, depends_on: { key: 'enable_web_search', equals: true } },
        {
            key: 'notice_text',
            type: 'textarea',
            label: 'Notice text',
            group: notice,
            depends_on: { all_of: [{ key: 'enable_web_search', equals: true }, { key: 'enable_notice', equals: true }] },
        },
    ];
    assert.deepEqual(emphasisOf(fields), {
        enable_web_search: 'primary',
        web_search_max_results: 'dependent',
        notice_text: 'dependent',
    });
});

check('mirrors, components, readouts, and interrupted runs never nest', () => {
    const fields: AdminField[] = [
        { key: 'enable_thing', type: 'switch', label: 'Thing' },
        { key: 'thing_mirror', type: 'switch', label: 'Mirror', readonly: true, depends_on: { key: 'enable_thing', equals: true } },
        { key: 'thing_mode', type: 'select', label: 'Mode', depends_on: { key: 'enable_thing', equals: true } },
        { type: 'status', label: 'Readout', status_source: 'thing', depends_on: { key: 'enable_thing', equals: true } },
    ];
    // The mirror right under the lead interrupts the run, so the select below it is not
    // drawn as nested even though it shares the condition.
    assert.deepEqual(emphasisOf(fields), { enable_thing: 'primary' });
    assert.deepEqual(dependencyKeys({ any_of: [{ key: 'a' }, [{ key: 'b' }, { flag: 'c' }]] } as never), ['a', 'b']);
});

check('a declared status rule wins over the derived one', () => {
    const fields = [capability('enable_thing'), required('thing_endpoint')];
    const rule = { enabled_key: 'enable_declared' };
    assert.equal(computeSectionStatus(fields, { enable_thing: true }, {}, rule), 'off');
    assert.equal(computeSectionStatus(fields, { enable_thing: true }, {}), 'incomplete');
    assert.equal(computeSectionStatus(fields, { enable_thing: true, enable_declared: true }, {}, rule), 'ready');
});

check('only the workspace-permission cues remain declared by hand', () => {
    assert.deepEqual(Object.keys(agentSectionAppearances), ['agent-toggles-card']);
    for (const field of Object.values(agentSectionAppearances['agent-toggles-card']?.fields ?? {})) {
        assert.equal(field?.emphasis, undefined, 'emphasis is derived from the schema now');
        assert.ok(field?.Icon, 'each permission keeps its person or group cue');
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

check('every section renders as a labelled region with its derived emphasis', () => {
    const values = { enable_semantic_kernel: true, per_user_semantic_kernel: false };
    const calls: string[] = [];
    const markup = renderSection(undefined, AGENT_RUNTIME_FIELDS, values, calls);

    // Merge-global hides while Workspace Mode is off; order and visibility are unchanged.
    assert.deepEqual(calls, [
        'field:enable_semantic_kernel',
        'field:per_user_semantic_kernel',
        'field:enable_multi_agent_orchestration',
        'field:undefined',
    ]);
    assert.match(markup, /class="[^"]*admin-settings-distinct/);
    assert.match(markup, /role="region" aria-labelledby="agents-config-title"/);
    assert.match(markup, /id="agents-config-title" tabindex="-1"/);
    assert.match(markup, /data-setting-emphasis="primary"/);
    assert.match(markup, /data-setting-emphasis="dependent"/);
    assert.doesNotMatch(markup, /Add Global Agents/);
    assert.doesNotMatch(markup, /admin-switch-grid/, 'a lead and its nested switch keep their own rows');
});

check('runtime emphasis does not turn an ordinary switch into a capability status', () => {
    const calls: string[] = [];
    const markup = renderSection(undefined, AGENT_RUNTIME_FIELDS, { enable_semantic_kernel: true }, calls);
    assert.match(markup, /data-setting-emphasis="primary"/);
    assert.doesNotMatch(markup, /Configured|Needs configuration/);
});

check('independent switches flow into one grid; an override can drop an emphasis', () => {
    const fields: AdminField[] = [
        { key: 'allow_a', type: 'switch', label: 'Allow A' },
        { key: 'allow_b', type: 'switch', label: 'Allow B' },
        { key: 'allow_c', type: 'switch', label: 'Allow C' },
        { key: 'name', type: 'text', label: 'Name' },
        { key: 'allow_d', type: 'switch', label: 'Allow D' },
    ];
    const calls: string[] = [];
    const markup = renderSection(undefined, fields, {}, calls);
    assert.equal(markup.match(/class="admin-switch-grid"/g)?.length, 1, 'a lone switch after the text field stays on its own row');
    assert.match(markup, /admin-switch-grid"[^>]*><span>Allow A<\/span><span>Allow B<\/span><span>Allow C<\/span><\/div>/);
    assert.deepEqual(calls, ['field:allow_a', 'field:allow_b', 'field:allow_c', 'field:name', 'field:allow_d']);

    const overridden = renderSection(
        { fields: { enable_semantic_kernel: { emphasis: 'none' } } },
        AGENT_RUNTIME_FIELDS,
        { enable_semantic_kernel: true, per_user_semantic_kernel: true },
        [],
    );
    assert.doesNotMatch(overridden, /data-setting-emphasis="primary"/);
    assert.match(overridden, /data-setting-emphasis="dependent"/);
});

check('a precomputed status is shown in place of a derived one', () => {
    const fields = [capability('enable_thing'), required('thing_endpoint')];
    const markup = renderToStaticMarkup(createElement(SettingsSection, {
        sectionId: 'thing-section',
        label: 'Thing',
        groupLabel: 'Group',
        tabLabel: '',
        fields,
        settings: { enable_thing: false },
        draft: {},
        status: 'ready',
        renderField: () => null,
        renderCapability: () => null,
    }));
    assert.match(markup, /Configured/);
    assert.doesNotMatch(markup, />Off</);
});

check('distinct subsection presentation preserves collapsed defaults and counts', () => {
    const fields = [
        { key: 'agents_page_title', type: 'text', label: 'Hero Title', group: 'Hero' },
        { key: 'agents_page_subtitle', type: 'text', label: 'Hero Subtitle', group: 'Hero' },
    ];
    const calls: string[] = [];
    const markup = renderSection(undefined, fields, {}, calls);
    assert.match(markup, /aria-expanded="false"/);
    assert.match(markup, /2 settings/);
    assert.doesNotMatch(markup, /Hero Title|Hero Subtitle/);
    assert.deepEqual(calls, []);
});

// --- Enhanced Extraction ------------------------------------------------------------
//
// Enhanced extraction and the Content Understanding connection behind it are one card,
// led by the switch. These checks hold the three decisions that make that card read as
// one capability: an optional connection opens while it is blank, the engine in force is
// named, and turning the switch on brings the extraction mode with it.

const MODE_KEY = 'document_intelligence_pdf_image_extraction_mode';
const CU_ENDPOINT = 'azure_content_understanding_endpoint';
const CU_AUTH = 'azure_content_understanding_authentication_type';
const CU_KEY = 'azure_content_understanding_key';
const CU_FLAG = { flag: 'content_understanding_supported', equals: true } as const;
const ENHANCED_ON = { key: 'enable_enhanced_extraction', equals: true } as const;

const ENHANCED_SWITCH: AdminField = {
    key: 'enable_enhanced_extraction',
    type: 'switch',
    label: 'Enable Enhanced extraction',
    default: false,
    role: 'capability',
    on_enable: { set: { [MODE_KEY]: 'auto' }, when: { key: MODE_KEY, equals: 'read' } },
};

const MODE_FIELD: AdminField = {
    key: MODE_KEY,
    type: 'select',
    label: 'PDF and Image Extraction Mode',
    default: 'read',
    options: [
        { value: 'read', label: 'Standard' },
        { value: 'layout', label: 'Enhanced' },
        { value: 'auto', label: 'Auto' },
    ],
    depends_on: ENHANCED_ON,
};

const CU_GROUP = {
    id: 'content-understanding',
    label: 'Content Understanding connection',
    variant: 'connection' as const,
};

/** The shape of the declared section, down to the gates each field carries. */
const ENHANCED_EXTRACTION_FIELDS: AdminField[] = [
    ENHANCED_SWITCH,
    MODE_FIELD,
    {
        type: 'component',
        component: 'enhanced-extraction-engine',
        label: 'Extraction engine',
        depends_on: ENHANCED_ON,
    },
    {
        key: CU_ENDPOINT,
        type: 'text',
        label: 'Foundry Endpoint',
        group: { ...CU_GROUP, open_until_set: CU_ENDPOINT },
        depends_on: [ENHANCED_ON, CU_FLAG],
    },
    {
        key: CU_AUTH,
        type: 'select',
        label: 'Authentication Type',
        group: CU_GROUP,
        depends_on: [ENHANCED_ON, CU_FLAG],
    },
    {
        key: 'azure_content_understanding_analyzer_id',
        type: 'text',
        label: 'Document Analyzer',
        group: { id: 'analyzers', label: 'Content Understanding analyzers', variant: 'advanced' },
        depends_on: [ENHANCED_ON, CU_FLAG],
    },
];

function renderEnhancedExtraction(
    settings: Record<string, unknown>,
    runtimeFlags: Record<string, boolean> | undefined,
    calls: string[],
) {
    return renderToStaticMarkup(createElement(SettingsSection, {
        sectionId: 'enhanced-extraction-section',
        label: 'Enhanced Extraction',
        groupLabel: 'Knowledge',
        tabLabel: 'Document Extraction',
        fields: ENHANCED_EXTRACTION_FIELDS,
        settings,
        draft: {},
        runtimeFlags,
        renderField: (field) => {
            calls.push(`field:${field.key ?? field.component}`);
            return createElement('span', { key: field.key ?? field.component }, field.label);
        },
        renderCapability: (field) => {
            calls.push(`capability:${field.key}`);
            return createElement('span', { key: field.key }, field.label);
        },
    }));
}

check('an optional connection opens while the key it waits on is blank', () => {
    const group: RenderedFieldGroup = {
        ...renderedGroup('content-understanding', 'connection'),
        openUntilSet: CU_ENDPOINT,
    };
    const read = (values: Record<string, unknown>) => (key: string) => values[key];

    // Enhanced works without Content Understanding, so the section is ready rather than
    // incomplete; the group still opens because connecting it is the likely next step.
    assert.equal(shouldGroupStartOpen(group, 'ready', true, read({ [CU_ENDPOINT]: '' })), true);
    assert.equal(
        shouldGroupStartOpen(group, 'ready', true, read({ [CU_ENDPOINT]: 'https://cu.example.invalid' })),
        false,
        'a connected service reads as a summary',
    );
    assert.equal(shouldGroupStartOpen(group, 'off', false, read({})), false, 'not while the switch is off');
    assert.equal(shouldGroupStartOpen(group, 'ready', true), false, 'no reader, no guess');
    assert.equal(
        shouldGroupStartOpen({ ...group, collapsed: true }, 'ready', true, read({})),
        false,
        'a group the schema asks to keep closed stays closed',
    );
});

check('open_until_set survives when the field declaring it is not the first one shown', () => {
    const fields: AdminField[] = [
        { key: CU_AUTH, type: 'select', label: 'Authentication Type', group: CU_GROUP },
        { key: CU_ENDPOINT, type: 'text', label: 'Foundry Endpoint', group: { ...CU_GROUP, open_until_set: CU_ENDPOINT } },
    ];
    assert.equal(groupFields(fields)[0].openUntilSet, CU_ENDPOINT);
});

check('the engine is Content Understanding only where it can actually run', () => {
    const read = (values: Record<string, unknown>) => (key: string) => values[key];
    const endpoint = 'https://cu.example.invalid/';

    assert.deepEqual(
        resolveEnhancedExtractionEngine(read({ [CU_ENDPOINT]: endpoint, [CU_KEY]: 'k' }), false),
        { engine: 'document_intelligence', reason: 'unsupported_cloud' },
        'a cloud without the service never uses it, however it is configured',
    );
    assert.deepEqual(
        resolveEnhancedExtractionEngine(read({}), true),
        { engine: 'document_intelligence', reason: 'missing_endpoint' },
    );
    assert.equal(
        resolveEnhancedExtractionEngine(read({ [CU_ENDPOINT]: ' // ' }), true).reason,
        'missing_endpoint',
        'slashes alone are trimmed to nothing on the server too',
    );
    assert.equal(
        resolveEnhancedExtractionEngine(read({ [CU_ENDPOINT]: endpoint, [CU_AUTH]: 'key', [CU_KEY]: '' }), true).reason,
        'missing_key',
    );
    assert.equal(
        resolveEnhancedExtractionEngine(read({ [CU_ENDPOINT]: endpoint, [CU_AUTH]: 'key', [CU_KEY]: SECRET_PLACEHOLDER }), true).engine,
        'content_understanding',
        'a stored key arrives as the placeholder and still counts',
    );
    assert.equal(
        resolveEnhancedExtractionEngine(read({ [CU_ENDPOINT]: endpoint, [CU_AUTH]: 'managed_identity' }), true).engine,
        'content_understanding',
    );
    assert.equal(
        resolveEnhancedExtractionEngine(read({ [CU_ENDPOINT]: endpoint, [CU_AUTH]: 'something-else' }), true).reason,
        'missing_key',
        'the server treats an unrecognised authentication type as key authentication',
    );
});

check('turning Enhanced on moves Standard to Auto, and turning it back off takes that back', () => {
    const index = new Map<string, AdminField>([
        ['enable_enhanced_extraction', ENHANCED_SWITCH],
        [MODE_KEY, MODE_FIELD],
    ]);
    const saved = { enable_enhanced_extraction: false, [MODE_KEY]: 'read' };

    const on = applyEnableEffect({ enable_enhanced_extraction: true }, saved, ENHANCED_SWITCH, true, index);
    assert.equal(on[MODE_KEY], 'auto');

    const off = applyEnableEffect({ ...on, enable_enhanced_extraction: false }, saved, ENHANCED_SWITCH, false, index);
    assert.equal(Object.prototype.hasOwnProperty.call(off, MODE_KEY), false, 'the draft only keeps what was chosen');

    const chosen = applyEnableEffect(
        { enable_enhanced_extraction: true, [MODE_KEY]: 'layout' }, saved, ENHANCED_SWITCH, true, index,
    );
    assert.equal(chosen[MODE_KEY], 'layout', 'an edit already made wins');

    const keptOff = applyEnableEffect(
        { enable_enhanced_extraction: false, [MODE_KEY]: 'layout' }, saved, ENHANCED_SWITCH, false, index,
    );
    assert.equal(keptOff[MODE_KEY], 'layout', 'switching off only takes back the value it set');

    const enhancedSaved = { enable_enhanced_extraction: false, [MODE_KEY]: 'layout' };
    const kept = applyEnableEffect({ enable_enhanced_extraction: true }, enhancedSaved, ENHANCED_SWITCH, true, index);
    assert.equal(Object.prototype.hasOwnProperty.call(kept, MODE_KEY), false, 'a stored Enhanced or Auto choice returns as it was');

    const alreadyOn = applyEnableEffect(
        { enable_enhanced_extraction: true }, { enable_enhanced_extraction: true, [MODE_KEY]: 'read' }, ENHANCED_SWITCH, true, index,
    );
    assert.equal(Object.prototype.hasOwnProperty.call(alreadyOn, MODE_KEY), false, 'only a transition counts, as on the server');

    const fresh = applyEnableEffect({ enable_enhanced_extraction: true }, {}, ENHANCED_SWITCH, true, index);
    assert.equal(fresh[MODE_KEY], 'auto', 'a never-saved mode reads as its declared default');

    const plain: AdminField = { key: 'enable_other', type: 'switch', label: 'Other' };
    const untouched = { enable_other: true };
    assert.equal(applyEnableEffect(untouched, {}, plain, true, index), untouched, 'no effect, no new draft');
});

check('the engine notice names the engine and says when it is not in force yet', () => {
    const connected = renderToStaticMarkup(createElement(EnhancedExtractionEngine, {
        label: 'Extraction engine',
        reading: { engine: 'content_understanding', reason: null },
    }));
    assert.match(connected, /data-engine="content_understanding"/);
    assert.match(connected, /role="status"/);
    assert.match(connected, /Azure AI Content Understanding/);
    assert.match(connected, /descriptions of figures and charts/);
    assert.doesNotMatch(connected, /Takes effect when you save/);

    const fallback = renderToStaticMarkup(createElement(EnhancedExtractionEngine, {
        label: 'Extraction engine',
        reading: { engine: 'document_intelligence', reason: 'missing_endpoint' },
        pending: true,
    }));
    assert.match(fallback, /data-engine="document_intelligence"/);
    assert.match(fallback, /Document Intelligence Layout/);
    assert.match(fallback, /Add a Foundry endpoint/);
    assert.match(fallback, /Takes effect when you save/);

    const keyless = renderToStaticMarkup(createElement(EnhancedExtractionEngine, {
        label: 'Extraction engine',
        reading: { engine: 'document_intelligence', reason: 'missing_key' },
    }));
    assert.match(keyless, /an endpoint but no key/);

    const sovereign = renderToStaticMarkup(createElement(EnhancedExtractionEngine, {
        label: 'Extraction engine',
        reading: { engine: 'document_intelligence', reason: 'unsupported_cloud' },
    }));
    assert.match(sovereign, /not offered in this Azure cloud/);
    assert.match(sovereign, /nothing more to configure/);
});

check('with Enhanced off the card is the switch and nothing that depends on it', () => {
    const calls: string[] = [];
    const markup = renderEnhancedExtraction(
        { enable_enhanced_extraction: false, [MODE_KEY]: 'read', [CU_ENDPOINT]: '' },
        { content_understanding_supported: true },
        calls,
    );
    assert.deepEqual(calls, ['capability:enable_enhanced_extraction']);
    assert.match(markup, />Off</);
    assert.doesNotMatch(markup, /Content Understanding connection|aria-expanded/);
});

check('with Enhanced on and nothing connected, the Content Understanding connection is open', () => {
    const calls: string[] = [];
    const markup = renderEnhancedExtraction(
        { enable_enhanced_extraction: true, [MODE_KEY]: 'auto', [CU_ENDPOINT]: '' },
        { content_understanding_supported: true },
        calls,
    );
    assert.deepEqual(calls, [
        'capability:enable_enhanced_extraction',
        `field:${MODE_KEY}`,
        'field:enhanced-extraction-engine',
        `field:${CU_ENDPOINT}`,
        `field:${CU_AUTH}`,
    ], 'the connection renders; the analyzers stay folded away');
    assert.match(markup, /aria-expanded="true"[^>]*>[\s\S]*?Content Understanding connection/);
    assert.match(markup, /aria-expanded="false"[^>]*>[\s\S]*?Content Understanding analyzers/);
    assert.match(markup, /Configured/, 'Layout is a working setup, so the chip does not cry wolf');
});

check('a connected Content Understanding folds into a summary', () => {
    const calls: string[] = [];
    const markup = renderEnhancedExtraction(
        { enable_enhanced_extraction: true, [MODE_KEY]: 'auto', [CU_ENDPOINT]: 'https://cu.example.invalid' },
        { content_understanding_supported: true },
        calls,
    );
    assert.doesNotMatch(markup, /aria-expanded="true"/);
    assert.deepEqual(calls, [
        'capability:enable_enhanced_extraction',
        `field:${MODE_KEY}`,
        'field:enhanced-extraction-engine',
    ]);
});

check('runtime flags reach the card, so a cloud without the service never shows it', () => {
    const settings = { enable_enhanced_extraction: true, [MODE_KEY]: 'auto', [CU_ENDPOINT]: '' };

    const sovereign = renderEnhancedExtraction(settings, { content_understanding_supported: false }, []);
    assert.doesNotMatch(sovereign, /Content Understanding connection|Content Understanding analyzers/);

    // Without the flags every flag-gated field reads as unmet and is dropped, which is
    // why the page has to hand them to the card rather than only filtering itself.
    const unflagged = renderEnhancedExtraction(settings, undefined, []);
    assert.doesNotMatch(unflagged, /Content Understanding connection/);

    const supported = renderEnhancedExtraction(settings, { content_understanding_supported: true }, []);
    assert.match(supported, /Content Understanding connection/);
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
