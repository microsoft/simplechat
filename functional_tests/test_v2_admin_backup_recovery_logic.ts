// test_v2_admin_backup_recovery_logic.ts
//
// Runtime checks for the V2 Admin Settings > Backup & Recovery decisions.
// Version: 0.261.260
// Implemented in: 0.261.260
//
// The Backup & Recovery cards sit on a server contract that is easy to break without any
// visible symptom: the settings save sends one whole document, a review fingerprint is
// checked against the *saved* settings, typed phrases are compared verbatim, and history
// paging is forward-only. Each decision the browser makes about those lives in
// `dataManagementLogic.ts` or the store, and is executed here.
//
// Run by test_v2_admin_backup_recovery.py, which bundles this with the esbuild Vite brings
// in and runs it under node, skipping when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import {
    COSMOS_EDITOR_SAVE_PHRASE,
    DM_DEFAULTS,
    DM_EDITABLE_KEYS,
    DM_REDACTED,
    MIRROR_CONFIRMATION_PHRASE,
    RESTORE_OVERWRITE_PHRASE,
    migrationManifestUrl,
    type DataManagementJob,
    type DmSettings,
    type MigrationReview,
    type RestoreReview,
} from '../application/v2_ui/src/lib/dataManagement';
import {
    DM_SECTION_IDS,
    FIRST_PAGE,
    buildDmSettingsPayload,
    buildMigrationPlan,
    buildReadinessChecklist,
    buildRestorePlan,
    canExecuteMigration,
    canQueueRestore,
    checkCosmosEdit,
    computeRetentionDays,
    dmDirtyKeys,
    dmSectionStatuses,
    flattenDetails,
    formatOperation,
    furthestOpenStep,
    humanizeToken,
    initialMigrationState,
    initialRestoreDraft,
    isMigrationReviewCurrent,
    jobArtifacts,
    jobWarnings,
    migrationLiveMetrics,
    migrationReviewKey,
    migrationStepIssue,
    normalizeReviewChecks,
    pagerAfterLoad,
    pagerBack,
    pagerForward,
    pagerPageNumber,
    progressPercent,
    readDmValues,
    restoreReviewKey,
    retentionMaxValue,
    retryLabel,
    reviewHeadline,
    summarizeCosmosChanges,
    validateCosmosQuery,
    validateDmValues,
    validateHistoryDateRange,
    type MigrationWizardState,
} from '../application/v2_ui/src/lib/dataManagementLogic';
import { useDataManagementStore } from '../application/v2_ui/src/stores/dataManagementStore';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

const SAVED: DmSettings = {
    ...DM_DEFAULTS,
    backup_storage_blob_endpoint: 'https://backups.blob.core.windows.net',
    target_cosmos_endpoint: 'https://dest.documents.azure.com:443/',
    encryption_key_storage: 'key_vault',
    encryption_key_reference: DM_REDACTED,
};

function migrationState(overrides: Partial<MigrationWizardState> = {}): MigrationWizardState {
    const state = initialMigrationState();
    state.scopes.users = {
        mode: 'selected',
        selected: [{ id: 'user-1', label: 'Ada' }, { id: 'user-2', label: 'Grace' }],
        includeDocuments: true,
    };
    state.searchWritesFrozen = true;
    return { ...state, ...overrides };
}

const READY_MIGRATION_REVIEW: MigrationReview = {
    ready: true,
    blocker_count: 0,
    warning_count: 0,
    review_fingerprint: 'fingerprint',
    authorization_token: 'token',
    authorization_expires_at: '2099-01-01T00:00:00Z',
    checks: [],
};

// ---------------------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------------------

check('values prefer the unsaved edit, then the saved value, then the default', () => {
    const values = readDmValues({ retention_value: 45 }, { retention_unit: 'weeks' });
    assert.equal(values.retention_value, 45);
    assert.equal(values.retention_unit, 'weeks');
    assert.equal(values.full_backup_frequency, 'weekly');
});

