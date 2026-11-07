// cosmosThroughput.ts
// Cosmos DB throughput: status, container policies, and the rules the server enforces.
//
// The Scale group reads `/api/admin/settings/cosmos-throughput/*`, the same endpoints the
// server-rendered page uses. Most of this module decides what to show from what those
// return -- which actions are allowed, what a container's utilization is when Azure
// Monitor sent no percentage, which policy actually governs a container.
//
// Two pieces mirror `functions_cosmos_throughput.py` so the page can explain itself before
// anything is sent: the policy rules a save must pass, and the target a manual scale will
// land on. The server stays authoritative for both; `test_v2_admin_scale_logic.ts` runs the
// same cases the Python tests do, so a change on one side fails until the other follows.

import { formatCount, formatRu, toNumber, type ToneText } from './scaleFormat';

export const COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU = 10000;
export const COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU = 1000;
export const COSMOS_THROUGHPUT_MANUAL_MIN_RU = 400;
export const COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE =
    'Throughput above 10,000 RU/s is monitored only in SimpleChat. Use the Azure portal to change capacity; ' +
    'capacity changes above this level can take 4 to 6 hours.';

/** Mirrors `COSMOS_THROUGHPUT_SETTING_KEYS`: what access validation sends from the draft. */
export const COSMOS_THROUGHPUT_SETTING_KEYS = [
    'cosmos_throughput_autoscale_enabled',
    'cosmos_throughput_auto_scale_up_enabled',
    'cosmos_throughput_auto_scale_down_enabled',
    'cosmos_throughput_subscription_id',
    'cosmos_throughput_resource_group',
    'cosmos_throughput_account_name',
    'cosmos_throughput_database_name',
    'cosmos_throughput_metrics_window_minutes',
    'cosmos_throughput_scale_up_threshold_percent',
    'cosmos_throughput_scale_down_threshold_percent',
    'cosmos_throughput_scale_up_step_ru',
    'cosmos_throughput_scale_down_step_ru',
    'cosmos_throughput_scale_up_cooldown_minutes',
    'cosmos_throughput_scale_down_cooldown_minutes',
    'cosmos_throughput_min_ru',
    'cosmos_throughput_max_ru',
    'cosmos_throughput_ignore_min_limit',
    'cosmos_throughput_ignore_max_limit',
    'cosmos_throughput_convert_manual_to_autoscale_enabled',
    'cosmos_throughput_enforce_container_defaults',
    'cosmos_throughput_container_policies',
] as const;

export const CONTAINER_POLICIES_KEY = 'cosmos_throughput_container_policies';

/** Written by the automation, never by an administrator; the server keeps its own copy. */
export const COSMOS_POLICY_RUNTIME_FIELDS = [
    'last_scale_up_at',
    'last_scale_down_at',
    'last_mode_conversion_at',
] as const;

export interface CosmosThroughputTarget {
    scope?: string;
    mode?: string | null;
    current_ru?: number | null;
    is_scalable?: boolean;
    throughput_not_found?: boolean;
    message?: string;
    simplechat_scaling_supported?: boolean;
    portal_managed_scaling_required?: boolean;
    portal_managed_message?: string;
}

export interface CosmosContainerPolicy {
    container_name?: string;
    enabled?: boolean;
    auto_scale_up_enabled?: boolean;
    auto_scale_down_enabled?: boolean;
    scale_up_threshold_percent?: number;
    scale_down_threshold_percent?: number;
    scale_up_step_ru?: number;
    scale_down_step_ru?: number;
    scale_up_cooldown_minutes?: number;
    scale_down_cooldown_minutes?: number;
    min_ru?: number;
    max_ru?: number;
    ignore_min_limit?: boolean;
    ignore_max_limit?: boolean;
    convert_manual_to_autoscale_enabled?: boolean;
    last_scale_up_at?: string | null;
    last_scale_down_at?: string | null;
    last_mode_conversion_at?: string | null;
}

export type CosmosContainerPolicies = Record<string, CosmosContainerPolicy>;

export interface CosmosContainerStatus extends CosmosThroughputTarget {
    container_name: string;
    database_name?: string;
    normalized_ru_percent?: number | null;
    request_units?: number | null;
    error?: string;
    has_normalized_ru_metric?: boolean;
    has_request_units_metric?: boolean;
    policy?: CosmosContainerPolicy;
}

