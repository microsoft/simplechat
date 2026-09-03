// test_v2_workspace_sections_logic.mjs
//
// Runtime test for the V2 personal workspace section resolution.
// Version: 0.261.039
// Implemented in: 0.261.039
//
// The companion test, test_v2_workspace_sections.py, asserts that the client reads the field
// names the routes actually return. That is a source assertion: it proves the wiring, not the
// behaviour.
//
// This file executes the gating itself, because getting it wrong fails quietly in both
// directions. Showing a section the server did not authorise produces a page whose every
// request is refused, and hiding one it did authorise looks identical to the capability not
// existing -- which is the confusion this whole redesign is meant to remove. The default
// selection matters for the same reason: a bookmark to a section that has since been turned
// off must land somewhere sensible rather than on a blank pane.
//
// Run directly with `node functional_tests/test_v2_workspace_sections_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';
import {
    WORKSPACE_GROUPS,
    defaultSectionId,
    groupWorkspaceSections,
    hasAnyWorkspaceSection,
    navigableSections,
    resolveWorkspaceSections,
} from '../application/v2_ui/src/lib/workspaceSections.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

const DESCRIPTORS = [
    { id: 'documents', group: 'knowledge' },
    { id: 'sync', group: 'knowledge' },
    { id: 'prompts', group: 'knowledge' },
    { id: 'agents', group: 'automation' },
    { id: 'actions', group: 'automation' },
    { id: 'workflows', group: 'automation' },
    { id: 'identities', group: 'connections' },
    { id: 'endpoints', group: 'connections' },
];

/** Build an availability payload of the shape /api/v2/bootstrap returns. */
function availability(overrides = {}) {
    const sections = {};
    for (const descriptor of DESCRIPTORS) {
        sections[descriptor.id] = {
            enabled: true,
            reason: null,
            group: descriptor.group,
        };
    }
    for (const [id, value] of Object.entries(overrides)) {
        sections[id] = { ...sections[id], ...value };
    }
    return { enabled: true, sections };
}

/* ------------------------------- resolution -------------------------------- */

check('a section the server enabled is available and carries no reason', () => {
    const resolved = resolveWorkspaceSections(DESCRIPTORS, availability());
    assert.equal(resolved.length, DESCRIPTORS.length);
    for (const entry of resolved) {
        assert.equal(entry.enabled, true);
        assert.equal(entry.reason, null);
    }
});

check('a disabled section keeps the server reason', () => {
    const resolved = resolveWorkspaceSections(
        DESCRIPTORS,
        availability({
            agents: { enabled: false, reason: 'Personal agents are not enabled for your account.' },
        }),
    );
    const agents = resolved.find((entry) => entry.section.id === 'agents');
    assert.equal(agents.enabled, false);
    assert.equal(agents.reason, 'Personal agents are not enabled for your account.');
});

check('a section the server never mentioned fails closed', () => {
    // Failing open would render a section whose every endpoint refuses the request, which
    // reads as the feature being broken rather than as it being unavailable.
    const partial = { enabled: true, sections: { documents: { enabled: true, reason: null } } };
    const resolved = resolveWorkspaceSections(DESCRIPTORS, partial);
    const agents = resolved.find((entry) => entry.section.id === 'agents');
    assert.equal(agents.enabled, false);
    assert.ok(agents.reason, 'an unmentioned section must still explain itself');
});

check('a missing payload disables everything rather than throwing', () => {
    for (const payload of [null, undefined, {}]) {
        const resolved = resolveWorkspaceSections(DESCRIPTORS, payload);
        assert.equal(resolved.length, DESCRIPTORS.length);
        assert.equal(hasAnyWorkspaceSection(resolved), false);
    }
});

/* --------------------------------- the rail --------------------------------- */

check('the rail carries only enabled sections', () => {
    const resolved = resolveWorkspaceSections(
        DESCRIPTORS,
        availability({
            sync: { enabled: false, reason: 'File sync is not enabled for your account.' },
            endpoints: { enabled: false, reason: 'Not enabled.' },
        }),
    );
    const ids = navigableSections(resolved).map((entry) => entry.section.id);
    assert.ok(!ids.includes('sync'));
    assert.ok(!ids.includes('endpoints'));
    assert.ok(ids.includes('documents'));
    assert.equal(ids.length, DESCRIPTORS.length - 2);
});

check('every disabled section still reaches the overview', () => {
    // The overview is the only place a switched-off section is accounted for, so it has to
    // receive all of them -- that is what the rail deliberately drops.
    const resolved = resolveWorkspaceSections(
        DESCRIPTORS,
        availability({ agents: { enabled: false, reason: 'Not enabled.' } }),
    );
    const overviewIds = groupWorkspaceSections(resolved).flatMap((view) =>
        view.sections.map((entry) => entry.section.id),
    );
    assert.equal(overviewIds.length, DESCRIPTORS.length);
    assert.ok(overviewIds.includes('agents'));
});

/* -------------------------------- grouping ---------------------------------- */

check('sections are grouped in the declared order', () => {
    const resolved = resolveWorkspaceSections(DESCRIPTORS, availability());
    const groups = groupWorkspaceSections(resolved);
    assert.deepEqual(
        groups.map((view) => view.group.id),
        ['knowledge', 'automation', 'connections'],
    );
    assert.deepEqual(
        groups[0].sections.map((entry) => entry.section.id),
        ['documents', 'sync', 'prompts'],
    );
});

check('an empty group is dropped rather than rendered as a bare heading', () => {
    const resolved = resolveWorkspaceSections(
        [
            { id: 'documents', group: 'knowledge' },
            { id: 'agents', group: 'automation' },
        ],
        availability(),
    );
    const groups = groupWorkspaceSections(navigableSections(resolved));
    assert.deepEqual(
        groups.map((view) => view.group.id),
        ['knowledge', 'automation'],
    );
});

check('every group has a label and a blurb', () => {
    for (const group of WORKSPACE_GROUPS) {
        assert.ok(group.label, `${group.id} needs a label`);
        assert.ok(group.blurb, `${group.id} needs a blurb`);
    }
});

/* ---------------------------- default selection ----------------------------- */

check('a requested section is honoured when it is enabled', () => {
    const resolved = resolveWorkspaceSections(DESCRIPTORS, availability());
    assert.equal(defaultSectionId(resolved, 'workflows'), 'workflows');
});

check('a requested section that is off falls back to the first available one', () => {
    const resolved = resolveWorkspaceSections(
        DESCRIPTORS,
        availability({
            documents: { enabled: false, reason: 'Not enabled.' },
            sync: { enabled: false, reason: 'Not enabled.' },
            agents: { enabled: false, reason: 'Not enabled.' },
        }),
    );
    assert.equal(defaultSectionId(resolved, 'agents'), 'prompts');
});

check('nothing enabled yields no default rather than an arbitrary one', () => {
    const resolved = resolveWorkspaceSections(DESCRIPTORS, { enabled: true, sections: {} });
    assert.equal(defaultSectionId(resolved, 'documents'), null);
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
process.exit(failed > 0 ? 1 : 0);
