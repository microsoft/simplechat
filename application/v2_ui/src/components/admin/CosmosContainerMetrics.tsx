// CosmosContainerMetrics.tsx
// Per-container throughput, and each container's automation policy, as a workbench.
//
// The list answers "which container is hot": utilization, RU/s and request units for every
// container over the metrics window, filterable and sortable. Selecting one shows the rest
// of what is known about it, its manual capacity actions, and its policy, edited in place.
// It is the same list-beside-detail pattern the Model Catalog uses, so a collection is
// browsed the same way everywhere in Admin Settings.
//
// The policies are one settings value, `cosmos_throughput_container_policies`, and are
// edited into the page draft. The status comes from the store this card shares with Cosmos
// DB Throughput, so a refresh in either updates both.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { ArrowDownCircle, ArrowDownUp, ArrowUpCircle, RefreshCw, RotateCcw, Search, Zap } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';
import {
    CONTAINER_POLICIES_KEY,
    buildGlobalContainerPolicy,
    containerActions,
    containerPolicyLabel,
    containerUtilization,
    effectiveContainerPolicy,
    filterContainers,
    formatContainerUtilization,
    hasStatusData,
    isPortalManaged,
    mergeRuntimePolicyFields,
    normalizeContainerPolicy,
    portalManagedMessage,
    readContainerPolicies,
    readGlobalPolicy,
    sortContainers,
    validateCosmosThroughputPolicy,
    type ContainerSort,
    type ContainerSortField,
    type CosmosContainerPolicies,
    type CosmosContainerPolicy,
    type CosmosContainerStatus,
    type CosmosThroughputStatus,
} from '../../lib/cosmosThroughput';
import { formatCount, formatRu, type ToneText } from '../../lib/scaleFormat';
import type { Json } from '../../lib/types';
import { useScaleStatusStore } from '../../stores/scaleStatusStore';
import { inputClass } from './fields';
import { CosmosContainerPolicyForm } from './CosmosContainerPolicyForm';
import {
    OpsButton,
    OpsEmptyState,
    OpsHeading,
    OpsMessage,
    OpsPanel,
    Readout,
    ReadoutGrid,
    StatePill,
} from './OperationalReadouts';

const THROUGHPUT_SECTION_ID = 'cosmos-throughput-section';

const SORT_OPTIONS: { value: ContainerSortField; label: string }[] = [
    { value: 'container_name', label: 'Container' },
    { value: 'ru_utilization', label: 'RU utilization' },
    { value: 'current_ru', label: 'Current RU/s' },
    { value: 'request_units', label: 'Request units' },
    { value: 'policy', label: 'Policy' },
];

function containerBadge(container: CosmosContainerStatus): ToneText | null {
    if (isPortalManaged(container)) {
        return { text: 'Monitor only', tone: 'info' };
    }
    if (!container.is_scalable) {
        return { text: 'Shared throughput', tone: 'neutral' };
    }
    return null;
}

