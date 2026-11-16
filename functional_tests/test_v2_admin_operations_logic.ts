// test_v2_admin_operations_logic.ts
//
// Runtime test for the decisions behind the V2 Operations settings.
// Version: 0.261.269
// Implemented in: 0.261.269
//
// The Operations readouts make claims an administrator will act on: who the Control Center
// admits under a pair of role switches, when a logging timer ends, whether a save would
// restart it, and when a daily refresh in another timezone next runs. Each mirrors a rule
// the server applies when it stores the value, so the cases below are the server's own --
// the DST answers are the ones test_control_center_auto_refresh_schedule.py pins for
// calculate_next_control_center_auto_refresh_run -- and a readout that drifted from them
// would be describing a schedule that does not exist.
//
// Run by test_v2_admin_operations_derivations.py, which bundles this with esbuild and executes
// it under node, skipping when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
    buildLogCleanupRequest,
    clampTimerValue,
    controlCenterAccess,
    describeLoggingTimer,
    describeRefreshSchedule,
    describeRestartState,
    findNavLocation,
    formatRelative,
    formatWallTime,
    nextDailyRun,
    readStoredInstant,
    safeHttpsUrl,
    safeSameOriginUrl,
    wallTimeToInstant,
} from '../application/v2_ui/src/lib/adminOperations';
import type { AdminLoggingTimerKeys } from '../application/v2_ui/src/lib/adminFields';
import type { AdminNavGroup } from '../application/v2_ui/src/lib/types';
import { ControlCenterAccessMatrix } from '../application/v2_ui/src/components/admin/ControlCenterAccessMatrix';
import { EndpointLinks } from '../application/v2_ui/src/components/admin/EndpointLinks';
import { RestartStatus } from '../application/v2_ui/src/components/admin/RestartStatus';
import { SettingsSection } from '../application/v2_ui/src/components/admin/SettingsSection';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

const DEBUG: AdminLoggingTimerKeys = {
    enabled_key: 'enable_debug_logging',
    timer_key: 'debug_logging_timer_enabled',
    value_key: 'debug_timer_value',
    unit_key: 'debug_timer_unit',
    turnoff_key: 'debug_logging_turnoff_time',
};

const NOW = new Date('2026-10-06T12:00:00Z');
const HOUR = 3_600_000;

// ---------------------------------------------------------------------------------------
// Control Center access
// ---------------------------------------------------------------------------------------

check('general Admins have full access until ControlCenterAdmin is required', () => {
    assert.deepEqual(controlCenterAccess(false, false), [
        { role: 'Admin', access: 'full' },
        { role: 'ControlCenterAdmin', access: 'none' },
        { role: 'ControlCenterDashboardReader', access: 'none' },
    ]);
});

check('requiring ControlCenterAdmin moves full access from Admin to the role', () => {
    const rows = controlCenterAccess(true, false);
    assert.equal(rows.find((row) => row.role === 'Admin')?.access, 'none');
    assert.equal(rows.find((row) => row.role === 'ControlCenterAdmin')?.access, 'full');
});

check('the dashboard reader role works whether or not ControlCenterAdmin is required', () => {
    for (const requireAdminRole of [false, true]) {
        const reader = controlCenterAccess(requireAdminRole, true).find(
            (row) => row.role === 'ControlCenterDashboardReader',
        );
        assert.equal(reader?.access, 'dashboard', `requireAdminRole=${requireAdminRole}`);
    }
});

// ---------------------------------------------------------------------------------------
// Logging timers
// ---------------------------------------------------------------------------------------

check('timer durations are clamped to their unit exactly as the server clamps them', () => {
    const cases: [unknown, unknown, number, string][] = [
        [0, 'minutes', 1, 'minutes'],
        [150, 'minutes', 120, 'minutes'],
        [30, 'hours', 24, 'hours'],
        [10, 'days', 7, 'days'],
        [100, 'weeks', 52, 'weeks'],
        [2.7, 'hours', 2, 'hours'],
        ['not a number', 'hours', 1, 'hours'],
        [true, 'hours', 1, 'hours'],
        [5, 'fortnights', 5, 'hours'],
        [5, 'constructor', 5, 'hours'],
    ];
    for (const [value, unit, expectedValue, expectedUnit] of cases) {
        assert.deepEqual(clampTimerValue(value, unit), { value: expectedValue, unit: expectedUnit }, `${value} ${unit}`);
    }
});

