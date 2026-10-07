// DataManagementRestoreDialog.tsx
// Restore is isolated in its own dialog because each opening must forget the previous
// draft and force a fresh, saved-server review before a destructive queue action.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { ArrowRight, CheckCircle2, Database, HardDrive, RotateCcw, Search } from 'lucide-react';
import { ApiError } from '../../../lib/apiClient';
import {
    errorMessage,
    queueJob,
    readWorkflowStep,
    RESTORE_OVERWRITE_PHRASE,
    reviewRestore,
    type BackupRow,
    type RestoreReview,
} from '../../../lib/dataManagement';
import {
    buildDmSettingsPayload,
    buildRestorePlan,
    canQueueRestore,
    DM_SECTION_IDS,
    endpointHost,
    formatBackupType,
    formatBytes,
    formatDateTime,
    formatNumber,
    initialRestoreDraft,
    isDestinationConfigured,
    normalizeReviewChecks,
    readDmValues,
    restoreReviewKey,
    restoreSurfaceSelected,
    reviewHeadline,
    secondsUntil,
    type RestoreDraft,
} from '../../../lib/dataManagementLogic';
import { useDataManagementStore, useDmDirtyCount, useDmValues } from '../../../stores/dataManagementStore';
import { toast } from '../../../stores/toastStore';
import { Modal } from '../../ui/Modal';
import { GlassButton } from '../../ui/primitives';
import { DmEvidenceChecks, DmMetricGrid, DmNotice, DmPhraseField, useNow } from './DmShared';
import { useSaveFirst } from './useSaveFirst';