check('the save payload carries exactly the editable keys the classic page sends', () => {
    const payload = buildDmSettingsPayload(readDmValues(SAVED, {}));
    assert.deepEqual(Object.keys(payload).sort(), [...DM_EDITABLE_KEYS].sort());
    assert.equal(DM_EDITABLE_KEYS.length, 42);
    assert.ok(!('encryption_key_reference' in payload), 'the key reference is never sent back');
});

check('retention days are derived and clamped like the classic page', () => {
    assert.equal(computeRetentionDays(2, 'weeks'), 14);
    assert.equal(computeRetentionDays(20, 'years'), 3650);
    assert.equal(computeRetentionDays(0, 'days'), 1);
    assert.equal(retentionMaxValue('months'), 121);
    const payload = buildDmSettingsPayload(readDmValues(SAVED, { retention_value: 3, retention_unit: 'months' }));
    assert.equal(payload.retention_days, 90);
});

check('only the credential for the selected sign-in mode is sent', () => {
    const managed = buildDmSettingsPayload(readDmValues(SAVED, { backup_storage_connection_string: 'secret' }));
    assert.equal(managed.backup_storage_connection_string, '');
    assert.equal(managed.backup_storage_blob_endpoint, 'https://backups.blob.core.windows.net');

    const connection = buildDmSettingsPayload(
        readDmValues(SAVED, { backup_storage_authentication_type: 'connection_string', backup_storage_connection_string: DM_REDACTED }),
    );
    assert.equal(connection.backup_storage_blob_endpoint, '');
    assert.equal(connection.backup_storage_connection_string, DM_REDACTED, 'an untouched secret round-trips as the placeholder');

    const target = buildDmSettingsPayload(
        readDmValues(SAVED, {
            target_enhanced_citations_storage_authentication_type: 'connection_string',
            target_enhanced_citations_storage_blob_endpoint: 'https://ignored.blob.core.windows.net',
        }),
    );
    assert.equal(target.target_enhanced_citations_storage_blob_endpoint, '');
    assert.equal(target.target_cosmos_database_name, 'SimpleChat');
});

check('numbers typed as text are sent as numbers', () => {
    const payload = buildDmSettingsPayload(readDmValues(SAVED, { backup_retry_count: '7', migration_temporary_destination_ru: '4000' }));
    assert.equal(payload.backup_retry_count, 7);
    assert.equal(payload.migration_temporary_destination_ru, 4000);
});

check('an edit typed back to the saved value is not an unsaved change', () => {
    assert.deepEqual(dmDirtyKeys(SAVED, { backup_retry_count: '5', enabled: false, retention_days: 9 }), []);
    assert.deepEqual(dmDirtyKeys(SAVED, { backup_retry_count: 6 }), ['backup_retry_count']);
});

check('clearing a stored secret counts as a change, because saving removes it', () => {
    const saved = { ...SAVED, target_cosmos_key: DM_REDACTED };
    assert.deepEqual(dmDirtyKeys(saved, { target_cosmos_key: '' }), ['target_cosmos_key']);
    assert.deepEqual(dmDirtyKeys(saved, { target_cosmos_key: DM_REDACTED }), []);
});

check('values the server would clamp are refused before saving', () => {
    const errors = validateDmValues(
        readDmValues(SAVED, {
            scheduled_time_utc: '25:00',
            retention_value: 200,
            retention_unit: 'months',
            backup_temporary_source_ru: 1500,
            backup_blob_chunk_size_mib: 32,
            backup_storage_container_name: '  ',
        }),
    );
    assert.ok(errors.scheduled_time_utc);
    assert.match(errors.retention_value ?? '', /1 to 121/);
    assert.match(errors.backup_temporary_source_ru ?? '', /steps of 1,000/);
    assert.ok(errors.backup_blob_chunk_size_mib);
    assert.ok(errors.backup_storage_container_name);
    assert.deepEqual(validateDmValues(readDmValues(SAVED, {})), {});
});