check('a log that is off, or has no timer, reports that rather than a time', () => {
    assert.deepEqual(describeLoggingTimer(DEBUG, { enable_debug_logging: false }, {}, NOW), { kind: 'off' });
    assert.deepEqual(
        describeLoggingTimer(DEBUG, { enable_debug_logging: true, debug_logging_timer_enabled: false }, {}, NOW),
        { kind: 'no-timer' },
    );
});

check('changing the duration says the clock restarts on save', () => {
    const settings = {
        enable_debug_logging: true,
        debug_logging_timer_enabled: true,
        debug_timer_value: 1,
        debug_timer_unit: 'hours',
        debug_logging_turnoff_time: '2026-10-06T12:30:00+00:00',
    };
    const readout = describeLoggingTimer(DEBUG, settings, { debug_timer_value: 3 }, NOW);
    assert.equal(readout.kind, 'on-save');
    assert.ok(readout.kind === 'on-save');
    assert.equal(readout.reason, 'changed');
    assert.equal(readout.projected.getTime(), NOW.getTime() + 3 * HOUR);
});

check('switching a log on restarts its timer from the save', () => {
    const settings = {
        enable_debug_logging: false,
        debug_logging_timer_enabled: true,
        debug_timer_value: 2,
        debug_timer_unit: 'hours',
    };
    const readout = describeLoggingTimer(DEBUG, settings, { enable_debug_logging: true }, NOW);
    assert.ok(readout.kind === 'on-save');
    assert.equal(readout.reason, 'enabling');
    assert.equal(readout.projected.getTime(), NOW.getTime() + 2 * HOUR);
});

check('a saved timer with nothing stored is reported as not yet started', () => {
    const settings = {
        enable_debug_logging: true,
        debug_logging_timer_enabled: true,
        debug_timer_value: 1,
        debug_timer_unit: 'hours',
        debug_logging_turnoff_time: null,
    };
    const readout = describeLoggingTimer(DEBUG, settings, {}, NOW);
    assert.ok(readout.kind === 'on-save');
    assert.equal(readout.reason, 'missing');
});

check('a stored UTC turnoff is shown as scheduled, or overdue once passed', () => {
    const base = {
        enable_debug_logging: true,
        debug_logging_timer_enabled: true,
        debug_timer_value: 1,
        debug_timer_unit: 'hours',
    };
    const future = describeLoggingTimer(
        DEBUG,
        { ...base, debug_logging_turnoff_time: '2026-10-06T13:00:00.123456+00:00' },
        {},
        NOW,
    );
    assert.ok(future.kind === 'scheduled');
    assert.equal(future.at.toISOString(), '2026-10-06T13:00:00.123Z');

    const past = describeLoggingTimer(DEBUG, { ...base, debug_logging_turnoff_time: '2026-10-06T11:59:00Z' }, {}, NOW);
    assert.equal(past.kind, 'overdue');
});

check('an unrelated edit keeps the stored turnoff, as the server does', () => {
    const settings = {
        enable_debug_logging: true,
        debug_logging_timer_enabled: true,
        debug_timer_value: 1,
        debug_timer_unit: 'hours',
        debug_logging_turnoff_time: '2026-10-06T13:00:00+00:00',
    };
    const readout = describeLoggingTimer(DEBUG, settings, { app_title: 'Renamed' }, NOW);
    assert.equal(readout.kind, 'scheduled');
});

check('a turnoff written before UTC storage is shown as written, not guessed at', () => {
    const settings = {
        enable_debug_logging: true,
        debug_logging_timer_enabled: true,
        debug_timer_value: 1,
        debug_timer_unit: 'hours',
        debug_logging_turnoff_time: '2026-01-22T11:05:44.417753',
    };
    assert.deepEqual(describeLoggingTimer(DEBUG, settings, {}, NOW), {
        kind: 'legacy',
        text: '2026-01-22T11:05:44.417753',
    });
});

