// test_v2_documents_explorer_logic.ts
//
// Runtime test for the V2 documents explorer rules.
// Version: 0.261.048
// Implemented in: 0.261.048
//
// The companion test, test_v2_documents_explorer.py, asserts that the pieces are wired
// together: routes carry their decorators, settings keys are whitelisted, the section is
// registered on both sides. Those are source assertions and prove connection, not behaviour.
//
// This file executes the behaviour, because these failure modes are all quiet ones:
//
//   - A sort field the server does not accept is silently replaced with `_ts`, so a column
//     header would appear to sort and reorder by something else entirely.
//   - A filter change that does not reset the page lands on an empty page, which reads as
//     "you have no documents" rather than "you are past the end".
//   - A Shift+click range read from the selection rather than from the rendered order selects
//     a different set than the one under the pointer once the table is re-sorted.
//   - A selection not pruned after paging leaves ids in it that the user can no longer see,
//     which a Delete button would then act on.
//   - Tags arrive as objects, as arrays of strings, and as one comma-separated string, and
//     rendering the object form directly is what caused React error #31 on this page before.
//
// Run by test_v2_documents_explorer.py, which bundles this with the esbuild Vite already
// brings in and executes it under node, skipping it when the front-end toolchain is absent.
// Bundling rather than running directly is what resolves the extensionless import between
// documentSavedViews and documentExplorer.

import assert from 'node:assert/strict';
import {
    DEFAULT_DOCUMENT_QUERY,
    EMPTY_SELECTION,
    applyQueryChange,
    applySelection,
    batched,
    buildDocumentListParams,
    clearAllFilters,
    clearFilterChip,
    commonTags,
    describeActiveFilters,
    describePage,
    documentDisplayName,
    documentStatus,
    extractionMode,
    extractionModeLabel,
    formatFileSize,
    formatRelativeDate,
    moveSelection,
    normalizeSortField,
    normalizeTags,
    paginationItems,
    placeCount,
    pruneSelection,
    selectionIntentFromEvent,
    summarizeExtraction,
    supportsExtractionModeChange,
    toggleSelectAll,
    toggleSort,
    visiblePlaces,
} from '../application/v2_ui/src/lib/documentExplorer';
import {
    applySavedView,
    createSavedView,
    isSaveableQuery,
    matchesSavedView,
    parseSavedViews,
    removeSavedView,
    upsertSavedView,
} from '../application/v2_ui/src/lib/documentSavedViews';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

const query = (overrides: Record<string, unknown> = {}): any => ({ ...DEFAULT_DOCUMENT_QUERY, ...overrides });
const params = (input: string): Record<string, string> => Object.fromEntries(new URLSearchParams(input));

/* ------------------------------ query parameters ------------------------------ */

check('the default query asks for page one at the default size', () => {
    const result = params(buildDocumentListParams(query()));
    assert.equal(result.page, '1');
    assert.equal(result.page_size, '50');
    assert.equal(result.sort_by, '_ts');
    assert.equal(result.sort_order, 'desc');
});

check('empty filters are omitted rather than sent blank', () => {
    // A present-but-empty `search` filters on the empty string server-side, which matches
    // everything and only makes the request harder to read.
    const result = params(buildDocumentListParams(query({ search: '   ' })));
    assert.equal('search' in result, false);
    assert.equal('tags' in result, false);
    assert.equal('classification' in result, false);
    assert.equal('place' in result, false);
});

check('tags are sent comma separated and de-duplicated', () => {
    const result = params(
        buildDocumentListParams(query({ tags: ['alpha', 'beta', 'alpha'] })),
    );
    assert.equal(result.tags, 'alpha,beta');
});

check('the "all" place is not sent, every other place is', () => {
    assert.equal('place' in params(buildDocumentListParams(query({ place: 'all' }))), false);
    assert.equal(
        params(buildDocumentListParams(query({ place: 'untagged' }))).place,
        'untagged',
    );
});