export interface CosmosThroughputStatus {
    configured?: boolean;
    error?: string;
    resource?: {
        subscription_id?: string;
        resource_group?: string;
        account_name?: string;
        database_name?: string;
    };
    throughput?: CosmosThroughputTarget;
    capacity_scope?: string | null;
    metrics?: {
        window_minutes?: number | null;
        normalized_ru_percent?: number | null;
        total_request_units?: number | null;
    };
    containers?: CosmosContainerStatus[];
    throughput_error?: string;
    metric_error?: string;
    container_error?: string;
    last_checked_at?: string | null;
    is_cached?: boolean;
    cached_at?: string | null;
}

export interface CosmosAccessCheck {
    name?: string;
    label?: string;
    passed?: boolean;
    message?: string;
}

export interface CosmosAccessValidation {
    success?: boolean;
    variant?: string;
    message?: string;
    checks?: CosmosAccessCheck[];
    status?: CosmosThroughputStatus;
}

export interface CosmosScaleResult {
    success?: boolean;
    scope?: string;
    container_name?: string;
    from_ru?: number | null;
    to_ru?: number | null;
    mode?: string;
}

/** Above 10,000 RU/s SimpleChat only monitors; the Azure portal owns capacity changes. */
export function isPortalManaged(target: CosmosThroughputTarget | null | undefined): boolean {
    const current = toNumber(target?.current_ru);
    return Boolean(target?.portal_managed_scaling_required) || (
        Boolean(target?.is_scalable) && current !== null && current > COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU
    );
}

export function isScaleUpBlockedBySimpleChatLimit(target: CosmosThroughputTarget | null | undefined): boolean {
    const current = toNumber(target?.current_ru);
    return Boolean(target?.is_scalable) && current !== null && current >= COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU;
}

export function portalManagedMessage(target: CosmosThroughputTarget | null | undefined): string {
    return target?.portal_managed_message || COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE;
}

/** Whether a saved snapshot holds anything worth showing before the first live refresh. */
export function hasStatusData(status: CosmosThroughputStatus | null | undefined): boolean {
    if (!status || typeof status !== 'object' || Array.isArray(status)) {
        return false;
    }
    return Boolean(status.last_checked_at || status.capacity_scope || (status.containers ?? []).length);
}

function hasContainerLevelMetrics(status: CosmosThroughputStatus): boolean {
    return (status.containers ?? []).some(
        (container) =>
            (container.normalized_ru_percent !== null && container.normalized_ru_percent !== undefined) ||
            (container.request_units !== null && container.request_units !== undefined),
    );
}

function hasPortalManagedThroughput(status: CosmosThroughputStatus): boolean {
    return isPortalManaged(status.throughput) || (status.containers ?? []).some((container) => isPortalManaged(container));
}

/** What to say about a freshly loaded status, in the classic page's order of precedence. */
export function describeCosmosThroughputStatus(status: CosmosThroughputStatus): ToneText {
    if (!status.configured) {
        return {
            text: status.error || 'Cosmos throughput management needs subscription, resource group, account, and database settings.',
            tone: 'warn',
        };
    }
    if (status.throughput_error) {
        return { text: `Cosmos database throughput could not be read. ${status.throughput_error}`, tone: 'danger' };
    }
    const aggregate = status.metrics?.normalized_ru_percent;
    if (
        status.capacity_scope === 'container' &&
        aggregate !== null &&
        aggregate !== undefined &&
        !hasContainerLevelMetrics(status)
    ) {
        return {
            text:
                'Azure Monitor returned aggregate RU utilization, but not per-container metric dimensions for this window. ' +
                'Container autoscale waits for per-container utilization before scaling individual containers; refresh again after a few minutes.',
            tone: 'warn',
        };
    }
    if (hasPortalManagedThroughput(status)) {
        return {
            text:
                'One or more Cosmos throughput targets are above 10,000 RU/s. SimpleChat monitors their utilization and request units only; ' +
                'use the Azure portal for capacity changes, which can take 4 to 6 hours.',
            tone: 'warn',
        };
    }
    if (status.capacity_scope === 'container') {
        return {
            text:
                'Container-targeted throughput is active. Dedicated-throughput containers can be monitored and scaled individually; ' +
                'containers sharing database throughput stay view-only.',
            tone: 'info',
        };
    }
    if (status.metric_error) {
        return {
            text: 'Throughput loaded, but Azure Monitor metrics are unavailable. Check the app identity permissions and Cosmos metrics availability.',
            tone: 'warn',
        };
    }
    return { text: 'Cosmos throughput status loaded.', tone: 'ok' };
}

/**
 * A container's RU utilization over the metrics window.
 *
 * Azure Monitor's normalized percentage is preferred. Without it the average is estimated
 * from request units over the window against current RU/s, and marked as an estimate.
 */