check('stored instants are read the way the server writes them', () => {
    assert.deepEqual(readStoredInstant(null), { kind: 'none' });
    assert.deepEqual(readStoredInstant('   '), { kind: 'none' });
    assert.deepEqual(readStoredInstant('not-a-date+00:00'), { kind: 'none' });
    const zulu = readStoredInstant('2026-10-06T12:00:00Z');
    assert.ok(zulu.kind === 'instant');
    assert.equal(zulu.at.toISOString(), '2026-10-06T12:00:00.000Z');
    const offset = readStoredInstant('2026-10-06T14:00:00.999999+02:00');
    assert.ok(offset.kind === 'instant');
    assert.equal(offset.at.toISOString(), '2026-10-06T12:00:00.999Z');
});

// ---------------------------------------------------------------------------------------
// The daily Control Center refresh
// ---------------------------------------------------------------------------------------

check('next runs match the server across daylight saving, including the gap', () => {
    const cases: [string, string, string][] = [
        // The four cases test_control_center_auto_refresh_schedule.py pins in Python.
        ['2026-01-15T06:30:00Z', '02:00', '2026-01-15T07:00:00.000Z'],
        ['2026-07-15T05:30:00Z', '02:00', '2026-07-15T06:00:00.000Z'],
        ['2026-03-08T06:30:00Z', '02:00', '2026-03-08T07:00:00.000Z'],
        ['2026-11-01T06:30:00Z', '02:00', '2026-11-01T07:00:00.000Z'],
        // Today's run has passed, so tomorrow's at the same wall-clock time.
        ['2026-01-15T08:00:00Z', '02:00', '2026-01-16T07:00:00.000Z'],
    ];
    for (const [now, time, expected] of cases) {
        assert.equal(nextDailyRun(time, 'America/New_York', new Date(now))?.toISOString(), expected, now);
    }
});

check('a wall time that happens twice resolves to its first occurrence', () => {
    // 01:30 on the November change happens at 05:30Z (EDT) and again at 06:30Z (EST).
    assert.equal(
        wallTimeToInstant('America/New_York', 2026, 11, 1, 1, 30).toISOString(),
        '2026-11-01T05:30:00.000Z',
    );
});

check('a schedule in another zone matches the server, which stored 01:30 UTC for 03:30 Paris', () => {
    assert.equal(
        nextDailyRun('03:30', 'Europe/Paris', new Date('2026-10-06T21:15:59Z'))?.toISOString(),
        '2026-10-07T01:30:00.000Z',
    );
});

check('an unreadable time or zone projects nothing', () => {
    assert.equal(nextDailyRun('25:00', 'America/New_York', NOW), null);
    assert.equal(nextDailyRun('02:00', 'Mars/Olympus', NOW), null);
});

check('the schedule readout follows unsaved edits and keeps the stored run otherwise', () => {
    const saved = {
        control_center_auto_refresh_enabled: true,
        control_center_auto_refresh_time: '02:00',
        control_center_auto_refresh_timezone: 'America/New_York',
        control_center_auto_refresh_next_run: '2026-10-07T06:00:00+00:00',
    };
    const scheduled = describeRefreshSchedule(saved, {}, NOW);
    assert.ok(scheduled.kind === 'scheduled');
    assert.equal(scheduled.at.toISOString(), '2026-10-07T06:00:00.000Z');

    const edited = describeRefreshSchedule(saved, { control_center_auto_refresh_time: '04:15' }, NOW);
    assert.ok(edited.kind === 'on-save');
    assert.equal(edited.projected?.toISOString(), '2026-10-07T08:15:00.000Z');

    // The browser's time input may submit seconds; 02:00:00 is the same schedule.
    assert.equal(describeRefreshSchedule(saved, { control_center_auto_refresh_time: '02:00:00' }, NOW).kind, 'scheduled');

    assert.deepEqual(describeRefreshSchedule(saved, { control_center_auto_refresh_enabled: false }, NOW), { kind: 'off' });
    assert.equal(
        describeRefreshSchedule({ ...saved, control_center_auto_refresh_next_run: null }, {}, NOW).kind,
        'unscheduled',
    );
    assert.equal(
        describeRefreshSchedule({ ...saved, control_center_auto_refresh_next_run: '2026-10-06T06:00:00Z' }, {}, NOW).kind,
        'overdue',
    );
});

