// test_v2_admin_scale_logic.ts
//
// Runtime test for the browser logic behind the Admin Settings Scale group.
// Version: 0.261.260
// Implemented in: 0.261.260
//
// The Scale panels explain themselves before anything is sent: the throughput rules a save
// must pass, the RU/s a manual scale will land on, which capacity actions apply, and what a
// status means. None of that shows up in review or in a screenshot -- a wrong estimate is a
// plausible number in a confirmation dialog -- so it is executed here.
//
// Two kinds of check run. The mirror checks read cases that test_v2_admin_scale_logic.py
// generates from functions_cosmos_throughput.py and the live schema, and require the
// browser to reach exactly the server's answers, so a rule changed on one side fails until
// the other follows. The rest pin presentation logic with no server counterpart.
//
// Run by test_v2_admin_scale_logic.py, which bundles this with esbuild and executes it under
// node, passing the generated cases' path in SCALE_LOGIC_CASES.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE,
    buildAccessValidationPayload,
    containerActions,
    containerPolicyLabel,
    containerScalePolicy,
    containerUtilization,
    databaseActions,
    databaseScalePolicy,
    describeCosmosThroughputStatus,
    effectiveContainerPolicy,
    estimateManualScaleTarget,
    filterContainers,
    formatContainerUtilization,
    hasUnsavedThroughputEdits,
    mergeRuntimePolicyFields,
    nextContainerSort,
    normalizeContainerPolicy,
    normalizeRu,
    readGlobalPolicy,
    sortContainers,
    validateCosmosThroughputPolicy,
    type CosmosContainerPolicy,
    type CosmosContainerStatus,
    type CosmosThroughputStatus,
} from '../application/v2_ui/src/lib/cosmosThroughput';
import {
    formatBytes,
    formatRelativeTime,
    formatTtl,
    humanizeStatus,
    maintenanceStatusTone,
} from '../application/v2_ui/src/lib/scaleFormat';
import {
    describeRedisRefresh,
    readRedisExplorerError,
    redisHealthTone,
    type RedisMonitoringStatus,
} from '../application/v2_ui/src/lib/scaleRedis';
import {
    backfillStatusFromRun,
    describeBackfillRun,
    describeCleanupRun,
    indexingPolicyStatus,
    isBackfillRunning,
    type AppMaintenanceRunResult,
    type CosmosIndexingPolicyStatus,
    type DocumentAccessIndexStatus,
} from '../application/v2_ui/src/lib/scaleMaintenance';
import { resolveFieldPresentation, type AdminField } from '../application/v2_ui/src/lib/adminFields';
import { buildSectionDependents, collectRequirements } from '../application/v2_ui/src/lib/adminSections';

type Json = Record<string, unknown>;

interface MirrorCases {
    normalize_ru: { value: unknown; mode: unknown; direction: 'up' | 'down'; expected: number }[];
    policy_validation: {
        name: string;
        settings: Json;
        messages: string[];
        field_error_keys: string[];
        container_errors: Record<string, string[]>;
    }[];
    container_policies: {
        name: string;
        container: string;
        policy: CosmosContainerPolicy | null;
        settings: Json;
        repair: boolean;
        expected: Json;
    }[];
    manual_scale: {
        name: string;
        settings: Json;
        status: CosmosThroughputStatus;
        direction: 'up' | 'down';
        container: string;
        expected: { target?: number; error?: string };
    }[];
    sections: { sectionId: string; label: string; fields: AdminField[] }[];
}

const casesPath = process.env.SCALE_LOGIC_CASES;
const cases: MirrorCases | null = casesPath ? JSON.parse(readFileSync(casesPath, 'utf-8')) : null;

function requireCases(): MirrorCases {
    assert.ok(cases, 'SCALE_LOGIC_CASES is not set; run this through test_v2_admin_scale_logic.py');
    return cases;
}

/** A settings reader with `dict.get` semantics: a missing key reads as undefined. */
function reader(values: Json): (key: string) => unknown {
    return (key) => values[key];
}

function sectionFields(sectionId: string): AdminField[] {
    const section = requireCases().sections.find((candidate) => candidate.sectionId === sectionId);
    assert.ok(section, `${sectionId} is not in the generated schema`);
    return section.fields;
}

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

// --- Mirrors of functions_cosmos_throughput.py ----------------------------------------------

