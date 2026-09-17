// test_v2_content_screening_logic.mjs
// Version: 0.261.114
// Implemented in: 0.261.106
// Empty-policy activation implemented in: 0.261.114
// Exercises real V2 screening availability and Unicode edit boundaries without a browser.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    SCREENING_STATES,
    codePointSelection,
    isScreeningAvailable,
    isScreeningBusy,
    removeCodePointSpan,
    screeningPresentation,
    utf16ToCodePointOffset,
} = await import('../application/v2_ui/src/lib/contentScreening.ts');
const { documentDisplayName } = await import('../application/v2_ui/src/lib/documentExplorer.ts');
const { documentContextItem, PERSONAL_SCOPE } = await import('../application/v2_ui/src/lib/chatContext.ts');
const {
    appendScreeningEdit, previewScreeningEdits, screeningReviewAllows, screeningUnitView,
} = await import('../application/v2_ui/src/lib/contentScreeningReview.ts');
const {
    addScreeningStarterPack, approvedScreeningChoices, editableScreeningPolicy,
    isScreeningPolicyInitialization, newCustomScreeningRule, screeningCatalogChoices, screeningModelCatalog,
    screeningModelIndex, screeningPolicySummary, screeningPolicyTemplates, validateScreeningPolicy,
} = await import('../application/v2_ui/src/lib/contentScreeningPolicy.ts');
const screeningApi = await import('../application/v2_ui/src/lib/contentScreeningApi.ts');

const checks = [];
function check(name, run) {
    checks.push([name, run]);
}

check('genuinely unenrolled legacy documents retain ordinary behavior', () => {
    assert.equal(isScreeningAvailable({}), true);
    assert.equal(isScreeningAvailable({ percentage_complete: 100 }), true);
    assert.equal(isScreeningBusy({}), false);
});

check('malformed markers do not become unenrolled legacy records', () => {
    for (const content_screening of [null, undefined, {}, { available: true }, { state: 'unknown', available: true }]) {
        assert.equal(isScreeningAvailable({ content_screening }), false);
    }
});

check('a disabled capability never releases a persisted hold', () => {
    for (const state of Object.keys(SCREENING_STATES)) {
        const allowed = ['cleared', 'approved_with_flags'].includes(state);
        assert.equal(
            isScreeningAvailable({ content_screening: { state, available: true }, enable_content_screening: false }),
            allowed,
            state,
        );
        assert.equal(isScreeningAvailable({ content_screening: { state, available: false } }), false);
    }
});

check('held metadata does not masquerade as an ordinary extracted title', () => {
    assert.deepEqual(documentDisplayName({
        title: 'Protected extracted title',
        file_name: 'source.txt',
        content_screening: { state: 'pending_review', available: false },
    }), { primary: 'source.txt', secondary: null });
});

check('known held sources cannot become handoff, picker, or mention context', () => {
    assert.throws(() => documentContextItem({
        id: 'held',
        content_screening: { state: 'pending_review', available: false },
    }, PERSONAL_SCOPE), /held for content review/);
    assert.equal(documentContextItem({ id: 'legacy', file_name: 'legacy.txt' }, PERSONAL_SCOPE).id, 'legacy');
});

check('every state has a distinct accessible explanation', () => {
    const labels = Object.keys(SCREENING_STATES).map((state) => {
        const presentation = screeningPresentation({ state });
        assert.ok(presentation.description.length > 10);
        return presentation.label;
    });
    assert.equal(new Set(labels).size, labels.length);
    assert.equal(screeningPresentation(null).tone, 'danger');
    assert.equal(screeningPresentation({ state: '__proto__' }).tone, 'danger');
    assert.equal(isScreeningBusy({ content_screening: { state: 'scanning' } }), true);
    assert.equal(isScreeningBusy({ content_screening: { state: 'scan_error' } }), false);
});

check('UTF16 selections become exact Unicode codepoint spans', () => {
    const text = 'A😀cafe\u0301 中文 👩🏽‍💻 end';
    const start = text.indexOf('中文');
    const end = start + '中文 👩🏽‍💻'.length;
    const span = codePointSelection(text, start, end);
    assert.equal(span.start, Array.from(text.slice(0, start)).length);
    assert.equal(span.end, Array.from(text.slice(0, end)).length);
    assert.equal(span.selected_text, '中文 👩🏽‍💻');
    assert.equal(removeCodePointSpan(text, span.start, span.end), 'A😀cafe\u0301  end');
    assert.equal(utf16ToCodePointOffset(text, text.length), Array.from(text).length);
});