check('a schedule with no stored values reads as the seeded default, which is on', () => {
    const readout = describeRefreshSchedule({}, {}, NOW);
    assert.ok(readout.kind === 'unscheduled');
    assert.equal(readout.time, '02:00');
    assert.equal(readout.timezone, 'America/New_York');
});

// ---------------------------------------------------------------------------------------
// Restart-bound settings, cleanup and links
// ---------------------------------------------------------------------------------------

check('a startup-bound setting reports save, restart, and in-sync states', () => {
    assert.deepEqual(describeRestartState({ saved: true, draft: true, running: true, available: true }), {
        kind: 'in-sync',
        running: true,
    });
    assert.deepEqual(describeRestartState({ saved: true, draft: true, running: false, available: true }), {
        kind: 'restart',
        saved: true,
        running: false,
    });
    assert.deepEqual(describeRestartState({ saved: false, draft: true, running: false, available: true }), {
        kind: 'save-then-restart',
        next: true,
    });
    assert.deepEqual(describeRestartState({ saved: true, draft: true, running: false, available: false }), {
        kind: 'unavailable',
    });
});

check('the cleanup request states exactly what will be deleted', () => {
    assert.deepEqual(buildLogCleanupRequest('all', '', 'days'), {
        request: { delete_all: true },
        confirmation: 'Delete every stored file processing log?',
    });
    assert.deepEqual(buildLogCleanupRequest('older', '30', 'days'), {
        request: { delete_all: false, age: 30, unit: 'days' },
        confirmation: 'Delete every file processing log older than 30 days?',
    });
    assert.deepEqual(buildLogCleanupRequest('older', '1', 'months'), {
        request: { delete_all: false, age: 1, unit: 'months' },
        confirmation: 'Delete every file processing log older than 1 month?',
    });
    for (const age of ['', '0', '-2', '1.5', 'ten']) {
        assert.ok('error' in buildLogCleanupRequest('older', age, 'days'), `age ${age}`);
    }
    assert.ok('error' in buildLogCleanupRequest('older', '3', 'years'));
});

check('a related section resolves to the tab the classic page addresses', () => {
    const nav: AdminNavGroup[] = [
        {
            id: 'scale',
            label: 'Scale',
            tabs: [
                {
                    id: 'cosmos',
                    label: 'Cosmos',
                    sections: [{ id: 'document-access-index-section', label: 'DAI Metrics' }],
                },
            ],
        },
    ];
    assert.deepEqual(findNavLocation(nav, 'document-access-index-section'), {
        groupLabel: 'Scale',
        tabId: 'cosmos',
        tabLabel: 'Cosmos',
        sectionLabel: 'DAI Metrics',
    });
    assert.equal(findNavLocation(nav, 'missing-section'), null);
});

check('endpoint addresses are absolute on this deployment, and never leave it', () => {
    const origin = 'https://chat.contoso.com';
    assert.equal(safeSameOriginUrl('/external/healthcheck', origin), `${origin}/external/healthcheck`);
    // A path that resolves elsewhere is refused rather than linked.
    assert.equal(safeSameOriginUrl('//attacker.example/external/healthcheck', origin), null);
    assert.equal(safeSameOriginUrl('https://attacker.example/external/healthcheck', origin), null);
    assert.equal(safeSameOriginUrl('javascript:alert(1)', origin), null);
    assert.equal(safeSameOriginUrl('http://chat.contoso.com/external/healthcheck', origin), null);
});

check('outside links are kept only when they are plain HTTPS', () => {
    const docs = 'https://microsoft.github.io/simplechat/admin/operations/#health-check-section';
    assert.equal(safeHttpsUrl(docs), docs);
    assert.equal(safeHttpsUrl('javascript:alert(1)'), null);
    assert.equal(safeHttpsUrl('http://microsoft.github.io/simplechat/'), null);
    assert.equal(safeHttpsUrl('https://user:secret@example.com/'), null);
    assert.equal(safeHttpsUrl('/admin/operations/'), null);
    assert.equal(safeHttpsUrl(undefined), null);
});