check('normalizeRu reaches normalize_ru for every generated case', () => {
    const { normalize_ru: generated } = requireCases();
    assert.ok(generated.length > 100, 'too few normalize_ru cases were generated');
    for (const item of generated) {
        assert.equal(
            normalizeRu(item.value, item.mode, item.direction),
            item.expected,
            `normalize_ru(${JSON.stringify(item.value)}, ${JSON.stringify(item.mode)}, ${item.direction})`,
        );
    }
});

check('policy validation reports what collect_cosmos_throughput_policy_errors reports', () => {
    const { policy_validation: generated } = requireCases();
    for (const item of generated) {
        const result = validateCosmosThroughputPolicy(reader(item.settings));
        assert.deepEqual(result.messages, item.messages, `${item.name}: messages`);
        assert.deepEqual(
            Object.keys(result.fieldErrors).sort(),
            [...item.field_error_keys].sort(),
            `${item.name}: the controls carrying an error`,
        );
        for (const message of Object.values(result.fieldErrors)) {
            assert.ok(item.messages.includes(message), `${item.name}: "${message}" is not a server message`);
        }
        const containerFields = Object.fromEntries(
            Object.entries(result.containerErrors).map(([name, errors]) => [name, Object.keys(errors).sort()]),
        );
        const expectedContainerFields = Object.fromEntries(
            Object.entries(item.container_errors).map(([name, fields]) => [name, [...fields].sort()]),
        );
        assert.deepEqual(containerFields, expectedContainerFields, `${item.name}: container policy fields`);
    }
});

check('container policies normalize as normalize_container_policy does', () => {
    const { container_policies: generated } = requireCases();
    for (const item of generated) {
        const globals = readGlobalPolicy(reader(item.settings), item.repair);
        const actual = normalizeContainerPolicy(item.container, item.policy, globals, item.repair);
        assert.deepEqual(actual, item.expected, item.name);
    }
});

check('manual scale estimates land where calculate_manual_scale_target lands', () => {
    const { manual_scale: generated } = requireCases();
    for (const item of generated) {
        const globals = readGlobalPolicy(reader(item.settings));
        let estimate;
        if (item.container) {
            const container = (item.status.containers ?? []).find(
                (candidate) => candidate.container_name === item.container,
            );
            assert.ok(container, `${item.name}: the generated status has no ${item.container}`);
            estimate = estimateManualScaleTarget(container, containerScalePolicy(container, globals), item.direction);
        } else {
            estimate = estimateManualScaleTarget(item.status.throughput, databaseScalePolicy(globals), item.direction);
        }
        const outcome = estimate.target !== undefined ? { target: estimate.target } : { error: estimate.error };
        assert.deepEqual(outcome, item.expected, item.name);
    }
});

// --- The declared Scale schema ----------------------------------------------------------------

check('the Redis key reads as a Key Vault secret name only in Key Vault mode', () => {
    const redisKey = sectionFields('redis-cache-section').find((field) => field.key === 'redis_key');
    assert.ok(redisKey, 'redis_key is not declared');

    const vault = resolveFieldPresentation(redisKey, reader({ redis_auth_type: 'key_vault' }));
    assert.equal(vault.label, 'Key Vault Secret Name');
    assert.notEqual(vault.help, redisKey.help);
    assert.equal(vault.key, 'redis_key', 'the variant relabels the same stored setting');

    assert.equal(resolveFieldPresentation(redisKey, reader({ redis_auth_type: 'key' })), redisKey);
});

check('the Key Vault prerequisite applies only while Redis reads its key from a vault', () => {
    const fields = sectionFields('redis-cache-section');
    const needsVault = (settings: Json, draft: Json = {}) =>
        collectRequirements(fields, settings, draft).some(
            (requirement) => requirement.key === 'enable_key_vault_secret_storage',
        );

    assert.equal(needsVault({ enable_redis_cache: true, redis_auth_type: 'key_vault' }), true);
    assert.equal(needsVault({ enable_redis_cache: true, redis_auth_type: 'key' }), false);
    assert.equal(needsVault({ enable_redis_cache: true, redis_auth_type: 'managed_identity' }), false);
    // An unsaved choice counts, so the notice appears as the administrator picks Key Vault.
    assert.equal(needsVault({ enable_redis_cache: true, redis_auth_type: 'key' }, { redis_auth_type: 'key_vault' }), true);
});

