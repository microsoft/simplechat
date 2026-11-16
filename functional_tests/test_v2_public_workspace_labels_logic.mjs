// test_v2_public_workspace_labels_logic.mjs
// Version: 0.261.175
// Implemented in: 0.261.175
// Executes the real V2 public workspace label selector (lib/publicWorkspaceLabels.ts). The
// selector mirrors the classic getPublicWorkspaceLabel helper: it reads the server-resolved
// public_workspace_labels block with a per-key fallback, so a missing or malformed block leaves
// the default English forms rather than blanking the surface, a fully custom block round-trips,
// and each key falls back independently. The store reader is exercised end to end against a
// seeded bootstrap payload. The companion Python pin ties the module default to the real server
// get_public_workspace_label_context, so the literal block below cannot drift from the server.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { readPublicWorkspaceLabels, DEFAULT_PUBLIC_WORKSPACE_LABELS, getPublicWorkspaceLabels } =
    await import('../application/v2_ui/src/lib/publicWorkspaceLabels.ts');
const { useBootstrapStore } = await import('../application/v2_ui/src/stores/bootstrapStore.ts');

let checks = 0;

function check(name, run) {
    run();
    checks += 1;
    console.log(`ok ${name}`);
}

// The block the server's get_public_workspace_label_context produces for an unconfigured
// deployment. The Python pin asserts this equals the real server function's default output.
const SERVER_DEFAULT_BLOCK = {
    singular: 'Public Workspace',
    plural: 'Public Workspaces',
    lower_singular: 'public workspace',
    lower_plural: 'public workspaces',
    short: 'Public',
    is_custom: false,
    max_length: 32,
};

check('the module default matches the server default block', () => {
    assert.deepEqual(DEFAULT_PUBLIC_WORKSPACE_LABELS, SERVER_DEFAULT_BLOCK);
});

check('a missing or malformed settings object yields the defaults', () => {
    for (const missing of [
        undefined, null, {}, 'x', 42, [],
        { public_workspace_labels: null }, { public_workspace_labels: 'x' },
        { public_workspace_labels: 42 }, { public_workspace_labels: [] },
    ]) {
        assert.deepEqual(readPublicWorkspaceLabels(missing), DEFAULT_PUBLIC_WORKSPACE_LABELS);
    }
});

check('a fully custom block round-trips verbatim', () => {
    // The server sends every form as the custom name when an admin renames the surface.
    const custom = {
        singular: 'Community Hub', plural: 'Community Hub', lower_singular: 'Community Hub',
        lower_plural: 'Community Hub', short: 'Community Hub', is_custom: true, max_length: 32,
    };
    assert.deepEqual(readPublicWorkspaceLabels({ public_workspace_labels: custom }), custom);
});

check('each label key falls back independently when empty, blank or non-string', () => {
    const block = {
        singular: 'Custom S', plural: '', lower_singular: '   ', lower_plural: 42, short: null,
    };
    const resolved = readPublicWorkspaceLabels({ public_workspace_labels: block });
    assert.equal(resolved.singular, 'Custom S');
    assert.equal(resolved.plural, DEFAULT_PUBLIC_WORKSPACE_LABELS.plural);
    assert.equal(resolved.lower_singular, DEFAULT_PUBLIC_WORKSPACE_LABELS.lower_singular);
    assert.equal(resolved.lower_plural, DEFAULT_PUBLIC_WORKSPACE_LABELS.lower_plural);
    assert.equal(resolved.short, DEFAULT_PUBLIC_WORKSPACE_LABELS.short);
});

check('is_custom is a strict boolean and max_length rejects non-positive or non-integer', () => {
    assert.equal(readPublicWorkspaceLabels({ public_workspace_labels: { is_custom: 'yes' } }).is_custom, false);
    assert.equal(readPublicWorkspaceLabels({ public_workspace_labels: { is_custom: 1 } }).is_custom, false);
    assert.equal(readPublicWorkspaceLabels({ public_workspace_labels: { is_custom: true } }).is_custom, true);
    for (const bad of [0, -1, 1.5, '32', null, undefined]) {
        assert.equal(readPublicWorkspaceLabels({ public_workspace_labels: { max_length: bad } }).max_length, 32);
    }
    assert.equal(readPublicWorkspaceLabels({ public_workspace_labels: { max_length: 45 } }).max_length, 45);
});

check('the store reader returns defaults when unseeded and the seeded block when present', () => {
    useBootstrapStore.setState({ data: undefined });
    assert.deepEqual(getPublicWorkspaceLabels(), DEFAULT_PUBLIC_WORKSPACE_LABELS);
    const custom = { ...DEFAULT_PUBLIC_WORKSPACE_LABELS, singular: 'Community Hub', short: 'Community', is_custom: true };
    useBootstrapStore.setState({ data: { settings: { public_workspace_labels: custom } } });
    assert.equal(getPublicWorkspaceLabels().singular, 'Community Hub');
    assert.equal(getPublicWorkspaceLabels().short, 'Community');
    assert.equal(getPublicWorkspaceLabels().is_custom, true);
    useBootstrapStore.setState({ data: undefined });
});

console.log(`${checks} public workspace label checks passed.`);