check('ambiguous or invalid boundaries cannot silently retarget an edit', () => {
    assert.throws(() => utf16ToCodePointOffset('A😀B', 2), RangeError);
    for (const offset of [-1, 5, 0.5, NaN, Infinity]) {
        assert.throws(() => utf16ToCodePointOffset('A😀B', offset), RangeError);
    }
    assert.throws(() => codePointSelection('test', 2, 2), RangeError);
    assert.throws(() => codePointSelection('test', 3, 1), RangeError);
    assert.throws(() => removeCodePointSpan('A😀B', 1, 4), RangeError);
    assert.equal(removeCodePointSpan('A😀B', 1, 2), 'AB');
});

const unit = (overrides = {}) => ({
    unit_id: 'unit-1', text: 'A😀B SECRET end', content_hash: 'unit-hash',
    normalization_version: 'canonical-v1', offset_encoding: 'unicode_codepoints',
    locator: {}, location: { label: 'Segment 1' }, ...overrides,
});

check('multiple exact spans preview against original codepoints without shifting later edits', () => {
    const source = unit();
    const first = { type: 'remove_span', unit_id: source.unit_id, content_hash: source.content_hash, start: 1, end: 2, selected_text: '😀' };
    const second = { ...first, start: 4, end: 10, selected_text: 'SECRET' };
    const edits = appendScreeningEdit(appendScreeningEdit([], first), second);
    assert.equal(previewScreeningEdits([source], edits)[0].after, 'AB  end');
    assert.throws(() => appendScreeningEdit(edits, { ...second, start: 5 }), /overlaps/);
    assert.throws(() => appendScreeningEdit(edits, { ...first, content_hash: 'new-hash' }), /source changed/);
    assert.equal(source.text, 'A😀B SECRET end');
});

check('stale hashes, unsupported offsets, and ungrounded text cannot preview a candidate', () => {
    const source = unit();
    const edit = { type: 'remove_span', unit_id: source.unit_id, content_hash: source.content_hash, start: 1, end: 2, selected_text: '😀' };
    assert.throws(() => previewScreeningEdits([unit({ content_hash: 'changed' })], [edit]), /source/);
    assert.throws(() => previewScreeningEdits([unit({ offset_encoding: 'utf16' })], [edit]), /offset/);
    assert.throws(() => previewScreeningEdits([source], [{ ...edit, selected_text: 'B' }]), /no longer matches/);
    assert.throws(() => previewScreeningEdits([], [edit]), /source/);
});

check('physical page removal never treats legacy segments as pages', () => {
    const page = unit({ location: { label: 'Physical page 3', physicalPage: 3 } });
    const figure = unit({ unit_id: 'figure', location: { label: 'Figure on page 3', physicalPage: 3 } });
    const segment = unit({ unit_id: 'segment', location: { label: 'Legacy segment 3' } });
    const edit = { type: 'remove_page', unit_id: 'unit-1', content_hash: 'unit-hash', page: 3 };
    const diffs = previewScreeningEdits([page, figure, segment], [edit]);
    assert.deepEqual(diffs.map((diff) => [diff.unit_id, diff.removed]), [['unit-1', true], ['figure', true]]);
    assert.throws(() => previewScreeningEdits([unit()], [edit]), /physical page/);
});

check('cell edits require structured identity and keep formula-like replacements inert', () => {
    const cell = unit({ location: {
        label: 'Sheet 1 · A2',
        cell: { sheet_index: 0, sheet: 'Sheet 1', row: 2, column: 'A', value_type: 'text' },
    } });
    const edit = { type: 'replace_cell', unit_id: 'unit-1', content_hash: 'unit-hash', replacement: '=HYPERLINK("javascript:test")' };
    assert.equal(previewScreeningEdits([cell], [edit])[0].after, edit.replacement);
    assert.throws(() => previewScreeningEdits([unit()], [edit]), /structured table-cell/);
    assert.equal(previewScreeningEdits([cell], [{ ...edit, type: 'clear_cell' }])[0].after, '');
});