check('"Used by" lists exactly the sections that show a prerequisite notice', () => {
    const { sections } = requireCases();
    const usedBy = (settings: Json, target: string, flags?: Record<string, boolean>) =>
        (buildSectionDependents(sections, settings, {}, flags).get(target) ?? []).map(
            (dependent) => dependent.sectionId,
        );
    const settings = { enable_redis_cache: true, redis_auth_type: 'key', enable_document_access_index_cache: true };

    const redis = usedBy(settings, 'redis-cache-section');
    for (const sectionId of ['conversation-cache-section', 'redis-monitoring-section', 'file-sync-section']) {
        assert.ok(redis.includes(sectionId), `Redis Cache should be used by ${sectionId}`);
    }
    // The index's Redis switch is a diagnostic, hidden without the debug flag.
    assert.ok(!redis.includes('document-access-index-section'), 'a hidden switch adds no "Used by" entry');
    assert.ok(
        usedBy(settings, 'redis-cache-section', { dai_debug_enabled: true }).includes('document-access-index-section'),
    );
    assert.ok(
        !usedBy({ ...settings, enable_document_access_index_cache: false }, 'redis-cache-section', {
            dai_debug_enabled: true,
        }).includes('document-access-index-section'),
        'a switched-off cache does not rely on Redis',
    );

    assert.ok(!usedBy(settings, 'keyvault-section').includes('redis-cache-section'));
    assert.ok(usedBy({ ...settings, redis_auth_type: 'key_vault' }, 'keyvault-section').includes('redis-cache-section'));
    assert.ok(usedBy(settings, 'cosmos-maintenance-section').includes('document-access-index-section'));

    // A section never lists itself.
    for (const [target, dependents] of buildSectionDependents(sections, settings, {})) {
        assert.ok(!dependents.some((dependent) => dependent.sectionId === target), `${target} lists itself`);
    }
});

// --- Throughput presentation ------------------------------------------------------------------

check('throughput status messages follow the classic precedence', () => {
    const describe = (status: Json) => describeCosmosThroughputStatus(status as CosmosThroughputStatus);

    assert.deepEqual(describe({ configured: false }), {
        text: 'Cosmos throughput management needs subscription, resource group, account, and database settings.',
        tone: 'warn',
    });
    assert.equal(describe({ configured: false, error: 'Missing subscription.' }).text, 'Missing subscription.');
    assert.deepEqual(describe({ configured: true, throughput_error: 'Forbidden.' }), {
        text: 'Cosmos database throughput could not be read. Forbidden.',
        tone: 'danger',
    });

    const aggregateOnly = {
        configured: true,
        capacity_scope: 'container',
        metrics: { normalized_ru_percent: 40 },
        containers: [{ container_name: 'a', current_ru: 1000, is_scalable: true }],
    };
    assert.equal(describe(aggregateOnly).tone, 'warn');
    assert.match(describe(aggregateOnly).text, /not per-container metric dimensions/);
    const perContainer = {
        ...aggregateOnly,
        containers: [{ container_name: 'a', current_ru: 1000, is_scalable: true, normalized_ru_percent: 40 }],
    };
    assert.equal(describe(perContainer).tone, 'info');

    const portal = { configured: true, throughput: { mode: 'autoscale', current_ru: 20000, is_scalable: true } };
    assert.match(describe(portal).text, /above 10,000 RU\/s/);
    assert.equal(describe({ ...portal, capacity_scope: 'container' }).tone, 'warn', 'portal-managed outranks the scope note');

    const loaded = { configured: true, throughput: { mode: 'autoscale', current_ru: 4000, is_scalable: true } };
    assert.equal(describe({ ...loaded, metric_error: 'No metrics.' }).tone, 'warn');
    assert.deepEqual(describe(loaded), { text: 'Cosmos throughput status loaded.', tone: 'ok' });
});

check('container utilization prefers Azure Monitor and marks estimates', () => {
    const measured = { container_name: 'a', normalized_ru_percent: 37.5, request_units: 1, current_ru: 1000 };
    assert.deepEqual(containerUtilization(measured as CosmosContainerStatus, 5), { value: 37.5, estimated: false });

    // 600,000 RU over a five-minute window against 4,000 RU/s is half the capacity.
    const estimated = { container_name: 'b', request_units: 600000, current_ru: 4000 } as CosmosContainerStatus;
    assert.deepEqual(containerUtilization(estimated, 5), { value: 50, estimated: true });
    assert.equal(formatContainerUtilization(estimated, 5), '50.0% est.');
    assert.equal(formatContainerUtilization(estimated, 0), 'Not available');
    assert.equal(formatContainerUtilization({ container_name: 'c' } as CosmosContainerStatus, 5), 'Not available');
});

