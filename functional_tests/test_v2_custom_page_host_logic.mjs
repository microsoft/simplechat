// test_v2_custom_page_host_logic.mjs
//
// Runtime test for how V2 decides what to show for a custom page, and for the two messages
// it exchanges with the embedded page.
// Version: 0.261.448
// Implemented in: 0.261.448
//
// A custom page is a server-rendered document, so V2 shows a chrome-less copy of it in a frame.
// The decisions that matter are all small and all easy to get subtly wrong: which pages may be
// framed at all, whether the host can tell a page that rendered from an error page (the frame's
// `load` event fires for both), and whether a message from some other window can be mistaken for
// the page. The frame state and the pane that draws it are covered by
// ui_tests/test_v2_custom_pages.py; this file runs the real decisions.
//
// Run directly with `node functional_tests/test_v2_custom_page_host_logic.mjs`. Requires Node
// 22.6 or newer, which strips the TypeScript types so the real module is imported.

import './test_support/tsResolve.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Imported dynamically, after the resolver above has registered: a static import is resolved
// before the resolver runs, and the module imports its siblings extensionless.
const {
    CUSTOM_PAGE_READY_MESSAGE,
    CUSTOM_PAGE_THEME_MESSAGE,
    customPageThemeMessage,
    isCustomPageReadyMessage,
    isValidCustomPageSlug,
    nextCustomPageFrameStatus,
    opensInsideV2,
    resolveCustomPageHost,
    safeCustomPageEmbedSrc,
    safeCustomPageHref,
    safeCustomPageStandaloneHref,
    safeCustomPageUrl,
} = await import('../application/v2_ui/src/lib/customPageEmbed.ts');

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

function navPage(slug, overrides = {}) {
    return {
        slug,
        label: slug,
        icon: 'bi-file-earmark-text',
        url: `/custom/${slug}`,
        open_in_new_tab: false,
        embeddable: true,
        ...overrides,
    };
}

function navigation(items, overrides = {}) {
    return {
        custom_pages: { enabled: true, menu_name: 'Custom Pages', force_menu: false, items, ...overrides },
    };
}

/* ----------------------------------- slugs ------------------------------------ */

check('a slug is accepted exactly as the server accepts it', () => {
    for (const slug of ['handbook', 'a', '0day', 'a-b_c1', 'x'.repeat(64)]) {
        assert.equal(isValidCustomPageSlug(slug), true, slug);
    }
});

check('anything else is refused before it reaches an address', () => {
    // The slug is written into the frame's address and into the page's own route, so a value
    // that could climb out of /custom/ or carry a query must never get that far.
    for (const slug of [
        '', '-lead', '_lead', 'Upper', 'a b', 'a/b', '../admin', 'a.html', 'a?x=1', 'a#x', '%2e%2e',
        'x'.repeat(65), undefined, null, 7, {},
    ]) {
        assert.equal(isValidCustomPageSlug(slug), false, String(slug));
    }
});

check('the frame address is the chrome-less copy of the page, from the site root', () => {
    assert.equal(safeCustomPageEmbedSrc('handbook'), '/custom/handbook?embed=1');
    assert.equal(safeCustomPageUrl('handbook'), '/custom/handbook');
    assert.equal(safeCustomPageHref('handbook'), '/custom/handbook');
});

check('an invalid slug builds no address at all', () => {
    assert.equal(safeCustomPageEmbedSrc('../x'), '');
    assert.equal(safeCustomPageUrl('A'), '');
    // A router link falls back to the home page rather than to a path built from the value.
    assert.equal(safeCustomPageHref('a/b'), '/');
});

