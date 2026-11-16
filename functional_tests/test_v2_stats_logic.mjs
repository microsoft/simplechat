// test_v2_stats_logic.mjs
//
// Runtime test for the V2 stats tab's pure logic.
// Version: 0.261.041
// Implemented in: 0.261.041
//
// The companion test, test_v2_stats_parity.py, asserts that the tab and the routes agree on
// names. Those are source assertions: they prove the pieces are wired together, not that they
// behave. This file executes the parts where a quiet mistake produces a page that renders
// perfectly and states something false -- a window sent as the wrong pair of parameters, a
// series drawn against the wrong dates, or an export whose columns have slipped by one.
//
// Run directly with `node functional_tests/test_v2_stats_logic.mjs`. Requires Node 22.6 or
// newer, which strips the TypeScript types so the real module is imported rather than a copy.

import assert from 'node:assert/strict';
import {
    DEFAULT_EXPORT_SECTIONS,
    STATS_WINDOWS,
    activityCsvFileName,
    alignSeries,
    buildActivityCsv,
    formatBytes,
    formatCompactNumber,
    formatDisplayDate,
    formatRelativeTime,
    formatShortDate,
    isCustomWindow,
    lastDays,
    resolveDateRange,
    statsWindowLabel,
    statsWindowQuery,
    sumSeries,
    validateCustomRange,
} from '../application/v2_ui/src/lib/userStats.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/* ------------------------------- the window -------------------------------- */

check('a preset window sends days and nothing else', () => {
    const query = new URLSearchParams(statsWindowQuery({ days: 7, startDate: '', endDate: '' }));
    assert.equal(query.get('days'), '7');
    assert.equal(query.get('start_date'), null);
    assert.equal(query.get('end_date'), null);
});

check('a custom window sends dates and not days', () => {
    // resolve_stats_time_window branches on the presence of either date and ignores `days`
    // in that branch. Sending both would let the two disagree with no way to tell which won.
    const query = new URLSearchParams(
        statsWindowQuery({ days: 5, startDate: '2026-01-01', endDate: '2026-01-05' }),
    );
    assert.equal(query.get('start_date'), '2026-01-01');
    assert.equal(query.get('end_date'), '2026-01-05');
    assert.equal(query.get('days'), null);
});

check('only the presets the route accepts are offered', () => {
    // Mirrors ALLOWED_STATS_WINDOW_DAYS. An unrecognised count is not rejected by the
    // server, it silently becomes 30, so the tab would highlight a window it is not showing.
    assert.deepEqual(
        STATS_WINDOWS.map((window) => window.days),
        [7, 30, 90],
    );
});

check('a custom window is recognised only when both dates are present', () => {
    assert.equal(isCustomWindow({ days: 30, startDate: '', endDate: '' }), false);
    assert.equal(isCustomWindow({ days: 30, startDate: '2026-01-01', endDate: '' }), false);
    assert.equal(
        isCustomWindow({ days: 3, startDate: '2026-01-01', endDate: '2026-01-03' }),
        true,
    );
});

/* ---------------------------- range validation ----------------------------- */

check('a range missing a date is refused', () => {
    const result = validateCustomRange('2026-01-01', '');
    assert.equal(result.ok, false);
    assert.match(result.error, /both/i);
});

check('a reversed range is refused before it is sent', () => {
    // The server answers this with a 400. Catching it here is what turns "request failed"
    // into a sentence about the dates the user just typed.
    const result = validateCustomRange('2026-02-10', '2026-02-01');
    assert.equal(result.ok, false);
    assert.match(result.error, /start date/i);
});

check('a valid range counts both end days', () => {
    const result = validateCustomRange('2026-01-01', '2026-01-05');
    assert.equal(result.ok, true);
    // Inclusive of both ends, matching the resolver's (end - start).days + 1.
    assert.equal(result.window.days, 5);
    assert.equal(result.window.startDate, '2026-01-01');
});

check('a single-day range is one day, not zero', () => {
    const result = validateCustomRange('2026-03-04', '2026-03-04');
    assert.equal(result.ok, true);
    assert.equal(result.window.days, 1);
});

check('a nonsense date is refused rather than sent as NaN', () => {
    const result = validateCustomRange('not-a-date', '2026-01-05');
    assert.equal(result.ok, false);
});

/* ------------------------------- the labels -------------------------------- */

check('a preset window is labelled by its length', () => {
    assert.equal(statsWindowLabel({ days: 90, startDate: '', endDate: '' }), 'Last 90 Days');
});

check('a custom window is labelled by its dates, matching the server format', () => {
    // functions_stats_windows._format_display_date writes M/D/YYYY with no zero padding.
    assert.equal(
        statsWindowLabel({ days: 3, startDate: '2026-01-01', endDate: '2026-01-03' }),
        '1/1/2026 - 1/3/2026',
    );
    assert.equal(formatDisplayDate('2026-12-25'), '12/25/2026');
});