check('bounded evidence windows use whole-unit hashes and global codepoint offsets', () => {
    const first = unit({ text: 'earlier', text_offset: 0, text_total: 200 });
    const window = unit({ text: 'A😀B', text_offset: 100, text_total: 200 });
    const edit = { type: 'remove_span', unit_id: 'unit-1', content_hash: 'unit-hash', start: 101, end: 102, selected_text: '😀' };
    assert.equal(previewScreeningEdits([first, window], [edit])[0].after, 'AB');
    assert.deepEqual(screeningApi.screeningWireEdits([edit], [window], false), [{
        action: 'remove_span', unit_id: 'unit-1', content_hash: 'unit-hash', start: 101, end: 102,
    }]);
});

check('page and clear-cell operations map only to published API edit types', () => {
    const page = unit({ location: { label: 'Page 1', physicalPage: 1 } });
    const imageText = unit({ unit_id: 'image', location: { label: 'Figure', physicalPage: 1 } });
    const edit = { type: 'remove_page', unit_id: 'unit-1', content_hash: 'unit-hash', page: 1 };
    assert.throws(() => screeningApi.screeningWireEdits([edit], [page], false), /complete unit inventory/);
    assert.deepEqual(screeningApi.screeningWireEdits([edit], [page, imageText], true), [
        { action: 'remove_unit', unit_id: 'unit-1', content_hash: 'unit-hash' },
        { action: 'remove_unit', unit_id: 'image', content_hash: 'unit-hash' },
    ]);
    assert.deepEqual(screeningApi.screeningWireEdits([
        { type: 'clear_cell', unit_id: 'unit-1', content_hash: 'unit-hash' },
    ], [page], true), [{ action: 'replace_cell', unit_id: 'unit-1', content_hash: 'unit-hash', text: '' }]);
});

const choices = [
    { endpointId: 'connection-1', modelId: 'model', modelLabel: 'Scanner', connectionName: 'Configured model', provider: 'aoai', deploymentName: 'shared-name' },
    { endpointId: 'connection-2', modelId: 'model', modelLabel: 'Scanner 2', connectionName: 'https://private.example.test', provider: 'new_foundry', deploymentName: 'shared-name' },
];
const policy = () => ({
    enabled: true,
    rules: [{ id: 'rule-1', name: 'Literal test', type: 'literal', enabled: true, values: ['SECRET'], severity: 'high', category: 'sensitive' }],
    ai: {
        enabled: true, model_selection: { endpoint_id: 'connection-2', model_id: 'model' }, instructions: 'Check untrusted text.',
        severity: 'high', category: 'injection', window_unit: 'chunks', window_size: 3, max_characters: 2000, overlap_characters: 100,
    },
    limits: { max_units: 1000, regex_timeout_seconds: 0.05 },
});

const templateCatalog = {
    rules: {
        literal: policy().rules[0],
        regex: { id: 'regex', name: 'Starter regex', type: 'regex', pattern: 'STARTER', enabled: true, severity: 'critical', category: 'credentials' },
        pii: { id: 'pii', name: 'Email addresses', type: 'pii', pii_type: 'email', enabled: true, severity: 'medium', category: 'pii' },
    },
    packs: { first_pack: ['literal', 'regex'], overlapping_pack: ['literal', 'pii'] },
    ai: { starter: 'Flag untrusted instructions.' },
};

check('custom rules use server defaults without copying starter match values', () => {
    const templates = screeningPolicyTemplates(templateCatalog);
    const before = structuredClone(templates);
    const ids = new Set();
    for (const type of ['literal', 'regex', 'pii']) {
        for (let index = 0; index < 2; index += 1) {
            const rule = newCustomScreeningRule(type, templates);
            assert.match(rule.id, /^[a-f0-9]{32}$/);
            assert.ok(!ids.has(rule.id));
            ids.add(rule.id);
            assert.equal(rule.name, '');
            assert.equal(rule.type, type);
            assert.equal(rule.category, templateCatalog.rules[type].category);
            assert.equal(rule.severity, templateCatalog.rules[type].severity);
            assert.equal(rule.enabled, templateCatalog.rules[type].enabled);
            if (type === 'literal') {
                assert.deepEqual(rule.values, []);
                assert.equal(rule.whole_word, false);
            } else if (type === 'regex') {
                assert.equal(rule.pattern, '');
            } else {
                assert.equal(rule.pii_type, '');
            }
            rule.name = 'Changed custom rule';
        }
    }
    assert.deepEqual(templates, before);
    assert.throws(() => newCustomScreeningRule('regex', { ...templates, rules: [] }), /Reload the policy/);
});