check('"Open in a new tab" opens the chrome-less document on its own, not the classic address', () => {
    // In the modern interface the server sends the classic address of a page V2 can host to the
    // host's own route, so a tab opened there would be a second host (and from the failure panel
    // the same failing frame). `embed=1` is the one query that redirect never touches.
    const href = safeCustomPageStandaloneHref('handbook');
    assert.equal(href, '/custom/handbook?embed=1');
    assert.notEqual(href, safeCustomPageUrl('handbook'));
    assert.equal(href, safeCustomPageEmbedSrc('handbook'), 'the tab shows the document the frame loads');

    const parsed = new URL(href, 'https://chat.contoso.test');
    assert.equal(parsed.origin, 'https://chat.contoso.test', 'a path on this site, never another origin');
    assert.equal(parsed.pathname, '/custom/handbook');
    assert.equal(parsed.search, '?embed=1', 'exactly the embed pair and nothing else');
    assert.equal(parsed.hash, '');
});

check('the new-tab address holds a slug only as one validated segment', () => {
    // The address is built with the same validation and the same encoding as the frame's, for every
    // slug the server accepts; none of its characters needs escaping, so the slug appears as is.
    for (const slug of ['a', '0day', 'a-b_c1', 'x'.repeat(64)]) {
        assert.equal(safeCustomPageStandaloneHref(slug), `/custom/${slug}?embed=1`, slug);
        assert.equal(safeCustomPageStandaloneHref(slug), safeCustomPageEmbedSrc(slug), slug);
    }
    // Anything that could climb out of /custom/, carry a query or a fragment, or name another site
    // produces no address, so the link is never built from it.
    for (const slug of [
        '', '../admin', 'a/b', 'a?x=1', 'a#x', '%2e%2e', '//evil.test', 'https://evil.test', 'a:b',
        'a\\b', 'a b', 'Upper', 'a.html', 'x'.repeat(65), undefined, null, 7, {},
    ]) {
        assert.equal(safeCustomPageStandaloneHref(slug), '', String(slug));
    }
});

/* ------------------------------ what the host shows ------------------------------ */

check('a page in the navigation list is framed', () => {
    const view = resolveCustomPageHost('handbook', navigation([navPage('handbook')]));
    assert.equal(view.kind, 'frame');
    assert.equal(view.page.slug, 'handbook');
});

check('a slug that is not in the list is not available, whatever the reason', () => {
    // The list is already filtered by role and by the page being enabled, so a missing slug is
    // one this user cannot open: removed, switched off, or restricted to another role.
    assert.equal(resolveCustomPageHost('other', navigation([navPage('handbook')])).kind, 'unavailable');
    assert.equal(resolveCustomPageHost('handbook', navigation([])).kind, 'unavailable');
    assert.equal(resolveCustomPageHost('handbook', null).kind, 'unavailable');
    assert.equal(resolveCustomPageHost('handbook', {}).kind, 'unavailable');
});

check('a group that is switched off shows nothing, even with entries in it', () => {
    const view = resolveCustomPageHost(
        'handbook',
        navigation([navPage('handbook')], { enabled: false }),
    );
    assert.equal(view.kind, 'unavailable');
});

check('an invalid slug is not available and is not looked up', () => {
    for (const slug of [undefined, '', '../handbook', 'Handbook', 'handbook.html']) {
        assert.equal(resolveCustomPageHost(slug, navigation([navPage('handbook')])).kind, 'unavailable');
    }
});

check('a page that asks for its own tab is not framed, even when it could be', () => {
    const view = resolveCustomPageHost(
        'policy',
        navigation([navPage('policy', { open_in_new_tab: true })]),
    );
    assert.deepEqual([view.kind, view.reason], ['new-tab', 'own-tab']);
});

check('a page the server did not mark embeddable is not framed', () => {
    // Either a Python page that has not opted in, or a payload from a server that predates the
    // flag. The page would draw the classic navigation inside the frame.
    for (const embeddable of [false, undefined]) {
        const view = resolveCustomPageHost(
            'dash',
            navigation([navPage('dash', { embeddable })]),
        );
        assert.deepEqual([view.kind, view.reason], ['new-tab', 'not-embeddable']);
    }
});

check('nothing is framed when the interface is hosted on another origin', () => {
    const view = resolveCustomPageHost('handbook', navigation([navPage('handbook')]), false);
    assert.deepEqual([view.kind, view.reason], ['new-tab', 'cross-origin']);
});

