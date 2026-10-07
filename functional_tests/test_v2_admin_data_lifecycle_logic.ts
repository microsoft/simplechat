// test_v2_admin_data_lifecycle_logic.ts
//
// Runtime checks for the V2 Admin Settings Data Lifecycle controls.
// Version: 0.261.260
// Implemented in: 0.261.260
//
// The decisions behind Retention Policy and Document Classification are easy to get
// subtly wrong and invisible in a screenshot: whether an unsaved edit holds a run, which
// workspace types a run may touch, whether a save will move the next run, what an hour or
// a stored timestamp reads as, how a run's response is summarised, and which category row
// a problem belongs to. They are executed here, and the components are rendered to markup
// to prove the held and empty states actually reach the page.
//
// Run by test_v2_admin_data_lifecycle_parity.py, which bundles this with the esbuild Vite
// already brings in and executes it under node, skipping when the front-end toolchain is
// absent.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    CONVERSATION_ARCHIVING_KEY,
    RETENTION_RUN_KEYS,
    RETENTION_SCHEDULE_KEYS,
    RETENTION_SETTING_KEYS,
    describeRunTime,
    localTimeForUtcHour,
    parseStoredTimestamp,
    projectNextRun,
    readExecutionHour,
    retentionDefaultPhrase,
    retentionPeriodLabel,
    retentionRequestError,
    savedEnabledScopes,
    scopeDefaultsSummary,
    summarizeRetentionReset,
    summarizeRetentionRun,
    unsavedKeys,
    utcHourLabel,
    willReschedule,
} from '../application/v2_ui/src/lib/retentionPolicy';
import {
    describeCategoryProblems,
    readClassificationCategories,
    safeBadgeColor,
} from '../application/v2_ui/src/lib/classificationCategories';
import {
    RetentionResetDefaults,
    RetentionRunNow,
} from '../application/v2_ui/src/components/admin/RetentionOperations';
import { RetentionSchedule } from '../application/v2_ui/src/components/admin/RetentionSchedule';
import { ClassificationCategoriesEditor } from '../application/v2_ui/src/components/admin/ClassificationCategoriesEditor';
import type { AdminField } from '../application/v2_ui/src/lib/adminFields';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

const NOW = new Date('2026-10-06T17:43:00Z');

check('periods read the way resolve_retention_value applies them', () => {
    assert.equal(retentionPeriodLabel('none'), 'No automatic deletion');
    assert.equal(retentionPeriodLabel('30'), '30 days');
    assert.equal(retentionPeriodLabel(1), '1 day');
    for (const nothing of ['0', '', 'abc', null, undefined, -5, '7.5']) {
        assert.equal(retentionPeriodLabel(nothing), 'No automatic deletion', String(nothing));
    }
    assert.equal(retentionDefaultPhrase('90'), 'deleted after 90 days');
    assert.equal(retentionDefaultPhrase('none'), 'kept');
});

check('a review says what a type defaults mean, and who a run can touch when they keep everything', () => {
    const settings = {
        default_retention_conversation_group: '90',
        default_retention_document_group: '365',
        default_retention_conversation_personal: 'none',
        default_retention_document_personal: 'none',
    };
    assert.equal(
        scopeDefaultsSummary(settings, 'group', 'run'),
        'Defaults: conversations deleted after 90 days, documents deleted after 365 days.',
    );
    assert.equal(
        scopeDefaultsSummary(settings, 'group', 'reset'),
        'Will follow: conversations deleted after 90 days, documents deleted after 365 days.',
    );
    assert.equal(
        scopeDefaultsSummary(settings, 'personal', 'run'),
        'Defaults keep everything, so only users with their own period are affected.',
    );
    assert.equal(scopeDefaultsSummary(settings, 'personal', 'reset'), 'Will follow defaults that keep everything.');
    assert.match(scopeDefaultsSummary({}, 'public', 'run'), /only workspaces with their own period/);
});

