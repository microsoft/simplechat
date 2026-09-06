// test_v2_workspace_agent_picker_rendering.mjs
// Version: 0.261.096
// Implemented in: 0.261.096
// Renders native agent controls for attachment permissions and positional-secret feedback.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire, registerHooks } from 'node:module';
import './test_support/tsResolve.mjs';

const require = createRequire(new URL('../application/v2_ui/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

// Reuse the installed UI compiler, without building or writing production assets.
registerHooks({
    load(url, context, nextLoad) {
        if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
        const source = ts.transpileModule(readFileSync(new URL(url), 'utf8'), {
            compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
            fileName: url,
        }).outputText;
        return { format: 'module', source, shortCircuit: true };
    },
});

const { AgentActionPicker } = await import('../application/v2_ui/src/components/workspaceAgents/AgentActionPicker.tsx');
const { AgentIdentityFields } = await import('../application/v2_ui/src/components/workspaceAgents/AgentIdentityFields.tsx');
const { AgentAdvancedFields, agentAdvancedError } = await import('../application/v2_ui/src/components/workspaceAgents/AgentAdvancedFields.tsx');
const { newAgentDraft, applySafeAgentDraft } = await import('../application/v2_ui/src/lib/workspaceAgentAuthoring.ts');
const { toggleAgentAction, updateAgentCapability } = await import('../application/v2_ui/src/lib/workspaceAgentActions.ts');
const { buildEditorWrite, EDITOR_SECRET_MASK } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');

const ordinary = {
    id: 'personal-http', name: 'personal-http', displayName: 'Personal HTTP', type: 'http', description: '',
    endpoint: '', auth: { type: 'user' }, metadata: {}, additionalFields: {},
};
const provided = {
    ...ordinary, id: 'provided-chart', name: 'provided-chart', displayName: 'Provided chart', type: 'chart', is_global: true,
};
const target = { id: 'global-target', scope_type: 'global', scope_id: 'global', name: 'Global target', agent_type: 'local' };
const providedCall = {
    ...provided, id: 'provided-call', name: 'provided-call', displayName: 'Provided call', type: 'agent',
    additionalFields: { target_agent: target },
};
const actions = [ordinary, provided, providedCall];
const draft = {
    ...newAgentDraft(), id: 'local-agent', user_id: 'owner', display_name: 'Caller',
    actions_to_load: ['personal-http', 'provided-chart', 'unlisted-legacy'],
    other_settings: { action_capabilities: { 'provided-chart': { line: false, future: 'keep' } }, custom: { preserved: 0 } },
};
const props = {
    draft, setDraft: () => {}, actions, targets: { targets: [target], can_manage: false, scope_type: 'personal', scope_id: 'owner' },
    loading: false, error: null, targetError: null, ownerId: 'owner', builtinActions: [],
    canCreateActions: false, onRefresh: () => {}, onNewAction: () => {}, readOnly: false,
};
const render = (overrides = {}) => renderToStaticMarkup(React.createElement(AgentActionPicker, { ...props, ...overrides }));
const DISABLED_ATTRIBUTE = /\sdisabled(?:=|(?=[\s/>]))/;
const inputFor = (markup, label) => {
    const input = [...markup.matchAll(/<input\b[^>]*>/g)].map((match) => match[0]).find((tag) => tag.includes(`aria-label="${label}"`));
    assert.ok(input, `Missing checkbox ${label}`);
    return input;
};
const buttonFor = (markup, text) => {
    const button = [...markup.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map((match) => match[0]).find((element) => element.includes(text));
    assert.ok(button, `Missing button ${text}`);
    return button;
};
let checks = 0;
function check(label, run) {
    run();
    checks += 1;
    console.log(`ok ${label}`);
}

check('management disabled hides creation without disabling authorized existing assignments', () => {
    const markup = render();
    assert.doesNotMatch(markup, /New action<\/button>/);
    assert.doesNotMatch(inputFor(markup, 'Assign Personal HTTP'), DISABLED_ATTRIBUTE);
    assert.doesNotMatch(inputFor(markup, 'Assign Provided chart'), DISABLED_ATTRIBUTE);
    assert.doesNotMatch(inputFor(markup, 'Assign Provided call'), DISABLED_ATTRIBUTE);
    assert.doesNotMatch(buttonFor(markup, 'Refresh actions'), DISABLED_ATTRIBUTE);
    assert.match(markup, /unlisted-legacy/);
});
check('rendered internal-name pattern is valid under HTML Unicode-set semantics', () => {
    const options = { settings: {}, agent_types: [{ value: 'local', label: 'Local agent', enabled: true }], model_endpoints: [], builtin_actions: [] };
    const markup = renderToStaticMarkup(React.createElement(AgentIdentityFields, { draft, setDraft: () => {}, options, isNew: false }));
    const pattern = markup.match(/<input\b[^>]*\bpattern="([^"]+)"/)?.[1];
    assert.ok(pattern);
    const expression = new RegExp(`^(?:${pattern})$`, 'v');
    assert.ok(expression.test('Agent-123_name'));
    assert.ok(!expression.test('Agent with spaces'));
    assert.ok(!expression.test('Agent/name'));
});
check('personal Call agent permission is distinct from readable actions and provided calls', () => {
    const personalCall = { ...providedCall, id: 'personal-call', name: 'personal-call', displayName: 'Personal call', is_global: false };
    const available = [...actions, personalCall];
    const denied = render({ actions: available });
    assert.match(inputFor(denied, 'Assign Personal call'), DISABLED_ATTRIBUTE);
    assert.doesNotMatch(inputFor(denied, 'Assign Provided call'), DISABLED_ATTRIBUTE);
    assert.doesNotMatch(inputFor(denied, 'Assign Personal HTTP'), DISABLED_ATTRIBUTE);
    const bound = render({ actions: available, draft: { ...draft, actions_to_load: [...draft.actions_to_load, personalCall.id] } });
    assert.match(inputFor(bound, 'Assign Personal call'), /\schecked=/);
    assert.doesNotMatch(inputFor(bound, 'Assign Personal call'), DISABLED_ATTRIBUTE);
    const allowed = render({ actions: available, targets: { ...props.targets, can_manage: true } });
    assert.doesNotMatch(inputFor(allowed, 'Assign Personal call'), DISABLED_ATTRIBUTE);
});
check('creation is offered only when the management capability is present', () => {
    assert.match(render({ canCreateActions: true }), /New action<\/button>/);
    assert.doesNotMatch(render({ canCreateActions: true, readOnly: true }), /New action<\/button>/);
});
check('optional display names use the machine name in both local and Foundry views', () => {
    const legacy = { ...ordinary, id: 'legacy-action', name: 'LegacyAction' };
    delete legacy.displayName;
    const configured = { ...draft, actions_to_load: [legacy.id] };
    assert.ok(inputFor(render({ actions: [legacy], draft: configured }), 'Assign LegacyAction'));
    const foundry = render({ actions: [legacy], draft: { ...configured, agent_type: 'new_foundry' } });
    assert.match(foundry, /<li>LegacyAction<\/li>/);
    assert.ok(inputFor(render({ actions: [{ ...legacy, name: '' }], draft: configured }), 'Assign Untitled action'));
    assert.equal(legacy.id, 'legacy-action');
    assert.equal(legacy.name, 'LegacyAction');
});
check('capability controls remain editable without action-management permission', () => {
    const markup = render();
    const label = [...markup.matchAll(/<label\b[^>]*>[\s\S]*?<\/label>/g)].map((match) => match[0]).find((element) => element.includes('Line charts'));
    assert.ok(label);
    assert.doesNotMatch(label, DISABLED_ATTRIBUTE);
    let next = toggleAgentAction(draft, providedCall, true, actions);
    next = toggleAgentAction(next, ordinary, false, actions);
    next = updateAgentCapability(next, provided, 'line', true);
    const write = buildEditorWrite(next, { record: draft, revision: 'original', secret_paths: [], read_only: false });
    assert.deepEqual(write.updates.actions_to_load, ['provided-chart', 'unlisted-legacy', 'provided-call']);
    assert.equal(next.other_settings.action_capabilities['provided-chart'].future, 'keep');
    assert.equal(next.other_settings.custom.preserved, 0);
    assert.equal(write.updates.other_settings.action_capabilities['provided-chart'].line, true);
});
check('read-only envelopes and unavailable targets still prevent attachment', () => {
    const readOnly = render({ readOnly: true });
    assert.match(inputFor(readOnly, 'Assign Personal HTTP'), DISABLED_ATTRIBUTE);
    assert.match(inputFor(readOnly, 'Assign Provided call'), DISABLED_ATTRIBUTE);
    const unavailable = render({ targets: { ...props.targets, targets: [] } });
    assert.match(inputFor(unavailable, 'Assign Provided call'), DISABLED_ATTRIBUTE);
    assert.match(unavailable, /no longer available/);
});
check('a failed or pending catalogue cannot authorize a new selection', () => {
    const denied = render({ error: 'Catalogue access denied.' });
    assert.match(denied, /Catalogue access denied/);
    assert.match(inputFor(denied, 'Assign Provided call'), DISABLED_ATTRIBUTE);
    assert.doesNotMatch(inputFor(denied, 'Assign Personal HTTP'), DISABLED_ATTRIBUTE);
    assert.match(inputFor(render({ loading: true }), 'Assign Provided call'), DISABLED_ATTRIBUTE);
});
check('direct self-call detection is unchanged by the creation capability split', () => {
    const self = {
        ...ordinary, id: 'self-call', name: 'self-call', displayName: 'Self call', type: 'agent',
        additionalFields: { target_agent: { id: draft.id, scope_type: 'personal', scope_id: 'owner' } },
    };
    const markup = render({ actions: [...actions, self] });
    assert.match(inputFor(markup, 'Assign Self call'), DISABLED_ATTRIBUTE);
    assert.match(markup, /Direct self-calls are blocked/);
});
check('advanced JSON keeps unrelated editing available and reports rejected positional secret changes', () => {
    const original = {
        record: { ...draft, other_settings: { credentials: [
            { name: 'first', key: EDITOR_SECRET_MASK }, { name: 'second', key: EDITOR_SECRET_MASK },
        ] } },
        revision: 'saved', secret_paths: ['/other_settings/credentials/0/key', '/other_settings/credentials/1/key'], read_only: false,
    };
    const options = { settings: {}, agent_types: [], model_endpoints: [], builtin_actions: [] };
    const initial = renderToStaticMarkup(React.createElement(AgentAdvancedFields, { draft: original.record, original, options, setDraft: () => {} }));
    const textarea = initial.match(/<textarea\b[^>]*id="agent-additional-settings"[^>]*>/)?.[0];
    assert.ok(textarea);
    assert.doesNotMatch(textarea, /\sreadonly(?:=|(?=[\s/>]))/i);
    assert.match(initial, /Array credentials are tied to saved positions/);
    const attempted = structuredClone(original.record);
    attempted.other_settings.credentials.reverse();
    attempted._editor_settings_text = JSON.stringify(attempted.other_settings);
    const rejected = applySafeAgentDraft(original.record, attempted, original);
    assert.match(agentAdvancedError(rejected, original), /saved array positions/);
    assert.deepEqual(rejected.other_settings, original.record.other_settings);
    const markup = renderToStaticMarkup(React.createElement(AgentAdvancedFields, { draft: rejected, original, options, setDraft: () => {} }));
    assert.match(markup, /role="alert"/);
    assert.match(markup, /Reset JSON text to current settings/);
});

console.log(`${checks} real-source agent picker rendering checks passed.`);