export function CosmosContainerMetrics({
    field,
    value,
    error,
    settings,
    draft,
    saving,
    onChange,
    onNavigate,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    settings: Json;
    draft: Json;
    saving: boolean;
    onChange: (next: CosmosContainerPolicies) => void;
    onNavigate: (sectionId: string) => void;
}) {
    const throughput = useScaleStatusStore((state) => state.throughput);
    const seedThroughput = useScaleStatusStore((state) => state.seedThroughput);
    const refreshThroughput = useScaleStatusStore((state) => state.refreshThroughput);
    const requestCapacityAction = useScaleStatusStore((state) => state.requestCapacityAction);
    const containerFocus = useScaleStatusStore((state) => state.containerFocus);

    const [filter, setFilter] = useState('');
    const [sort, setSort] = useState<ContainerSort>({ field: 'container_name', direction: 'asc' });
    const [selectedName, setSelectedName] = useState<string | null>(null);

    // This card can be on screen without Cosmos DB Throughput, during a search for one.
    const cached = settings['cosmos_throughput_cached_status'] as CosmosThroughputStatus | undefined;
    useEffect(() => {
        if (hasStatusData(cached)) {
            seedThroughput({ ...(cached as CosmosThroughputStatus), is_cached: true });
        }
    }, [cached, seedThroughput]);

    useEffect(() => {
        if (containerFocus.revision === 0) {
            return;
        }
        if (containerFocus.name) {
            setFilter('');
            setSelectedName(containerFocus.name);
        }
    }, [containerFocus]);

    const read = (key: string): unknown =>
        Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];
    const globals = readGlobalPolicy(read);
    // Editing reads values as typed, unrepaired, so a broken relationship stays visible
    // beside the value that breaks it instead of being quietly corrected on screen.
    const editingGlobals = readGlobalPolicy(read, false);
    const policies = readContainerPolicies(value);
    const savedPolicies = readContainerPolicies(settings[CONTAINER_POLICIES_KEY]);
    const validation = validateCosmosThroughputPolicy(read);

    const status = throughput.status;
    const containers = useMemo(() => status?.containers ?? [], [status]);
    const windowMinutes = status?.metrics?.window_minutes ?? globals.metrics_window_minutes;

    // A value the policy leaves out inherits the global one, so every field shows what
    // governs the container now -- including one discovered after its policy was saved.
    // A value the policy does set is shown as typed: normalizing it here would round a
    // half-typed number on every keystroke.
    const effective = (container: CosmosContainerStatus): CosmosContainerPolicy => {
        const own = effectiveContainerPolicy(container, policies, globals);
        const inherited = normalizeContainerPolicy(container.container_name, own, editingGlobals, false);
        const typed = Object.fromEntries(
            Object.entries(own).filter(([, fieldValue]) => fieldValue !== undefined && fieldValue !== null),
        ) as CosmosContainerPolicy;
        return { ...inherited, ...typed };
    };
    const labelFor = (container: CosmosContainerStatus) => containerPolicyLabel(container, effective(container), globals);
    const visible = sortContainers(filterContainers(containers, filter), sort, { windowMinutes, policyLabel: labelFor });
    const selected =
        containers.find((container) => container.container_name === selectedName) ?? visible[0] ?? null;

    const isUnsaved = (name: string) =>
        Object.prototype.hasOwnProperty.call(draft, CONTAINER_POLICIES_KEY) &&
        JSON.stringify(policies[name] ?? null) !== JSON.stringify(savedPolicies[name] ?? null);

    const updatePolicy = (container: CosmosContainerStatus, patch: Partial<CosmosContainerPolicy>) => {
        const name = container.container_name;
        onChange({ ...policies, [name]: { ...effective(container), ...patch, container_name: name } });
    };

    const applyGlobalPolicyTo = (targets: CosmosContainerStatus[]) => {
        const next: CosmosContainerPolicies = { ...policies };
        for (const container of targets) {
            const name = container.container_name;
            if (!name) {
                continue;
            }
            next[name] = mergeRuntimePolicyFields(
                buildGlobalContainerPolicy(globals, name),
                policies[name] ?? container.policy,
            );
        }
        onChange(next);
    };

    const busy = throughput.loading || throughput.acting;
    const editable = Boolean(selected) && !globals.enforce_container_defaults;

    return (
        <OpsPanel testId="cosmos-container-metrics">
            <OpsHeading label={field.label} help={field.help} />

            <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-48 flex-1">
                    <label htmlFor="cosmos-container-filter" className="mb-1 block text-xs text-text-2">
                        Filter containers
                    </label>
                    <div className="relative">
                        <Search
                            size={14}
                            aria-hidden="true"
                            className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                        />
                        <input
                            id="cosmos-container-filter"
                            type="search"
                            value={filter}
                            onChange={(event) => setFilter(event.target.value)}
                            placeholder="Container name"
                            autoComplete="off"
                            className={clsx(inputClass, 'pl-9')}
                        />
                    </div>
                </div>
                <div>
                    <label htmlFor="cosmos-container-sort" className="mb-1 block text-xs text-text-2">
                        Sort by
                    </label>
                    <div className="flex items-center gap-1">
                        <select
                            id="cosmos-container-sort"
                            value={sort.field}
                            onChange={(event) =>
                                setSort({
                                    field: event.target.value as ContainerSortField,
                                    direction:
                                        event.target.value === 'container_name' || event.target.value === 'policy'
                                            ? 'asc'
                                            : 'desc',
                                })
                            }
                            className={clsx(inputClass, 'w-40')}
                        >
                            {SORT_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                        <OpsButton
                            icon={ArrowDownUp}
                            aria-label={`Sort ${sort.direction === 'asc' ? 'descending' : 'ascending'}`}
                            onClick={() =>
                                setSort((current) => ({
                                    ...current,
                                    direction: current.direction === 'asc' ? 'desc' : 'asc',
                                }))
                            }
                        >
                            {sort.direction === 'asc' ? 'Ascending' : 'Descending'}
                        </OpsButton>
                    </div>
                </div>
                <OpsButton icon={RefreshCw} busy={throughput.loading} onClick={() => void refreshThroughput()}>
                    Refresh table
                </OpsButton>
                {containers.length && !globals.enforce_container_defaults ? (
                    <OpsButton
                        icon={RotateCcw}
                        disabled={saving}
                        onClick={() => applyGlobalPolicyTo(containers)}
                        title="Write the global policy into every discovered container's policy. Save to apply."
                    >
                        Apply global policy to all
                    </OpsButton>
                ) : null}
            </div>

            <OpsMessage message={error ? { text: error, tone: 'danger' } : null} />
            {globals.enforce_container_defaults ? (
                <OpsMessage
                    message={{
                        text: 'Global policy is enforced, so every container follows the Cosmos DB Throughput settings and per-container policies are not used.',
                        tone: 'info',
                    }}
                >
                    <button
                        type="button"
                        className="mt-1 text-xs text-accent underline"
                        onClick={() => onNavigate(THROUGHPUT_SECTION_ID)}
                    >
                        Change it in Cosmos DB Throughput
                    </button>
                </OpsMessage>
            ) : null}

            {!status ? (
                <OpsEmptyState title="No container metrics yet">
                    Refresh reads each container's throughput from Azure Resource Manager and its utilization from
                    Azure Monitor.
                </OpsEmptyState>
            ) : status.configured === false ? (
                <OpsEmptyState title="The Cosmos resource is not configured">
                    {status.error || 'Subscription, resource group, account and database are needed.'}{' '}
                    <button type="button" className="text-accent underline" onClick={() => onNavigate(THROUGHPUT_SECTION_ID)}>
                        Configure it in Cosmos DB Throughput
                    </button>
                </OpsEmptyState>
            ) : !containers.length ? (
                <OpsEmptyState title="No containers were returned">
                    The configured Cosmos database reported no containers.
                </OpsEmptyState>
            ) : (
                <div className="grid min-w-0 overflow-hidden rounded-xl border border-edge-strong bg-surface-solid @3xl:h-[clamp(26rem,64vh,44rem)] @3xl:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
                    <div className="flex min-h-0 min-w-0 flex-col border-b border-edge-strong @3xl:border-r @3xl:border-b-0">
                        <p className="border-b border-edge px-3 py-2 text-xs text-text-3" aria-live="polite">
                            Showing {visible.length} of {containers.length} containers · {windowMinutes} min window
                        </p>
                        <ul aria-label="Cosmos containers" className="max-h-[24rem] min-h-0 flex-1 divide-y divide-edge overflow-y-auto @3xl:max-h-none">
                            {!visible.length ? (
                                <li className="px-3 py-4 text-xs text-text-3">No containers match “{filter}”.</li>
                            ) : null}
                            {visible.map((container) => {
                                const isSelected = container.container_name === selected?.container_name;
                                const utilization = containerUtilization(container, windowMinutes);
                                const badge = containerBadge(container);
                                return (
                                    <li key={container.container_name}>
                                        <button
                                            type="button"
                                            aria-pressed={isSelected}
                                            onClick={() => setSelectedName(container.container_name)}
                                            className={clsx(
                                                'block w-full px-3 py-2 text-left transition-colors',
                                                isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2',
                                            )}
                                        >
                                            <span className="flex items-baseline justify-between gap-2">
                                                <span className="min-w-0 truncate text-sm font-semibold text-text-1">
                                                    {container.container_name}
                                                </span>
                                                <span className="shrink-0 text-xs font-semibold text-text-1 tabular-nums">
                                                    {utilization.value === null
                                                        ? '—'
                                                        : `${utilization.value.toFixed(1)}%${utilization.estimated ? ' est.' : ''}`}
                                                </span>
                                            </span>
                                            <span className="mt-0.5 block text-[0.6875rem] text-text-3 tabular-nums">
                                                {container.mode || 'unknown'} · {formatRu(container.current_ru)} ·{' '}
                                                {formatCount(container.request_units)} RU
                                            </span>
                                            <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[0.6875rem] text-text-2">
                                                {/* A shared or monitor-only container has no policy of its own to show. */}
                                                {badge ? <StatePill state={badge} /> : <span>{labelFor(container)}</span>}
                                                {isUnsaved(container.container_name) ? (
                                                    <StatePill state={{ text: 'Unsaved', tone: 'warn' }} />
                                                ) : null}
                                                {validation.containerErrors[container.container_name] ? (
                                                    <StatePill state={{ text: 'Needs attention', tone: 'danger' }} />
                                                ) : null}
                                            </span>
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    </div>

                    <div className="@container min-h-0 min-w-0 space-y-3 overflow-y-auto p-3 sm:p-4">
                        {selected ? (
                            <ContainerDetail
                                container={selected}
                                windowMinutes={windowMinutes}
                                policy={effective(selected)}
                                policyLabel={labelFor(selected)}
                                errors={validation.containerErrors[selected.container_name] ?? {}}
                                editable={editable}
                                busy={busy || saving}
                                onChange={(patch) => updatePolicy(selected, patch)}
                                onUseGlobal={() => applyGlobalPolicyTo([selected])}
                                onAction={(kind, direction) =>
                                    requestCapacityAction({ kind, direction, containerName: selected.container_name })
                                }
                            />
                        ) : null}
                    </div>
                </div>
            )}
        </OpsPanel>
    );
}

function ContainerDetail({
    container,
    windowMinutes,
    policy,
    policyLabel,
    errors,
    editable,
    busy,
    onChange,
    onUseGlobal,
    onAction,
}: {
    container: CosmosContainerStatus;
    windowMinutes: number | null | undefined;
    policy: CosmosContainerPolicy;
    policyLabel: string;
    errors: Parameters<typeof CosmosContainerPolicyForm>[0]['errors'];
    editable: boolean;
    busy: boolean;
    onChange: (patch: Partial<CosmosContainerPolicy>) => void;
    onUseGlobal: () => void;
    onAction: (kind: 'scale' | 'convert', direction?: 'up' | 'down') => void;
}) {
    const actions = containerActions(container);
    const portal = isPortalManaged(container);
    const badge = containerBadge(container);
    const actionReason = [actions.convert, actions.up, actions.down].every((action) => action.disabled)
        ? actions.down.reason || actions.up.reason
        : '';

    return (
        <>
            <div className="flex flex-wrap items-center gap-2">
                <h3 className="min-w-0 text-base font-semibold break-all text-text-1">{container.container_name}</h3>
                {badge ? <StatePill state={badge} /> : null}
            </div>

            <ReadoutGrid className="@4xl:grid-cols-4">
                <Readout label="Mode" value={container.mode || 'unknown'} />
                <Readout label="Current RU/s" value={formatRu(container.current_ru)} />
                <Readout label="RU utilization" value={formatContainerUtilization(container, windowMinutes)} />
                <Readout label="Request units" value={formatCount(container.request_units)} detail={`Over ${windowMinutes ?? '?'} min`} />
                <Readout label="Policy" value={!container.is_scalable && !portal ? 'Database policy' : policyLabel} wide />
            </ReadoutGrid>
            {containerUtilization(container, windowMinutes).estimated ? (
                <p className="text-xs text-text-3">
                    Azure Monitor sent no utilization percentage for this window, so it is estimated from request
                    units against current RU/s.
                </p>
            ) : null}
            {container.error ? <OpsMessage message={{ text: container.error, tone: 'warn' }} /> : null}

            <div className="space-y-2">
                <div role="group" aria-label={`Capacity actions for ${container.container_name}`} className="flex flex-wrap gap-2">
                    <OpsButton
                        icon={Zap}
                        disabled={busy || actions.convert.disabled}
                        title={actions.convert.reason || `Convert ${container.container_name} to Cosmos autoscale`}
                        onClick={() => onAction('convert')}
                    >
                        Convert to autoscale
                    </OpsButton>
                    <OpsButton
                        icon={ArrowUpCircle}
                        tone="primary"
                        disabled={busy || actions.up.disabled}
                        title={actions.up.reason || `Scale ${container.container_name} up by one step`}
                        onClick={() => onAction('scale', 'up')}
                    >
                        Scale up
                    </OpsButton>
                    <OpsButton
                        icon={ArrowDownCircle}
                        disabled={busy || actions.down.disabled}
                        title={actions.down.reason || `Scale ${container.container_name} down by one step`}
                        onClick={() => onAction('scale', 'down')}
                    >
                        Scale down
                    </OpsButton>
                </div>
                {actionReason ? <p className="text-xs leading-relaxed text-text-3">{actionReason}</p> : null}
            </div>

            {portal ? (
                <OpsMessage message={{ text: portalManagedMessage(container), tone: 'info' }} />
            ) : !container.is_scalable ? (
                <p className="text-xs leading-relaxed text-text-3">
                    This container shares the database's throughput, so it has no policy of its own. Database
                    automation covers it.
                </p>
            ) : editable ? (
                <div className="space-y-3 rounded-xl border border-edge bg-surface-1 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-text-1">Automation policy</p>
                        <OpsButton icon={RotateCcw} disabled={busy} onClick={onUseGlobal}>
                            Use global values
                        </OpsButton>
                    </div>
                    <CosmosContainerPolicyForm
                        containerName={container.container_name}
                        policy={policy}
                        errors={errors}
                        disabled={busy}
                        onChange={onChange}
                    />
                </div>
            ) : null}
        </>
    );
}