check('container sorting keeps missing values last and breaks ties by name', () => {
    const rows = [
        { container_name: 'beta', current_ru: 4000, normalized_ru_percent: 20 },
        { container_name: 'alpha', current_ru: 4000, normalized_ru_percent: 80 },
        { container_name: 'gamma', current_ru: null },
        { container_name: 'Delta', current_ru: 1000, normalized_ru_percent: 20 },
    ] as CosmosContainerStatus[];
    const options = { windowMinutes: 5, policyLabel: () => '' };
    const names = (field: Parameters<typeof nextContainerSort>[1], direction: 'asc' | 'desc') =>
        sortContainers(rows, { field, direction }, options).map((row) => row.container_name);

    assert.deepEqual(names('current_ru', 'desc'), ['alpha', 'beta', 'Delta', 'gamma']);
    assert.deepEqual(names('current_ru', 'asc'), ['Delta', 'alpha', 'beta', 'gamma']);
    assert.deepEqual(names('ru_utilization', 'desc'), ['alpha', 'beta', 'Delta', 'gamma']);
    assert.deepEqual(names('container_name', 'asc'), ['alpha', 'beta', 'Delta', 'gamma']);

    assert.deepEqual(nextContainerSort({ field: 'current_ru', direction: 'desc' }, 'current_ru'), {
        field: 'current_ru',
        direction: 'asc',
    });
    assert.deepEqual(nextContainerSort({ field: 'current_ru', direction: 'desc' }, 'container_name'), {
        field: 'container_name',
        direction: 'asc',
    });
    assert.deepEqual(nextContainerSort({ field: 'container_name', direction: 'asc' }, 'request_units'), {
        field: 'request_units',
        direction: 'desc',
    });

    assert.deepEqual(filterContainers(rows, '  ALP ').map((row) => row.container_name), ['alpha']);
    assert.equal(filterContainers(rows, '').length, rows.length);
});

check('capacity actions are offered by the classic page rules', () => {
    const database = (status: Json | null) => databaseActions(status as CosmosThroughputStatus | null);

    const unloaded = database(null);
    assert.ok(unloaded.up.disabled && unloaded.down.disabled && unloaded.convert.disabled);
    assert.equal(unloaded.up.reason, 'Refresh the status before changing throughput.');

    const manual = database({ throughput: { mode: 'manual', current_ru: 4000, is_scalable: true } });
    assert.deepEqual(
        [manual.convert.disabled, manual.up.disabled, manual.down.disabled],
        [false, false, false],
    );

    const autoscale = database({ throughput: { mode: 'autoscale', current_ru: 4000, is_scalable: true } });
    assert.equal(autoscale.convert.reason, 'Throughput already uses Cosmos autoscale.');

    const atCeiling = database({ throughput: { mode: 'autoscale', current_ru: 10000, is_scalable: true } });
    assert.equal(atCeiling.up.reason, COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE);
    assert.equal(atCeiling.down.disabled, false, 'scaling down from the ceiling is still allowed');

    const portal = database({ throughput: { mode: 'autoscale', current_ru: 20000, is_scalable: true } });
    assert.ok(portal.up.disabled && portal.down.disabled && portal.convert.disabled);

    const containerScope = database({
        capacity_scope: 'container',
        throughput: { mode: 'container_or_serverless', is_scalable: false },
    });
    assert.equal(containerScope.up.reason, 'Throughput is set per container. Use the actions in Cosmos Metrics.');

    const shared = containerActions({ container_name: 'a', mode: 'manual', current_ru: 400, is_scalable: false } as CosmosContainerStatus);
    assert.equal(shared.up.reason, 'This container shares database throughput.');
    assert.ok(shared.convert.disabled && shared.down.disabled);

    const dedicated = containerActions({ container_name: 'b', mode: 'manual', current_ru: 4000, is_scalable: true } as CosmosContainerStatus);
    assert.deepEqual(
        [dedicated.convert.disabled, dedicated.up.disabled, dedicated.down.disabled],
        [false, false, false],
    );
});