function text(value: unknown, fallback = ''): string {
    return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function authLabel(value: unknown, keyLabel: string): string {
    const auth = text(value, 'managed_identity');
    if (auth === 'connection_string') return 'Connection string';
    if (auth === 'key') return keyLabel;
    return 'Managed identity';
}

function storageDestinationLabel(values: ReturnType<typeof useDmValues>): string {
    const auth = text(values.target_enhanced_citations_storage_authentication_type, 'managed_identity');
    if (auth === 'connection_string') return 'connection string';
    return endpointHost(values.target_enhanced_citations_storage_blob_endpoint) || 'Not set';
}

function surfaceCheckboxId(surface: string): string {
    return `dm-restore-surface-${surface}`;
}

function updateDraft(draft: RestoreDraft, update: Partial<RestoreDraft>): RestoreDraft {
    return { ...draft, ...update };
}

function ReviewSummary({ review }: { review: RestoreReview }) {
    const summary = review.summary ?? {};
    const serviceCounts = summary.service_counts ?? {};
    const failed = Array.isArray(summary.failed_resource_names) ? summary.failed_resource_names : [];
    return (
        <div className="space-y-3">
            <DmMetricGrid
                label="Restore review summary"
                items={[
                    { label: 'Artifacts', value: formatNumber(summary.artifact_count) },
                    { label: 'Cosmos DB', value: formatNumber(serviceCounts.cosmos) },
                    { label: 'AI Search', value: formatNumber(serviceCounts.ai_search) },
                    { label: 'Enhanced Citation files', value: formatNumber(serviceCounts.source_blobs) },
                    { label: 'Warnings', value: formatNumber(summary.warnings) },
                    { label: 'Failed resources', value: formatNumber(failed.length) },
                ]}
            />
            {summary.differential_mode === 'latest_item_state' ? (
                <DmNotice>
                    A partial backup restores the latest captured items without replaying deletions.
                </DmNotice>
            ) : null}
            {failed.length ? (
                <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2">
                    <p className="text-xs font-semibold text-text-1">Failed resources</p>
                    <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-text-3">
                        {failed.map((name) => (
                            <li key={name} className="break-all">
                                {name}
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </div>
    );
}

export function DataManagementRestoreDialog({
    backup,
    onClose,
    onNavigate,
}: {
    backup: BackupRow;
    onClose: () => void;
    onNavigate: (sectionId: string) => void;
}) {
    const values = useDmValues();
    const dirtyCount = useDmDirtyCount();
    const now = useNow(1000, true);
    const { ensure, dialog } = useSaveFirst();
    const requestMigrationStep = useDataManagementStore((state) => state.requestMigrationStep);

    const [draft, setDraft] = useState<RestoreDraft>(() => initialRestoreDraft());
    const [review, setReview] = useState<RestoreReview | null>(null);
    const [reviewKey, setReviewKey] = useState<string | null>(null);
    const [busy, setBusy] = useState<'review' | 'queue' | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [forcedStale, setForcedStale] = useState(false);
    const requestGeneration = useRef(0);
    const mounted = useRef(true);

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            requestGeneration.current += 1;
        };
    }, []);

    useEffect(() => {
        setDraft(initialRestoreDraft());
        setReview(null);
        setReviewKey(null);
        setMessage(null);
        setForcedStale(false);
    }, [backup.id]);

    const destinationReady = isDestinationConfigured(values);
    const currentReviewKey = useMemo(
        () => restoreReviewKey(backup.id, draft, values),
        [backup.id, draft, values],
    );
    const expiresInSeconds = secondsUntil(review?.authorization_expires_at, now);
    const expired = review ? expiresInSeconds === 0 : false;
    const reviewCurrent = Boolean(review && reviewKey === currentReviewKey && !forcedStale && !expired);
    const headline = reviewHeadline(review, Boolean(review && (!reviewCurrent || expired)));
    const canQueue =
        destinationReady &&
        restoreSurfaceSelected(draft) &&
        canQueueRestore({
            review,
            reviewCurrent,
            draft,
            expiresInSeconds,
            busy: busy !== null,
        });

    const safeClose = () => {
        if (!busy) onClose();
    };

    const setUpDestination = () => {
        requestMigrationStep('target');
        onNavigate(DM_SECTION_IDS.migration);
        onClose();
    };

    const runReview = async () => {
        if (!destinationReady) {
            setMessage('Set up the destination before running a restore review.');
            return;
        }
        if (!restoreSurfaceSelected(draft)) {
            setMessage('Select at least one surface to restore.');
            return;
        }
        if (!(await ensure('restore-review'))) return;

        const state = useDataManagementStore.getState();
        const freshValues = readDmValues(state.settings, state.draft);
        const plan = buildRestorePlan(backup.id, draft);
        const key = restoreReviewKey(backup.id, draft, freshValues);
        const generation = requestGeneration.current + 1;
        requestGeneration.current = generation;
        setBusy('review');
        setMessage(null);
        setForcedStale(false);
        try {
            const nextReview = await state.trackRequest(
                reviewRestore(buildDmSettingsPayload(freshValues), plan),
            );
            if (!mounted.current || requestGeneration.current !== generation) return;
            setReview(nextReview);
            setReviewKey(key);
            setDraft((current) => updateDraft(current, { acknowledged: false }));
            toast[nextReview.ready ? 'success' : 'info'](
                nextReview.ready ? 'Restore review passed.' : 'Restore review found blockers.',
            );
        } catch (error) {
            if (!mounted.current || requestGeneration.current !== generation) return;
            setReview(null);
            setReviewKey(null);
            setMessage(errorMessage(error, 'Restore review failed.'));
        } finally {
            if (mounted.current && requestGeneration.current === generation) setBusy(null);
        }
    };

    const queueRestore = async () => {
        if (!review) return;
        if (!(await ensure('restore-queue'))) return;

        const state = useDataManagementStore.getState();
        const freshValues = readDmValues(state.settings, state.draft);
        const freshKey = restoreReviewKey(backup.id, draft, freshValues);
        if (freshKey !== reviewKey) {
            setForcedStale(true);
            setDraft((current) => updateDraft(current, { acknowledged: false }));
            setMessage('Inputs changed after settings were saved. Run the review again.');
            return;
        }

        const generation = requestGeneration.current + 1;
        requestGeneration.current = generation;
        setBusy('queue');
        setMessage(null);
        try {
            const job = await state.trackRequest(
                queueJob('restore', null, {
                    restore_plan: buildRestorePlan(backup.id, draft),
                    review_fingerprint: review.review_fingerprint || '',
                    review_authorization_token: review.authorization_token || '',
                }),
            );
            if (!mounted.current || requestGeneration.current !== generation) return;
            toast.success('Restore job queued.');
            state.notifyJobsChanged();
            state.notifyBackupsChanged();
            state.focusJob(job.id);
            setBusy(null);
            onClose();
            onNavigate(DM_SECTION_IDS.jobs);
        } catch (error) {
            if (!mounted.current || requestGeneration.current !== generation) return;
            const workflowStep = readWorkflowStep(error);
            if ((error instanceof ApiError && error.status === 409) || workflowStep === 'review') {
                setForcedStale(true);
                setDraft((current) => updateDraft(current, { acknowledged: false }));
                setMessage(errorMessage(error, 'The review is no longer current. Run it again.'));
            } else if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                setMessage(errorMessage(error, 'Restore could not be queued.'));
            } else {
                state.notifyJobsChanged();
                setMessage(
                    'The restore request did not finish cleanly. It may have been queued; check Job history before retrying.',
                );
            }
        } finally {
            if (mounted.current && requestGeneration.current === generation) setBusy(null);
        }
    };

    const reviewChecks = normalizeReviewChecks(review?.checks);
    const noSurface = !restoreSurfaceSelected(draft);

    return (
        <Modal
            title="Restore backup"
            description="Review the destination, policy and backup manifest before queueing a restore job."
            size="xl"
            onClose={safeClose}
            footer={
                <>
                    <GlassButton
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={busy !== null}
                        onClick={safeClose}
                    >
                        Cancel
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="danger"
                        size="sm"
                        disabled={!canQueue}
                        onClick={() => void queueRestore()}
                    >
                        <RotateCcw size={14} aria-hidden="true" />
                        {dirtyCount ? 'Save and queue restore' : 'Queue restore'}
                    </GlassButton>
                </>
            }
        >
            {/* The dialog body is the size container, so its grids widen with the dialog. */}
            <div className="@container space-y-4">
                <DmNotice tone="warning">
                    Restore writes into the destination environment configured in Migration. Create only
                    never replaces data that is already there; Overwrite existing can, after a review and
                    the typed confirmation.
                </DmNotice>

                <DmMetricGrid
                    label="Selected backup"
                    items={[
                        { label: 'Backup ID', value: <span className="break-all">{backup.id}</span> },
                        { label: 'Type', value: formatBackupType(backup.backup_type) },
                        {
                            label: 'Completed',
                            value: formatDateTime(backup.completed_at || backup.created_at) || 'Not recorded',
                        },
                        {
                            label: 'Contents',
                            value: `${formatNumber(backup.record_count)} records / ${formatNumber(backup.blob_count)} blobs`,
                        },
                        { label: 'Manifest', value: backup.manifest_path ? 'Recorded' : 'Missing' },
                        { label: 'Protection', value: backup.encrypted ? 'Encrypted' : 'Not encrypted' },
                        { label: 'Size', value: formatBytes(backup.bytes) },
                        { label: 'Artifacts', value: formatNumber(backup.artifact_count) },
                    ]}
                />

                <section className="rounded-xl border border-edge-strong bg-surface-solid p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                            <h3 className="text-sm font-semibold text-text-1">Destination</h3>
                            <p className="mt-0.5 text-xs text-text-3">
                                Restore uses the target settings from the Migration card.
                            </p>
                        </div>
                        {!destinationReady ? (
                            <GlassButton type="button" variant="primary" size="sm" onClick={setUpDestination}>
                                Set up the destination
                                <ArrowRight size={14} aria-hidden="true" />
                            </GlassButton>
                        ) : null}
                    </div>
                    <div className="mt-3 grid gap-2 @2xl:grid-cols-3">
                        <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2">
                            <p className="flex items-center gap-1.5 text-xs font-semibold text-text-1">
                                <Database size={13} aria-hidden="true" />
                                Cosmos DB
                            </p>
                            <p className="mt-1 text-xs text-text-3">
                                {endpointHost(values.target_cosmos_endpoint) || 'Not set'} ·{' '}
                                {authLabel(values.target_cosmos_authentication_type, 'account key')}
                            </p>
                        </div>
                        <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2">
                            <p className="flex items-center gap-1.5 text-xs font-semibold text-text-1">
                                <Search size={13} aria-hidden="true" />
                                AI Search
                            </p>
                            <p className="mt-1 text-xs text-text-3">
                                {endpointHost(values.target_ai_search_endpoint) || 'Not set'}
                            </p>
                        </div>
                        <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2">
                            <p className="flex items-center gap-1.5 text-xs font-semibold text-text-1">
                                <HardDrive size={13} aria-hidden="true" />
                                Enhanced Citation storage
                            </p>
                            <p className="mt-1 text-xs text-text-3">{storageDestinationLabel(values)}</p>
                        </div>
                    </div>
                    {!destinationReady ? (
                        <DmNotice tone="warning" className="mt-3">
                            The destination is not configured. Set it up before reviewing or queueing a
                            restore.
                        </DmNotice>
                    ) : null}
                </section>

                <fieldset
                    className="rounded-xl border border-edge-strong bg-surface-solid p-3"
                    disabled={busy !== null}
                >
                    <legend className="text-sm font-semibold text-text-1">Policy</legend>
                    <div className="mt-2 grid gap-2 @2xl:grid-cols-2">
                        {[
                            {
                                value: 'create_only',
                                title: 'Create only',
                                description:
                                    'Recommended. Non-destructive: items that already exist in the destination are skipped and reported as collisions.',
                            },
                            {
                                value: 'overwrite_existing',
                                title: 'Overwrite existing',
                                description:
                                    'Can replace existing destination data after review and exact phrase confirmation.',
                            },
                        ].map((option) => (
                            <label
                                key={option.value}
                                className={clsx(
                                    'rounded-lg border px-3 py-2 transition-colors',
                                    draft.policy === option.value
                                        ? 'border-accent/50 bg-accent-soft ring-1 ring-accent/30'
                                        : 'border-edge bg-surface-1 hover:bg-surface-sunken',
                                )}
                            >
                                <span className="flex items-start gap-2">
                                    <input
                                        type="radio"
                                        name="dm-restore-policy"
                                        value={option.value}
                                        checked={draft.policy === option.value}
                                        onChange={() => {
                                            setForcedStale(false);
                                            setDraft((current) =>
                                                updateDraft(current, {
                                                    policy: option.value as RestoreDraft['policy'],
                                                    acknowledged: false,
                                                }),
                                            );
                                        }}
                                    />
                                    <span className="min-w-0">
                                        <span className="block text-sm font-semibold text-text-1">
                                            {option.title}
                                        </span>
                                        <span className="mt-0.5 block text-xs leading-relaxed text-text-3">
                                            {option.description}
                                        </span>
                                    </span>
                                </span>
                            </label>
                        ))}
                    </div>
                    {draft.policy === 'overwrite_existing' ? (
                        <div className="mt-3">
                            <DmPhraseField
                                phrase={RESTORE_OVERWRITE_PHRASE}
                                value={draft.overwritePhrase}
                                disabled={busy !== null}
                                onChange={(overwritePhrase) =>
                                    setDraft((current) => updateDraft(current, { overwritePhrase }))
                                }
                            />
                        </div>
                    ) : null}
                </fieldset>

                <fieldset
                    className="rounded-xl border border-edge-strong bg-surface-solid p-3"
                    disabled={busy !== null}
                >
                    <legend className="text-sm font-semibold text-text-1">What to restore</legend>
                    <div className="mt-2 grid gap-2 @2xl:grid-cols-3">
                        {[
                            ['cosmos', 'Cosmos DB', 'includeCosmos'],
                            ['search', 'AI Search', 'includeAiSearch'],
                            ['files', 'Enhanced Citation files', 'includeSourceBlobs'],
                        ].map(([id, label, key]) => (
                            <label
                                key={id}
                                htmlFor={surfaceCheckboxId(id)}
                                className="flex items-start gap-2 rounded-lg border border-edge bg-surface-1 px-3 py-2"
                            >
                                <input
                                    id={surfaceCheckboxId(id)}
                                    type="checkbox"
                                    checked={Boolean(draft[key as keyof RestoreDraft])}
                                    onChange={(event) =>
                                        setDraft((current) =>
                                            updateDraft(current, {
                                                [key]: event.target.checked,
                                                acknowledged: false,
                                            }),
                                        )
                                    }
                                />
                                <span className="text-sm font-medium text-text-1">{label}</span>
                            </label>
                        ))}
                    </div>
                    {noSurface ? (
                        <p role="alert" className="mt-2 text-xs text-danger">
                            Select at least one surface to restore.
                        </p>
                    ) : null}
                </fieldset>

                <section className="rounded-xl border border-edge-strong bg-surface-solid p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                            <h3 className="text-sm font-semibold text-text-1">Review</h3>
                            <p className="mt-0.5 text-xs text-text-3">
                                {headline.text}
                                {expiresInSeconds !== null && reviewCurrent
                                    ? ` · Authorization expires in ${expiresInSeconds}s`
                                    : ''}
                            </p>
                        </div>
                        <GlassButton
                            type="button"
                            variant="primary"
                            size="sm"
                            disabled={busy !== null || !destinationReady || noSurface}
                            onClick={() => void runReview()}
                        >
                            {busy === 'review' ? (
                                <CheckCircle2 size={14} aria-hidden="true" className="animate-pulse" />
                            ) : (
                                <CheckCircle2 size={14} aria-hidden="true" />
                            )}
                            Run review
                        </GlassButton>
                    </div>

                    {review && !reviewCurrent ? (
                        <DmNotice tone="warning" role="alert" className="mt-3">
                            Inputs changed after the review. Run it again.
                        </DmNotice>
                    ) : null}
                    {expired ? (
                        <DmNotice tone="warning" role="alert" className="mt-3">
                            The review authorization expired. Run the review again before queueing.
                        </DmNotice>
                    ) : null}
                    {message ? (
                        <DmNotice tone="danger" role="alert" className="mt-3">
                            {message}
                        </DmNotice>
                    ) : null}

                    <div className="mt-3 space-y-3" aria-live="polite">
                        {review ? (
                            <>
                                <DmEvidenceChecks checks={reviewChecks} />
                                <ReviewSummary review={review} />
                            </>
                        ) : (
                            <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-3">
                                No restore review has run yet.
                            </div>
                        )}
                    </div>
                </section>

                <label
                    className={clsx(
                        'flex items-start gap-2 rounded-xl border border-edge px-3 py-2',
                        busy !== null && 'opacity-60',
                    )}
                >
                    <input
                        type="checkbox"
                        checked={draft.acknowledged}
                        disabled={busy !== null}
                        onChange={(event) =>
                            setDraft((current) =>
                                updateDraft(current, { acknowledged: event.target.checked }),
                            )
                        }
                    />
                    <span className="text-sm font-semibold text-text-1">
                        I reviewed the destination, the policy and the review result.
                    </span>
                </label>
            </div>
            {dialog}
        </Modal>
    );
}
