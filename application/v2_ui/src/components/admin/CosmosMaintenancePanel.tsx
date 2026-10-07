// CosmosMaintenancePanel.tsx
// What background maintenance last found in Cosmos, and on-demand runs of its two tasks.
//
// Index maintenance compares each hot container's composite indexes with what the code
// expects and can add the missing ones. Stale cleanup finds obsolete cache documents in the
// settings container and can delete one bounded batch. Both can be checked here without
// waiting for the scheduler; the two that change Cosmos ask first, with the server-rendered
// page's explanation of what is and is not touched.
//
// Shares the app maintenance status with DAI Metrics and Conversation Cache.

import { useEffect, useRef, useState } from 'react';
import { ScanSearch, Trash2, Zap } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import type { AdminField } from '../../lib/adminFields';
import { describeMaintenanceStatus, formatCount, formatTimestamp, humanizeStatus, type ToneText } from '../../lib/scaleFormat';
import {
    MAINTENANCE_RUN_PAYLOADS,
    describeCleanupRun,
    describeIndexApply,
    findRunStep,
    indexingPolicyStatus,
    type AppMaintenanceRunResult,
    type CosmosIndexingPolicyStatus,
    type StaleCacheCleanupStatus,
} from '../../lib/scaleMaintenance';
import { useFirstVisible } from '../../lib/useFirstVisible';
import { toast } from '../../stores/toastStore';
import { useScaleStatusStore } from '../../stores/scaleStatusStore';
import { ConfirmActionModal } from './ConfirmActionModal';
import {
    OpsButton,
    OpsHeading,
    OpsMessage,
    OpsPanel,
    OpsToolbar,
    Readout,
    ReadoutGrid,
    ReadoutGroup,
    ReadoutSkeleton,
} from './OperationalReadouts';

const RUN_PATH = '/api/admin/settings/app-maintenance/run';

type MaintenanceAction = 'apply-indexes' | 'dry-run' | 'delete';