check('the run hour is read defensively and labelled in UTC', () => {
    assert.equal(readExecutionHour(5), 5);
    assert.equal(readExecutionHour('7'), 7);
    assert.equal(readExecutionHour(24), 2);
    assert.equal(readExecutionHour('soon'), 2);
    assert.equal(utcHourLabel(0), '00:00 UTC (midnight)');
    assert.equal(utcHourLabel(2), '02:00 UTC (2 AM)');
    assert.equal(utcHourLabel(12), '12:00 UTC (noon)');
    assert.equal(utcHourLabel(13), '13:00 UTC (1 PM)');
});

check('the local-clock hint is omitted on UTC and shown everywhere else', () => {
    assert.equal(localTimeForUtcHour(2, NOW, { locale: 'en-US', timeZone: 'UTC' }), null);
    const eastern = localTimeForUtcHour(2, NOW, { locale: 'en-US', timeZone: 'America/New_York' });
    assert.ok(eastern && /10:00\s?PM/.test(eastern), String(eastern));
    const india = localTimeForUtcHour(2, NOW, { locale: 'en-US', timeZone: 'Asia/Kolkata' });
    assert.ok(india && /7:30\s?AM/.test(india), String(india));
});

check('a projected next run follows compute_retention_next_run', () => {
    assert.equal(
        projectNextRun(2, new Date('2026-10-06T01:00:00Z')),
        '2026-10-06T02:00:00.000Z',
    );
    assert.equal(
        projectNextRun(2, new Date('2026-10-06T02:00:00Z')),
        '2026-10-07T02:00:00.000Z',
    );
    assert.equal(projectNextRun(23, NOW), '2026-10-06T23:00:00.000Z');
});

check('only a changed schedule key, or a missing next run, moves the next run', () => {
    const stored = {
        enable_retention_policy_group: true,
        retention_policy_execution_hour: 2,
        retention_policy_next_run: '2026-10-07T02:00:00+00:00',
    };
    assert.equal(willReschedule(stored, {}), false);
    assert.equal(willReschedule(stored, { default_retention_document_group: '30' }), false);
    assert.equal(willReschedule(stored, { retention_policy_execution_hour: 5 }), true);
    assert.equal(willReschedule(stored, { enable_retention_policy_personal: true }), true);
    // Flipped and flipped back: still in the draft, but nothing moves.
    assert.equal(willReschedule(stored, { enable_retention_policy_group: true }), false);
    assert.equal(
        willReschedule({ ...stored, retention_policy_next_run: null }, { retention_policy_execution_hour: 2 }),
        true,
    );
    assert.deepEqual(
        [...RETENTION_SCHEDULE_KEYS].sort(),
        [
            'enable_retention_policy_group',
            'enable_retention_policy_personal',
            'enable_retention_policy_public',
            'retention_policy_execution_hour',
        ],
    );
});

check('stored timestamps tolerate Python microseconds and read relative to now', () => {
    const parsed = parseStoredTimestamp('2026-10-07T02:00:00.123456+00:00');
    assert.ok(parsed);
    assert.equal(parsed?.toISOString(), '2026-10-07T02:00:00.123Z');
    assert.equal(parseStoredTimestamp('not a time'), null);
    assert.equal(parseStoredTimestamp(null), null);

    const next = describeRunTime('2026-10-07T02:00:00+00:00', NOW, 'en-US');
    assert.ok(next);
    assert.equal(next?.past, false);
    assert.match(next?.relative ?? '', /in 8 hours/);
    assert.match(next?.absolute ?? '', /UTC/);

    const last = describeRunTime('2026-10-05T02:00:00+00:00', NOW, 'en-US');
    assert.equal(last?.past, true);
    assert.match(last?.relative ?? '', /2 days ago/);
});