check('card statuses come from the data-management document', () => {
    assert.deepEqual(dmSectionStatuses(null, {}), {});
    const statuses = dmSectionStatuses(SAVED, {});
    assert.equal(statuses[DM_SECTION_IDS.schedule], 'off');
    assert.equal(statuses[DM_SECTION_IDS.storage], 'ready');
    assert.equal(statuses[DM_SECTION_IDS.encryption], 'ready');
    assert.equal(statuses[DM_SECTION_IDS.backup], 'none');

    const unconfigured = dmSectionStatuses({ ...SAVED, backup_storage_blob_endpoint: '', encryption_key_storage: 'not_configured' }, { enabled: true });
    assert.equal(unconfigured[DM_SECTION_IDS.schedule], 'ready');
    assert.equal(unconfigured[DM_SECTION_IDS.storage], 'incomplete');
    assert.equal(unconfigured[DM_SECTION_IDS.encryption], 'incomplete');
    assert.equal(unconfigured[DM_SECTION_IDS.backup], 'blocked');

    const stored = dmSectionStatuses(
        { ...SAVED, backup_storage_authentication_type: 'connection_string', backup_storage_connection_string: DM_REDACTED },
        { encryption_enabled: false },
    );
    assert.equal(stored[DM_SECTION_IDS.storage], 'ready', 'a stored, hidden connection string counts as configured');
    assert.equal(stored[DM_SECTION_IDS.encryption], 'off');
});

check('the readiness checklist only reports what the server said', () => {
    const items = buildReadinessChecklist({ ...SAVED, encryption_key_storage: 'settings' }, {}, null);
    const byId = Object.fromEntries(items.map((item) => [item.id, item]));
    assert.equal(byId.storage.state, 'ok');
    assert.equal(byId.encryption.state, 'attention', 'a key in the settings document is worth attention');
    assert.equal(byId.schedule.state, 'off');
    assert.match(byId['latest-full'].detail, /not loaded/);
    assert.equal(byId.destination.state, 'ok');
    const withBackup = buildReadinessChecklist(SAVED, {}, { latest_full: { id: 'b', completed_at: '2026-01-01T00:00:00Z' } });
    assert.equal(withBackup.find((item) => item.id === 'latest-full')?.state, 'ok');
});

// ---------------------------------------------------------------------------------------
// History lists
// ---------------------------------------------------------------------------------------

check('previous goes back to the token each earlier page was fetched with', () => {
    let pager = pagerAfterLoad(FIRST_PAGE, 'token-2');
    pager = pagerForward(pager);
    assert.equal(pager.current, 'token-2');
    pager = pagerForward(pagerAfterLoad(pager, 'token-3'));
    assert.equal(pagerPageNumber(pager), 3);
    pager = pagerBack(pager);
    assert.equal(pager.current, 'token-2');
    pager = pagerBack(pager);
    assert.equal(pager.current, null);
    assert.equal(pagerPageNumber(pager), 1);
    assert.equal(pagerForward(pager), pager, 'no next token, no move');
});

check('created-date filters are sent only as a valid pair within a year', () => {
    assert.equal(validateHistoryDateRange('', ''), null);
    assert.match(validateHistoryDateRange('2026-01-01', '') ?? '', /both/);
    assert.match(validateHistoryDateRange('2026-02-01', '2026-01-01') ?? '', /on or after/);
    assert.equal(validateHistoryDateRange('2026-01-01', '2027-01-01'), null, '366 days inclusive is allowed');
    assert.match(validateHistoryDateRange('2026-01-01', '2027-01-02') ?? '', /366/);
});

// ---------------------------------------------------------------------------------------
// Review evidence
// ---------------------------------------------------------------------------------------

check('restore and migration checks read the same way', () => {
    const checks = normalizeReviewChecks([
        { id: 'a', label: 'Restore', status: 'warn', message: 'Partial backup' },
        { id: 'b', label: 'Migration', status: 'warning', summary: 'Deletes', workflow_step: 'options' },
        { id: 'c', label: 'Odd', status: 'mystery' },
        { id: 'd', label: 'Fine', status: 'pass', message: 'ok' },
    ]);
    assert.deepEqual(checks.map((item) => item.tone), ['warning', 'warning', 'block', 'pass']);
    assert.equal(checks[1].message, 'Deletes');
    assert.equal(checks[1].workflowStep, 'options');
    assert.equal(checks[2].message, 'No details were returned.');
});

