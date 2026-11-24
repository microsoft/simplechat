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

import { useCallback, useEffect, useRef, useState } from 'react';
import { ClipboardCopy, RefreshCw, ScanSearch, Trash2, Zap } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import type { AdminField } from '../../lib/adminFields';
import { describeMaintenanceStatus, formatCount, formatTimestamp, humanizeStatus, type ToneText } from '../../lib/scaleFormat';
import {
    MAINTENANCE_RUN_PAYLOADS,
    describeCleanupRun,
    describeIndexApply,
    describeMaintenanceFailure,
    findRunStep,
    indexingPolicyStatus,
    indexingFailureReason,
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
const REPLAY_INDEX_PATH = '/api/admin/settings/cosmos-replay-indexing';

type MaintenanceAction = 'apply-indexes' | 'dry-run' | 'delete';
type ReplayAction = 'apply' | 'verify' | 'disable';
type ReplayIndexStatus = {
    enabled: boolean;
    redis_enabled: boolean;
    database: string;
    container: string;
    excluded_path: string;
    policy_state: 'ready' | 'missing' | 'conflict' | 'unavailable' | 'manual' | 'pending';
    proposed_policy: Record<string, unknown> | null;
};

function CosmosReplayIndexControl({ seen }: { seen: boolean }) {
    const [status, setStatus] = useState<ReplayIndexStatus | null>(null);
    const [message, setMessage] = useState<ToneText | null>(null);
    const [busy, setBusy] = useState<ReplayAction | 'refresh' | null>(null);
    const [confirm, setConfirm] = useState<'apply' | 'verify' | null>(null);
    const [readersReady, setReadersReady] = useState(false);

    const refresh = useCallback(async () => {
        setBusy('refresh');
        setMessage(null);
        try {
            setStatus(await api.get<ReplayIndexStatus>(REPLAY_INDEX_PATH));
        } catch {
            setMessage({ tone: 'danger', text: 'Could not read Cosmos replay indexing status.' });
        } finally {
            setBusy(null);
        }
    }, []);
    useEffect(() => {
        if (seen) void refresh();
    }, [seen, refresh]);

    const update = async (action: ReplayAction) => {
        setBusy(action);
        setMessage(null);
        try {
            setStatus(await api.post<ReplayIndexStatus>(REPLAY_INDEX_PATH, {
                action, ...(action !== 'disable' ? { readers_ready: readersReady } : {}),
            }));
            setMessage({
                tone: 'ok',
                text: action === 'disable'
                    ? 'New streams use indexed replay again. The existing exclusion is unchanged.'
                    : 'Verified. New Cosmos streams can omit replay text from the index.',
            });
        } catch (error) {
            const body = error instanceof ApiError
                ? error.payload as { error?: string; status?: ReplayIndexStatus } | null
                : null;
            if (body?.status) setStatus(body.status);
            setMessage({ tone: 'danger', text: body?.error || 'Could not confirm the replay indexing change.' });
        } finally {
            setBusy(null);
            setConfirm(null);
        }
    };

    const active = status?.enabled && status.policy_state === 'ready' && !status.redis_enabled;
    const policyText = status ? JSON.stringify(status.proposed_policy || { path: status.excluded_path }, null, 2) : '';
    const copyPolicy = async () => {
        try {
            await navigator.clipboard.writeText(policyText);
            toast.success(status?.proposed_policy ? 'Merged policy copied.' : 'Replay exclusion copied.');
        } catch {
            toast.error('Could not copy automatically. Select and copy the JSON.');
        }
    };
    const showPolicy = status && !status.redis_enabled && status.policy_state !== 'ready'
        && status.policy_state !== 'conflict';
    return (
        <ReadoutGroup title="Optimize Cosmos replay when Redis is off">
            <div data-testid="cosmos-replay-indexing" className="space-y-3">
                <p className="text-sm text-text-2">
                    Reduce Cosmos write cost for long replies by excluding only replay text from indexing. Chunks still save one at a time.
                </p>
                {status && (
                    <p role="status" className="text-sm text-text-2">
                        {status.redis_enabled
                            ? 'Inactive: Redis is enabled.'
                            : active ? 'Active for new Cosmos streams.'
                                : status.policy_state === 'manual' ? 'Manual action required.'
                                    : status.policy_state === 'pending' ? 'Awaiting Azure policy confirmation.'
                                        : status.policy_state === 'conflict' ? 'Current index policy conflicts with this exclusion.'
                                            : status.enabled ? 'Inactive until the exclusion can be verified.' : 'Off.'}
                    </p>
                )}
                <OpsMessage message={message} />
                <div className="flex flex-wrap gap-2">
                    <OpsButton icon={RefreshCw} busy={busy === 'refresh'} disabled={busy !== null} onClick={() => void refresh()}>
                        Refresh policy
                    </OpsButton>
                    {status && !status.redis_enabled && !active && status.policy_state !== 'conflict' && (
                        <>
                            {(status.policy_state === 'missing' || status.policy_state === 'ready') && (
                                <OpsButton icon={Zap} disabled={busy !== null} onClick={() => {
                                    setReadersReady(false);
                                    setConfirm('apply');
                                }}>
                                    Enable replay exclusion
                                </OpsButton>
                            )}
                            <OpsButton icon={ScanSearch} disabled={busy !== null} onClick={() => {
                                setReadersReady(false);
                                setConfirm('verify');
                            }}>
                                Verify policy
                            </OpsButton>
                        </>
                    )}
                    {status?.enabled && (
                        <OpsButton icon={Zap} busy={busy === 'disable'} disabled={busy !== null} onClick={() => void update('disable')}>
                            Disable replay exclusion
                        </OpsButton>
                    )}
                </div>
                {showPolicy && (
                    <details>
                        <summary className="cursor-pointer text-sm font-medium text-text-2">Manual policy instructions</summary>
                        <div className="mt-2 space-y-2">
                            <p className="text-sm text-text-2">
                                In the Azure portal, open Data Explorer, then {status.database} / {status.container} → Scale &amp; Settings → Indexing Policy.
                                {' '}{status.proposed_policy
                                    ? 'Refresh here first so the merged policy includes Azure’s latest rules. Review, paste, and save the merged JSON.'
                                    : 'Add this entry to the existing excludedPaths array without replacing the rest of the policy.'}
                                {' '}Then return here and select Verify policy.
                            </p>
                            <textarea aria-label={status.proposed_policy ? 'Merged index policy' : 'Replay exclusion entry'} readOnly
                                value={policyText} rows={7}
                                className="w-full rounded-md border border-edge bg-surface-2 p-2 font-mono text-xs text-text-1" />
                            <OpsButton icon={ClipboardCopy} onClick={() => void copyPolicy()}>
                                {status.proposed_policy ? 'Copy merged policy' : 'Copy exclusion entry'}
                            </OpsButton>
                        </div>
                    </details>
                )}
                {confirm !== null && (
                    <ConfirmActionModal
                        title={confirm === 'apply' ? 'Enable Cosmos replay exclusion' : 'Verify Cosmos replay exclusion'}
                        confirmLabel={confirm === 'apply' ? 'Apply and verify' : 'Verify and enable'}
                        confirmDisabled={!readersReady}
                        busy={busy === confirm}
                        onConfirm={() => void update(confirm)}
                        onClose={() => setConfirm(null)}
                    >
                        <p>
                            {confirm === 'apply'
                                ? 'Adds only the replay-only exclusion if it is missing. Throughput and unrelated indexes are unchanged.'
                                : 'Checks the existing policy only; it does not update Azure.'}
                            {' '}Existing streams keep their current replay format.
                        </p>
                        <label className="flex items-start gap-2">
                            <input type="checkbox" className="mt-1" checked={readersReady}
                                onChange={(event) => setReadersReady(event.target.checked)} />
                            <span>All app workers sharing this container can read both replay formats.</span>
                        </label>
                    </ConfirmActionModal>
                )}
            </div>
        </ReadoutGroup>
    );
}

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
            if (result.success === false) {
                failure = describeMaintenanceFailure(result);
            }
        } catch (error) {
            result = error instanceof ApiError ? (error.payload as AppMaintenanceRunResult | null) : null;
            failure = describeMaintenanceFailure(result);
        }

        if (action === 'apply-indexes') {
            const indexing = findRunStep(result, 'cosmos_indexing_policy_maintenance') as CosmosIndexingPolicyStatus | null;
            if (indexing) {
                mergeMaintenance({
                    cosmos_indexing_policies: indexing,
                    last_cosmos_indexing_policy_apply: { run_id: result?.run_id, results: indexing },
                });
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
    const lastApply = maintenance.data?.last_cosmos_indexing_policy_apply;
    const applyResults = lastApply?.results;
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

                <OpsMessage message={message} />
                <OpsMessage message={loadError} />
                <CosmosReplayIndexControl seen={seen} />

                {!hasData && maintenance.loading ? <ReadoutSkeleton rows={8} /> : null}

                {hasData ? (
                    <>
                        <ReadoutGroup title="Current index inspection">
                            <ReadoutGrid>
                                <Readout label="Status" state={describeMaintenanceStatus(indexingPolicyStatus(indexing))} />
                                <Readout label="Indexing mode" value={humanizeStatus(indexing?.mode || 'not_loaded')} />
                                <Readout label="Containers checked" value={formatCount(indexing?.container_count ?? 0)} />
                                <Readout
                                    label="Containers missing expected indexes"
                                    value={formatCount(indexing?.containers_missing_expected_indexes ?? 0)}
                                />
                                <Readout label="Updated containers" value={formatCount(indexing?.updated_container_count ?? 0)} />
                                <Readout label="Failures" value={formatCount(indexing?.failed_container_count ?? 0)} />
                                <Readout label="Last evaluated" value={formatTimestamp(indexing?.evaluated_at, 'Not loaded')} wide />
                            </ReadoutGrid>
                        </ReadoutGroup>

                        {applyResults ? (
                            <ReadoutGroup title="Last index apply result">
                                <div data-testid="last-index-apply-result">
                                    <OpsMessage message={{
                                        text: Number(applyResults.failed_container_count || 0) > 0
                                            ? `Index updates failed for ${formatCount(applyResults.failed_container_count)} container(s); updates were submitted for ${formatCount(applyResults.updated_container_count ?? 0)}. Successful submissions were not rolled back.`
                                            : describeIndexApply(applyResults).text,
                                        tone: Number(applyResults.failed_container_count || 0) > 0 ? 'danger' : 'ok',
                                    }} />
                                    {(applyResults.containers ?? []).filter((container) => container.status === 'failed').map((container, index) => (
                                        <p key={`${container.container_name}-${index}`} className="mb-2 text-sm text-text-2 break-words">
                                            <strong>{container.container_name || 'Unknown container'}:</strong>{' '}
                                            {indexingFailureReason(container.error_code)}
                                        </p>
                                    ))}
                                    <p className="text-xs text-text-3 break-words">
                                        {lastApply?.completed_at ? `Completed: ${formatTimestamp(lastApply.completed_at)}. ` : ''}
                                        {lastApply?.run_id ? `Run reference: ${lastApply.run_id}. ` : ''}
                                        Refresh status inspects current policies; it does not retry failed updates.
                                    </p>
                                </div>
                            </ReadoutGroup>
                        ) : null}

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