check('runs and resets read only saved settings, and the right edits hold them', () => {
    const settings = {
        enable_retention_policy_personal: false,
        enable_retention_policy_group: true,
        enable_retention_policy_public: 'true',
    };
    assert.deepEqual(savedEnabledScopes(settings), ['group', 'public']);
    assert.ok(RETENTION_RUN_KEYS.includes(CONVERSATION_ARCHIVING_KEY));
    assert.ok(!RETENTION_SETTING_KEYS.includes(CONVERSATION_ARCHIVING_KEY));
    assert.deepEqual(unsavedKeys({ enable_conversation_archiving: true }, RETENTION_SETTING_KEYS), []);
    assert.deepEqual(
        unsavedKeys({ enable_conversation_archiving: true }, RETENTION_RUN_KEYS),
        ['enable_conversation_archiving'],
    );
    assert.deepEqual(unsavedKeys({ app_title: 'x' }, RETENTION_RUN_KEYS), []);
});

check('a run response is summarised per processed type, without its error text', () => {
    const summary = summarizeRetentionRun(
        {
            success: true,
            results: {
                success: true,
                scopes_processed: ['public', 'personal'],
                personal: { conversations: 4, documents: 2, users_affected: 3, details: [] },
                group: { conversations: 9, documents: 9, workspaces_affected: 9 },
                public: { conversations: 1, documents: 5, workspaces_affected: 2 },
                errors: [],
            },
        },
        ['personal', 'public'],
    );
    assert.equal(summary.ok, true);
    assert.deepEqual(summary.rows.map((row) => row.scope), ['personal', 'public']);
    assert.deepEqual(summary.rows[0], { scope: 'personal', conversations: 4, documents: 2, affected: 3 });
    assert.equal(summary.rows[1].affected, 2);
    assert.equal(summary.conversations, 5);
    assert.equal(summary.documents, 7);
    assert.equal(summary.errorCount, 0);

    const failed = summarizeRetentionRun(
        { success: false, results: { success: false, errors: ['Traceback: secret detail'] } },
        ['group'],
    );
    assert.equal(failed.ok, false);
    assert.equal(failed.errorCount, 1);
    assert.deepEqual(failed.rows, [{ scope: 'group', conversations: 0, documents: 0, affected: 0 }]);
    assert.ok(!JSON.stringify(failed).includes('secret detail'));
});

check('a reset response is summarised per type', () => {
    const summary = summarizeRetentionReset(
        { success: true, updated_count: 12, scopes: ['group', 'personal'], details: { personal: 10, group: 2 } },
        ['personal', 'group'],
    );
    assert.deepEqual(summary.rows, [
        { scope: 'personal', updated: 10 },
        { scope: 'group', updated: 2 },
    ]);
    assert.equal(summary.total, 12);
    const withoutTotal = summarizeRetentionReset({ success: true, details: { public: 3 } }, ['public']);
    assert.equal(withoutTotal.total, 3);
});

check('request failures quote only messages written for people', () => {
    const invalid = new ApiError('Bad request', 400, { success: false, error: 'Invalid workspace scopes: tenant' });
    assert.equal(retentionRequestError(invalid, 'run'), 'Invalid workspace scopes: tenant');
    const crashed = new ApiError('x', 500, { error: 'Failed to execute retention policy: KeyError secret' });
    const crashedMessage = retentionRequestError(crashed, 'run');
    assert.ok(!crashedMessage.includes('KeyError'));
    assert.match(crashedMessage, /application logs/);
    assert.match(retentionRequestError(new ApiError('x', 504, ''), 'run'), /may still be running/);
    assert.match(retentionRequestError(new TypeError('Failed to fetch'), 'run'), /may still be running/);
    assert.match(retentionRequestError(new ApiError('x', 403, {}), 'reset'), /administrator access/);
});

check('category problems land on the row that has them', () => {
    const problems = describeCategoryProblems([
        { label: 'Public', color: '#00ff00' },
        { label: '  ', color: '#808080' },
        { label: 'public', color: '#123456' },
        { label: 'Secret', color: 'red' },
        { label: 'x'.repeat(81), color: '#808080' },
        { label: 'Secret', color: '#808080' },
    ]);
    assert.equal(problems[0], null);
    assert.match(problems[1] ?? '', /label/);
    assert.match(problems[2] ?? '', /Same label as category 1/);
    assert.match(problems[3] ?? '', /hex/);
    assert.match(problems[4] ?? '', /80 characters/);
    // A row with a bad colour still claims its label.
    assert.match(problems[5] ?? '', /Same label as category 4/);
});