check('the review headline says ready, warnings, blockers or out of date', () => {
    assert.equal(reviewHeadline(null, false).tone, 'none');
    assert.equal(reviewHeadline({ ready: true }, true).tone, 'stale');
    assert.equal(reviewHeadline({ ready: true, warning_count: 0 }, false).text, 'Ready');
    assert.equal(reviewHeadline({ ready: true, warning_count: 2 }, false).text, 'Ready with 2 warnings');
    assert.equal(reviewHeadline({ ready: false, blocker_count: 1 }, false).text, '1 blocker');
});

// ---------------------------------------------------------------------------------------
// Restore
// ---------------------------------------------------------------------------------------

check('the restore plan carries the overwrite phrase only for an overwrite', () => {
    const createOnly = buildRestorePlan('backup-1', { ...initialRestoreDraft(), overwritePhrase: 'x' });
    assert.equal(createOnly.restore_policy, 'create_only');
    assert.equal(createOnly.overwrite_confirmed, false);
    assert.equal(createOnly.overwrite_confirmation_phrase, '');
    const overwrite = buildRestorePlan('backup-1', {
        ...initialRestoreDraft(),
        policy: 'overwrite_existing',
        overwritePhrase: RESTORE_OVERWRITE_PHRASE,
    });
    assert.equal(overwrite.overwrite_confirmed, true);
    assert.equal(overwrite.overwrite_confirmation_phrase, RESTORE_OVERWRITE_PHRASE);
});

check('typing the phrase or acknowledging does not make a restore review stale', () => {
    const values = readDmValues(SAVED, {});
    const draft = { ...initialRestoreDraft(), policy: 'overwrite_existing' as const };
    const key = restoreReviewKey('backup-1', draft, values);
    assert.equal(restoreReviewKey('backup-1', { ...draft, overwritePhrase: RESTORE_OVERWRITE_PHRASE, acknowledged: true }, values), key);
    assert.notEqual(restoreReviewKey('backup-1', { ...draft, includeAiSearch: false }, values), key);
    assert.notEqual(
        restoreReviewKey('backup-1', draft, readDmValues(SAVED, { target_cosmos_endpoint: 'https://other.documents.azure.com' })),
        key,
        'a different destination is a different review',
    );
});

check('a restore queues only with a current, ready, unexpired review and every confirmation', () => {
    const review: RestoreReview = { ready: true, authorization_token: 'token' };
    const draft = { ...initialRestoreDraft(), acknowledged: true };
    const ready = { review, reviewCurrent: true, draft, expiresInSeconds: 120, busy: false };
    assert.equal(canQueueRestore(ready), true);
    assert.equal(canQueueRestore({ ...ready, reviewCurrent: false }), false);
    assert.equal(canQueueRestore({ ...ready, expiresInSeconds: 0 }), false);
    assert.equal(canQueueRestore({ ...ready, draft: { ...draft, acknowledged: false } }), false);
    assert.equal(canQueueRestore({ ...ready, review: { ready: true } }), false, 'no authorization, no queue');
    assert.equal(canQueueRestore({ ...ready, draft: { ...draft, policy: 'overwrite_existing', overwritePhrase: 'restore with overwrite' } }), false);
    assert.equal(canQueueRestore({ ...ready, draft: { ...draft, policy: 'overwrite_existing', overwritePhrase: RESTORE_OVERWRITE_PHRASE } }), true);
});

// ---------------------------------------------------------------------------------------
// Migration
// ---------------------------------------------------------------------------------------

check('the migration plan is built as the classic page builds it', () => {
    const state = migrationState();
    state.scopes.groups = { mode: 'none', selected: [{ id: 'g' }], includeDocuments: true };
    state.scopes.public_workspaces = { mode: 'all', selected: [{ id: 'p' }], includeDocuments: true };
    state.baselineJobId = '1b4e28ba-2fa1-11d2-883f-0016d3cca427';
    state.mirrorPhrase = 'anything';
    const plan = buildMigrationPlan(state);
    assert.deepEqual(plan.users, { mode: 'selected', ids: ['user-1', 'user-2'], include_documents: true });
    assert.deepEqual(plan.groups, { mode: 'none', ids: [], include_documents: false });
    assert.deepEqual(plan.public_workspaces, { mode: 'all', ids: [], include_documents: true });
    assert.equal(plan.baseline_job_id, '', 'new_only ignores a baseline');
    assert.equal(plan.mirror_confirmation, '', 'only mirror mode sends the phrase');
    assert.equal(buildMigrationPlan({ ...state, includeAiSearch: false }).target_ai_search_writes_frozen, false);
    const mirror = buildMigrationPlan({ ...state, mode: 'mirror_with_deletions', mirrorPhrase: MIRROR_CONFIRMATION_PHRASE });
    assert.equal(mirror.mirror_confirmation, MIRROR_CONFIRMATION_PHRASE);
    assert.equal(mirror.baseline_job_id, '1b4e28ba-2fa1-11d2-883f-0016d3cca427');
});