check('starter packs retain stable IDs and never duplicate or overwrite existing edits', () => {
    const templates = screeningPolicyTemplates(templateCatalog);
    const draft = addScreeningStarterPack({ ...policy(), rules: [] }, templates.packs[0].rules);
    draft.rules[0].name = 'Reviewed custom name';
    draft.rules[0].values.push('Another phrase');
    draft.rules[0].enabled = false;
    assert.deepEqual(addScreeningStarterPack(draft, templates.packs[0].rules), draft);
    const combined = addScreeningStarterPack(draft, templates.packs[1].rules);
    assert.equal(combined.rules.length, 3);
    assert.deepEqual(combined.rules[0], draft.rules[0]);
    assert.deepEqual(combined.rules.map((rule) => rule.id), ['rule-1', 'regex', 'pii']);
    assert.deepEqual(templates.packs[0].rules[0], templateCatalog.rules.literal);
    assert.equal(templates.packs[0].name, 'first pack');
    assert.deepEqual(templates.piiTypes, [{ value: 'email', label: 'Email addresses' }]);
});

check('configured summaries count active deterministic rules, not model permissions', () => {
    const draft = policy();
    draft.rules.push({ ...draft.rules[0], id: 'disabled', enabled: false });
    draft.ai.enabled = false;
    draft.allowed_models = choices.map((model) => ({ endpoint_id: model.endpointId, model_id: model.modelId }));
    assert.equal(screeningPolicySummary(draft, true).label, '1 deterministic check | AI screening off');
    draft.ai.enabled = true;
    assert.equal(screeningPolicySummary(draft, true).label, '1 deterministic check | 1 AI check');
    draft.enabled = false;
    assert.equal(screeningPolicySummary(draft, true).label, 'Policy disabled');
});

check('workspace summaries never hide inherited AI when local additions are disabled', () => {
    const inherited = { enabled: true, rule_count: 2, ai_check_count: 1 };
    const draft = policy();
    assert.equal(screeningPolicySummary(draft, false, inherited).label, '3 deterministic checks | 2 AI checks');
    draft.ai.enabled = false;
    let summary = screeningPolicySummary(draft, false, inherited);
    assert.equal(summary.label, '3 deterministic checks | 1 AI check');
    assert.match(summary.detail, /1 required administrator AI check/);
    draft.enabled = false;
    summary = screeningPolicySummary(draft, false, inherited);
    assert.equal(summary.label, '2 deterministic checks | 1 AI check');
    assert.equal(screeningPolicySummary(draft, false, { ...inherited, enabled: false }).label, 'Administrator baseline disabled');
    assert.equal(screeningPolicySummary(draft, false, null).label, 'Required baseline unavailable');
});

check('enabled empty and disabled-check policies can be saved without claiming screening coverage', () => {
    const empty = { ...policy(), rules: [], ai: { ...policy().ai, enabled: false } };
    assert.deepEqual(validateScreeningPolicy(empty, []), []);
    const summary = screeningPolicySummary(empty, true);
    assert.equal(summary.label, 'No active checks configured');
    assert.match(summary.detail, /normal processing.*workspace adds checks/);
    assert.match(summary.detail, /Existing holds are unchanged/);
    const disabledChecks = { ...empty, rules: [{ ...policy().rules[0], enabled: false }] };
    assert.deepEqual(validateScreeningPolicy(disabledChecks, []), []);
    assert.equal(screeningPolicySummary(disabledChecks, true).label, summary.label);
    const workspace = screeningPolicySummary(policy(), false, { enabled: true, rule_count: 0, ai_check_count: 0 });
    assert.equal(workspace.label, '1 deterministic check | 1 AI check');
});