export function containerUtilization(
    container: CosmosContainerStatus,
    windowMinutes: number | null | undefined,
): { value: number | null; estimated: boolean } {
    const normalized = toNumber(container.normalized_ru_percent);
    if (normalized !== null) {
        return { value: normalized, estimated: false };
    }
    const requestUnits = toNumber(container.request_units);
    const currentRu = toNumber(container.current_ru);
    const minutes = Number(windowMinutes || 0);
    if (requestUnits !== null && currentRu !== null && currentRu > 0 && minutes > 0) {
        return { value: (requestUnits / (minutes * 60) / currentRu) * 100, estimated: true };
    }
    return { value: null, estimated: false };
}

export function formatContainerUtilization(
    container: CosmosContainerStatus,
    windowMinutes: number | null | undefined,
): string {
    const { value, estimated } = containerUtilization(container, windowMinutes);
    return value === null ? 'Not available' : `${value.toFixed(1)}%${estimated ? ' est.' : ''}`;
}

/** The global policy, read from the settings an administrator edits. */
export interface CosmosGlobalPolicy {
    autoscale_enabled: boolean;
    enforce_container_defaults: boolean;
    metrics_window_minutes: number;
    auto_scale_up_enabled: boolean;
    auto_scale_down_enabled: boolean;
    scale_up_threshold_percent: number;
    scale_down_threshold_percent: number;
    scale_up_step_ru: number;
    scale_down_step_ru: number;
    scale_up_cooldown_minutes: number;
    scale_down_cooldown_minutes: number;
    min_ru: number;
    max_ru: number;
    ignore_min_limit: boolean;
    ignore_max_limit: boolean;
    convert_manual_to_autoscale_enabled: boolean;
}

/** Mirrors `_coerce_bool` in `functions_cosmos_throughput.py`. */
export function coerceBool(value: unknown, fallback = false): boolean {
    if (typeof value === 'boolean') {
        return value;
    }
    if (value === null || value === undefined) {
        return fallback;
    }
    if (typeof value === 'string') {
        return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
    }
    return Boolean(value);
}

/** Mirrors `_coerce_int`: integers only, falling back rather than guessing, then clamped. */
export function coerceInt(value: unknown, fallback: number, minimum?: number, maximum?: number): number {
    let parsed = fallback;
    if (typeof value === 'number' && Number.isFinite(value)) {
        parsed = Math.trunc(value);
    } else if (typeof value === 'boolean') {
        parsed = value ? 1 : 0;
    } else if (typeof value === 'string' && /^\s*[+-]?\d+\s*$/.test(value)) {
        parsed = Number.parseInt(value, 10);
    }
    if (minimum !== undefined) {
        parsed = Math.max(minimum, parsed);
    }
    if (maximum !== undefined) {
        parsed = Math.min(maximum, parsed);
    }
    return parsed;
}

/** Mirrors `normalize_ru`: Cosmos moves autoscale in 1,000 RU/s and manual in 100 RU/s. */
export function normalizeRu(value: unknown, mode: unknown = 'autoscale', direction: 'up' | 'down' = 'up'): number {
    const autoscale = String(mode ?? '').trim().toLowerCase() === 'autoscale';
    const quantum = autoscale ? 1000 : 100;
    const serviceMinimum = autoscale ? COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU : COSMOS_THROUGHPUT_MANUAL_MIN_RU;
    const raw = coerceInt(value, serviceMinimum, serviceMinimum);
    const adjusted = direction === 'down'
        ? Math.floor(raw / quantum) * quantum
        : Math.ceil(raw / quantum) * quantum;
    return Math.max(serviceMinimum, adjusted);
}

/**
 * Read the global policy the way `normalize_cosmos_throughput_settings` does.
 *
 * `repair` matches its `repair_policy_relationships`: validation reads without repair so a
 * broken relationship is reported, while an estimate reads with it, as the server would.
 */