check('the mirror phrase does not stale a review, but destination and scope edits do', () => {
    const values = readDmValues(SAVED, {});
    const state = migrationState({ mode: 'mirror_with_deletions' });
    const key = migrationReviewKey(state, values);
    assert.equal(migrationReviewKey({ ...state, mirrorPhrase: MIRROR_CONFIRMATION_PHRASE, acknowledged: true }, values), key);
    assert.notEqual(migrationReviewKey(state, readDmValues(SAVED, { target_cosmos_endpoint: 'https://x.documents.azure.com' })), key);
    assert.notEqual(migrationReviewKey(state, readDmValues(SAVED, { migration_retry_count: 9 })), key);
    assert.notEqual(migrationReviewKey({ ...state, includeAiSearch: false }, values), key);
    const reviewed = { ...state, review: READY_MIGRATION_REVIEW, reviewKey: key };
    assert.equal(isMigrationReviewCurrent(reviewed, values), true);
    assert.equal(isMigrationReviewCurrent(reviewed, readDmValues(SAVED, { target_ai_search_key: 'new' })), false);
});

check('each wizard step says why it cannot be left', () => {
    const empty = readDmValues({ ...SAVED, target_cosmos_endpoint: '' }, {});
    const values = readDmValues(SAVED, {});
    assert.match(migrationStepIssue('target', migrationState(), empty) ?? '', /endpoint/);
    assert.equal(migrationStepIssue('target', migrationState(), values), null);
    assert.match(migrationStepIssue('scope', initialMigrationState(), values) ?? '', /at least one/);
    assert.match(migrationStepIssue('options', migrationState({ searchWritesFrozen: false }), values) ?? '', /frozen/);
    assert.equal(migrationStepIssue('options', migrationState({ includeAiSearch: false, searchWritesFrozen: false }), values), null);
    assert.match(migrationStepIssue('options', migrationState({ mode: 'delta_upsert', baselineJobId: 'not-a-guid' }), values) ?? '', /GUID/);
    assert.match(
        migrationStepIssue('options', migrationState(), readDmValues(SAVED, { migration_temporary_destination_ru_enabled: true })) ?? '',
        /subscription ID and resource group/,
    );
    assert.match(migrationStepIssue('review', migrationState(), values) ?? '', /Run the preflight/);
    const state = migrationState();
    const blocked = { ...state, review: { ...READY_MIGRATION_REVIEW, ready: false }, reviewKey: migrationReviewKey(state, values) };
    assert.match(migrationStepIssue('review', blocked, values) ?? '', /blockers/);
    assert.equal(furthestOpenStep(initialMigrationState(), values), 1);
    assert.equal(furthestOpenStep(migrationState(), values), 3);
});

check('a migration starts only with a current authorized review and every confirmation', () => {
    const values = readDmValues(SAVED, {});
    const now = Date.parse('2026-06-01T00:00:00Z');
    const base = migrationState({ acknowledged: true });
    const ready = { ...base, review: READY_MIGRATION_REVIEW, reviewKey: migrationReviewKey(base, values) };
    assert.equal(canExecuteMigration(ready, values, now), true);
    assert.equal(canExecuteMigration({ ...ready, acknowledged: false }, values, now), false);
    assert.equal(canExecuteMigration({ ...ready, submission: 'submitting' }, values, now), false);
    assert.equal(
        canExecuteMigration({ ...ready, review: { ...READY_MIGRATION_REVIEW, authorization_expires_at: '2020-01-01T00:00:00Z' } }, values, now),
        false,
    );
    const mirror = { ...ready, mode: 'mirror_with_deletions' as const };
    const mirrorReady = { ...mirror, reviewKey: migrationReviewKey(mirror, values) };
    assert.equal(canExecuteMigration(mirrorReady, values, now), false, 'mirror needs the phrase');
    assert.equal(canExecuteMigration({ ...mirrorReady, mirrorPhrase: MIRROR_CONFIRMATION_PHRASE }, values, now), true);
});

