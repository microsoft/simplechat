// test_v2_classic_links_logic.ts
//
// Runtime test for lib/classicLinks.ts: the V2 side of the classic to V2 redirect.
// Version: 0.261.445
// Implemented in: 0.261.445
//
// Three promises that do not show in a screenshot are executed here:
//
// - `classicHrefFor` (the "Open this page in classic" address) gives the very answers the server's
//   `resolve_classic_target` gives, for every row of the registry and for hostile addresses, and
//   `translateClassicFragment` gives the very answers `resolve_v2_target` gives for a fragment;
// - the address a visitor is sent to is always a same-site absolute path, and the fragment
//   translation can never loop;
// - the account menu's link keeps the open conversation on the chat page, carries `ui=classic`
//   everywhere, and falls back to the classic chat page for a page that has no classic counterpart.
//
// Run by test_v2_classic_links.py, which bundles this with the esbuild Vite already brings in and
// executes it under node. CLASSIC_LINKS_CASES names the JSON file of cases the server's resolver
// produced for the real registry.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    CLASSIC_ESCAPE_PARAM,
    CLASSIC_ESCAPE_VALUE,
    classicBackHref,
    classicHrefFor,
    translateClassicFragment,
    withClassicEscape,
} from '../application/v2_ui/src/lib/classicLinks';
import { UI_ROUTE_MAP } from '../application/v2_ui/src/lib/generated/uiRouteMap';

interface ClassicAnswer {
    path: string;
    key: string;
    status: string;
}

interface ReverseCase {
    label: string;
    pathname: string;
    search: string;
    hash: string;
    expected: ClassicAnswer | null;
}

interface ForwardCase {
    label: string;
    pathname: string;
    search: string;
    hash: string;
    /** The V2 address the server's redirect sends the classic URL to, before the fragment is read. */
    arrival: string;
    /** The V2 address the whole classic URL, fragment included, names. */
    expected: string;
}

interface Cases {
    reverse: ReverseCase[];
    forward: ForwardCase[];
}

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

function loadCases(): Cases | null {
    const file = process.env.CLASSIC_LINKS_CASES;
    if (!file) {
        console.log('       (differential checks skipped: no case file supplied)');
        return null;
    }
    return JSON.parse(readFileSync(file, 'utf8')) as Cases;
}

function sameSite(path: string): boolean {
    return path.startsWith('/') && path[1] !== '/' && path[1] !== '\\' && !path.includes('\\')
        && !/[\u0000-\u001f\u007f ]/.test(path);
}

function describeMismatches(mismatches: string[]): string {
    return `${mismatches.length} mismatch(es):\n         ${mismatches.slice(0, 12).join('\n         ')}`;
}

// ---------------------------------------------------------------------------
// The escape pair
// ---------------------------------------------------------------------------

check('the escape pair is ui=classic', () => {
    assert.equal(CLASSIC_ESCAPE_PARAM, 'ui');
    assert.equal(CLASSIC_ESCAPE_VALUE, 'classic');
});

check('withClassicEscape adds the pair last, replaces an earlier one and keeps the fragment last', () => {
    const table: Array<[string, string]> = [
        ['/chats', '/chats?ui=classic'],
        ['/chats?conversationId=abc', '/chats?conversationId=abc&ui=classic'],
        ['/profile?tab=settings#m365-chat-connection', '/profile?tab=settings&ui=classic#m365-chat-connection'],
        ['/workspace#documents-tab', '/workspace?ui=classic#documents-tab'],
        ['/chats?ui=modern', '/chats?ui=classic'],
        ['/chats?ui=classic', '/chats?ui=classic'],
        ['/chats?ui=classic&ui=modern&a=1', '/chats?a=1&ui=classic'],
        ['/chats?ui', '/chats?ui=classic'],
        ['/chats?', '/chats?ui=classic'],
        ['/chats?uix=1&xui=2', '/chats?uix=1&xui=2&ui=classic'],
        ['/', '/?ui=classic'],
    ];
    for (const [input, expected] of table) {
        assert.equal(withClassicEscape(input), expected, input);
    }
});

check('withClassicEscape is idempotent', () => {
    for (const input of ['/chats', '/groups/abc?x=1', '/workspace#documents-tab', '/profile?tab=feedback&ui=classic']) {
        const once = withClassicEscape(input);
        assert.equal(withClassicEscape(once), once, input);
    }
});

check('withClassicEscape never extends an address that is not a same-site path', () => {
    const foreign = [
        'https://evil.example/x', 'http://evil.example', '//evil.example/x', '/\\evil.example', '\\\\evil.example',
        'javascript:alert(1)', 'data:text/html,x', 'chats', '', '/chats\nx', '/chats\u0000', '/chats x', '/a\\b',
    ];
    for (const input of foreign) {
        assert.equal(withClassicEscape(input), '/chats?ui=classic', JSON.stringify(input));
    }
});

// ---------------------------------------------------------------------------
// "Back to classic UI"
// ---------------------------------------------------------------------------

