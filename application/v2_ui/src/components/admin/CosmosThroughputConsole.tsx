// CosmosThroughputConsole.tsx
// Current Cosmos throughput, access validation and database-level capacity changes.
//
// The card opens on the snapshot automation last saved, so nothing is asked of Azure just
// because the page was opened; Refresh reads it live. When automation is on and no snapshot
// exists yet, the first check runs once the card is seen, as on the server-rendered page.
//
// Validate access runs against the values on screen, so a configuration can be proved
// before it is saved. Scaling and conversion are different: the server applies the saved
// policy, so they say so when there are unsaved throughput edits, and every capacity change
// goes through the confirmation the page draws once for this card and Cosmos Metrics.

import { useEffect, useMemo, useRef } from 'react';
import { ArrowDownCircle, ArrowUpCircle, CheckCircle2, ShieldCheck, SlidersHorizontal, XCircle, Zap } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';
import {
    buildAccessValidationPayload,
    databaseActions,
    hasStatusData,
    hasUnsavedThroughputEdits,
    type CosmosThroughputStatus,
} from '../../lib/cosmosThroughput';
import { formatPercent, formatRu, formatTimestamp, type ToneText } from '../../lib/scaleFormat';
import type { Json } from '../../lib/types';
import { useFirstVisible } from '../../lib/useFirstVisible';
import { useScaleStatusStore } from '../../stores/scaleStatusStore';
import {
    OpsButton,
    OpsHeading,
    OpsMessage,
    OpsNote,
    OpsPanel,
    OpsToolbar,
    Readout,
    ReadoutGrid,
    ReadoutGroup,
    StatePill,
} from './OperationalReadouts';

export const COSMOS_METRICS_SECTION_ID = 'cosmos-throughput-metrics-table-section';