check('a sort field the server does not accept falls back to _ts', () => {
    // ALLOWED_DOCUMENT_SORT_FIELDS in functions_documents.py silently replaces an unknown
    // field, so sending one would look like it sorted and quietly order by date instead.
    assert.equal(normalizeSortField('num_chunks'), '_ts');
    assert.equal(normalizeSortField('file_size'), 'file_size');
    assert.equal(params(buildDocumentListParams(query({ sortBy: 'nonsense' }))).sort_by, '_ts');
});

/* -------------------------------- query changes -------------------------------- */

check('narrowing the result set returns to page one', () => {
    for (const change of [
        { search: 'budget' },
        { tags: ['alpha'] },
        { classification: 'Internal' },
        { place: 'untagged' },
        { pageSize: 100 },
    ]) {
        const next = applyQueryChange(query({ page: 4 }), change);
        assert.equal(next.page, 1, `${JSON.stringify(change)} should reset the page`);
    }
});

check('paging itself does not reset the page', () => {
    assert.equal(applyQueryChange(query({ page: 1 }), { page: 3 }).page, 3);
});

check('a change that does not narrow anything keeps the page', () => {
    const next = applyQueryChange(query({ page: 4 }), { sortOrder: 'asc' });
    assert.equal(next.page, 4);
});

check('re-selecting the same tag list keeps the page', () => {
    const next = applyQueryChange(query({ page: 3, tags: ['alpha'] }), { tags: ['alpha'] });
    assert.equal(next.page, 3);
});

check('dates and sizes start descending, names start ascending', () => {
    // Newest-first and largest-first are the useful ends; A-Z is the useful end of a name.
    assert.equal(toggleSort(query(), 'file_size').sortOrder, 'desc');
    assert.equal(toggleSort(query(), 'upload_date').sortOrder, 'desc');
    assert.equal(toggleSort(query(), 'file_name').sortOrder, 'asc');
    assert.equal(toggleSort(query(), 'title').sortOrder, 'asc');
});

check('clicking the active column flips its direction', () => {
    const first = toggleSort(query(), 'file_name');
    const second = toggleSort(first, 'file_name');
    assert.equal(second.sortBy, 'file_name');
    assert.equal(second.sortOrder, 'desc');
});

/* --------------------------------- filter chips -------------------------------- */

check('every active filter is described as a chip', () => {
    const chips = describeActiveFilters(
        query({
            place: 'untagged',
            search: 'budget',
            tags: ['alpha', 'beta'],
            classification: 'Internal',
        }),
    );
    assert.deepEqual(
        chips.map((chip) => chip.kind),
        ['place', 'search', 'tag', 'tag', 'classification'],
    );
    assert.equal(chips[0].label, 'Untagged');
    assert.equal(chips[1].label, 'Search: budget');
});

check('an unfiltered query has no chips', () => {
    assert.equal(describeActiveFilters(query()).length, 0);
});

check('clearing one tag chip leaves the others alone', () => {
    const current = query({ tags: ['alpha', 'beta'], search: 'budget' });
    const next = clearFilterChip(current, { kind: 'tag', value: 'alpha', label: 'alpha' });
    assert.deepEqual(next.tags, ['beta']);
    assert.equal(next.search, 'budget');
});

check('clearing everything keeps the presentation but drops the filters', () => {
    const next = clearAllFilters(
        query({ place: 'recent', search: 'x', tags: ['a'], classification: 'C', sortBy: 'title' }),
    );
    assert.equal(next.place, 'all');
    assert.equal(next.search, '');
    assert.deepEqual(next.tags, []);
    assert.equal(next.classification, null);
    assert.equal(next.sortBy, 'title', 'sort is presentation, not a filter');
});

/* ----------------------------------- selection --------------------------------- */

const ids = ['a', 'b', 'c', 'd', 'e'];

check('modifier keys map to the expected intent', () => {
    assert.equal(selectionIntentFromEvent({}), 'replace');
    assert.equal(selectionIntentFromEvent({ ctrlKey: true }), 'toggle');
    assert.equal(selectionIntentFromEvent({ metaKey: true }), 'toggle');
    assert.equal(selectionIntentFromEvent({ shiftKey: true }), 'range');
});

