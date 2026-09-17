// test_v2_content_screening_rendering.mjs
// Version: 0.261.108
// Implemented in: 0.261.106
// Execute the actual React components using the installed UI compiler and renderer.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire, registerHooks } from 'node:module';
import './test_support/tsResolve.mjs';

const require = createRequire(new URL('../application/v2_ui/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

registerHooks({
    load(url, context, nextLoad) {
        if (!url.startsWith('file:') || !url.endsWith('.tsx')) {
            return nextLoad(url, context);
        }
        return {
            format: 'module',
            source: ts.transpileModule(readFileSync(new URL(url), 'utf8'), {
                compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
                fileName: url,
            }).outputText,
            shortCircuit: true,
        };
    },
});

const { ProtectedEvidence } = await import('../application/v2_ui/src/components/screening/ProtectedEvidence.tsx');
const { ScreeningDiffPreview } = await import('../application/v2_ui/src/components/screening/ScreeningDiffPreview.tsx');
const { ScreeningScanControls } = await import('../application/v2_ui/src/components/screening/ScreeningScanControls.tsx');
const { ScreeningPolicyFields } = await import('../application/v2_ui/src/components/screening/ScreeningPolicyFields.tsx');
const { ScreeningStatusBadge } = await import('../application/v2_ui/src/components/screening/ScreeningStatusBadge.tsx');
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const sourceText = '<script>window.screeningEvidenceExecuted=true</script><img src=x onerror=alert(1)>😀';
const source = {
    unit_id: 'unit-1', text: sourceText, content_hash: 'hash',
    locator: {}, normalization_version: 'v1', offset_encoding: 'unicode_codepoints',
    text_offset: 100, text_total: 300,
    location: { label: 'Legacy segment 1' },
};
let count = 0;
function check(label, run) {
    run();
    count += 1;
    console.log(`PASS ${label}`);
}

check('protected HTML, formulas and active payloads render only as text', () => {
    const markup = render(ProtectedEvidence, { unit: source, allowedEdits: [], onAddEdit: () => {} });
    assert.doesNotMatch(markup, /<script>|<img src=x|<iframe/);
    assert.match(markup, /&lt;script&gt;/);
    assert.match(markup, /readonly=""/);
    assert.match(markup, /Showing code points 100/);
    assert.doesNotMatch(markup, /Remove source unit|Remove selected span|Replace cell/);
});

check('page actions require physical provenance, not a segment number', () => {
    const props = { unit: source, allowedEdits: ['remove_page', 'remove_unit'], onAddEdit: () => {} };
    assert.doesNotMatch(render(ProtectedEvidence, props), /Remove extracted page/);
    assert.match(render(ProtectedEvidence, {
        ...props, unit: { ...source, location: { label: 'Physical page 7', physicalPage: 7 } },
    }), /Remove extracted page 7/);
});

check('diff previews do not turn before or after content into active markup', () => {
    const markup = render(ScreeningDiffPreview, {
        differences: [{ unit_id: 'unit-1', text_offset: 0, label: '<img src=x>', before: sourceText, after: '<iframe src=x>', removed: false }],
    });
    assert.doesNotMatch(markup, /<script>|<img src=x|<iframe src=x/);
    assert.match(markup, /&lt;iframe src=x&gt;/);
});

check('scan controls cannot infer an all-workspace permission from a role', () => {
    const props = {
        scopes: [{ key: 'personal', label: 'My workspace' }], job: null, busy: false,
        onStart: () => {}, onCancel: () => {}, onResume: () => {}, onRefresh: () => {},
        onRetry: () => {},
    };
    const markup = render(ScreeningScanControls, props);
    assert.doesNotMatch(markup, /Confirm all-workspace scan|<option[^>]*>All workspaces/);
    assert.doesNotMatch(render(ScreeningScanControls, { ...props, scopes: [] }), />Start scan</);
    assert.match(markup, /never releases an existing hold/);
});

check('scan state/counters render verbatim while actions follow the server allowlist', () => {
    const markup = render(ScreeningScanControls, {
        scopes: [], busy: false,
        job: {
            id: 'job-1', state: 'failed', counters: { completed: 7, failed: 2 },
            allowed_actions: ['retry'], enumeration_complete: true, cancel_requested: false,
        },
        onStart: () => {}, onCancel: () => {}, onResume: () => {}, onRetry: () => {}, onRefresh: () => {},
    });
    assert.match(markup, /job-1 · failed/);
    assert.match(markup, /completed/);
    assert.match(markup, /Retry failed items/);
    assert.doesNotMatch(markup, /Cancel scan|Resume scan|Pause scan/);
});

check('busy and approved-with-flags markers have distinct persistent indicators', () => {
    const scanning = render(ScreeningStatusBadge, { summary: { state: 'scanning', available: false, finding_count: 0 } });
    const approved = render(ScreeningStatusBadge, { summary: { state: 'approved_with_flags', available: true, finding_count: 2 } });
    assert.match(scanning, /Held · Scanning/);
    assert.match(scanning, /animate-spin/);
    assert.match(approved, /Approved with flags/);
    assert.match(approved, /2 findings/);
    assert.doesNotMatch(approved, /Held ·/);
});

check('read-only inherited policies offer no rule removal and keep model identity safe', () => {
    const markup = render(ScreeningPolicyFields, {
        policy: {
            enabled: true, rules: [{ id: 'required', name: 'Mandatory rule', type: 'literal', enabled: true, values: [sourceText], severity: 'high', category: 'custom' }],
            ai: { enabled: false, model_selection: null, instructions: sourceText, severity: 'high', category: 'injection', window_unit: 'pages', window_size: 1, max_characters: 3000, overlap_characters: 100 },
            limits: { max_units: 100 },
        },
        templates: { rules: [], packs: [], ai: [], severities: ['high'], piiTypes: [] },
        models: [], disabled: true, onChange: () => {},
    });
    assert.match(markup, /<fieldset disabled=""/);
    assert.doesNotMatch(markup, /Remove rule|<script>/);
    assert.match(markup, /Pages or chunks per window/);
    assert.match(markup, /Boundary overlap characters/);
});

check('AI execution controls are disabled separately from workspace permissions', () => {
    const props = {
        policy: {
            enabled: true, rules: [],
            ai: { enabled: false, model_selection: null, instructions: 'Saved criteria', severity: 'high', category: 'custom', window_unit: 'pages', window_size: 1, max_characters: 3000, overlap_characters: 100 },
            allowed_models: [], limits: {},
        },
        templates: { rules: [], packs: [], ai: [{ id: 'starter', name: 'Starter', instructions: 'Flag instructions' }], severities: ['high'], piiTypes: [] },
        models: [{ endpointId: 'connection', modelId: 'model', modelLabel: 'Workspace scanner', connectionName: 'Saved connection' }],
        baseline: true, onChange: () => {},
    };
    const markup = render(ScreeningPolicyFields, props);
    assert.match(markup, /<fieldset disabled=""[^>]*><legend[^>]*>AI check configuration/);
    assert.match(markup, /<fieldset class="space-y-2"><legend[^>]*>Workspace model permissions/);
    assert.ok(markup.indexOf('Enable AI checks') < markup.indexOf('Scanner model'));
    assert.ok(markup.indexOf('</fieldset>', markup.indexOf('AI check configuration')) < markup.indexOf('Models workspaces may use'));
    assert.match(markup, /permission list, not a list of models to run/);
    assert.match(markup, /Add literal rule/);
    assert.match(markup, /Add regex rule/);
    assert.match(markup, /Add PII rule/);
    assert.doesNotMatch(
        render(ScreeningPolicyFields, { ...props, policy: { ...props.policy, ai: { ...props.policy.ai, enabled: true } } }),
        /<fieldset disabled=""[^>]*><legend[^>]*>AI check configuration/,
    );
});

console.log(`${count} V2 screening rendering checks passed.`);