export function readGlobalPolicy(read: (key: string) => unknown, repair = true): CosmosGlobalPolicy {
    const upThreshold = coerceInt(read('cosmos_throughput_scale_up_threshold_percent'), 90, 1, 100);
    let downThreshold = coerceInt(read('cosmos_throughput_scale_down_threshold_percent'), 70, 0, 99);
    if (repair && downThreshold >= upThreshold) {
        downThreshold = Math.max(0, upThreshold - 1);
    }
    const minRu = Math.min(normalizeRu(read('cosmos_throughput_min_ru')), COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU);
    // `dict.get(key, default)` semantics: only a missing key takes the default.
    const rawMax = read('cosmos_throughput_max_ru');
    let maxRu = Math.min(normalizeRu(rawMax === undefined ? COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU : rawMax), COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU);
    if (repair && maxRu < minRu) {
        maxRu = minRu;
    }
    return {
        autoscale_enabled: coerceBool(read('cosmos_throughput_autoscale_enabled'), false),
        enforce_container_defaults: coerceBool(read('cosmos_throughput_enforce_container_defaults'), false),
        metrics_window_minutes: coerceInt(read('cosmos_throughput_metrics_window_minutes'), 5, 1, 60),
        auto_scale_up_enabled: coerceBool(read('cosmos_throughput_auto_scale_up_enabled'), true),
        auto_scale_down_enabled: coerceBool(read('cosmos_throughput_auto_scale_down_enabled'), true),
        scale_up_threshold_percent: upThreshold,
        scale_down_threshold_percent: downThreshold,
        scale_up_step_ru: normalizeRu(read('cosmos_throughput_scale_up_step_ru')),
        scale_down_step_ru: normalizeRu(read('cosmos_throughput_scale_down_step_ru')),
        scale_up_cooldown_minutes: coerceInt(read('cosmos_throughput_scale_up_cooldown_minutes'), 5, 1, 1440),
        scale_down_cooldown_minutes: coerceInt(read('cosmos_throughput_scale_down_cooldown_minutes'), 20, 1, 1440),
        min_ru: minRu,
        max_ru: maxRu,
        ignore_min_limit: coerceBool(read('cosmos_throughput_ignore_min_limit'), false),
        ignore_max_limit: coerceBool(read('cosmos_throughput_ignore_max_limit'), false),
        convert_manual_to_autoscale_enabled: coerceBool(read('cosmos_throughput_convert_manual_to_autoscale_enabled'), false),
    };
}

/**
 * Normalize one container policy, mirroring `normalize_container_policy`.
 *
 * A value the policy leaves out inherits the global one, which is why a container with no
 * saved policy of its own still behaves predictably.
 */
export function normalizeContainerPolicy(
    containerName: string,
    policy: CosmosContainerPolicy | null | undefined,
    globals: CosmosGlobalPolicy,
    repair = true,
): Required<Omit<CosmosContainerPolicy, 'last_scale_up_at' | 'last_scale_down_at' | 'last_mode_conversion_at'>> &
    Pick<CosmosContainerPolicy, 'last_scale_up_at' | 'last_scale_down_at' | 'last_mode_conversion_at'> {
    const source = policy ?? {};
    // `source.get(key, global)` semantics: only a missing key inherits the global value.
    const inherit = <T,>(value: T | undefined, fallback: T): T | undefined | null =>
        value === undefined ? fallback : value;
    const upThreshold = coerceInt(source.scale_up_threshold_percent, globals.scale_up_threshold_percent, 1, 100);
    let downThreshold = coerceInt(source.scale_down_threshold_percent, globals.scale_down_threshold_percent, 0, 99);
    if (repair && downThreshold >= upThreshold) {
        downThreshold = Math.max(0, upThreshold - 1);
    }
    const minRu = Math.min(normalizeRu(inherit(source.min_ru, globals.min_ru)), COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU);
    let maxRu = Math.min(normalizeRu(inherit(source.max_ru, globals.max_ru)), COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU);
    if (repair && maxRu < minRu) {
        maxRu = minRu;
    }
    return {
        container_name: String(containerName || source.container_name || '').trim(),
        enabled: coerceBool(source.enabled, true),
        auto_scale_up_enabled: coerceBool(source.auto_scale_up_enabled, globals.auto_scale_up_enabled),
        auto_scale_down_enabled: coerceBool(source.auto_scale_down_enabled, globals.auto_scale_down_enabled),
        scale_up_threshold_percent: upThreshold,
        scale_down_threshold_percent: downThreshold,
        scale_up_step_ru: normalizeRu(inherit(source.scale_up_step_ru, globals.scale_up_step_ru)),
        scale_down_step_ru: normalizeRu(inherit(source.scale_down_step_ru, globals.scale_down_step_ru)),
        scale_up_cooldown_minutes: coerceInt(source.scale_up_cooldown_minutes, globals.scale_up_cooldown_minutes, 1, 1440),
        scale_down_cooldown_minutes: coerceInt(source.scale_down_cooldown_minutes, globals.scale_down_cooldown_minutes, 1, 1440),
        min_ru: minRu,
        max_ru: maxRu,
        ignore_min_limit: coerceBool(source.ignore_min_limit, globals.ignore_min_limit),
        ignore_max_limit: coerceBool(source.ignore_max_limit, globals.ignore_max_limit),
        convert_manual_to_autoscale_enabled: coerceBool(
            source.convert_manual_to_autoscale_enabled,
            globals.convert_manual_to_autoscale_enabled,
        ),
        last_scale_up_at: source.last_scale_up_at ?? null,
        last_scale_down_at: source.last_scale_down_at ?? null,
        last_mode_conversion_at: source.last_mode_conversion_at ?? null,
    };
}