check('a plain click selects one document and anchors there', () => {
    const next = applySelection(EMPTY_SELECTION, 'c', 'replace', ids);
    assert.deepEqual(next.ids, ['c']);
    assert.equal(next.anchorId, 'c');
});

check('ctrl-click adds and removes without losing the rest', () => {
    let selection = applySelection(EMPTY_SELECTION, 'b', 'replace', ids);
    selection = applySelection(selection, 'd', 'toggle', ids);
    assert.deepEqual(selection.ids, ['b', 'd']);
    selection = applySelection(selection, 'b', 'toggle', ids);
    assert.deepEqual(selection.ids, ['d']);
});

check('a ctrl-click selection stays in the order shown, not the order clicked', () => {
    let selection = applySelection(EMPTY_SELECTION, 'e', 'replace', ids);
    selection = applySelection(selection, 'a', 'toggle', ids);
    assert.deepEqual(selection.ids, ['a', 'e']);
});

check('shift-click selects the range between the anchor and the click', () => {
    const anchored = applySelection(EMPTY_SELECTION, 'b', 'replace', ids);
    assert.deepEqual(applySelection(anchored, 'd', 'range', ids).ids, ['b', 'c', 'd']);
});

check('a range works backwards from the anchor too', () => {
    const anchored = applySelection(EMPTY_SELECTION, 'd', 'replace', ids);
    assert.deepEqual(applySelection(anchored, 'b', 'range', ids).ids, ['b', 'c', 'd']);
});

check('a second shift-click replaces the range rather than growing it', () => {
    // This is what lets an over-long range be corrected by clicking nearer, instead of the
    // user having to start the selection again.
    const anchored = applySelection(EMPTY_SELECTION, 'a', 'replace', ids);
    const wide = applySelection(anchored, 'e', 'range', ids);
    assert.equal(wide.ids.length, 5);
    const narrowed = applySelection(wide, 'b', 'range', ids);
    assert.deepEqual(narrowed.ids, ['a', 'b']);
});

check('a range follows the order currently displayed', () => {
    // Re-sorting changes which documents lie between the anchor and the click. Reading the
    // order from the rendered list is what keeps the selection matching what is on screen.
    const reordered = ['e', 'd', 'c', 'b', 'a'];
    const anchored = applySelection(EMPTY_SELECTION, 'e', 'replace', reordered);
    assert.deepEqual(applySelection(anchored, 'c', 'range', reordered).ids, ['e', 'd', 'c']);
});

check('a range without an anchor falls back to selecting one row', () => {
    assert.deepEqual(applySelection(EMPTY_SELECTION, 'c', 'range', ids).ids, ['c']);
});

check('select-all toggles the whole page', () => {
    const all = toggleSelectAll(EMPTY_SELECTION, ids);
    assert.deepEqual(all.ids, ids);
    assert.deepEqual(toggleSelectAll(all, ids).ids, []);
});

check('a partial selection selects all rather than clearing', () => {
    const partial = { ids: ['a', 'b'], anchorId: 'a' };
    assert.deepEqual(toggleSelectAll(partial, ids).ids, ids);
});

check('documents no longer on the page drop out of the selection', () => {
    // Without this a bulk action taken after paging would apply to documents the user can no
    // longer see, which is exactly the surprise a Delete button must never produce.
    const selection = { ids: ['a', 'b', 'z'], anchorId: 'z' };
    const pruned = pruneSelection(selection, ids);
    assert.deepEqual(pruned.ids, ['a', 'b']);
    assert.equal(pruned.anchorId, 'a', 'the anchor moves to something still visible');
});

check('pruning nothing returns the same object', () => {
    const selection = { ids: ['a'], anchorId: 'a' };
    assert.equal(pruneSelection(selection, ids), selection);
});

