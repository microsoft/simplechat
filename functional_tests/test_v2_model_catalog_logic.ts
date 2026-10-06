// test_v2_model_catalog_logic.ts
//
// Runtime test for the V2 Model Catalog's behaviour-deciding helpers.
// Version: 0.261.254
// Implemented in: 0.261.254
//
// The V2 catalog is native React now, so the rules that used to live only in the classic
// module -- which profiles a filter keeps, the order they list in, what a saved profile
// contains, which evidence links are safe to render -- are executed here against
// `application/v2_ui/src/lib/modelCatalog.ts`. Run by test_v2_model_catalog_workbench.py,
// which bundles this with esbuild and executes it under node.

import assert from 'node:assert/strict';
import {
    CATALOG_CAPABILITIES,
    DEFAULT_CATALOG_FILTERS,
    activeFilterCount,
    capabilityLabel,
    catalogChanged,
    duplicateProfileForm,
    evidenceLabel,
    filterCatalogProfiles,
    formToPayload,
    formatTokenLimit,
    isLifecycleWarning,
    lifecycleLabel,
    loadCatalogChoices,
    profileToForm,
    profileToPayload,
    publisherLabel,
    publisherOptions,
    readSuitability,
    safeEvidenceUrl,
    type CatalogFilters,
    type CatalogProfile,
} from '../application/v2_ui/src/lib/modelCatalog';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

function profile(id: string, overrides: Partial<CatalogProfile> = {}): CatalogProfile {
    return {
        id,
        displayName: id,
        publisher: 'openai',
        origin: 'built_in',
        summary: '',
        strengths: [],
        limitations: [],
        aliases: [],
        tasks: {},
        capabilities: {},
        sources: [],
        evidence: 'capability_derived',
        archived: false,
        preferences: { favorite: false, priority: 'standard' },
        linked_models: [],
        ...overrides,
    };
}

function filters(overrides: Partial<CatalogFilters> = {}): CatalogFilters {
    return { ...DEFAULT_CATALOG_FILTERS, ...overrides };
}

const linked = [{ connection: 'Primary', connection_id: 'c1', model: 'prod', model_id: 'm1', enabled: true, capabilities: {} }];

const PROFILES: CatalogProfile[] = [
    profile('Zeta', { publisher: 'anthropic', tasks: { coding: 'strong' }, capabilities: { reasoning: true } }),
    profile('Alpha', { aliases: ['alpha-latest'], tasks: { coding: 'suitable' }, linked_models: linked }),
    profile('Beta', { origin: 'custom', publisher: 'Contoso Labs', evidence: 'admin_declared', tasks: { coding: 'unsuitable' } }),
    profile('Gamma', { archived: true, origin: 'custom', publisher: '' }),
    profile('Delta', { preferences: { favorite: true, priority: 'preferred' }, summary: 'Summarizes long reports.' }),
];

const names = (items: CatalogProfile[]) => items.map((item) => item.displayName);

check('the default filters list active profiles, favorites first, then by name', () => {
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters())), ['Delta', 'Alpha', 'Beta', 'Zeta']);
});

check('each filter keeps what the classic module keeps', () => {
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ origin: 'custom' }))), ['Beta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ favorites: true }))), ['Delta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ publisher: 'anthropic' }))), ['Zeta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ capability: 'reasoning' }))), ['Zeta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ availability: 'linked' }))), ['Alpha']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ availability: 'unlinked' }))), ['Delta', 'Beta', 'Zeta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ lifecycle: 'archived' }))), ['Gamma']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ lifecycle: '' }))), ['Delta', 'Alpha', 'Beta', 'Gamma', 'Zeta']);
    // A task filter keeps profiles rated suitable or strong, never unsuitable or unknown.
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ task: 'coding' }))), ['Alpha', 'Zeta']);
});

check('search reads names, aliases, summaries, and the publisher as shown', () => {
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ query: 'ALPHA-latest' }))), ['Alpha']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ query: 'long reports' }))), ['Delta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ query: 'Anthropic' }))), ['Zeta']);
    assert.deepEqual(names(filterCatalogProfiles(PROFILES, filters({ query: 'nothing matches' }))), []);
});

check('applied filters are counted without the search text', () => {
    assert.equal(activeFilterCount(filters()), 0);
    assert.equal(activeFilterCount(filters({ query: 'x' })), 0);
    assert.equal(activeFilterCount(filters({ origin: 'custom', favorites: true, lifecycle: '' })), 3);
});

check('publishers read as names, and custom ones as typed', () => {
    assert.equal(publisherLabel('openai'), 'OpenAI');
    assert.equal(publisherLabel('xai'), 'xAI');
    assert.equal(publisherLabel('blackforestlabs'), 'Black Forest Labs');
    assert.equal(publisherLabel('Contoso Labs'), 'Contoso Labs');
    assert.equal(publisherLabel(''), 'Unspecified publisher');
    assert.deepEqual(publisherOptions(PROFILES), ['anthropic', 'Contoso Labs', 'openai']);
});