check('an enforced global policy governs every container but keeps its timestamps', () => {
    const container = {
        container_name: 'conversations',
        policy: { min_ru: 5000, last_scale_up_at: '2026-01-01T00:00:00Z' },
    } as CosmosContainerStatus;

    const enforced = readGlobalPolicy(
        reader({ cosmos_throughput_enforce_container_defaults: true, cosmos_throughput_min_ru: 2000, cosmos_throughput_max_ru: 6000 }),
    );
    const governed = effectiveContainerPolicy(container, {}, enforced);
    assert.equal(governed.min_ru, 2000);
    assert.equal(governed.max_ru, 6000);
    assert.equal(governed.last_scale_up_at, '2026-01-01T00:00:00Z');
    assert.equal(containerPolicyLabel(container, governed, enforced), 'Global policy');

    const open = readGlobalPolicy(reader({ cosmos_throughput_min_ru: 2000, cosmos_throughput_max_ru: 6000 }));
    const staged = effectiveContainerPolicy(container, { conversations: { min_ru: 3000 } }, open);
    assert.equal(staged.min_ru, 3000, 'a staged edit wins over the policy the status reported');
    assert.equal(
        containerPolicyLabel(container, { ...staged, max_ru: 7000 }, open),
        `${(3000).toLocaleString()}-${(7000).toLocaleString()} RU/s`,
    );
    assert.equal(containerPolicyLabel(container, { ...staged, enabled: false }, open), 'Disabled');
    assert.equal(
        containerPolicyLabel({ ...container, current_ru: 20000, is_scalable: true }, staged, open),
        'Monitor only',
    );

    const merged = mergeRuntimePolicyFields({ container_name: 'x', min_ru: 1000 }, { last_scale_down_at: 'earlier' });
    assert.equal(merged.last_scale_down_at, 'earlier');
    assert.equal(merged.min_ru, 1000);
});

check('access validation sends the throughput settings as they would be saved', () => {
    const values: Json = {
        cosmos_throughput_account_name: 'draft-account',
        cosmos_throughput_min_ru: 2000,
        cosmos_throughput_container_policies: '{"conversations": {"min_ru": 2000}}',
        enable_redis_cache: true,
    };
    assert.deepEqual(buildAccessValidationPayload(reader(values)), {
        cosmos_throughput_account_name: 'draft-account',
        cosmos_throughput_min_ru: 2000,
        cosmos_throughput_container_policies: { conversations: { min_ru: 2000 } },
    });

    assert.equal(hasUnsavedThroughputEdits(['enable_redis_cache']), false);
    assert.equal(hasUnsavedThroughputEdits(['enable_redis_cache', 'cosmos_throughput_max_ru']), true);
    assert.equal(hasUnsavedThroughputEdits(['cosmos_throughput_container_policies']), true);
});

// --- Formatting, Redis and maintenance --------------------------------------------------------

check('Scale formatters read the way the classic page reads', () => {
    assert.equal(formatTtl(-1), 'No expiry');
    assert.equal(formatTtl(-2), 'Expired or missing');
    assert.equal(formatTtl(90), `${(90).toLocaleString()} sec`);
    assert.equal(formatTtl(null), 'Not available');

    assert.equal(formatBytes(512), `${(512).toLocaleString()} bytes`);
    assert.equal(formatBytes(2048), `${(2).toLocaleString()} KB`);
    assert.equal(formatBytes(1.5 * 1024 * 1024), `${(1.5).toLocaleString(undefined, { maximumFractionDigits: 2 })} MB`);
    assert.equal(formatBytes(-1), 'Not available');

    assert.equal(humanizeStatus('succeeded_with_errors'), 'Succeeded With Errors');
    assert.equal(humanizeStatus(''), 'Not loaded');

    const now = Date.UTC(2026, 0, 1, 12, 0, 0);
    assert.equal(formatRelativeTime(null, now), 'Not loaded yet');
    assert.equal(formatRelativeTime(now - 10_000, now), 'Updated just now');
    assert.equal(formatRelativeTime(now - 5 * 60_000, now), 'Updated 5 min ago');
    assert.equal(formatRelativeTime(now - 3 * 3_600_000, now), 'Updated 3 h ago');

    const tones: [string, string][] = [
        ['succeeded', 'ok'],
        ['aligned', 'ok'],
        ['running', 'info'],
        ['completed_with_errors', 'warn'],
        ['missing_expected_indexes', 'warn'],
        ['failed', 'danger'],
        ['something_new', 'neutral'],
    ];
    for (const [status, tone] of tones) {
        assert.equal(maintenanceStatusTone(status), tone, status);
    }
});