check('arrow keys move the selection and shift extends it', () => {
    const start = applySelection(EMPTY_SELECTION, 'b', 'replace', ids);
    assert.deepEqual(moveSelection(start, ids, 1, false).ids, ['c']);
    assert.deepEqual(moveSelection(start, ids, 1, true).ids, ['b', 'c']);
    assert.deepEqual(moveSelection(start, ids, -1, false).ids, ['a']);
});

check('arrow keys stop at the ends of the list', () => {
    const first = applySelection(EMPTY_SELECTION, 'a', 'replace', ids);
    assert.deepEqual(moveSelection(first, ids, -1, false).ids, ['a']);
    const last = applySelection(EMPTY_SELECTION, 'e', 'replace', ids);
    assert.deepEqual(moveSelection(last, ids, 1, false).ids, ['e']);
});

/* ------------------------------------- tags ------------------------------------ */

check('tags are read from every shape the API returns', () => {
    // /api/documents/tags returns objects; a document carries strings, or one joined string.
    assert.deepEqual(normalizeTags(['alpha', ' beta ']), ['alpha', 'beta']);
    assert.deepEqual(normalizeTags('alpha, beta'), ['alpha', 'beta']);
    assert.deepEqual(normalizeTags([{ name: 'alpha' }, { name: ' beta ' }]), ['alpha', 'beta']);
    assert.deepEqual(normalizeTags(undefined), []);
    assert.deepEqual(normalizeTags(null), []);
    assert.deepEqual(normalizeTags(''), []);
});

check('only tags on every selected document count as shared', () => {
    const documents = [
        { tags: ['alpha', 'beta'] },
        { tags: ['beta', 'gamma'] },
        { tags: 'beta, delta' },
    ];
    assert.deepEqual(commonTags(documents), ['beta']);
});

check('no documents means no shared tags', () => {
    assert.deepEqual(commonTags([]), []);
});

/* ---------------------------------- status ------------------------------------- */

check('a complete document is ready', () => {
    assert.equal(documentStatus({ percentage_complete: 100 }).state, 'ready');
    assert.equal(documentStatus({ percentage_complete: 140 }).state, 'ready');
});

check('a document with no progress field at all is ready, not stuck', () => {
    // Records that predate progress tracking have no percentage. Showing them at 0% forever
    // would be worse than saying nothing.
    assert.equal(documentStatus({}).state, 'ready');
});

check('an error is detected from the status text at any percentage', () => {
    assert.equal(documentStatus({ status: 'Error: could not read file' }).state, 'error');
    assert.equal(
        documentStatus({ status: 'Error: x', percentage_complete: 100 }).state,
        'error',
    );
});

check('an in-flight document reports its percentage', () => {
    const status = documentStatus({ percentage_complete: 62, status: 'Saving page 3 of 5' });
    assert.equal(status.state, 'processing');
    assert.equal(status.percent, 62);
    assert.equal(status.label, '62%');
});

check('a document awaiting approval says so', () => {
    assert.equal(
        documentStatus({ percentage_complete: 100, shared_approval_status: 'not_approved' })
            .state,
        'pending_approval',
    );
});

/* ------------------------------- display name ---------------------------------- */

check('the title leads and the file name sits beneath it', () => {
    const name = documentDisplayName({ title: 'Q3 Budget', file_name: 'q3_FINAL(3).xlsx' });
    assert.equal(name.primary, 'Q3 Budget');
    assert.equal(name.secondary, 'q3_FINAL(3).xlsx');
});

check('without a title the file name is promoted rather than captioned', () => {
    const name = documentDisplayName({ file_name: 'notes.txt' });
    assert.equal(name.primary, 'notes.txt');
    assert.equal(name.secondary, null);
});

check('a title identical to the file name is not repeated', () => {
    const name = documentDisplayName({ title: 'notes.txt', file_name: 'notes.txt' });
    assert.equal(name.primary, 'notes.txt');
    assert.equal(name.secondary, null);
});

/* -------------------------------- formatting ----------------------------------- */