check('the rail and the host agree on which pages open inside V2', () => {
    const pages = [
        navPage('a'),
        navPage('b', { embeddable: false }),
        navPage('c', { open_in_new_tab: true }),
        navPage('d', { embeddable: undefined }),
    ];
    for (const page of pages) {
        const framed = resolveCustomPageHost(page.slug, navigation(pages)).kind === 'frame';
        assert.equal(opensInsideV2(page), framed, page.slug);
    }
});

/* --------------------------------- messages --------------------------------- */

const ORIGIN = 'https://chat.contoso.test';
const FRAME = { name: 'the frame the host created' };
const OTHER = { name: 'some other window' };

function readyEvent(overrides = {}) {
    return {
        origin: ORIGIN,
        source: FRAME,
        data: { type: CUSTOM_PAGE_READY_MESSAGE, slug: 'handbook' },
        ...overrides,
    };
}

check('the page reporting that it rendered is recognised', () => {
    assert.equal(isCustomPageReadyMessage(readyEvent(), FRAME, ORIGIN), true);
});

check('a message from another origin, another window or another kind is not the page', () => {
    assert.equal(isCustomPageReadyMessage(readyEvent({ origin: 'https://evil.test' }), FRAME, ORIGIN), false);
    assert.equal(isCustomPageReadyMessage(readyEvent({ source: OTHER }), FRAME, ORIGIN), false);
    assert.equal(isCustomPageReadyMessage(readyEvent({ data: { type: CUSTOM_PAGE_THEME_MESSAGE } }), FRAME, ORIGIN), false);
    assert.equal(isCustomPageReadyMessage(readyEvent({ data: null }), FRAME, ORIGIN), false);
    assert.equal(isCustomPageReadyMessage(readyEvent({ data: CUSTOM_PAGE_READY_MESSAGE }), FRAME, ORIGIN), false);
});

check('nothing is accepted while the frame has no window yet', () => {
    // Before the iframe is attached its window is null, and an unattached sender is `null` too.
    assert.equal(isCustomPageReadyMessage(readyEvent({ source: null }), null, ORIGIN), false);
    assert.equal(isCustomPageReadyMessage(readyEvent(), undefined, ORIGIN), false);
});

check('the theme message carries only the theme', () => {
    assert.deepEqual(customPageThemeMessage('dark'), { type: CUSTOM_PAGE_THEME_MESSAGE, theme: 'dark' });
    assert.deepEqual(customPageThemeMessage('light'), { type: CUSTOM_PAGE_THEME_MESSAGE, theme: 'light' });
});

check('the message names match what the server template sends and listens for', () => {
    // The two ends are in different languages and nothing else ties them together. If one
    // changed alone the host would wait for a message that never comes and show every page as
    // failed, or the page would ignore the theme.
    const template = readFileSync(
        new URL('../application/single_app/templates/custom_page_embed_base.html', import.meta.url),
        'utf8',
    );
    assert.ok(template.includes(`"${CUSTOM_PAGE_READY_MESSAGE}"`), 'the ready message');
    assert.ok(template.includes(`"${CUSTOM_PAGE_THEME_MESSAGE}"`), 'the theme message');
});

/* ------------------------------ frame status ------------------------------ */

check('a page that reports in is ready, and a page that stays silent has failed', () => {
    assert.equal(nextCustomPageFrameStatus('loading', 'ready'), 'ready');
    assert.equal(nextCustomPageFrameStatus('loading', 'timeout'), 'failed');
});

check('a page that reports late recovers from the failure panel', () => {
    // A slow server is not a broken one, so the failure is not final.
    assert.equal(nextCustomPageFrameStatus('failed', 'ready'), 'ready');
});

check('a stale timer never takes a visible page down', () => {
    assert.equal(nextCustomPageFrameStatus('ready', 'timeout'), 'ready');
    assert.equal(nextCustomPageFrameStatus('failed', 'timeout'), 'failed');
});

check('trying again starts over from loading', () => {
    assert.equal(nextCustomPageFrameStatus('failed', 'retry'), 'loading');
    assert.equal(nextCustomPageFrameStatus('ready', 'retry'), 'loading');
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
