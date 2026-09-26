// test_v2_public_directory_visibility_logic.mjs
// Version: 0.261.186
// Implemented in: 0.261.184
// Executes the real V2 public directory visibility logic: the pure map helpers in
// lib/publicVisibility.ts (visibleIdsFromMap, markEvery, mapForSavedList) that the bulk and
// saved-list controls compute their writes from, the availability filter (isChattableStatus,
// chattableIds) that keeps a bulk "show" or a saved list from claiming an unavailable workspace
// for chat (decision 32), and the bounded directory enumeration (listAllWorkspaceIds /
// listAllWorkspaces + DirectoryBulkTooLargeError) in lib/publicDirectory.ts that walks the server's
// pages so a bulk action covers the whole directory rather than the page on screen. Sits beside
// test_v2_public_membership_logic.mjs and pins that a bulk action either covers the whole directory
// or refuses, never marks an unavailable workspace visible, and never claims more than it wrote.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const visibility = await import('../application/v2_ui/src/lib/publicVisibility.ts');
const directory = await import('../application/v2_ui/src/lib/publicDirectory.ts');
const {
    visibleIdsFromMap, markEvery, mapForSavedList, hasCustomVisibility,
    isChattableStatus, chattableIds,
} = visibility;
const {
    PUBLIC_DIRECTORY, DirectoryBulkTooLargeError,
    DIRECTORY_BULK_MAX_WORKSPACES, DIRECTORY_BULK_PAGE_SIZE,
} = directory;