check('file sizes are formatted in binary units', () => {
    assert.equal(formatFileSize(0), '—');
    assert.equal(formatFileSize(undefined), '—');
    assert.equal(formatFileSize(900), '900 B');
    assert.equal(formatFileSize(1024), '1 KB');
    assert.equal(formatFileSize(1536), '1.5 KB');
    assert.equal(formatFileSize(5 * 1024 * 1024), '5 MB');
});

check('recent times are relative and older ones fall back to a date', () => {
    const now = new Date('2026-03-01T12:00:00Z');
    assert.equal(formatRelativeDate(new Date('2026-03-01T11:59:30Z'), now), 'Just now');
    assert.equal(formatRelativeDate(new Date('2026-03-01T11:30:00Z'), now), '30 min ago');
    assert.equal(formatRelativeDate(new Date('2026-03-01T09:00:00Z'), now), '3 hr ago');
    assert.equal(formatRelativeDate(new Date('2026-02-28T12:00:00Z'), now), 'Yesterday');
    assert.equal(formatRelativeDate(new Date('2026-02-20T12:00:00Z'), now), '9 days ago');
    assert.equal(formatRelativeDate(null, now), '—');
    // Beyond a month a relative label is harder to act on than the date itself.
    assert.notEqual(formatRelativeDate(new Date('2025-06-01T12:00:00Z'), now), '');
});

/* -------------------------------- pagination ----------------------------------- */

check('the status bar range counts the whole filtered set', () => {
    const range = describePage(2, 50, 142);
    assert.equal(range.from, 51);
    assert.equal(range.to, 100);
    assert.equal(range.total, 142);
    assert.equal(range.pageCount, 3);
});

check('the last page stops at the total', () => {
    const range = describePage(3, 50, 142);
    assert.equal(range.from, 101);
    assert.equal(range.to, 142);
});

check('an empty result set reports no items rather than a broken range', () => {
    const range = describePage(1, 50, 0);
    assert.equal(range.from, 0);
    assert.equal(range.to, 0);
    assert.equal(range.pageCount, 1);
});

check('a page beyond the end is clamped', () => {
    const range = describePage(99, 50, 60);
    assert.equal(range.from, 51);
    assert.equal(range.to, 60);
});

check('the pager keeps a stable width and marks its gaps', () => {
    assert.deepEqual(paginationItems(1, 3), [1, 2, 3]);

    // Counting the gap markers as slots is what makes the width constant. Sizing only the
    // numbers lets the control grow as the window leaves an edge, which moves the Next
    // button out from under the pointer on the very click that moved it.
    const widths = new Set<number>();
    for (let page = 1; page <= 20; page += 1) {
        const items = paginationItems(page, 20);
        widths.add(items.length);
        assert.equal(items[0], 1, 'the first page is always reachable');
        assert.equal(items[items.length - 1], 20, 'the last page is always reachable');
        assert.ok(items.includes(page), `page ${page} should be among its own items`);
    }
    assert.deepEqual([...widths], [7], 'every page renders the same number of slots');

    assert.deepEqual(paginationItems(1, 20), [1, 2, 3, 4, 5, null, 20]);
    assert.deepEqual(paginationItems(10, 20), [1, null, 9, 10, 11, null, 20]);
    assert.deepEqual(paginationItems(20, 20), [1, null, 16, 17, 18, 19, 20]);
});

/* ----------------------------------- facets ------------------------------------ */

const facets = {
    total: 142,
    untagged: 14,
    processing: 0,
    errors: 1,
    recent: 23,
    shared_with_me: 0,
    by_tag: { alpha: 12 },
    by_classification: { Internal: 30 },
};

check('rail counts come from the facets, not the page', () => {
    assert.equal(placeCount(facets, 'all'), 142);
    assert.equal(placeCount(facets, 'untagged'), 14);
    assert.equal(placeCount(facets, 'shared'), 0);
    assert.equal(placeCount(null, 'all'), null);
});