// ---------------------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------------------

check('job labels and progress read like the classic page', () => {
    assert.equal(progressPercent({ percent_complete: '140' }), 100);
    assert.equal(progressPercent({ percent_complete: 'x' }), 0);
    assert.equal(humanizeToken('completed_with_warnings'), 'Completed with warnings');
    assert.equal(humanizeToken('mirror_with_deletions'), 'Make destination match source');
    assert.equal(formatOperation('backup', 'partial'), 'Partial backup');
    assert.equal(formatOperation('dry_run'), 'Dry run');
    assert.equal(retryLabel({ id: '1', status: 'running', operation: 'migration' }), 'Resume');
    assert.equal(retryLabel({ id: '1', status: 'failed', operation: 'backup' }), 'Retry failures');
    assert.equal(retryLabel({ id: '1', status: 'failed', operation: 'restore' }), 'Retry');
});

check('live migration metrics include liveness only while the job runs', () => {
    const now = Date.parse('2026-06-01T00:00:30Z');
    const job: DataManagementJob = {
        id: 'job',
        operation: 'migration',
        status: 'running',
        last_heartbeat_at: '2026-06-01T00:00:25Z',
        last_progress_at: '2026-06-01T00:00:00Z',
        migration_state: {
            totals: { processed_count: 1200, bytes: 2048, copied_count: 1000, skipped_count: 200 },
            resources: { a: { status: 'in_progress', progress: { items_per_second: 12 } } },
            capacity: { status: 'boosted' },
        },
    };
    const metrics = Object.fromEntries(migrationLiveMetrics(job, now).map((metric) => [metric.label, metric.value]));
    assert.equal(metrics.Processed, (1200).toLocaleString());
    assert.equal(metrics.Transferred, '2.0 KB');
    assert.equal(metrics['Items per second'], '12');
    assert.equal(metrics['Destination capacity'], 'Boosted');
    assert.equal(metrics.Liveness, 'Running, alive with no recent progress');
    assert.ok(!migrationLiveMetrics({ ...job, status: 'completed' }, now).some((metric) => metric.label === 'Liveness'));
});

check('artifacts and warnings come from the result, falling back to the timeline', () => {
    const job: DataManagementJob = { id: 'j', warnings: ['Job warning'], result: {} };
    const items = [{ details: { artifacts: [{ name: 'users', warning: 'Throttled' }] } }];
    const artifacts = jobArtifacts(job, items);
    assert.equal(artifacts.length, 1);
    assert.deepEqual(jobWarnings(job, artifacts), ['Job warning', 'users: Throttled']);
    const details = flattenDetails({ counts: { created: 2, skipped: 0 }, ids: ['a', 'b'], flag: true, empty: '' });
    assert.deepEqual(details.map((item) => item.label), ['Counts created', 'Counts skipped', 'Ids', 'Flag']);
    assert.equal(details.find((item) => item.label === 'Flag')?.value, 'Yes');
});

check('manifest links are same-origin with an encoded job id', () => {
    assert.equal(
        migrationManifestUrl('a/b c'),
        '/api/admin/data-management/jobs/a%2Fb%20c/migration-manifest',
    );
    assert.equal(
        migrationManifestUrl('job', true),
        '/api/admin/data-management/jobs/job/migration-manifest?statuses=failed%2Cmissing%2Ccollision',
    );
});

// ---------------------------------------------------------------------------------------
// Cosmos editor
// ---------------------------------------------------------------------------------------

