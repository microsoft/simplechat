// test_v2_navigation_groups_logic.mjs
//
// Runtime test for the V2 rail's administrator-configured navigation groups.
// Version: 0.261.055
// Implemented in: 0.261.047
//
// Custom Pages and External Links are configured in Admin Settings and had no
// representation in the V2 rail at all, so a deployment that had set them up saw none of
// its own links. Bringing them across means getting the visibility rules right, and those
// are easy to get subtly wrong in ways review does not catch: a group that renders as an
// empty heading, or entries that collide into one row.
//
// The companion test, test_v2_bootstrap_branding_and_navigation.py, proves the server
// sends the groups. This file executes the client's decisions about them, and
// test_v2_sidebar_menu_state_logic.mjs covers whether a group is drawn open or closed.
//
// Run directly with `node functional_tests/test_v2_navigation_groups_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';
import {
    isGroupVisible,
    toCustomPageLinks,
    toExternalLinks,
} from '../application/v2_ui/src/lib/navigationGroups.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/** Build a navigation group of the shape /api/v2/bootstrap returns. */
function group(items, overrides = {}) {
    return {
        enabled: true,
        menu_name: 'Custom Pages',
        force_menu: false,
        items,
        ...overrides,
    };
}

function page(slug, overrides = {}) {
    return {
        slug,
        label: slug,
        icon: 'bi-file-earmark-text',
        url: `/custom/${slug}`,
        open_in_new_tab: false,
        ...overrides,
    };
}

/* -------------------------------- visibility -------------------------------- */

check('a group with entries and enabled is shown', () => {
    assert.equal(isGroupVisible(group([page('handbook')])), true);
});

check('a disabled group is hidden even when it has entries', () => {
    assert.equal(isGroupVisible(group([page('handbook')], { enabled: false })), false);
});

check('an enabled but empty group is hidden', () => {
    // Otherwise the rail grows a heading with nothing under it, which reads as broken
    // rather than as unused.
    assert.equal(isGroupVisible(group([])), false);
});

check('a missing group does not throw', () => {
    for (const value of [undefined, null, {}]) {
        assert.equal(isGroupVisible(value), false);
    }
});

/* --------------------------------- mapping ---------------------------------- */

check('custom pages keep their own new-tab choice', () => {
    const links = toCustomPageLinks(
        group([page('handbook'), page('policy', { open_in_new_tab: true })]),
    );
    assert.deepEqual(
        links.map((link) => link.newTab),
        [false, true],
    );
    assert.deepEqual(
        links.map((link) => link.href),
        ['/custom/handbook', '/custom/policy'],
    );
});

check('a custom page with no label falls back to its slug', () => {
    const [link] = toCustomPageLinks(group([page('handbook', { label: '' })]));
    assert.equal(link.label, 'handbook');
});

check('external links always open in a new tab', () => {
    // They leave the application, and losing an in-progress conversation to a policy link
    // would be a poor trade.
    const links = toExternalLinks(
        group([
            { label: 'Policies', url: 'https://example.invalid/policies' },
            { label: 'Handbook', url: 'https://example.invalid/handbook' },
        ]),
    );
    assert.ok(links.every((link) => link.newTab === true));
});

check('repeated external links still get distinct keys', () => {
    // Labels and URLs are both administrator-supplied and may legitimately repeat, so a
    // key derived from either alone would collapse two rows into one in React.
    const duplicate = { label: 'Policies', url: 'https://example.invalid/policies' };
    const links = toExternalLinks(group([duplicate, duplicate]));
    assert.equal(new Set(links.map((link) => link.key)).size, 2);
});

check('custom page keys do not collide with external link keys', () => {
    const pageKeys = toCustomPageLinks(group([page('policies')])).map((link) => link.key);
    const linkKeys = toExternalLinks(
        group([{ label: 'policies', url: 'https://example.invalid/policies' }]),
    ).map((link) => link.key);
    assert.equal(new Set([...pageKeys, ...linkKeys]).size, 2);
});

check('an absent group maps to no links rather than throwing', () => {
    assert.deepEqual(toCustomPageLinks(undefined), []);
    assert.deepEqual(toExternalLinks(null), []);
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