check('the chat page carries the open conversation to the classic chat page', () => {
    assert.equal(classicBackHref('/chat', '', '', 'c1'), '/chats?conversationId=c1&ui=classic');
    assert.equal(classicBackHref('/chat', '?conversationId=other', '', 'c1'), '/chats?conversationId=c1&ui=classic');
    assert.equal(classicBackHref('/chat', '', '', null), '/chats?ui=classic');
    assert.equal(classicBackHref('/v2/chat', '', '', 'c 1&x'), '/chats?conversationId=c%201%26x&ui=classic');
});

check('a page with a classic counterpart leads to it, with the escape pair', () => {
    assert.equal(classicBackHref('/settings', '?tab=feedback', '', 'c1'), '/profile?tab=feedback&ui=classic');
    assert.equal(
        classicBackHref('/settings', '?tab=preferences&section=m365-chat-connection', '', null),
        '/profile?tab=settings&ui=classic#m365-chat-connection',
    );
    assert.equal(classicBackHref('/groups/abc-123/members', '', '', 'c1'), '/groups/abc-123?ui=classic');
    assert.equal(classicBackHref('/notifications', '', '', 'c1'), '/notifications?ui=classic');
});

check('a page with no classic counterpart falls back to the classic chat page', () => {
    for (const pathname of ['/groups/directory', '/nope', '//evil.example', '/settings/../x', '/groups/a%2fb']) {
        assert.equal(classicBackHref(pathname, '', '', 'c1'), '/chats?conversationId=c1&ui=classic', pathname);
        assert.equal(classicBackHref(pathname, '', '', null), '/chats?ui=classic', pathname);
    }
});

check('the V2 landing route has the classic landing page as its counterpart', () => {
    assert.equal(classicBackHref('/', '', '', 'c1'), '/?ui=classic');
});

