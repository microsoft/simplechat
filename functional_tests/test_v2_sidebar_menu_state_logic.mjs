// test_v2_sidebar_menu_state_logic.mjs
//
// Runtime test for the V2 rail's remembered menu state.
// Version: 0.261.052
// Implemented in: 0.261.052
//
// The External Links and Custom Pages groups in the V2 rail now collapse and remember that
// choice, and they remember it in the same per-user setting the classic interface uses so a
// group put away in one interface stays away in the other.
//
// That sharing is the whole risk. `update_user_settings()` merges only the top level of the
// settings document, so a write carrying one key replaces the entire object: getting this
// wrong does not break the V2 rail at all, it silently resets the *classic* interface's
// Workspaces, Support and Conversations menus for anybody who collapses a group in V2. None
// of that is visible in review or in a screenshot, which is why it is executed here.
//
// Run directly with `node functional_tests/test_v2_sidebar_menu_state_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';
import {
    SIDEBAR_MENU_STATE_KEYS,
    normalizeSidebarMenuState,
    readSidebarMenuExpanded,
    withSidebarMenuExpanded,
} from '../application/v2_ui/src/lib/sidebarMenuState.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/* ------------------------------- the whitelist ------------------------------- */

check('the whitelist matches the classic interface', () => {
    // Quoted from `sidebarMenuStateKeys` in application/single_app/static/js/sidebar.js.
    // A key missing here is dropped by V2; a key invented here is dropped by the classic
    // interface on its next write, so the two lists have to stay identical.
    assert.deepEqual(
        [...SIDEBAR_MENU_STATE_KEYS].sort(),
        [
            'adminSettings',
            'controlCenter',
            'conversations',
            'customPages',
            'externalLinks',
            'support',
            'workspaces',
        ],
    );
});

check('the two groups V2 renders are both storable', () => {
    assert.ok(SIDEBAR_MENU_STATE_KEYS.includes('externalLinks'));
    assert.ok(SIDEBAR_MENU_STATE_KEYS.includes('customPages'));
});

/* ------------------------------- normalisation ------------------------------- */

check('booleans pass through', () => {
    assert.deepEqual(normalizeSidebarMenuState({ externalLinks: false, customPages: true }), {
        externalLinks: false,
        customPages: true,
    });
});

check('the string forms the setting has held are coerced', () => {
    // The setting has been written by more than one code path over time, so a document in
    // the wild may hold "true"/"false" rather than a boolean.
    assert.deepEqual(
        normalizeSidebarMenuState({ externalLinks: 'false', customPages: ' TRUE ' }),
        { externalLinks: false, customPages: true },
    );
});

check('unknown keys are dropped', () => {
    // The classic interface drops them on its next write, so keeping them here would make
    // the two interfaces disagree about what is stored.
    assert.deepEqual(normalizeSidebarMenuState({ externalLinks: true, madeUp: true }), {
        externalLinks: true,
    });
});

check('unusable values are dropped rather than guessed at', () => {
    assert.deepEqual(
        normalizeSidebarMenuState({ externalLinks: 1, customPages: null, support: 'yes' }),
        {},
    );
});

check('a missing or malformed setting does not throw', () => {
    for (const value of [undefined, null, 'externalLinks', 42, ['externalLinks']]) {
        assert.deepEqual(normalizeSidebarMenuState(value), {});
    }
});

/* --------------------------------- defaults ---------------------------------- */

check('a group nobody has touched is expanded', () => {
    // Matches `sidebar_menu_state.get('externalLinks', true)` in the classic templates. The
    // alternative hides a deployment's own links behind a heading that does not look like a
    // control until you click it.
    assert.equal(readSidebarMenuExpanded(undefined, 'externalLinks'), true);
    assert.equal(readSidebarMenuExpanded({}, 'customPages'), true);
    assert.equal(readSidebarMenuExpanded({ customPages: false }, 'externalLinks'), true);
});

check('a group that was collapsed stays collapsed', () => {
    assert.equal(readSidebarMenuExpanded({ externalLinks: false }, 'externalLinks'), false);
    assert.equal(readSidebarMenuExpanded({ externalLinks: 'false' }, 'externalLinks'), false);
});

check('a group that was expanded stays expanded', () => {
    assert.equal(readSidebarMenuExpanded({ externalLinks: true }, 'externalLinks'), true);
});

/* ---------------------------------- writing ---------------------------------- */

check("a write keeps the classic interface's own menus", () => {
    // The failure this guards against: /api/user/settings replaces the whole object, so a
    // payload built from only the toggled key would collapse-or-expand every classic menu
    // back to its default for that user.
    const stored = {
        workspaces: false,
        support: false,
        conversations: false,
        adminSettings: true,
        controlCenter: false,
    };

    assert.deepEqual(withSidebarMenuExpanded(stored, 'externalLinks', false), {
        ...stored,
        externalLinks: false,
    });
});

check('a write does not mutate the stored object', () => {
    // The store holds this object; mutating it in place would change what a failed save
    // rolls back to.
    const stored = { externalLinks: true };
    withSidebarMenuExpanded(stored, 'externalLinks', false);
    assert.deepEqual(stored, { externalLinks: true });
});

check('a write replaces the value for the toggled group only', () => {
    const next = withSidebarMenuExpanded({ externalLinks: true, customPages: true }, 'customPages', false);
    assert.deepEqual(next, { externalLinks: true, customPages: false });
});

check('a write from an empty or malformed setting still produces valid state', () => {
    assert.deepEqual(withSidebarMenuExpanded(undefined, 'externalLinks', false), {
        externalLinks: false,
    });
    assert.deepEqual(withSidebarMenuExpanded('nonsense', 'customPages', true), {
        customPages: true,
    });
});

check('a write drops junk it inherited rather than posting it back', () => {
    assert.deepEqual(
        withSidebarMenuExpanded({ madeUp: true, externalLinks: 'true' }, 'customPages', false),
        { externalLinks: true, customPages: false },
    );
});

check('the written value is always a boolean', () => {
    // Posting a string would work, but the two interfaces would then hold different types
    // for the same setting depending on which one wrote last.
    const next = withSidebarMenuExpanded({}, 'externalLinks', 1);
    assert.equal(next.externalLinks, true);
    assert.equal(typeof next.externalLinks, 'boolean');
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