check('axis labels are month and day only', () => {
    assert.equal(formatShortDate('2026-07-04'), '7/4');
});

/* ----------------------------- series alignment ---------------------------- */

check('a sparse series is placed on its own dates', () => {
    // The server normally returns every day, but relying on that would let values be drawn
    // against whatever label sat at the same index if it ever stopped.
    const range = ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04'];
    const series = [
        { date: '2026-01-03', count: 5 },
        { date: '2026-01-01', count: 2 },
    ];
    assert.deepEqual(alignSeries(series, range), [2, 0, 5, 0]);
});

check('a day outside the window is not drawn', () => {
    const range = ['2026-01-01', '2026-01-02'];
    const series = [
        { date: '2026-01-02', count: 4 },
        { date: '2025-12-31', count: 99 },
    ];
    assert.deepEqual(alignSeries(series, range), [0, 4]);
});

check('the token series is read by its own key', () => {
    // Token days carry `tokens`; every other series carries `count`. Reading the wrong one
    // yields a chart of zeroes rather than an error.
    const range = ['2026-01-01', '2026-01-02'];
    const series = [
        { date: '2026-01-01', tokens: 1200 },
        { date: '2026-01-02', tokens: 800 },
    ];
    assert.deepEqual(alignSeries(series, range, 'tokens'), [1200, 800]);
    assert.deepEqual(alignSeries(series, range), [0, 0]);
});

check('an absent series is zeroes, not a crash', () => {
    assert.deepEqual(alignSeries(undefined, ['2026-01-01']), [0]);
    assert.equal(sumSeries(undefined), 0);
});

check('totals add the whole series', () => {
    assert.equal(
        sumSeries([
            { date: 'a', count: 3 },
            { date: 'b', count: 4 },
        ]),
        7,
    );
    assert.equal(sumSeries([{ date: 'a', tokens: 10 }], 'tokens'), 10);
});

check('the date range prefers the server and falls back to a local one', () => {
    const supplied = { dateRange: ['2026-01-01', '2026-01-02'] };
    assert.deepEqual(resolveDateRange(supplied, { days: 30, startDate: '', endDate: '' }), [
        '2026-01-01',
        '2026-01-02',
    ]);
    assert.equal(resolveDateRange(null, { days: 7, startDate: '', endDate: '' }).length, 7);
    assert.equal(lastDays(1).length, 1);
});

/* ------------------------------- formatting -------------------------------- */

check('large counts are abbreviated the way the classic cards abbreviate them', () => {
    assert.equal(formatCompactNumber(999), '999');
    assert.equal(formatCompactNumber(1500), '1.5K');
    assert.equal(formatCompactNumber(2400000), '2.4M');
    assert.equal(formatCompactNumber(0), '0');
});

check('storage sizes are scaled to a readable unit', () => {
    assert.equal(formatBytes(0), '0 Bytes');
    assert.equal(formatBytes(1024), '1 KB');
    assert.equal(formatBytes(1536), '1.5 KB');
    assert.equal(formatBytes(5 * 1024 ** 3), '5 GB');
});

check('an absent timestamp reads as never, not as the epoch', () => {
    assert.equal(formatRelativeTime(undefined), 'Never');
    assert.equal(formatRelativeTime(''), 'Never');
    assert.equal(formatRelativeTime('not a date'), 'Unknown');
});

check('recency is described in the largest useful unit', () => {
    const now = new Date('2026-06-15T12:00:00Z');
    assert.equal(formatRelativeTime('2026-06-15T11:59:40Z', now), 'Just now');
    assert.equal(formatRelativeTime('2026-06-15T11:30:00Z', now), '30 min ago');
    assert.equal(formatRelativeTime('2026-06-15T08:00:00Z', now), '4 hr ago');
    assert.equal(formatRelativeTime('2026-06-13T12:00:00Z', now), '2 days ago');
    assert.equal(formatRelativeTime('2026-06-14T12:00:00Z', now), '1 day ago');
});

/* --------------------------------- export ---------------------------------- */

const trends = {
    logins: [
        { date: '2026-01-01', count: 2 },
        { date: '2026-01-02', count: 0 },
    ],
    conversations: {
        creates: [
            { date: '2026-01-01', count: 3 },
            { date: '2026-01-02', count: 1 },
        ],
        deletes: [{ date: '2026-01-02', count: 2 }],
    },
    documents: {
        uploads: [{ date: '2026-01-01', count: 4 }],
        deletes: [{ date: '2026-01-01', count: 1 }],
    },
    tokens: [{ date: '2026-01-01', tokens: 12345 }],
};

const metrics = {
    calculated_at: '2026-01-02T09:00:00Z',
    login_metrics: { total_logins: 11, last_login: '2026-01-02T08:00:00Z' },
    chat_metrics: { total_conversations: 5, total_messages: 42, total_message_size: 8192 },
    document_metrics: { total_documents: 7, ai_search_size: 1024, storage_account_size: 2048 },
};