let checks = 0;
function check(name, run) {
    run();
    checks += 1;
    console.log(`ok ${name}`);
}
async function checkAsync(name, run) {
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

// -- The pure map helpers ---------------------------------------------------------------------

check('visibleIdsFromMap: an empty map means every workspace in the directory is visible', () => {
    assert.deepEqual(visibleIdsFromMap({}, ['a', 'b', 'c']), ['a', 'b', 'c']);
    assert.deepEqual(visibleIdsFromMap(undefined, ['a', 'b']), ['a', 'b']);
    assert.deepEqual(visibleIdsFromMap({}, []), []);
});

check('visibleIdsFromMap: a custom map keeps only the true ids that still exist', () => {
    // b is hidden, c is untoggled (absent) so hidden; only a survives.
    assert.deepEqual(visibleIdsFromMap({ a: true, b: false }, ['a', 'b', 'c']), ['a']);
    // z is true but no longer in the directory, so it is dropped like the classic snapshot.
    assert.deepEqual(visibleIdsFromMap({ a: true, z: true }, ['a', 'b']), ['a']);
    // Order follows the directory's ids, not the map's insertion order.
    assert.deepEqual(visibleIdsFromMap({ b: true, a: true }, ['a', 'b', 'c']), ['a', 'b']);
});

check('markEvery: marks every id and preserves entries it did not name (additive R2)', () => {
    assert.deepEqual(markEvery({ a: false }, ['a', 'b'], true), { a: true, b: true });
    assert.deepEqual(markEvery({ x: false }, ['a'], true), { x: false, a: true });
    assert.deepEqual(markEvery(undefined, ['a', 'b'], false), { a: false, b: false });
    // The source map is not mutated.
    const source = { a: true };
    markEvery(source, ['a', 'b'], false);
    assert.deepEqual(source, { a: true });
});

check('mapForSavedList: a non-empty list is a custom map of just those ids, so the rest hide', () => {
    assert.deepEqual(mapForSavedList(['a', 'b']), { a: true, b: true });
    assert.ok(hasCustomVisibility(mapForSavedList(['a'])), 'A non-empty list yields a custom map.');
    // An empty list cannot be expressed as a custom map (an empty map means "all visible").
    assert.deepEqual(mapForSavedList([]), {});
    assert.equal(hasCustomVisibility(mapForSavedList([])), false);
});

// -- The availability filter --------------------------------------------------------------------

check('isChattableStatus: only the reader-chattable statuses pass; everything else is unavailable', () => {
    for (const status of ['active', 'locked', 'upload_disabled']) {
        assert.equal(isChattableStatus(status), true, `${status} is chattable`);
    }
    for (const status of ['inactive', 'archived', 'unknown', 'deleting', '']) {
        assert.equal(isChattableStatus(status), false, `${status} is not chattable`);
    }
});

check('chattableIds: keeps the available ids and drops the unavailable, preserving order', () => {
    const walked = [
        { id: 'a', status: 'active' },
        { id: 'b', status: 'inactive' },
        { id: 'c', status: 'locked' },
        { id: 'd', status: 'archived' },
        { id: 'e', status: 'upload_disabled' },
    ];
    assert.deepEqual(chattableIds(walked), ['a', 'c', 'e']);
    assert.deepEqual(chattableIds([]), []);
    // A saved list marked from these ids never names an unavailable member, so the map cannot
    // claim one for chat: mapForSavedList over the filtered ids is available-only.
    assert.deepEqual(mapForSavedList(chattableIds(walked)), { a: true, c: true, e: true });
});

// -- The bounded directory enumeration --------------------------------------------------------

const originalFetch = globalThis.fetch;

function row(id) {
    return {
        id, name: `Name ${id}`, description: '', heroColor: '#123456',
        hasLogo: false, logoVersion: 0, userRole: 'User', membership: 'none', status: 'active',
    };
}
function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
// A directory of `total` ids, paged at `pageSize`; responds to the walk's page query.
function serveDirectory(total, pageSize, calls) {
    return async (path, options = {}) => {
        calls.push(String(path));
        const params = new URLSearchParams(String(path).split('?')[1] ?? '');
        const page = Number(params.get('page'));
        const start = (page - 1) * pageSize;
        const ids = Array.from({ length: total }, (_, index) => `ws-${index}`).slice(start, start + pageSize);
        return json({
            workspaces: ids.map(row), page, page_size: pageSize, total_count: total,
            public_directory: { schema_version: 1, can_create: false },
        });
    };
}

try {
    assert.equal(DIRECTORY_BULK_PAGE_SIZE, 100, 'The walk uses the server max page size.');
    assert.equal(DIRECTORY_BULK_MAX_WORKSPACES, 1000, 'The bulk bound is 1000.');

    await checkAsync('listAllWorkspaceIds: a single page returns every id in one request', async () => {
        const calls = [];
        globalThis.fetch = serveDirectory(3, DIRECTORY_BULK_PAGE_SIZE, calls);
        const ids = await PUBLIC_DIRECTORY.listAllWorkspaceIds();
        assert.deepEqual(ids, ['ws-0', 'ws-1', 'ws-2']);
        assert.equal(calls.length, 1, 'A single page needs one request.');
        const first = new URLSearchParams(calls[0].split('?')[1]);
        assert.equal(first.get('view'), 'all');
        assert.equal(first.get('page'), '1');
        assert.equal(first.get('page_size'), '100');
        assert.equal(first.get('search'), null, 'The walk sends no search filter.');
    });

    await checkAsync('listAllWorkspaceIds: it walks every page and covers the whole directory', async () => {
        const calls = [];
        globalThis.fetch = serveDirectory(250, DIRECTORY_BULK_PAGE_SIZE, calls);
        const ids = await PUBLIC_DIRECTORY.listAllWorkspaceIds();
        assert.equal(ids.length, 250, 'All 250 ids across three pages.');
        assert.equal(new Set(ids).size, 250, 'Every id is present exactly once.');
        assert.deepEqual(calls.map((path) => new URLSearchParams(path.split('?')[1]).get('page')), ['1', '2', '3']);
    });

    await checkAsync('listAllWorkspaceIds: an empty directory returns nothing in one request', async () => {
        const calls = [];
        globalThis.fetch = serveDirectory(0, DIRECTORY_BULK_PAGE_SIZE, calls);
        assert.deepEqual(await PUBLIC_DIRECTORY.listAllWorkspaceIds(), []);
        assert.equal(calls.length, 1);
    });

    await checkAsync('listAllWorkspaceIds: it refuses past the bound before walking, carrying the count', async () => {
        const calls = [];
        globalThis.fetch = serveDirectory(DIRECTORY_BULK_MAX_WORKSPACES + 1, DIRECTORY_BULK_PAGE_SIZE, calls);
        const refusal = await PUBLIC_DIRECTORY.listAllWorkspaceIds().catch((error) => error);
        assert.ok(refusal instanceof DirectoryBulkTooLargeError, 'A too-large directory is refused.');
        assert.equal(refusal.count, DIRECTORY_BULK_MAX_WORKSPACES + 1);
        assert.match(refusal.message, /1001 public workspaces/);
        assert.equal(calls.length, 1, 'It refuses on the first page, never fanning out further requests.');
    });

    await checkAsync('listAllWorkspaceIds: a workspace shifting pages mid-walk is counted once', async () => {
        // total_count says 150 (two pages) but page 2 repeats an id from page 1; the Set dedupes it.
        const calls = [];
        globalThis.fetch = async (path) => {
            calls.push(String(path));
            const page = Number(new URLSearchParams(String(path).split('?')[1]).get('page'));
            const ids = page === 1
                ? ['ws-0', 'ws-1', 'ws-2']
                : ['ws-2', 'ws-3'];
            return json({
                workspaces: ids.map(row), page, page_size: DIRECTORY_BULK_PAGE_SIZE, total_count: 150,
                public_directory: { schema_version: 1, can_create: false },
            });
        };
        const ids = await PUBLIC_DIRECTORY.listAllWorkspaceIds();
        assert.deepEqual(ids, ['ws-0', 'ws-1', 'ws-2', 'ws-3'], 'The duplicated id appears once.');
    });

    await checkAsync('listAllWorkspaces: returns each id with its status, so availability can be read', async () => {
        const calls = [];
        const statuses = ['active', 'inactive', 'locked', 'archived'];
        globalThis.fetch = async (path) => {
            calls.push(String(path));
            const workspaces = statuses.map((status, index) => ({ ...row(`ws-${index}`), status }));
            return json({
                workspaces, page: 1, page_size: DIRECTORY_BULK_PAGE_SIZE, total_count: statuses.length,
                public_directory: { schema_version: 1, can_create: false },
            });
        };
        const walked = await PUBLIC_DIRECTORY.listAllWorkspaces();
        assert.deepEqual(walked, [
            { id: 'ws-0', status: 'active' },
            { id: 'ws-1', status: 'inactive' },
            { id: 'ws-2', status: 'locked' },
            { id: 'ws-3', status: 'archived' },
        ], 'Every walked workspace carries its id and status.');
        // The bulk "show" would mark only these, never the inactive or archived ones.
        assert.deepEqual(chattableIds(walked), ['ws-0', 'ws-2']);
        assert.equal(calls.length, 1);
    });

    await checkAsync('listAllWorkspaces: refuses past the bound like the id-only walk', async () => {
        const calls = [];
        globalThis.fetch = serveDirectory(DIRECTORY_BULK_MAX_WORKSPACES + 1, DIRECTORY_BULK_PAGE_SIZE, calls);
        const refusal = await PUBLIC_DIRECTORY.listAllWorkspaces().catch((error) => error);
        assert.ok(refusal instanceof DirectoryBulkTooLargeError, 'A too-large directory is refused.');
        assert.equal(refusal.count, DIRECTORY_BULK_MAX_WORKSPACES + 1);
        assert.equal(calls.length, 1, 'It refuses on the first page, never fanning out.');
    });

    console.log(`${checks} public directory visibility checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