/** The global policy written out as one container's policy, for "Apply global policy". */
export function buildGlobalContainerPolicy(globals: CosmosGlobalPolicy, containerName: string): CosmosContainerPolicy {
    return {
        container_name: containerName,
        enabled: true,
        auto_scale_up_enabled: globals.auto_scale_up_enabled,
        auto_scale_down_enabled: globals.auto_scale_down_enabled,
        scale_up_threshold_percent: globals.scale_up_threshold_percent,
        scale_down_threshold_percent: globals.scale_down_threshold_percent,
        scale_up_step_ru: globals.scale_up_step_ru,
        scale_down_step_ru: globals.scale_down_step_ru,
        scale_up_cooldown_minutes: globals.scale_up_cooldown_minutes,
        scale_down_cooldown_minutes: globals.scale_down_cooldown_minutes,
        min_ru: globals.min_ru,
        max_ru: globals.max_ru,
        ignore_min_limit: globals.ignore_min_limit,
        ignore_max_limit: globals.ignore_max_limit,
        convert_manual_to_autoscale_enabled: globals.convert_manual_to_autoscale_enabled,
    };
}

/** Keep the automation's timestamps when a policy is replaced. */
export function mergeRuntimePolicyFields(
    policy: CosmosContainerPolicy,
    existing: CosmosContainerPolicy | null | undefined,
): CosmosContainerPolicy {
    const merged: CosmosContainerPolicy = { ...policy };
    for (const field of COSMOS_POLICY_RUNTIME_FIELDS) {
        if (existing?.[field]) {
            merged[field] = existing[field];
        }
    }
    return merged;
}

/** The stored or staged policies, tolerating the JSON string the classic page may have saved. */
export function readContainerPolicies(value: unknown): CosmosContainerPolicies {
    let candidate = value;
    if (typeof candidate === 'string') {
        try {
            candidate = JSON.parse(candidate || '{}');
        } catch {
            return {};
        }
    }
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
        return {};
    }
    return candidate as CosmosContainerPolicies;
}

/**
 * The policy that governs a container, as the classic page resolves it.
 *
 * With the global policy enforced, the container follows the global settings and keeps
 * only its timestamps. Otherwise the staged or saved policy wins over the one the server
 * reported with the status.
 */
export function effectiveContainerPolicy(
    container: CosmosContainerStatus,
    policies: CosmosContainerPolicies,
    globals: CosmosGlobalPolicy,
): CosmosContainerPolicy {
    const name = container.container_name || '';
    if (globals.enforce_container_defaults) {
        return mergeRuntimePolicyFields(buildGlobalContainerPolicy(globals, name), policies[name] ?? container.policy);
    }
    return { ...(container.policy ?? {}), ...(policies[name] ?? {}), container_name: name };
}

/** The Policy column, in the classic page's words. */
export function containerPolicyLabel(
    container: CosmosContainerStatus,
    policy: CosmosContainerPolicy,
    globals: CosmosGlobalPolicy,
): string {
    if (isPortalManaged(container)) {
        return 'Monitor only';
    }
    if (globals.enforce_container_defaults) {
        return 'Global policy';
    }
    if (policy.enabled === false) {
        return 'Disabled';
    }
    return `${policy.min_ru ? formatCount(policy.min_ru) : 'min'}-${policy.max_ru ? formatCount(policy.max_ru) : 'max'} RU/s`;
}

export type ContainerSortField = 'container_name' | 'current_ru' | 'ru_utilization' | 'request_units' | 'policy';

export interface ContainerSort {
    field: ContainerSortField;
    direction: 'asc' | 'desc';
}

const TEXT_SORT_FIELDS = new Set<ContainerSortField>(['container_name', 'policy']);

/** Clicking a header flips its direction; a new numeric column starts with the largest first. */
export function nextContainerSort(current: ContainerSort, field: ContainerSortField): ContainerSort {
    if (current.field === field) {
        return { field, direction: current.direction === 'desc' ? 'asc' : 'desc' };
    }
    return { field, direction: TEXT_SORT_FIELDS.has(field) ? 'asc' : 'desc' };
}