check('a saved profile carries only what the server accepts', () => {
    const source = profile('Source', {
        strengths: ['Fast'],
        capabilities: { processesText: true, generatesEmbeddings: true, reasoning: false },
        tasks: { coding: 'strong' },
    });
    const payload = profileToPayload(source);
    assert.deepEqual(Object.keys(payload).sort(), [
        'aliases', 'archived', 'capabilities', 'displayName', 'limitations',
        'publisher', 'sources', 'strengths', 'summary', 'tasks',
    ]);
    assert.deepEqual(payload.capabilities, { processesText: true, reasoning: false });
    payload.strengths.push('Mutated');
    assert.deepEqual(source.strengths, ['Fast'], 'the payload must not share arrays with the profile');
});

check('list fields keep what was typed until saved, then split by line', () => {
    const form = profileToForm(profile('Typed', { strengths: ['One', 'Two'] }));
    assert.equal(form.strengths, 'One\nTwo');
    form.strengths = '  One  \n\n Two \n';
    form.sources = 'https://example.com/a\n';
    const payload = formToPayload(form);
    assert.deepEqual(payload.strengths, ['One', 'Two']);
    assert.deepEqual(payload.sources, ['https://example.com/a']);
});

check('a duplicate starts as a new, unarchived custom profile without aliases', () => {
    const form = duplicateProfileForm(profile('Original', { aliases: ['orig'], archived: true }));
    assert.equal(form.displayName, 'Original custom');
    assert.equal(form.aliases, '');
    assert.equal(form.archived, false);
});

check('only plain HTTPS evidence links are rendered', () => {
    assert.equal(safeEvidenceUrl('https://learn.microsoft.com/azure'), 'https://learn.microsoft.com/azure');
    for (const unsafe of [
        'http://example.com', 'javascript:alert(1)', 'https://user:secret@example.com/',
        'data:text/html,hi', '/relative/path', 'not a url', 42,
    ]) {
        assert.equal(safeEvidenceUrl(unsafe), null, String(unsafe));
    }
});

check('technical facts read plainly', () => {
    assert.equal(formatTokenLimit(128000), `${(128000).toLocaleString()} tokens`);
    assert.equal(formatTokenLimit({ default: 1 }), 'Varies by deployment');
    assert.equal(formatTokenLimit(undefined), 'Not documented');
    assert.equal(lifecycleLabel('limited-availability'), 'Limited availability');
    assert.equal(lifecycleLabel(''), null);
    assert.equal(isLifecycleWarning('retired'), true);
    assert.equal(isLifecycleWarning('current'), false);
    assert.equal(evidenceLabel('admin_declared'), 'Administrator declared');
    assert.equal(readSuitability('bogus'), 'unknown');
    assert.equal(capabilityLabel('processesBinaryFiles'), 'Processes binary files');
    assert.equal(capabilityLabel('imageGenerationTool'), 'Image generation tool');
    assert.equal(new Set(CATALOG_CAPABILITIES.map((item) => item.key)).size, 14);
});

check('pickers share one profile request until the catalog changes', async () => {
    let requests = 0;
    const events: string[] = [];
    const globals = globalThis as Record<string, unknown>;
    const original = { fetch: globals.fetch, window: globals.window };
    globals.window = { dispatchEvent: (event: Event) => events.push(event.type) };
    globals.fetch = async () => {
        requests += 1;
        return new Response(JSON.stringify({ profiles: [profile('Shared')], tasks: {} }), {
            headers: { 'content-type': 'application/json' },
        });
    };
    try {
        const [first, second] = await Promise.all([loadCatalogChoices(), loadCatalogChoices()]);
        assert.equal(requests, 1);
        assert.equal(first, second);
        catalogChanged();
        assert.deepEqual(events, ['model-catalog-changed']);
        await loadCatalogChoices();
        assert.equal(requests, 2, 'a save drops the shared list');

        globals.fetch = async () => new Response('<html>Sign in</html>', { headers: { 'content-type': 'text/html' } });
        catalogChanged();
        await assert.rejects(loadCatalogChoices(), /could not be loaded/);
        globals.fetch = async () => {
            requests += 1;
            return new Response(JSON.stringify({ profiles: [], tasks: {} }), {
                headers: { 'content-type': 'application/json' },
            });
        };
        await loadCatalogChoices();
        assert.equal(requests, 3, 'a failed read is not cached');
    } finally {
        globals.fetch = original.fetch;
        globals.window = original.window;
    }
});

let passed = 0;
for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${(error as Error).message}`);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