check('activation refresh only rebases the same blank baseline, not concurrent configuration edits', () => {
    const before = {
        ...policy(), enabled: false, rules: [], fingerprint: 'before',
        ai: { ...policy().ai, enabled: false, model_selection: { endpoint_id: '', model_id: '' } },
        allowed_models: [],
    };
    const initialized = { ...structuredClone(before), enabled: true, fingerprint: 'initialized' };
    assert.equal(isScreeningPolicyInitialization(before, initialized), true);
    assert.equal(isScreeningPolicyInitialization(before, { ...initialized, rules: policy().rules }), false);
    assert.equal(isScreeningPolicyInitialization(before, {
        ...initialized, ai: { ...initialized.ai, instructions: 'Another administrator changed the criteria.' },
    }), false);
    assert.equal(isScreeningPolicyInitialization(before, {
        ...initialized, allowed_models: [{ endpoint_id: 'approved', model_id: 'scanner' }],
    }), false);
    assert.equal(isScreeningPolicyInitialization(before, {
        ...initialized, limits: { ...initialized.limits, max_units: 42 },
    }), false);
});

check('configured scanner identity includes endpoint and excludes raw endpoint display', () => {
    assert.equal(screeningModelIndex(choices, { endpoint_id: 'connection-2', model_id: 'model' }), '1');
    assert.equal(screeningModelIndex(choices, { endpoint_id: 'missing', model_id: 'model' }), 'unavailable');
    assert.equal(screeningModelIndex(choices, null), '');
    const catalog = screeningModelCatalog(choices);
    assert.equal(catalog[1].endpoint, 'Configured connection');
    assert.ok(!JSON.stringify(catalog).includes('private.example'));
});

check('workspace picker filters only global configured choices by top-level approved references', () => {
    const catalog = [
        { selection_key: 'global::endpoint:one', endpoint_id: 'endpoint', model_id: 'one', display_name: 'Approved model' },
        { selection_key: 'global::endpoint:two', endpoint_id: 'endpoint', model_id: 'two', display_name: 'Other model' },
        { selection_key: 'personal:owner:endpoint:one', endpoint_id: 'endpoint', model_id: 'one', display_name: 'Personal impersonator' },
        { deployment_name: 'legacy-only' },
    ];
    const models = screeningCatalogChoices(catalog);
    assert.equal(models.length, 2);
    const approved = approvedScreeningChoices(models, [{ endpoint_id: 'endpoint', model_id: 'one' }]);
    assert.equal(approved.length, 1);
    assert.equal(approved[0].modelLabel, 'Approved model');
    const raw = { ...policy(), allowed_models: [{ endpoint_id: 'forbidden', model_id: 'substitution' }] };
    assert.equal('allowed_models' in editableScreeningPolicy(raw, false), false);
    assert.deepEqual(editableScreeningPolicy(raw, true).allowed_models, raw.allowed_models);
    assert.equal(raw.allowed_models[0].endpoint_id, 'forbidden');
});

check('policy validation enforces available model and full bounded window parameters', () => {
    assert.deepEqual(validateScreeningPolicy(policy(), choices), []);
    const invalid = policy();
    invalid.ai.overlap_characters = invalid.ai.max_characters;
    invalid.ai.model_selection.endpoint_id = 'removed';
    invalid.ai.window_size = 0;
    invalid.rules[0].values = [];
    assert.equal(validateScreeningPolicy(invalid, choices).length, 4);
    const literalOnly = policy();
    literalOnly.ai.enabled = false;
    literalOnly.ai.model_selection = null;
    assert.deepEqual(validateScreeningPolicy(literalOnly, []), []);
});