check('a place with nothing in it is not offered', () => {
    // Otherwise the rail carries a permanent "Processing 0" for a workspace at rest.
    const places = visiblePlaces(facets);
    assert.ok(places.includes('all'));
    assert.ok(places.includes('errors'));
    assert.ok(!places.includes('processing'));
    assert.ok(!places.includes('shared'));
    assert.deepEqual(visiblePlaces(null), ['all']);
});

/* --------------------------------- saved views --------------------------------- */

check('a view is only worth saving when it narrows something', () => {
    assert.equal(isSaveableQuery(query()), false);
    assert.equal(isSaveableQuery(query({ tags: ['alpha'] })), true);
    assert.equal(isSaveableQuery(query({ place: 'untagged' })), true);
    assert.equal(isSaveableQuery(query({ search: 'budget' })), true);
});

check('a saved view keeps the filters and drops the paging', () => {
    // Baking a page number into a saved view would make it land somewhere arbitrary later.
    const view = createSavedView('Contracts', query({ page: 4, tags: ['alpha'], sortBy: 'title' }));
    assert.equal(view.name, 'Contracts');
    assert.deepEqual(view.query.tags, ['alpha']);
    assert.equal('page' in view.query, false);
    assert.equal('sortBy' in view.query, false);
});

check('applying a view restores its filters and returns to page one', () => {
    const view = createSavedView('Contracts', query({ tags: ['alpha'], place: 'recent' }));
    const next = applySavedView(query({ page: 5, pageSize: 100 }), view);
    assert.deepEqual(next.tags, ['alpha']);
    assert.equal(next.place, 'recent');
    assert.equal(next.page, 1);
    assert.equal(next.pageSize, 100, 'presentation survives applying a view');
});

check('a view is marked active only when it matches exactly', () => {
    const view = createSavedView('Contracts', query({ tags: ['alpha'] }));
    assert.equal(matchesSavedView(query({ tags: ['alpha'], page: 3 }), view), true);
    assert.equal(matchesSavedView(query({ tags: ['alpha', 'beta'] }), view), false);
    assert.equal(matchesSavedView(query(), view), false);
});

check('stored views that are malformed are dropped rather than rendered', () => {
    // Settings are free-form JSON and writable by an older build, so they are untrusted.
    const parsed = parseSavedViews([
        null,
        'nonsense',
        { name: '' },
        { id: 'x', name: 'Good', query: { place: 'wat', tags: ['a', 'a', ''], search: ' b ' } },
    ]);
    assert.equal(parsed.length, 1);
    assert.equal(parsed[0].name, 'Good');
    assert.equal(parsed[0].query.place, 'all', 'an unknown place is coerced, not kept');
    assert.deepEqual(parsed[0].query.tags, ['a']);
    assert.equal(parsed[0].query.search, 'b');
    assert.equal(parsed[0].query.classification, null);
});

check('a non-array of views parses to nothing', () => {
    assert.deepEqual(parseSavedViews(undefined), []);
    assert.deepEqual(parseSavedViews({}), []);
});

check('saving a view under an existing name replaces it', () => {
    const first = createSavedView('Contracts', query({ tags: ['alpha'] }));
    const second = createSavedView('contracts', query({ tags: ['beta'] }));
    const views = upsertSavedView(upsertSavedView([], first), second);
    assert.equal(views.length, 1);
    assert.deepEqual(views[0].query.tags, ['beta']);
    assert.equal(views[0].id, first.id, 'the original entry keeps its identity');
});

check('a view can be removed', () => {
    const view = createSavedView('Contracts', query({ tags: ['alpha'] }));
    assert.deepEqual(removeSavedView([view], view.id), []);
});

/* --------------------------------- batching ------------------------------------ */