function exportCsv(sections = DEFAULT_EXPORT_SECTIONS) {
    return buildActivityCsv({
        trends,
        metrics,
        sections,
        userName: 'Ada Lovelace',
        userEmail: 'ada@example.com',
        windowLabel: '1/1/2026 - 1/2/2026',
        exportedAt: new Date('2026-01-02T10:00:00Z'),
    });
}

check('the export carries every section the classic one does', () => {
    const csv = exportCsv();
    for (const heading of [
        'User Activity Export',
        'SUMMARY METRICS',
        'LOGIN ACTIVITY (1/1/2026 - 1/2/2026)',
        'CONVERSATION ACTIVITY (1/1/2026 - 1/2/2026)',
        'DOCUMENT ACTIVITY (1/1/2026 - 1/2/2026)',
        'TOKEN USAGE (1/1/2026 - 1/2/2026)',
    ]) {
        assert.ok(csv.includes(heading), `missing section: ${heading}`);
    }
});

check('deletes are joined to their own date, not to the row position', () => {
    // The deletes series is shorter than the creates series here. Zipping by index would
    // report the 2nd's deletions against the 1st.
    const csv = exportCsv();
    const lines = csv.split('\n');
    const conversationHeader = lines.findIndex((line) =>
        line.startsWith('CONVERSATION ACTIVITY'),
    );
    assert.equal(lines[conversationHeader + 1], 'Date,Conversations Created,Conversations Deleted');
    assert.equal(lines[conversationHeader + 2], '2026-01-01,3,0');
    assert.equal(lines[conversationHeader + 3], '2026-01-02,1,2');
});

check('an unselected section is left out entirely', () => {
    const csv = exportCsv({
        metrics: false,
        logins: false,
        conversations: true,
        documents: false,
        tokens: false,
    });
    assert.ok(!csv.includes('SUMMARY METRICS'));
    assert.ok(!csv.includes('LOGIN ACTIVITY'));
    assert.ok(!csv.includes('DOCUMENT ACTIVITY'));
    assert.ok(!csv.includes('TOKEN USAGE'));
    assert.ok(csv.includes('CONVERSATION ACTIVITY'));
});

check('the summary carries the totals and the stamp that qualifies them', () => {
    const csv = exportCsv();
    assert.ok(csv.includes('Total Logins,11'));
    assert.ok(csv.includes('Total Conversations,5'));
    assert.ok(csv.includes('Total Messages,42'));
    assert.ok(csv.includes('Total Documents,7'));
    assert.ok(csv.includes('AI Search Size (bytes),1024'));
    assert.ok(csv.includes('Storage Size (bytes),2048'));
    assert.ok(csv.includes('Metrics Calculated At,2026-01-02T09:00:00Z'));
});

check('token rows carry tokens rather than counts', () => {
    const csv = exportCsv();
    assert.ok(csv.includes('Date,Total Tokens'));
    assert.ok(csv.includes('2026-01-01,12345'));
});

check('a name containing a comma does not shift the columns', () => {
    const csv = buildActivityCsv({
        trends: {},
        metrics: {},
        sections: { ...DEFAULT_EXPORT_SECTIONS, metrics: false },
        userName: 'Lovelace, Ada',
        userEmail: 'ada@example.com',
        windowLabel: 'Last 30 Days',
        exportedAt: new Date('2026-01-02T10:00:00Z'),
    });
    assert.ok(csv.includes('User,"Lovelace, Ada"'));
});

check('a quote in a field is doubled rather than ending it', () => {
    const csv = buildActivityCsv({
        trends: {},
        metrics: {},
        sections: { ...DEFAULT_EXPORT_SECTIONS, metrics: false },
        userName: 'Ada "The Countess" Lovelace',
        userEmail: 'ada@example.com',
        windowLabel: 'Last 30 Days',
        exportedAt: new Date('2026-01-02T10:00:00Z'),
    });
    assert.ok(csv.includes('User,"Ada ""The Countess"" Lovelace"'));
});

check('an empty response produces a header-only file rather than throwing', () => {
    const csv = buildActivityCsv({
        trends: {},
        metrics: {},
        sections: DEFAULT_EXPORT_SECTIONS,
        userName: 'Ada',
        userEmail: 'ada@example.com',
        windowLabel: 'Last 7 Days',
        exportedAt: new Date('2026-01-02T10:00:00Z'),
    });
    assert.ok(csv.startsWith('User Activity Export'));
    assert.ok(!csv.includes('LOGIN ACTIVITY'));
});

check('the file name is dated so successive exports do not collide', () => {
    assert.equal(
        activityCsvFileName(new Date('2026-01-02T10:00:00Z')),
        'activity_export_2026-01-02.csv',
    );
});

/* ---------------------------------- runner --------------------------------- */

let failures = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failures += 1;
        console.error(`FAIL  ${name}`);
        console.error(`      ${error.message}`);
    }
}

console.log(`\nResults: ${checks.length - failures}/${checks.length} checks passed`);
process.exit(failures === 0 ? 0 : 1);