export function filterContainers(containers: CosmosContainerStatus[], query: string): CosmosContainerStatus[] {
    const needle = query.trim().toLowerCase();
    if (!needle) {
        return [...containers];
    }
    return containers.filter((container) => (container.container_name || 'database').toLowerCase().includes(needle));
}

/** Sort rows, keeping missing values last and breaking ties by name. */
export function sortContainers(
    containers: CosmosContainerStatus[],
    sort: ContainerSort,
    options: { windowMinutes?: number | null; policyLabel: (container: CosmosContainerStatus) => string },
): CosmosContainerStatus[] {
    const valueOf = (container: CosmosContainerStatus, field: ContainerSortField): string | number | null => {
        switch (field) {
            case 'container_name':
                return (container.container_name || 'database').toLowerCase();
            case 'current_ru':
                return toNumber(container.current_ru);
            case 'ru_utilization':
                return containerUtilization(container, options.windowMinutes).value;
            case 'request_units':
                return toNumber(container.request_units);
            case 'policy':
                return options.policyLabel(container).toLowerCase();
            default:
                return null;
        }
    };
    const compare = (first: string | number | null, second: string | number | null, field: ContainerSortField, direction: 'asc' | 'desc') => {
        const firstMissing = first === null || first === '';
        const secondMissing = second === null || second === '';
        if (firstMissing && secondMissing) {
            return 0;
        }
        if (firstMissing) {
            return 1;
        }
        if (secondMissing) {
            return -1;
        }
        const multiplier = direction === 'desc' ? -1 : 1;
        if (TEXT_SORT_FIELDS.has(field)) {
            return String(first).localeCompare(String(second), undefined, { sensitivity: 'base', numeric: true }) * multiplier;
        }
        return (Number(first) - Number(second)) * multiplier;
    };
    return [...containers].sort((first, second) => {
        const primary = compare(valueOf(first, sort.field), valueOf(second, sort.field), sort.field, sort.direction);
        if (primary !== 0) {
            return primary;
        }
        return compare(valueOf(first, 'container_name'), valueOf(second, 'container_name'), 'container_name', 'asc');
    });
}

/** "Current 4,000 RU/s" style summary used in the workbench list. */
export function describeContainerCapacity(container: CosmosContainerStatus): string {
    return `${container.mode || 'unknown'} | ${formatRu(container.current_ru)}`;
}

/** Policy fields a rule can fault on a container, for inline errors in the workbench. */
export type ContainerPolicyField =
    | 'scale_up_threshold_percent'
    | 'scale_down_threshold_percent'
    | 'scale_up_cooldown_minutes'
    | 'scale_down_cooldown_minutes';

export interface CosmosPolicyValidation {
    /** Errors keyed by the global settings key they belong beside. */
    fieldErrors: Record<string, string>;
    /** Errors per container, keyed by the policy field they belong beside. */
    containerErrors: Record<string, Partial<Record<ContainerPolicyField, string>>>;
    /** Every message, in the order the server reports them. */
    messages: string[];
}

const GLOBAL_POLICY_FIELD_KEYS: Record<ContainerPolicyField, string> = {
    scale_up_threshold_percent: 'cosmos_throughput_scale_up_threshold_percent',
    scale_down_threshold_percent: 'cosmos_throughput_scale_down_threshold_percent',
    scale_up_cooldown_minutes: 'cosmos_throughput_scale_up_cooldown_minutes',
    scale_down_cooldown_minutes: 'cosmos_throughput_scale_down_cooldown_minutes',
};

interface PolicyProblem {
    fields: ContainerPolicyField[];
    message: string;
    involvesWindow: boolean;
}

/** Mirrors `_collect_policy_problems`, message for message. */
function collectPolicyProblems(
    policy: Record<ContainerPolicyField, number>,
    metricsWindowMinutes: number,
): PolicyProblem[] {
    const problems: PolicyProblem[] = [];
    if (policy.scale_up_threshold_percent <= policy.scale_down_threshold_percent) {
        problems.push({
            fields: ['scale_up_threshold_percent', 'scale_down_threshold_percent'],
            message: 'Scale Up At must be higher than Scale Down At.',
            involvesWindow: false,
        });
    }
    if (policy.scale_up_cooldown_minutes < metricsWindowMinutes) {
        problems.push({
            fields: ['scale_up_cooldown_minutes'],
            message: `Scale Up Interval must be greater than or equal to the Metrics Window (${metricsWindowMinutes} minutes).`,
            involvesWindow: true,
        });
    }
    if (policy.scale_down_cooldown_minutes < metricsWindowMinutes) {
        problems.push({
            fields: ['scale_down_cooldown_minutes'],
            message: `Scale Down Interval must be greater than or equal to the Metrics Window (${metricsWindowMinutes} minutes).`,
            involvesWindow: true,
        });
    }
    return problems;
}