check('queries are checked the way the server checks them', () => {
    assert.equal(validateCosmosQuery(''), null, 'an empty query browses');
    assert.equal(validateCosmosQuery('select * from c'), null);
    assert.match(validateCosmosQuery('SELECT * FROM c; DELETE') ?? '', /semicolons/);
    assert.match(validateCosmosQuery('DELETE FROM c') ?? '', /SELECT/);
    assert.match(validateCosmosQuery(`SELECT ${'x'.repeat(4000)}`) ?? '', /4,000/);
    assert.equal(COSMOS_EDITOR_SAVE_PHRASE, 'I understand this can damage system data');
});

check('an edit cannot change the id or the partition key', () => {
    const original = { id: 'doc-1', partitionKey: 'tenant-a', partitionKeyPath: '/owner/tenant' };
    assert.equal(checkCosmosEdit('{', original).ok, false);
    assert.equal(checkCosmosEdit('[]', original).ok, false);
    const idChanged = checkCosmosEdit('{"id":"doc-2","owner":{"tenant":"tenant-a"}}', original);
    assert.equal(idChanged.ok, false);
    const keyChanged = checkCosmosEdit('{"id":"doc-1","owner":{"tenant":"tenant-b"}}', original);
    assert.equal(keyChanged.ok, false);
    assert.match(keyChanged.ok ? '' : keyChanged.error, /partition key/);
    assert.equal(checkCosmosEdit('{"id":"doc-1","owner":{"tenant":"tenant-a"},"x":1}', original).ok, true);
});

check('the change summary skips system fields', () => {
    const summary = summarizeCosmosChanges(
        { id: '1', a: 1, b: { c: 1 }, gone: true, _etag: 'x' },
        { id: '1', a: 2, b: { c: 1, d: 2 }, _etag: 'y' },
    );
    assert.deepEqual(summary.changedPaths.sort(), ['a', 'b.d', 'gone']);
    assert.equal(summary.addedCount, 1);
    assert.equal(summary.removedCount, 1);
    assert.equal(summary.updatedCount, 1);
});

// ---------------------------------------------------------------------------------------
// Store: save, save-first and lifetime
// ---------------------------------------------------------------------------------------

interface Captured {
    method: string;
    url: string;
    body: unknown;
}

function mockFetch(handler: (request: Captured) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>) {
    const requests: Captured[] = [];
    globalThis.fetch = (async (input: unknown, init?: { method?: string; body?: string }) => {
        const request = { method: init?.method ?? 'GET', url: String(input), body: init?.body ? JSON.parse(init.body) : undefined };
        requests.push(request);
        const { status = 200, body } = await handler(request);
        return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
    }) as typeof fetch;
    return requests;
}

const store = useDataManagementStore;

function primeStore(draft = {}, mainDirtyKeys: string[] = []) {
    store.getState().reset();
    store.setState({ status: 'ready', settings: { ...SAVED }, draft, mainDirtyKeys });
}

check('a save sends the whole editable document and rebases on the response', async () => {
    primeStore({ backup_retry_count: 7 });
    const requests = mockFetch((request) => ({ body: { success: true, settings: { ...SAVED, ...(request.body as object), backup_retry_count: 7 } } }));
    const outcome = await store.getState().save();
    assert.equal(outcome.ok, true);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].method, 'PUT');
    assert.equal(requests[0].url, '/api/admin/data-management/settings');
    assert.deepEqual(Object.keys(requests[0].body as object).sort(), [...DM_EDITABLE_KEYS].sort());
    assert.equal(store.getState().settings?.backup_retry_count, 7);
    assert.deepEqual(store.getState().draft, {});
});

check('an edit made while saving survives the save', async () => {
    primeStore({ backup_retry_count: 7 });
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
        release = resolve;
    });
    mockFetch(async () => {
        await gate;
        return { body: { settings: { ...SAVED, backup_retry_count: 7 } } };
    });
    const saving = store.getState().save();
    store.getState().setValue('migration_retry_count', 9);
    release();
    await saving;
    assert.deepEqual(store.getState().draft, { migration_retry_count: 9 });
});