check('bulk work is split into fixed-size batches', () => {
    // Tagging costs a query, a write and a search-index update per document, so a single
    // request for a large selection ran long enough to be indistinguishable from a hang.
    assert.deepEqual(batched([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
    assert.deepEqual(batched([1, 2], 5), [[1, 2]]);
    assert.deepEqual(batched([], 5), []);
    assert.deepEqual(batched([1, 2, 3], 1), [[1], [2], [3]]);
});

check('a nonsense batch size still produces usable batches', () => {
    assert.deepEqual(batched([1, 2], 0), [[1], [2]]);
    assert.deepEqual(batched([1, 2], -3), [[1], [2]]);
});

/* ------------------------------ extraction mode --------------------------------- */

check('only PDFs and images can have their extraction mode changed', () => {
    // Anything else never goes through Document Intelligence, so offering the choice would
    // queue a job that changes nothing.
    assert.equal(supportsExtractionModeChange({ file_name: 'report.pdf' }), true);
    assert.equal(supportsExtractionModeChange({ file_name: 'SCAN.PDF' }), true);
    assert.equal(supportsExtractionModeChange({ file_name: 'photo.jpeg' }), true);
    assert.equal(supportsExtractionModeChange({ file_name: 'diagram.tiff' }), true);
    assert.equal(supportsExtractionModeChange({ file_name: 'notes.docx' }), false);
    assert.equal(supportsExtractionModeChange({ file_name: 'data.csv' }), false);
    assert.equal(supportsExtractionModeChange({}), false);
});

check('the current extraction mode is read back, or reported as unknown', () => {
    assert.equal(extractionMode({ document_intelligence_extraction_mode: 'layout' }), 'layout');
    assert.equal(extractionMode({ document_intelligence_extraction_mode: ' READ ' }), 'read');
    assert.equal(extractionMode({}), null);
    assert.equal(extractionMode({ document_intelligence_extraction_mode: 'other' }), null);
    assert.equal(extractionModeLabel('layout'), 'Enhanced');
    assert.equal(extractionModeLabel('read'), 'Standard');
    assert.equal(extractionModeLabel(null), 'Unknown');
});

check('a selection on one mode reports that mode', () => {
    // The pane previously offered Standard and Enhanced as two equal buttons without saying
    // which one the document was already on, so changing it meant guessing then checking.
    const summary = summarizeExtraction([
        { file_name: 'a.pdf', document_intelligence_extraction_mode: 'read' },
        { file_name: 'b.png', document_intelligence_extraction_mode: 'read' },
    ]);
    assert.equal(summary.current, 'read');
    assert.equal(summary.supported.length, 2);
    assert.equal(summary.unsupported.length, 0);
});

check('a selection on different modes reports mixed', () => {
    const summary = summarizeExtraction([
        { file_name: 'a.pdf', document_intelligence_extraction_mode: 'read' },
        { file_name: 'b.pdf', document_intelligence_extraction_mode: 'layout' },
    ]);
    assert.equal(summary.current, 'mixed');
});

check('a selection with no recorded mode is unknown, not mixed', () => {
    // These are different situations: mixed means switching changes some of them, unknown
    // means nothing is known about any of them.
    const summary = summarizeExtraction([{ file_name: 'a.pdf' }, { file_name: 'b.pdf' }]);
    assert.equal(summary.current, null);
});

check('documents the mode does not apply to are separated out', () => {
    const summary = summarizeExtraction([
        { file_name: 'a.pdf', document_intelligence_extraction_mode: 'layout' },
        { file_name: 'notes.docx' },
        { file_name: 'sheet.xlsx' },
    ]);
    assert.equal(summary.current, 'layout');
    assert.deepEqual(summary.supported.map((item) => item.file_name), ['a.pdf']);
    assert.deepEqual(
        summary.unsupported.map((item) => item.file_name),
        ['notes.docx', 'sheet.xlsx'],
    );
});

check('a selection of only unsupported documents offers nothing', () => {
    const summary = summarizeExtraction([{ file_name: 'notes.docx' }]);
    assert.equal(summary.supported.length, 0);
    assert.equal(summary.current, null);
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL  ${name}`);
        console.log(`      ${(error as Error).message}`);
        failed += 1;
    }
}

console.log(
    failed === 0
        ? `\nAll ${passed} checks passed.`
        : `\n${failed} of ${passed + failed} check(s) failed.`,
);
process.exit(failed > 0 ? 1 : 0);