/**
 * The rules a save must pass, mirroring `collect_cosmos_throughput_policy_errors`.
 *
 * Nothing is checked while automation is off, and container policies are skipped while
 * the global policy is enforced or a container's policy is disabled -- exactly when the
 * server skips them. `read` returns the value a save would leave behind: the draft where
 * there is one, otherwise the saved setting.
 */
export function validateCosmosThroughputPolicy(read: (key: string) => unknown): CosmosPolicyValidation {
    const result: CosmosPolicyValidation = { fieldErrors: {}, containerErrors: {}, messages: [] };
    const globals = readGlobalPolicy(read, false);
    if (!globals.autoscale_enabled) {
        return result;
    }

    const window = globals.metrics_window_minutes;
    for (const problem of collectPolicyProblems(globals, window)) {
        const message = `Cosmos throughput policy: ${problem.message}`;
        result.messages.push(message);
        for (const field of problem.fields) {
            result.fieldErrors[GLOBAL_POLICY_FIELD_KEYS[field]] ??= message;
        }
        if (problem.involvesWindow) {
            result.fieldErrors['cosmos_throughput_metrics_window_minutes'] ??= message;
        }
    }

    if (!globals.enforce_container_defaults) {
        const policies = readContainerPolicies(read(CONTAINER_POLICIES_KEY));
        for (const [name, policy] of Object.entries(policies)) {
            const containerName = String(name || '').trim();
            if (!containerName) {
                continue;
            }
            const normalized = normalizeContainerPolicy(containerName, policy, globals, false);
            if (normalized.enabled === false) {
                continue;
            }
            for (const problem of collectPolicyProblems(normalized, window)) {
                const message = `Container '${containerName}' policy: ${problem.message}`;
                result.messages.push(message);
                const errors = (result.containerErrors[containerName] ??= {});
                for (const field of problem.fields) {
                    errors[field] ??= problem.message;
                }
                result.fieldErrors[CONTAINER_POLICIES_KEY] ??= message;
            }
        }
    }

    return result;
}

/** The step and guardrails a manual scale uses for one target. */
export interface ManualScalePolicy {
    scale_up_step_ru: number;
    scale_down_step_ru: number;
    min_ru: number;
    max_ru: number;
    ignore_min_limit: boolean;
    ignore_max_limit: boolean;
}

export type ManualScaleEstimate = { target: number; error?: undefined } | { target?: undefined; error: string };

/**
 * The RU/s a manual scale will land on, mirroring `calculate_manual_scale_target`.
 *
 * Shown in the confirmation before the request is sent. The server computes the real target
 * from the saved settings, so the estimate is read from saved settings too, never the draft.
 */
export function estimateManualScaleTarget(
    target: CosmosThroughputTarget | null | undefined,
    policy: ManualScalePolicy,
    direction: 'up' | 'down',
): ManualScaleEstimate {
    const current = toNumber(target?.current_ru);
    const mode = target?.mode || 'autoscale';
    if (!current) {
        return { error: 'Current Cosmos throughput could not be determined.' };
    }
    if (isPortalManaged(target)) {
        return { error: COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE };
    }
    const limit = normalizeRu(COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU, mode, 'down');
    const currentRu = Math.trunc(current);

    if (direction === 'up') {
        let next = normalizeRu(currentRu + policy.scale_up_step_ru, mode, 'up');
        if (!policy.ignore_max_limit) {
            next = Math.min(next, normalizeRu(policy.max_ru, mode, 'up'));
        }
        next = Math.min(next, limit);
        if (next <= currentRu) {
            return currentRu >= limit
                ? { error: COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE }
                : { error: 'Maximum RU/s limit is already reached.' };
        }
        return { target: next };
    }

    const serviceMinimum = mode === 'autoscale' ? COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU : COSMOS_THROUGHPUT_MANUAL_MIN_RU;
    let next = normalizeRu(currentRu - policy.scale_down_step_ru, mode, 'down');
    if (!policy.ignore_min_limit) {
        next = Math.max(next, normalizeRu(policy.min_ru, mode, 'up'));
    }
    next = Math.max(serviceMinimum, next);
    if (next >= currentRu) {
        return { error: 'Minimum RU/s limit is already reached.' };
    }
    return { target: next };
}