check('every address the account menu link can take is a same-site path carrying the escape pair', () => {
    const pathnames = [
        '/chat', '/settings', '/groups', '/groups/abc', '/groups/abc/members', '/workspace', '/workspace/documents',
        '/notifications', '/approvals/dashboard', '/control-center', '/admin', '/custom/handbook', '/nope', '//evil.example',
    ];
    for (const pathname of pathnames) {
        const href = classicBackHref(pathname, '?tab=feedback&x=1', '#documents-tab', 'c1');
        assert.ok(sameSite(href), `${pathname}: ${href}`);
        assert.match(href, /[?&]ui=classic(?:#|$)/, `${pathname}: ${href}`);
        assert.ok(!href.startsWith('/v2'), `${pathname}: ${href}`);
    }
});

// ---------------------------------------------------------------------------
// V2 -> classic, against the server's resolver
// ---------------------------------------------------------------------------

check('classicHrefFor ignores a fragment, as V2 never addresses sections with one', () => {
    assert.deepEqual(classicHrefFor('/settings', '?tab=feedback', '#anything'), classicHrefFor('/settings', '?tab=feedback'));
});

check('an alias row never answers: its V2 page belongs to another row', () => {
    for (const entry of UI_ROUTE_MAP) {
        if (entry.status !== 'alias' || entry.v2 === null || entry.v2.includes(':')) continue;
        const answer = classicHrefFor(entry.v2, '');
        if (answer !== null) {
            assert.notEqual(answer.key, entry.key, `${entry.key} answered for its own V2 page ${entry.v2}`);
        }
    }
});

const cases = loadCases();

if (cases !== null) {
    check('classicHrefFor gives the server resolver\'s answer for every case', () => {
        assert.ok(cases.reverse.length >= 200, `only ${cases.reverse.length} reverse cases were supplied`);
        const mismatches: string[] = [];
        for (const item of cases.reverse) {
            const actual = classicHrefFor(item.pathname, item.search, item.hash);
            if (JSON.stringify(actual) !== JSON.stringify(item.expected)) {
                mismatches.push(
                    `${item.label} [${item.pathname}${item.search}]: expected ${JSON.stringify(item.expected)}, got ${JSON.stringify(actual)}`,
                );
            }
        }
        assert.equal(mismatches.length, 0, describeMismatches(mismatches));
    });

    check('the reverse cases cover answers and refusals, and every answer is a same-site path', () => {
        const answered = cases.reverse.filter((item) => item.expected !== null);
        const refused = cases.reverse.filter((item) => item.expected === null);
        assert.ok(answered.length >= 80, `only ${answered.length} cases have an answer`);
        assert.ok(refused.length >= 25, `only ${refused.length} cases are refused`);
        for (const item of answered) {
            assert.ok(sameSite(item.expected!.path), `${item.label}: ${item.expected!.path}`);
        }
    });

    check('translateClassicFragment gives the server resolver\'s answer for every case', () => {
        assert.ok(cases.forward.length >= 40, `only ${cases.forward.length} forward cases were supplied`);
        const mismatches: string[] = [];
        for (const item of cases.forward) {
            const result = translateClassicFragment(item.pathname, item.search, item.hash);
            const actual = result === null ? null : `${result.pathname}${result.search}`;
            // Null is right when the fragment adds nothing the address does not already say.
            const settled = actual === null ? item.arrival : actual;
            if (settled !== item.expected) {
                mismatches.push(`${item.label} [${item.pathname}${item.search}${item.hash}]: expected ${item.expected}, got ${actual}`);
            }
        }
        assert.equal(mismatches.length, 0, describeMismatches(mismatches));
    });

    check('the forward cases include fragments that change the address and fragments that do not', () => {
        const changed = cases.forward.filter((item) => item.expected !== item.arrival);
        const unchanged = cases.forward.filter((item) => item.expected === item.arrival);
        assert.ok(changed.length >= 12, `only ${changed.length} cases change the address`);
        assert.ok(unchanged.length >= 10, `only ${unchanged.length} cases leave it as it is`);
        for (const item of changed) {
            const result = translateClassicFragment(item.pathname, item.search, item.hash);
            assert.notEqual(result, null, `${item.label} should be translated`);
        }
    });

    check('a translated address carries no fragment, is a same-site path and translates to itself', () => {
        for (const item of cases.forward) {
            const result = translateClassicFragment(item.pathname, item.search, item.hash);
            if (result === null) continue;
            assert.ok(sameSite(result.pathname), `${item.label}: ${result.pathname}`);
            assert.ok(result.search === '' || result.search.startsWith('?'), `${item.label}: ${result.search}`);
            assert.ok(!result.pathname.includes('#') && !result.search.includes('#'), item.label);
            // The hook replaces the address with this and the fragment is gone, so there is nothing left to
            // translate. Were the fragment put back, the answer would be this same address.
            assert.equal(translateClassicFragment(result.pathname, result.search, ''), null, item.label);
            const again = translateClassicFragment(result.pathname, result.search, item.hash);
            if (again !== null) {
                assert.deepEqual(again, result, `${item.label} is not stable`);
            }
        }
    });
}

// ---------------------------------------------------------------------------
// Classic fragment -> V2, hostile input
// ---------------------------------------------------------------------------

check('a fragment the registry does not list is left alone', () => {
    const hostile = [
        '', '#', '##', '#nope', '#documents', '#DOCUMENTS-TAB', '#documents-tab/../x', '#documents-tab%0a', '#documents-tab%00',
        '#%E0%A4%A', '#%', '#__proto__', '#constructor', '#toString', '#hasOwnProperty', '#<script>alert(1)</script>',
        '#' + 'a'.repeat(300), '#documents-tab ', '# documents-tab', '#documents-tab#documents-tab', '#javascript:alert(1)',
        '#//evil.example', '#\\\\evil.example',
    ];
    for (const hash of hostile) {
        for (const pathname of ['/workspace', '/settings', '/approvals', '/chat', '/']) {
            assert.equal(translateClassicFragment(pathname, '', hash), null, `${pathname}${hash}`);
        }
    }
});

check('a fragment is read only on the page it belongs to and only on that page\'s own route', () => {
    for (const entry of UI_ROUTE_MAP) {
        const fragments = Object.keys(entry.hash_map ?? {});
        if (fragments.length === 0 || entry.v2 === null) continue;
        const own = entry.v2;
        const other = own === '/chat' ? '/settings' : '/chat';
        for (const fragment of fragments) {
            assert.equal(translateClassicFragment(other, '', `#${fragment}`), null, `${entry.key} ${fragment} on ${other}`);
            assert.equal(translateClassicFragment(`${own}/x/y/z`, '', `#${fragment}`), null, `${entry.key} ${fragment} on a deeper route`);
        }
    }
});

check('hostile paths and queries translate to nothing', () => {
    const fragment = Object.keys(UI_ROUTE_MAP.find((entry) => entry.key === 'workspace')?.hash_map ?? { 'documents-tab': {} })[0];
    for (const pathname of ['', 'workspace', '//workspace', '/workspace/../workspace', '/work\\space', '/workspace%2f', '/workspace?x=1', '/workspace#x']) {
        assert.equal(translateClassicFragment(pathname, '', `#${fragment}`), null, pathname);
    }
    assert.equal(translateClassicFragment('/workspace', '?' + 'a=1&'.repeat(80), `#${fragment}`), null);
    assert.equal(translateClassicFragment('/workspace', '?a=' + 'x'.repeat(5000), `#${fragment}`), null);
});

check('the fragment names are matched as own keys, never through the prototype', () => {
    for (const name of ['constructor', 'toString', 'valueOf', 'hasOwnProperty', '__proto__', 'isPrototypeOf']) {
        for (const pathname of ['/workspace', '/settings', '/approvals']) {
            assert.equal(translateClassicFragment(pathname, '', `#${name}`), null, name);
        }
    }
});

// ---------------------------------------------------------------------------

let passed = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${(error as Error).message}`);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