check('explorer failures read error first, then the endpoint detail, then the fallback', () => {
    assert.equal(
        readRedisExplorerError({ error: 'Failed to load Redis Explorer keys.', last_error: 'detail' }, ['last_error'], 'fallback'),
        'Failed to load Redis Explorer keys.',
    );
    assert.equal(
        readRedisExplorerError({ success: false, last_error: 'Redis cache is disabled.' }, ['last_error'], 'fallback'),
        'Redis cache is disabled.',
    );
    // A key deleted since the page loaded is a 404 explained in `preview`, with no `error`.
    assert.equal(
        readRedisExplorerError(
            { success: false, status: 'not_found', preview: 'Redis key was not found.' },
            ['preview', 'last_error'],
            'fallback',
        ),
        'Redis key was not found.',
    );
    assert.equal(
        readRedisExplorerError({ preview: '', last_error: 'Redis is unreachable.' }, ['preview', 'last_error'], 'fallback'),
        'Redis is unreachable.',
    );
    assert.equal(readRedisExplorerError({ error: '   ' }, ['last_error'], 'fallback'), 'fallback');
    assert.equal(readRedisExplorerError('<html>Bad gateway</html>', ['last_error'], 'fallback'), 'fallback');
    assert.equal(readRedisExplorerError(null, [], 'fallback'), 'fallback');
});

check('Redis health and refresh messages carry the classic tones', () => {
    assert.equal(redisHealthTone('healthy'), 'ok');
    assert.equal(redisHealthTone('degraded'), 'warn');
    assert.equal(redisHealthTone('not_configured'), 'warn');
    assert.equal(redisHealthTone('error'), 'danger');
    assert.equal(redisHealthTone(undefined), 'neutral');

    const refresh = (health: Json) => describeRedisRefresh({ health } as RedisMonitoringStatus);
    assert.deepEqual(refresh({ status: 'healthy' }), { text: 'Redis monitoring status loaded.', tone: 'ok' });
    assert.deepEqual(refresh({ status: 'error', last_error: 'Connection refused.' }), {
        text: 'Connection refused.',
        tone: 'danger',
    });
    assert.deepEqual(refresh({ status: 'degraded', last_error: 'Memory is nearly full.' }), {
        text: 'Memory is nearly full.',
        tone: 'warn',
    });
});

check('a manual backfill run reports the state it left behind', () => {
    const run = {
        success: true,
        steps: [
            { name: 'stale_cache_document_cleanup', results: {} },
            { name: 'document_access_index_backfill', results: { current_status: { state: { status: 'in_progress' } } } },
        ],
    } as AppMaintenanceRunResult;
    const status = backfillStatusFromRun(run);
    assert.deepEqual(status, { state: { status: 'in_progress' } });
    assert.equal(isBackfillRunning(status), false);
    assert.equal(describeBackfillRun(status).tone, 'info');
    assert.match(describeBackfillRun(status).text, /more documents remain/);

    const running = { state: { status: 'Running' } } as DocumentAccessIndexStatus;
    assert.equal(isBackfillRunning(running), true);
    assert.equal(describeBackfillRun({ state: { status: 'completed_with_errors' } } as DocumentAccessIndexStatus).tone, 'warn');
    assert.deepEqual(describeBackfillRun(null), { text: 'Document access index backfill batch completed.', tone: 'ok' });
    assert.equal(backfillStatusFromRun({ steps: [] }), null);
});

check('cleanup and index results are described as the classic page does', () => {
    assert.deepEqual(describeCleanupRun({ candidate_count: 3, deleted_count: 0 }, false), {
        text: `Stale cache cleanup dry run found ${(3).toLocaleString()} candidate document(s).`,
        tone: 'ok',
    });
    assert.equal(describeCleanupRun({ candidate_count: 3, deleted_count: 3, has_more_candidates: true }, true).tone, 'warn');

    const policy = (value: Json) => indexingPolicyStatus(value as CosmosIndexingPolicyStatus);
    assert.equal(indexingPolicyStatus(null), 'not_loaded');
    assert.equal(policy({ failed_container_count: 1, containers_missing_expected_indexes: 2 }), 'failed');
    assert.equal(policy({ containers_missing_expected_indexes: 2 }), 'missing_expected_indexes');
    assert.equal(policy({ updated_container_count: 0 }), 'aligned');
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