/** The database-level manual scale policy, from saved settings. */
export function databaseScalePolicy(globals: CosmosGlobalPolicy): ManualScalePolicy {
    return {
        scale_up_step_ru: globals.scale_up_step_ru,
        scale_down_step_ru: globals.scale_down_step_ru,
        min_ru: globals.min_ru,
        max_ru: globals.max_ru,
        ignore_min_limit: globals.ignore_min_limit,
        ignore_max_limit: globals.ignore_max_limit,
    };
}

/** A container's manual scale policy: the one the server reported with the status. */
export function containerScalePolicy(container: CosmosContainerStatus, globals: CosmosGlobalPolicy): ManualScalePolicy {
    const policy = normalizeContainerPolicy(container.container_name, container.policy, globals);
    return {
        scale_up_step_ru: policy.scale_up_step_ru,
        scale_down_step_ru: policy.scale_down_step_ru,
        min_ru: policy.min_ru,
        max_ru: policy.max_ru,
        ignore_min_limit: policy.ignore_min_limit,
        ignore_max_limit: policy.ignore_max_limit,
    };
}

export interface ActionAvailability {
    disabled: boolean;
    /** Why the action is unavailable, for its tooltip and accessible name. */
    reason: string;
}

export interface CapacityActions {
    convert: ActionAvailability;
    up: ActionAvailability;
    down: ActionAvailability;
}

const AVAILABLE: ActionAvailability = { disabled: false, reason: '' };

/** Which database-level actions apply, by the classic page's rules. */
export function databaseActions(status: CosmosThroughputStatus | null | undefined): CapacityActions {
    if (!status?.throughput) {
        const reason = 'Refresh the status before changing throughput.';
        return { convert: { disabled: true, reason }, up: { disabled: true, reason }, down: { disabled: true, reason } };
    }
    const throughput = status.throughput;
    const containerScope = status.capacity_scope === 'container';
    const portal = isPortalManaged(throughput);
    const unscalable = containerScope
        ? 'Throughput is set per container. Use the actions in Cosmos Metrics.'
        : !throughput.is_scalable
            ? 'The database has no scalable throughput of its own.'
            : portal
                ? portalManagedMessage(throughput)
                : '';
    const upReason = unscalable || (isScaleUpBlockedBySimpleChatLimit(throughput) ? COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE : '');
    const convertReason = unscalable || (throughput.mode !== 'manual' ? 'Throughput already uses Cosmos autoscale.' : '');
    return {
        convert: convertReason ? { disabled: true, reason: convertReason } : AVAILABLE,
        up: upReason ? { disabled: true, reason: upReason } : AVAILABLE,
        down: unscalable ? { disabled: true, reason: unscalable } : AVAILABLE,
    };
}

/** Which actions apply to one container row. */
export function containerActions(container: CosmosContainerStatus): CapacityActions {
    const portal = isPortalManaged(container);
    const shared = !container.is_scalable ? 'This container shares database throughput.' : '';
    const portalReason = portal ? portalManagedMessage(container) : '';
    const upReason =
        shared || portalReason || (isScaleUpBlockedBySimpleChatLimit(container) ? COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE : '');
    const downReason = shared || portalReason;
    const convertReason =
        shared || portalReason || (container.mode !== 'manual' ? 'Throughput already uses Cosmos autoscale.' : '');
    return {
        convert: convertReason ? { disabled: true, reason: convertReason } : AVAILABLE,
        up: upReason ? { disabled: true, reason: upReason } : AVAILABLE,
        down: downReason ? { disabled: true, reason: downReason } : AVAILABLE,
    };
}

/**
 * The body for "Validate access": every throughput setting as it would be saved.
 *
 * The classic page posts its current form values, so a configuration can be checked
 * before it is saved. Unset keys are left out and the server keeps the stored value.
 */
export function buildAccessValidationPayload(read: (key: string) => unknown): Record<string, unknown> {
    const payload: Record<string, unknown> = {};
    for (const key of COSMOS_THROUGHPUT_SETTING_KEYS) {
        const value = read(key);
        if (value === undefined) {
            continue;
        }
        payload[key] = key === CONTAINER_POLICIES_KEY ? readContainerPolicies(value) : value;
    }
    return payload;
}

/** Whether any throughput setting has an unsaved edit, which manual actions would ignore. */
export function hasUnsavedThroughputEdits(draftKeys: string[]): boolean {
    const keys = new Set<string>(COSMOS_THROUGHPUT_SETTING_KEYS);
    return draftKeys.some((key) => keys.has(key));
}