export function CosmosThroughputConsole({
    field,
    settings,
    draft,
    dirtyKeys,
    onNavigate,
}: {
    field: AdminField;
    settings: Json;
    draft: Json;
    dirtyKeys: string[];
    onNavigate: (sectionId: string) => void;
}) {
    const containerRef = useRef<HTMLDivElement>(null);
    const seen = useFirstVisible(containerRef);
    const throughput = useScaleStatusStore((state) => state.throughput);
    const seedThroughput = useScaleStatusStore((state) => state.seedThroughput);
    const refreshThroughput = useScaleStatusStore((state) => state.refreshThroughput);
    const validateThroughputAccess = useScaleStatusStore((state) => state.validateThroughputAccess);
    const requestCapacityAction = useScaleStatusStore((state) => state.requestCapacityAction);
    const requestContainerFocus = useScaleStatusStore((state) => state.requestContainerFocus);

    const cached = settings['cosmos_throughput_cached_status'] as CosmosThroughputStatus | undefined;
    const automationSaved = Boolean(settings['cosmos_throughput_autoscale_enabled']);

    useEffect(() => {
        if (hasStatusData(cached)) {
            seedThroughput({ ...(cached as CosmosThroughputStatus), is_cached: true });
        }
    }, [cached, seedThroughput]);

    // The first check runs on its own only where automation would have run it anyway.
    const firstCheckDone = useRef(false);
    useEffect(() => {
        if (!seen || firstCheckDone.current || !automationSaved || hasStatusData(cached)) {
            return;
        }
        firstCheckDone.current = true;
        void refreshThroughput();
    }, [seen, automationSaved, cached, refreshThroughput]);

    const read = (key: string): unknown =>
        Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];

    const status = throughput.status;
    const actions = useMemo(() => databaseActions(status), [status]);
    const unsavedEdits = hasUnsavedThroughputEdits(dirtyKeys);
    const containerScoped = status?.capacity_scope === 'container';
    const busy = throughput.loading || throughput.validating || throughput.acting;

    const snapshotNote: ToneText | null =
        throughput.source === 'saved'
            ? {
                  text: automationSaved
                      ? 'Showing the last saved status. Automation refreshes it every metrics window; Refresh reads it now.'
                      : 'Showing the last saved status. Automation is off, so use Refresh to read it now.',
                  tone: 'info',
              }
            : null;
    const capacityReason = actions.up.disabled && actions.down.disabled && actions.convert.disabled
        ? actions.down.reason || actions.up.reason
        : '';

    return (
        <div ref={containerRef}>
            <OpsPanel testId="cosmos-throughput-console">
                <OpsHeading label={field.label} help={field.help} />
                <OpsToolbar
                    label="Cosmos throughput actions"
                    loadedAt={throughput.loadedAt}
                    loading={throughput.loading}
                    onRefresh={() => void refreshThroughput()}
                >
                    <OpsButton
                        icon={ShieldCheck}
                        busy={throughput.validating}
                        disabled={busy}
                        onClick={() => void validateThroughputAccess(buildAccessValidationPayload(read))}
                    >
                        Validate access
                    </OpsButton>
                    <OpsButton
                        icon={SlidersHorizontal}
                        onClick={() => {
                            requestContainerFocus(null);
                            onNavigate(COSMOS_METRICS_SECTION_ID);
                        }}
                    >
                        Container policies
                    </OpsButton>
                </OpsToolbar>

                <OpsMessage message={throughput.message ?? snapshotNote} />

                {throughput.validation ? (
                    <OpsMessage
                        message={{
                            text: throughput.validation.message || 'Access validation finished.',
                            tone: throughput.validation.success ? 'ok' : 'danger',
                        }}
                    >
                        {(throughput.validation.checks ?? []).length ? (
                            <ul className="mt-2 space-y-1 pl-5">
                                {(throughput.validation.checks ?? []).map((check, index) => (
                                    <li key={check.name || index} className="flex items-start gap-2">
                                        {check.passed ? (
                                            <CheckCircle2 size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
                                        ) : (
                                            <XCircle size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-danger" />
                                        )}
                                        <span>
                                            <span className="font-semibold text-text-1">
                                                {check.passed ? 'Passed' : 'Failed'}: {check.label || 'Check'}.
                                            </span>{' '}
                                            {check.message || 'No detail returned.'}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        ) : null}
                    </OpsMessage>
                ) : null}

                {status ? (
                    <ReadoutGrid>
                        <Readout
                            label="Mode"
                            value={containerScoped ? 'Container targeted' : status.throughput?.mode || 'Unknown'}
                        />
                        <Readout label="Current RU/s" value={formatRu(status.throughput?.current_ru)} />
                        <Readout label="RU utilization" value={formatPercent(status.metrics?.normalized_ru_percent, 1)} />
                        <Readout
                            label="Last checked"
                            value={formatTimestamp(status.last_checked_at, 'Not checked yet')}
                            detail={throughput.source === 'saved' ? <StatePill state={{ text: 'Saved snapshot', tone: 'neutral' }} /> : undefined}
                        />
                    </ReadoutGrid>
                ) : (
                    <OpsNote>
                        No status yet. Refresh reads the current throughput and utilization from Azure Resource
                        Manager and Azure Monitor.
                    </OpsNote>
                )}

                <div className="space-y-2 rounded-xl border border-edge-strong bg-surface-solid p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-text-1">Database capacity</p>
                        <div role="group" aria-label="Database capacity actions" className="flex flex-wrap gap-2">
                            <OpsButton
                                icon={Zap}
                                disabled={busy || actions.convert.disabled}
                                title={actions.convert.reason || 'Convert database manual throughput to Cosmos autoscale'}
                                onClick={() => requestCapacityAction({ kind: 'convert', containerName: '' })}
                            >
                                Convert to autoscale
                            </OpsButton>
                            <OpsButton
                                icon={ArrowUpCircle}
                                tone="primary"
                                disabled={busy || actions.up.disabled}
                                title={actions.up.reason || 'Scale database throughput up by one step'}
                                onClick={() => requestCapacityAction({ kind: 'scale', direction: 'up', containerName: '' })}
                            >
                                Scale up
                            </OpsButton>
                            <OpsButton
                                icon={ArrowDownCircle}
                                disabled={busy || actions.down.disabled}
                                title={actions.down.reason || 'Scale database throughput down by one step'}
                                onClick={() => requestCapacityAction({ kind: 'scale', direction: 'down', containerName: '' })}
                            >
                                Scale down
                            </OpsButton>
                        </div>
                    </div>
                    {capacityReason ? (
                        <p className="text-xs leading-relaxed text-text-3">
                            {capacityReason}
                            {containerScoped ? (
                                <>
                                    {' '}
                                    <button
                                        type="button"
                                        className="text-accent underline"
                                        onClick={() => onNavigate(COSMOS_METRICS_SECTION_ID)}
                                    >
                                        Open Cosmos Metrics
                                    </button>
                                </>
                            ) : null}
                        </p>
                    ) : (
                        <p className="text-xs leading-relaxed text-text-3">
                            One step at a time, within the saved guardrails. Each change asks for confirmation first.
                        </p>
                    )}
                    {unsavedEdits ? (
                        <p className="text-xs leading-relaxed text-warn">
                            You have unsaved throughput changes. Validate access uses them; scaling and conversion
                            use the saved policy until you save.
                        </p>
                    ) : null}
                </div>

                <ReadoutGroup title="Setup guide" defaultOpen={false}>
                    <div className="space-y-3 text-xs leading-relaxed text-text-2">
                        <p>
                            Validate access runs the same read checks automation depends on, using the values on
                            screen: resource identity, Azure Resource Manager throughput reads, container discovery,
                            and Azure Monitor metrics.
                        </p>
                        <div>
                            <p className="font-semibold text-text-1">Required Azure access</p>
                            <ul className="mt-1 list-disc space-y-1 pl-5">
                                <li>
                                    Assign roles to the App Service managed identity, not the Microsoft Entra sign-in app
                                    registration. In the Azure portal, open the Web App, select Identity, and copy the
                                    Object (principal) ID.
                                </li>
                                <li>
                                    Assign the custom <code className="font-mono">SimpleChat Cosmos Throughput Operator</code>{' '}
                                    role to that identity at the resource group that holds the Cosmos DB account, or on
                                    the account itself.
                                </li>
                                <li>
                                    The role must read the Cosmos account, database and containers; read and write SQL
                                    database and container <code className="font-mono">throughputSettings</code>; run{' '}
                                    <code className="font-mono">migrateToAutoscale</code>; read throughput operation
                                    results; and read <code className="font-mono">Microsoft.Insights/metrics</code>.
                                </li>
                                <li>
                                    Without the custom role, grant equivalent custom permissions. Broad built-in roles
                                    such as Contributor pass validation but are not least privilege.
                                </li>
                            </ul>
                        </div>
                        <div>
                            <p className="font-semibold text-text-1">Capacity scope</p>
                            <ul className="mt-1 list-disc space-y-1 pl-5">
                                <li>Database mode scales the shared SimpleChat database throughput.</li>
                                <li>Container-targeted mode scales only containers with dedicated throughput.</li>
                                <li>Containers sharing database throughput are listed but cannot be scaled on their own.</li>
                                <li>
                                    Manual throughput converts to native Cosmos autoscale only when conversion is enabled
                                    globally or in the container's policy.
                                </li>
                            </ul>
                        </div>
                        <div>
                            <p className="font-semibold text-text-1">Metrics</p>
                            <ul className="mt-1 list-disc space-y-1 pl-5">
                                <li>RU utilization is the share of available throughput used over the metrics window.</li>
                                <li>Request units are the total consumed over the metrics window.</li>
                                <li>Azure Monitor metrics can lag traffic by a few minutes.</li>
                            </ul>
                        </div>
                        <OpsButton
                            icon={ShieldCheck}
                            busy={throughput.validating}
                            disabled={busy}
                            onClick={() => void validateThroughputAccess(buildAccessValidationPayload(read))}
                        >
                            Validate access
                        </OpsButton>
                    </div>
                </ReadoutGroup>
            </OpsPanel>
        </div>
    );
}