check('stored categories are read defensively and only hex colours are painted', () => {
    assert.deepEqual(readClassificationCategories('nope'), []);
    assert.deepEqual(
        readClassificationCategories([{ label: 'A', color: '#000000' }, null, 'x', { label: 3 }]),
        [{ label: 'A', color: '#000000' }, { label: '', color: '' }],
    );
    assert.equal(safeBadgeColor('#0000FF'), '#0000FF');
    assert.equal(safeBadgeColor('red; background:url(x)'), undefined);
});

const field = (overrides: Partial<AdminField>): AdminField => ({
    type: 'component',
    label: 'Label',
    help: 'Help text.',
    ...overrides,
});

const savedSettings = {
    enable_retention_policy_personal: false,
    enable_retention_policy_group: true,
    enable_retention_policy_public: false,
    default_retention_conversation_group: '30',
    default_retention_document_group: 'none',
    enable_conversation_archiving: true,
    retention_policy_execution_hour: 2,
};

check('run now is offered on saved settings and held by an unsaved edit', () => {
    const render = (draft: Record<string, unknown>) =>
        renderToStaticMarkup(
            createElement(RetentionRunNow, {
                field: field({ component: 'retention-run-now', label: 'Run retention now' }),
                settings: savedSettings,
                draft,
                onStoredSettingsChange: () => undefined,
                onOpenSection: () => undefined,
            }),
        );
    const ready = render({});
    assert.match(ready, /Run now…/);
    assert.doesNotMatch(ready, /Save or discard/);
    assert.doesNotMatch(ready, /disabled=""/);

    for (const draft of [{ default_retention_document_group: '30' }, { enable_conversation_archiving: false }]) {
        const held = render(draft);
        assert.match(held, /Save or discard your changes first/);
        assert.match(held, /disabled=""/);
    }
});

check('reset is held by retention edits but not by archiving', () => {
    const render = (draft: Record<string, unknown>) =>
        renderToStaticMarkup(
            createElement(RetentionResetDefaults, {
                field: field({ component: 'retention-reset-defaults', label: 'Reset to the defaults' }),
                settings: savedSettings,
                draft,
            }),
        );
    assert.doesNotMatch(render({ enable_conversation_archiving: false }), /Save or discard/);
    assert.match(render({ retention_policy_execution_hour: 5 }), /Save or discard your changes first/);
    assert.match(render({}), /Reset to defaults…/);
});

check('the schedule shows the stored runs and every UTC hour', () => {
    const markup = renderToStaticMarkup(
        createElement(RetentionSchedule, {
            field: field({ key: 'retention_policy_execution_hour', component: 'retention-schedule', label: 'Daily run time' }),
            value: 2,
            settings: { ...savedSettings, retention_policy_next_run: '2099-01-01T02:00:00+00:00' },
            draft: {},
            onChange: () => undefined,
            onStoredSettingsChange: () => undefined,
        }),
    );
    assert.match(markup, /Last run/);
    assert.match(markup, /Never run/);
    assert.match(markup, /Next run/);
    assert.match(markup, /2099/);
    assert.equal((markup.match(/<option /g) ?? []).length, 24);
    assert.match(markup, /02:00 UTC \(2 AM\)/);
});

check('the category editor teaches when empty and flags a duplicate on its row', () => {
    const render = (value: unknown) =>
        renderToStaticMarkup(
            createElement(ClassificationCategoriesEditor, {
                field: field({ key: 'document_classification_categories', component: 'document-classification-categories', label: 'Categories' }),
                value,
                onChange: () => undefined,
            }),
        );
    assert.match(render([]), /No categories yet/);
    const duplicate = render([
        { label: 'Internal', color: '#123456' },
        { label: 'internal', color: '#654321' },
    ]);
    assert.match(duplicate, /Same label as category 1/);
    assert.match(duplicate, /As users will see them/);
    assert.match(duplicate, /2 categories/);
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