export function CosmosMaintenancePanel({ field }: { field: AdminField }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const seen = useFirstVisible(containerRef);
    const maintenance = useScaleStatusStore((state) => state.maintenance);
    const loadMaintenance = useScaleStatusStore((state) => state.loadMaintenance);
    const mergeMaintenance = useScaleStatusStore((state) => state.mergeMaintenance);

    const [running, setRunning] = useState<MaintenanceAction | null>(null);
    const [confirm, setConfirm] = useState<'apply-indexes' | 'delete' | null>(null);
    const [message, setMessage] = useState<ToneText | null>(null);

    useEffect(() => {
        if (seen) {
            void loadMaintenance();
        }
    }, [seen, loadMaintenance]);

    const run = async (action: MaintenanceAction) => {
        setRunning(action);
        setMessage({
            text:
                action === 'apply-indexes'
                    ? 'Submitting the missing composite indexes. Cosmos may keep transforming indexes after this returns.'
                    : action === 'delete'
                        ? 'Deleting one bounded batch of stale cache documents…'
                        : 'Scanning for stale cache documents…',
            tone: 'info',
        });
        const payload =
            action === 'apply-indexes'
                ? MAINTENANCE_RUN_PAYLOADS.applyIndexes
                : action === 'delete'
                    ? MAINTENANCE_RUN_PAYLOADS.staleCleanupApply
                    : MAINTENANCE_RUN_PAYLOADS.staleCleanupDryRun;
        let result: AppMaintenanceRunResult | null = null;
        let failure: string | null = null;
        try {
            result = await api.post<AppMaintenanceRunResult>(RUN_PATH, payload);
        } catch (error) {
            result = error instanceof ApiError ? (error.payload as AppMaintenanceRunResult | null) : null;
            failure = error instanceof Error ? error.message : 'Cosmos maintenance failed.';
        }

        if (action === 'apply-indexes') {
            const indexing = findRunStep(result, 'cosmos_indexing_policy_maintenance') as CosmosIndexingPolicyStatus | null;
            if (indexing) {
                mergeMaintenance({ cosmos_indexing_policies: indexing });
            }
            if (!failure) {
                const outcome = describeIndexApply(indexing);
                setMessage(outcome);
                toast.success(outcome.text);
            }
        } else {
            const cleanup = findRunStep(result, 'stale_cache_document_cleanup') as StaleCacheCleanupStatus | null;
            if (cleanup) {
                mergeMaintenance({ stale_cache_cleanup: cleanup });
            }
            if (!failure) {
                const outcome = describeCleanupRun(cleanup, action === 'delete');
                setMessage(outcome);
                if (outcome.tone === 'ok') {
                    toast.success(outcome.text);
                } else {
                    toast.info(outcome.text);
                }
            }
        }

        if (failure) {
            setMessage({ text: failure, tone: 'danger' });
            toast.error(failure);
        }
        setRunning(null);
        setConfirm(null);
        void loadMaintenance({ force: true });
    };

    const indexing = maintenance.data?.cosmos_indexing_policies;
    const cleanup = maintenance.data?.stale_cache_cleanup;
    const hasData = Boolean(indexing || cleanup);
    const loadError: ToneText | null = maintenance.error ? { text: maintenance.error, tone: 'danger' } : null;

    return (
        <div ref={containerRef}>
            <OpsPanel testId="cosmos-maintenance-panel">
                <OpsHeading label={field.label} help={field.help} />
                <OpsToolbar
                    label="Cosmos maintenance actions"
                    loadedAt={maintenance.loadedAt}
                    loading={maintenance.loading}
                    onRefresh={() => void loadMaintenance({ force: true })}
                    refreshLabel="Refresh status"
                >
                    <OpsButton icon={Zap} disabled={running !== null} onClick={() => setConfirm('apply-indexes')}>
                        Apply missing indexes
                    </OpsButton>
                    <OpsButton
                        icon={ScanSearch}
                        busy={running === 'dry-run'}
                        disabled={running !== null}
                        onClick={() => void run('dry-run')}
                    >
                        Dry run cleanup
                    </OpsButton>
                    <OpsButton icon={Trash2} tone="danger" disabled={running !== null} onClick={() => setConfirm('delete')}>
                        Delete stale cache docs
                    </OpsButton>
                </OpsToolbar>

                <OpsMessage message={message ?? loadError} />

                {!hasData && maintenance.loading ? <ReadoutSkeleton rows={8} /> : null}

                {hasData ? (
                    <>
                        <ReadoutGroup title="Indexing policies">
                            <ReadoutGrid>
                                <Readout label="Status" state={describeMaintenanceStatus(indexingPolicyStatus(indexing))} />
                                <Readout label="Indexing mode" value={humanizeStatus(indexing?.mode || 'not_loaded')} />
                                <Readout label="Containers checked" value={formatCount(indexing?.container_count ?? 0)} />
                                <Readout
                                    label="Missing expected indexes"
                                    value={formatCount(indexing?.containers_missing_expected_indexes ?? 0)}
                                />
                                <Readout label="Updated containers" value={formatCount(indexing?.updated_container_count ?? 0)} />
                                <Readout label="Failures" value={formatCount(indexing?.failed_container_count ?? 0)} />
                                <Readout label="Last evaluated" value={formatTimestamp(indexing?.evaluated_at, 'Not loaded')} wide />
                            </ReadoutGrid>
                        </ReadoutGroup>

                        <ReadoutGroup title="Stale cache cleanup">
                            <ReadoutGrid>
                                <Readout label="Status" state={describeMaintenanceStatus(cleanup?.status || 'not_run', 'Not run')} />
                                <Readout label="Mode" value={humanizeStatus(cleanup?.mode || 'not_run')} />
                                <Readout label="Candidates" value={formatCount(cleanup?.candidate_count ?? 0)} />
                                <Readout label="Deleted" value={formatCount(cleanup?.deleted_count ?? 0)} />
                                <Readout label="Failures" value={formatCount(cleanup?.failed_count ?? 0)} />
                                <Readout label="More candidates" value={cleanup?.has_more_candidates ? 'Yes' : 'No'} />
                                <Readout label="Last evaluated" value={formatTimestamp(cleanup?.evaluated_at, 'Not run yet')} wide />
                            </ReadoutGrid>
                            {(cleanup?.categories ?? []).length ? (
                                <div className="overflow-x-auto rounded-lg border border-edge">
                                    <table className="w-full text-left text-xs">
                                        <caption className="sr-only">Stale cache cleanup by category</caption>
                                        <thead className="bg-surface-2 text-text-3">
                                            <tr>
                                                <th scope="col" className="px-2.5 py-1.5 font-medium">Category</th>
                                                <th scope="col" className="px-2.5 py-1.5 text-right font-medium">Candidates</th>
                                                <th scope="col" className="px-2.5 py-1.5 text-right font-medium">Deleted</th>
                                                <th scope="col" className="px-2.5 py-1.5 text-right font-medium">Failed</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-edge text-text-2">
                                            {(cleanup?.categories ?? []).map((category, index) => (
                                                <tr key={category.category || index}>
                                                    <td className="px-2.5 py-1.5">{humanizeStatus(category.category || 'unknown')}</td>
                                                    <td className="px-2.5 py-1.5 text-right tabular-nums">{formatCount(category.candidate_count ?? 0)}</td>
                                                    <td className="px-2.5 py-1.5 text-right tabular-nums">{formatCount(category.deleted_count ?? 0)}</td>
                                                    <td className="px-2.5 py-1.5 text-right tabular-nums">{formatCount(category.failed_count ?? 0)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : null}
                        </ReadoutGroup>
                    </>
                ) : null}
            </OpsPanel>

            {confirm === 'apply-indexes' ? (
                <ConfirmActionModal
                    title="Apply missing Cosmos indexes"
                    confirmLabel="Apply indexes"
                    cancelLabel="Decline"
                    busy={running === 'apply-indexes'}
                    onConfirm={() => void run('apply-indexes')}
                    onClose={() => setConfirm(null)}
                >
                    <p>
                        Adds the missing expected composite indexes to the hot Cosmos containers. Existing included
                        and excluded paths, default indexes, TTL settings and full-text policies are kept.
                    </p>
                    <p>
                        Composite indexes speed up supported lookups and ordered queries, but Cosmos maintains them
                        on every later write and may run an index transformation after the policy changes.
                    </p>
                    <p className="text-text-3">
                        Apply them only if the extra write-index overhead is worth the faster queries shown in the
                        maintenance status.
                    </p>
                </ConfirmActionModal>
            ) : null}

            {confirm === 'delete' ? (
                <ConfirmActionModal
                    title="Delete stale cache documents"
                    confirmLabel="Delete stale cache docs"
                    tone="danger"
                    busy={running === 'delete'}
                    onConfirm={() => void run('delete')}
                    onClose={() => setConfirm(null)}
                >
                    <p>
                        Deletes one bounded batch of allowlisted stale cache artifacts from the settings container,
                        such as retired conversation cache version documents and obsolete volatile cache payloads.
                    </p>
                    <p className="text-text-3">
                        App settings, active cache-version documents, DAI state, maintenance state, source documents
                        and user data are never deleted. Run a dry run first to see the candidate count.
                    </p>
                </ConfirmActionModal>
            ) : null}
        </div>
    );
}