check('an invalid value stops the save before any request', async () => {
    primeStore({ backup_retry_count: 99 });
    const requests = mockFetch(() => ({ body: {} }));
    const outcome = await store.getState().save();
    assert.equal(outcome.ok, false);
    assert.equal(outcome.invalid, true);
    assert.equal(requests.length, 0);
    assert.ok(store.getState().fieldErrors.backup_retry_count);
});

check('a save-first action saves pending backup settings, then proceeds', async () => {
    primeStore({ backup_retry_count: 6 });
    const requests = mockFetch(() => ({ body: { settings: { ...SAVED, backup_retry_count: 6 } } }));
    const ready = await store.getState().ensureReadyFor('queue-backup');
    assert.deepEqual(ready, { ok: true });
    assert.equal(requests.length, 1);
    assert.deepEqual(store.getState().draft, {});
});

check('nothing is saved when there is nothing to save', async () => {
    primeStore({});
    const requests = mockFetch(() => ({ body: {} }));
    assert.deepEqual(await store.getState().ensureReadyFor('retention-cleanup'), { ok: true });
    assert.equal(requests.length, 0);
});

check('pending Enhanced Citations edits require saving everything first', async () => {
    primeStore({ backup_retry_count: 6 }, ['office_docs_storage_account_url', 'app_title']);
    const requests = mockFetch(() => ({ body: {} }));
    const ready = await store.getState().ensureReadyFor('restore-review');
    assert.equal(ready.ok, false);
    assert.equal(ready.ok ? '' : ready.reason, 'save-all-required');
    assert.equal(requests.length, 0);

    primeStore({}, ['office_docs_storage_account_url']);
    assert.deepEqual(await store.getState().ensureReadyFor('queue-backup'), { ok: true }, 'no backup save, nothing to validate');
});

check('key generation waits for pending Key Vault edits but saves nothing', async () => {
    primeStore({ backup_retry_count: 6 }, ['key_vault_name']);
    const requests = mockFetch(() => ({ body: {} }));
    const ready = await store.getState().ensureReadyFor('generate-key');
    assert.equal(ready.ok ? '' : ready.reason, 'save-all-required');
    primeStore({ backup_retry_count: 6 }, []);
    assert.deepEqual(await store.getState().ensureReadyFor('generate-key'), { ok: true });
    assert.equal(requests.length, 0, 'generating a key never saves the backup draft');
});

check('a save that finishes after the page is left writes nothing', async () => {
    primeStore({ backup_retry_count: 7 });
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
        release = resolve;
    });
    mockFetch(async () => {
        await gate;
        return { body: { settings: { ...SAVED, backup_retry_count: 7 } } };
    });
    const saving = store.getState().save();
    store.getState().reset();
    release();
    await saving;
    assert.equal(store.getState().settings, null);
    assert.equal(store.getState().saving, false);
});

check('tracked requests are counted, and a reset never leaves a negative count', async () => {
    primeStore();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
        release = resolve;
    });
    const tracked = store.getState().trackRequest(gate);
    assert.equal(store.getState().pendingRequests, 1);
    store.getState().reset();
    release();
    await tracked;
    assert.equal(store.getState().pendingRequests, 0);
});

check('the Cosmos editor is dirty only when its JSON differs from what was opened', async () => {
    const { selectCosmosEditorDirty } = await import('../application/v2_ui/src/stores/dataManagementStore');
    primeStore();
    const original = { id: '1', value: 1 };
    store.getState().updateCosmos({
        document: {
            container: 'c', id: '1', partitionKey: '1', partitionKeyPath: '/id', etag: 'e', original,
            text: JSON.stringify(original, null, 2), editable: true,
        },
    });
    assert.equal(selectCosmosEditorDirty(store.getState()), false);
    store.getState().updateCosmos((session) => ({ ...session, document: session.document && { ...session.document, text: '{}' } }));
    assert.equal(selectCosmosEditorDirty(store.getState()), true);
    store.getState().lockCosmos();
    assert.equal(selectCosmosEditorDirty(store.getState()), false);
});

let failures = 0;
for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failures += 1;
        console.log(`  FAIL ${name}`);
        console.log(error);
    }
}
console.log(`\n${checks.length - failures}/${checks.length} backup and recovery logic checks passed`);
if (failures) {
    process.exit(1);
}