check('relative times round the way people read them', () => {
    const at = (offsetMs: number) => new Date(NOW.getTime() + offsetMs);
    // Pinned to English so the wording is checkable; the page uses the reader's locale.
    const english = (target: Date) => formatRelative(target, NOW, 'en-US');
    assert.equal(english(at(HOUR - 1_000)), 'in 1 hour');
    assert.equal(english(at(10 * 60_000)), 'in 10 minutes');
    assert.equal(english(at(-3 * HOUR)), '3 hours ago');
    assert.equal(english(at(23 * HOUR)), 'tomorrow');
    assert.equal(english(at(5 * 24 * HOUR)), 'in 5 days');
});

check('a schedule time reads the way the time picker shows it', () => {
    // ICU may separate "AM" with a narrow no-break space; the words are what matter.
    const english = (time: unknown) => formatWallTime(time, 'en-US').replace(/\s/g, ' ');
    assert.equal(english('02:00'), '2:00 AM');
    assert.equal(english('14:30'), '2:30 PM');
    assert.equal(formatWallTime('14:30', 'en-GB'), '14:30');
    // An unreadable value is shown as stored rather than as a guess.
    assert.equal(formatWallTime('later', 'en-US'), 'later');
});

// ---------------------------------------------------------------------------------------
// Rendered output
// ---------------------------------------------------------------------------------------

check('the access table reads the switches and offers each role value to copy', () => {
    const markup = renderToStaticMarkup(
        createElement(ControlCenterAccessMatrix, {
            label: 'Who can open the Control Center',
            requireAdminRole: true,
            allowDashboardReader: true,
            unsaved: true,
        }),
    );
    assert.match(markup, /<table/);
    assert.match(markup, /Copy the ControlCenterAdmin role value/);
    assert.match(markup, /Admin cannot use the dashboard/);
    assert.match(markup, /ControlCenterDashboardReader can use the dashboard/);
    assert.match(markup, /Showing your unsaved changes/);
});

check('a restart readout stays quiet when the setting cannot take effect at all', () => {
    const quiet = renderToStaticMarkup(
        createElement(RestartStatus, { label: 'Running state', saved: true, draft: true, running: false, available: false }),
    );
    assert.equal(quiet, '');
    const pending = renderToStaticMarkup(
        createElement(RestartStatus, { label: 'Running state', saved: true, draft: true, running: false, available: true }),
    );
    assert.match(pending, /Restart the App Service/);
});

check('endpoint rows offer Open only while the endpoint answers', () => {
    (globalThis as { window?: unknown }).window = { location: { origin: 'https://chat.contoso.com' } };
    const markup = renderToStaticMarkup(
        createElement(EndpointLinks, {
            label: 'Endpoints',
            endpoints: [
                { path: '/external/healthcheck', label: 'Authenticated check', gate_key: 'on_key', access: 'protected' },
                { path: '/external/healthcheckz', label: 'Unauthenticated check', gate_key: 'off_key', access: 'public' },
            ],
            isSavedOn: (key: string) => key === 'on_key',
            isDraftOn: (key: string) => key === 'on_key',
            runtimeFlags: {},
        }),
    );
    assert.ok(
        markup.includes('href="https://chat.contoso.com/external/healthcheck"'),
        'The live endpoint should link to its full address on this deployment.',
    );
    assert.equal((markup.match(/>Open</g) ?? []).length, 1);
    assert.match(markup, /No sign-in/);
});

check('a section with a guide offers it from the header', () => {
    const markup = renderToStaticMarkup(
        createElement(SettingsSection, {
            sectionId: 'health-check-section',
            label: 'Health Check',
            groupLabel: 'Operations',
            tabLabel: 'Logging & Health',
            fields: [],
            settings: {},
            draft: {},
            renderField: () => null,
            renderCapability: () => null,
            guide: { label: 'Configuration guide', onOpen: () => undefined },
        }),
    );
    assert.match(markup, /aria-haspopup="dialog"[^>]*>.*Configuration guide/);
});

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