check('API helpers bind exact ETags and Unicode spans to the published routes', async () => {
    const original = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, options) => {
        calls.push([url, options]);
        return new Response(JSON.stringify({ etag: 'next', allowed_actions: [] }), {
            status: 200, headers: { 'Content-Type': 'application/json' },
        });
    };
    try {
        await screeningApi.fetchScreeningPolicy({ scope_type: 'group', scope_id: 'a/b' });
        await screeningApi.decideScreeningReview('scan/id', '"revision-1"', 'approve_with_flags', 'Reviewed exceptions');
        await screeningApi.remediateScreeningReview('scan/id', '"revision-1"', [
            { action: 'remove_span', unit_id: 'unit-1', content_hash: 'unit-hash', start: 101, end: 102 },
        ]);
        await screeningApi.startAllWorkspaceScreeningScan();
        await screeningApi.fetchScreeningScans({ scope_type: 'personal', scope_id: 'owner' });
        await screeningApi.changeScreeningScan('job/id', 'resume');
        assert.equal(calls[0][0], '/api/content-screening/policies/group/a%2Fb');
        assert.equal(calls[1][0], '/api/content-screening/reviews/scan%2Fid/decision');
        assert.deepEqual(JSON.parse(calls[1][1].body), {
            etag: '"revision-1"', action: 'approve_with_flags', reason: 'Reviewed exceptions', acknowledge_flags: true,
        });
        assert.equal(JSON.parse(calls[2][1].body).edits[0].start, 101);
        assert.deepEqual(JSON.parse(calls[3][1].body), { all_workspaces: true });
        assert.equal(calls[4][0], '/api/content-screening/scans?page_size=100&scope_type=personal&scope_id=owner');
        assert.equal(calls[5][0], '/api/content-screening/scans/job%2Fid/actions');
        assert.deepEqual(JSON.parse(calls[5][1].body), { action: 'resume' });
        assert.ok(calls.every(([, options]) => options.credentials === 'same-origin'));
    } finally {
        globalThis.fetch = original;
    }
});

check('only server-permitted decisions for a complete exact revision can approve', () => {
    const review = {
        etag: '"review-etag"', state: 'pending_review', outcome: 'findings',
        coverage: { complete: true, units_total: 2 }, candidate_of: null, finding_count: 1,
        allowed_actions: ['approve_clean', 'approve_with_flags', 'reject', 'retry_publication'],
    };
    assert.equal(screeningReviewAllows(review, 'approve_with_flags'), true);
    assert.equal(screeningReviewAllows(review, 'approve_clean'), false);
    assert.equal(screeningReviewAllows({ ...review, outcome: 'pass', candidate_of: 'original', finding_count: 0 }, 'approve_clean'), true);
    assert.equal(screeningReviewAllows({ ...review, outcome: 'pass', candidate_of: 'original' }, 'approve_clean'), false);
    assert.equal(screeningReviewAllows({ ...review, allowed_actions: [], is_admin: true }, 'approve_with_flags'), false);
    assert.equal(screeningReviewAllows({ ...review, coverage: { complete: false } }, 'approve_with_flags'), false);
    for (const outcome of ['error', 'incomplete', null]) {
        assert.equal(screeningReviewAllows({ ...review, outcome }, 'approve_with_flags'), false);
    }
    for (const state of ['pending_scan', 'scan_error', 'incomplete', 'scanning', 'remediating', 'publishing', 'deleting', 'deleted']) {
        assert.equal(screeningReviewAllows({ ...review, state }, 'approve_with_flags'), false);
    }
    assert.equal(screeningReviewAllows({ ...review, etag: '' }, 'reject'), false);
    assert.equal(screeningReviewAllows(review, 'retry_publication'), false);
    assert.equal(screeningReviewAllows({ ...review, state: 'publishing' }, 'retry_publication'), true);
});

check('attachment metadata requires an allowed action and this exact local scan path', () => {
    const original = { url: '/api/content-screening/reviews/scan/downloads/original', file_name: 'original.txt' };
    const review = { id: 'scan', state: 'pending_review', allowed_actions: ['download_original'], downloads: { original } };
    assert.deepEqual(screeningApi.screeningAttachment(review, 'original'), original);
    assert.equal(screeningApi.screeningAttachment({ ...review, allowed_actions: [] }, 'original'), null);
    for (const url of [
        'javascript:alert(1)', 'https://private.invalid/original', '//private.invalid/original',
        '/api/content-screening/reviews/another/downloads/original',
        `${original.url}?source_ref=another`, `${original.url}#fragment`,
    ]) {
        assert.equal(screeningApi.screeningAttachment({
            ...review, downloads: { original: { ...original, url } },
        }, 'original'), null);
    }
});

check('clean downloads require released state and deletion never exposes attachments', () => {
    const clean = { url: '/api/content-screening/reviews/scan/downloads/clean', file_name: 'clean.txt' };
    const review = { id: 'scan', state: 'cleared', allowed_actions: ['download_clean'], downloads: { clean } };
    assert.deepEqual(screeningApi.screeningAttachment(review, 'clean'), clean);
    for (const state of ['pending_scan', 'pending_review', 'scanning', 'scan_error', 'deleting', 'deleted']) {
        assert.equal(screeningApi.screeningAttachment({ ...review, state }, 'clean'), null);
    }
});

check('attachment reads use credentials, no-store, manual redirects, and opaque bytes', async () => {
    const previousFetch = globalThis.fetch;
    const calls = [];
    const review = {
        id: 'scan', state: 'pending_review', allowed_actions: ['download_original'],
        downloads: { original: { url: '/api/content-screening/reviews/scan/downloads/original', file_name: 'original.html' } },
    };
    globalThis.fetch = async (url, options) => {
        calls.push([url, options]);
        return new Response('<script>untrusted</script>', {
            headers: {
                'Content-Type': 'application/octet-stream', 'Content-Disposition': 'attachment; filename="original.html"',
                'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            },
        });
    };
    try {
        const result = await screeningApi.fetchScreeningAttachment(review, 'original');
        assert.equal(new TextDecoder().decode(result.content), '<script>untrusted</script>');
        assert.equal(result.fileName, 'original.html');
        assert.equal(calls[0][0], review.downloads.original.url);
        assert.equal(calls[0][1].credentials, 'same-origin');
        assert.equal(calls[0][1].cache, 'no-store');
        assert.equal(calls[0][1].redirect, 'manual');
    } finally {
        globalThis.fetch = previousFetch;
    }
});

check('inline or cacheable attachment responses fail instead of creating a browser download', async () => {
    const previousFetch = globalThis.fetch;
    const review = {
        id: 'scan', state: 'pending_review', allowed_actions: ['download_original'],
        downloads: { original: { url: '/api/content-screening/reviews/scan/downloads/original', file_name: 'original.html' } },
    };
    try {
        for (const headers of [
            { 'Content-Disposition': 'inline', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' },
            { 'Content-Disposition': 'attachment', 'Cache-Control': 'public', 'X-Content-Type-Options': 'nosniff' },
            { 'Content-Disposition': 'attachment', 'Cache-Control': 'no-store' },
        ]) {
            globalThis.fetch = async () => new Response('untrusted', { headers });
            await assert.rejects(screeningApi.fetchScreeningAttachment(review, 'original'), (error) => error.status === 503);
        }
        globalThis.fetch = async () => new Response('private-provider-diagnostic', { status: 403 });
        await assert.rejects(screeningApi.fetchScreeningAttachment(review, 'original'), (error) =>
            error.status === 403 && !error.message.includes('private-provider-diagnostic'));
    } finally {
        globalThis.fetch = previousFetch;
    }
});

check('locator presentation distinguishes structured cells and rejects bad evidence windows', () => {
    const source = unit({ locator: {
        kind: 'table_formula', sheet_index: 0, sheet: 'Forecast', row: 2, column: 'A', value_type: 'formula',
    } });
    const view = screeningUnitView(source);
    assert.match(view.location.label, /^Table formula/);
    assert.deepEqual(view.location.cell, { sheet_index: 0, sheet: 'Forecast', row: 2, column: 'A', value_type: 'formula' });
    assert.equal(screeningUnitView(unit({ locator: { kind: 'legacy_segment', segment: 7 } })).location.physicalPage, undefined);
    assert.equal(screeningUnitView(unit({ locator: { kind: 'page', page: 7 } })).location.removeUnitLabel, 'Remove extracted page');
    assert.throws(() => screeningUnitView(unit({ text_offset: -1 })), /offset convention/);
    assert.throws(() => screeningUnitView(unit({ text_offset: 100, text_total: 1 })), /offset convention/);
    assert.throws(() => screeningUnitView(unit({ offset_encoding: 'utf16' })), /offset convention/);
});

for (const [name, run] of checks) {
    await run();
    console.log(`PASS ${name}`);
}
console.log(`${checks.length} V2 content screening checks passed.`);
