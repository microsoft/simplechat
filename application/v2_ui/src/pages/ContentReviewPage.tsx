// ContentReviewPage.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Download, Loader2, RefreshCw, ShieldAlert, Trash2 } from 'lucide-react';
import { ApiError } from '../lib/apiClient';
import { SCREENING_STATES } from '../lib/contentScreening';
import {
    decideScreeningReview,
    fetchScreeningFindings,
    fetchScreeningAttachment,
    fetchScreeningReview,
    fetchScreeningReviews,
    fetchScreeningUnits,
    isStaleScreeningError,
    previewScreeningCandidate,
    remediateScreeningReview,
    screeningErrorMessage,
    screeningAttachment,
    screeningWireEdits,
    type ScreeningCandidatePreview,
    type ScreeningAttachmentKind,
    type ScreeningDecision,
    type ScreeningReviewMetadata,
    type ScreeningScope,
} from '../lib/contentScreeningApi';
import {
    appendScreeningEdit,
    previewScreeningEdits,
    screeningReviewAllows,
    screeningUnitKey,
    screeningUnitView,
    type ScreeningEdit,
    type ScreeningEditType,
    type ScreeningUnitView,
} from '../lib/contentScreeningReview';
import { groupScope, publicScope } from '../lib/chatContext';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { AdminModal } from '../components/admin/AdminModal';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { ProtectedEvidence } from '../components/screening/ProtectedEvidence';
import { ScreeningDiffPreview } from '../components/screening/ScreeningDiffPreview';
import { ScreeningFindings } from '../components/screening/ScreeningFindings';
import { ScreeningStatusBadge } from '../components/screening/ScreeningStatusBadge';
import { ScreeningField, screeningInputClass } from '../components/screening/ScreeningFields';
import { ScreeningWorkspaceControls } from '../components/screening/ScreeningWorkspaceControls';

function ReviewStatus({ review }: { review: ScreeningReviewMetadata }) {
    return (
        <ScreeningStatusBadge summary={{
            state: review.state,
            available: review.state === 'cleared' || review.state === 'approved_with_flags',
            finding_count: review.finding_count,
            scan_id: review.id,
        }} />
    );
}

function ReviewQueue({ onOpen }: { onOpen: (id: string) => void }) {
    const bootstrap = useBootstrapStore((state) => state.data);
    const [scopeKey, setScopeKey] = useState('');
    const [state, setState] = useState<'pending' | 'resolved' | 'all'>('pending');
    const [reviews, setReviews] = useState<ScreeningReviewMetadata[]>([]);
    const [continuation, setContinuation] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [refresh, setRefresh] = useState(0);
    const generation = useRef(0);
    const scopes = useMemo<Array<{ key: string; label: string; scope: ScreeningScope }>>(() => [
        ...(bootstrap?.user.id ? [{
            key: 'personal', label: 'My workspace',
            scope: { scope_type: 'personal' as const, scope_id: bootstrap.user.id },
        }] : []),
        ...(bootstrap?.scope.groups ?? []).map((group) => ({
            key: `group:${group.id}`, label: groupScope(group).name,
            scope: { scope_type: 'group' as const, scope_id: group.id },
        })),
        ...(bootstrap?.scope.public_workspaces ?? []).map((workspace) => ({
            key: `public:${workspace.id}`, label: publicScope(workspace).name,
            scope: { scope_type: 'public' as const, scope_id: workspace.id },
        })),
    ], [bootstrap]);
    const scope = scopes.find((item) => item.key === scopeKey)?.scope;

    useEffect(() => {
        const controller = new AbortController();
        generation.current += 1;
        setLoading(true);
        setReviews([]);
        setContinuation(null);
        setError(null);
        void fetchScreeningReviews(scope, state, null, controller.signal)
            .then((page) => {
                if (!controller.signal.aborted) {
                    setReviews(page.items);
                    setContinuation(page.continuation);
                }
            })
            .catch((failure) => {
                if (!controller.signal.aborted) setError(screeningErrorMessage(failure));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [scope?.scope_type, scope?.scope_id, state, refresh]);

    const loadMore = async () => {
        if (!continuation || loading) return;
        const requestGeneration = generation.current;
        setLoading(true);
        try {
            const page = await fetchScreeningReviews(scope, state, continuation);
            if (requestGeneration !== generation.current) return;
            setReviews((current) => [...current, ...page.items.filter((item) => !current.some((review) => review.id === item.id))]);
            setContinuation(page.continuation);
        } catch (failure) {
            if (requestGeneration === generation.current) setError(screeningErrorMessage(failure));
        } finally {
            if (requestGeneration === generation.current) setLoading(false);
        }
    };

    return (
        <div className="space-y-4">
            <GlassPanel elevation="flat" className="grid gap-3 p-4 sm:grid-cols-[1fr_1fr_auto]">
                <ScreeningField label="Workspace">
                    {(id) => (
                        <select id={id} className={screeningInputClass} value={scopeKey}
                            onChange={(event) => setScopeKey(event.target.value)}>
                            <option value="">All authorized reviews</option>
                            {scopes.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                        </select>
                    )}
                </ScreeningField>
                <ScreeningField label="Review status">
                    {(id) => (
                        <select id={id} className={screeningInputClass} value={state}
                            onChange={(event) => {
                                const value = event.target.value;
                                setState(value === 'resolved' || value === 'all' ? value : 'pending');
                            }}>
                            <option value="pending">Pending</option>
                            <option value="resolved">Resolved</option>
                            <option value="all">All</option>
                        </select>
                    )}
                </ScreeningField>
                <GlassButton type="button" variant="subtle" className="self-end" disabled={loading}
                    onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={15} />Refresh reviews</GlassButton>
            </GlassPanel>
            {scope ? <ScreeningWorkspaceControls scope={scope} /> : null}
            {error ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
            {loading && !reviews.length ? <Skeleton className="h-32" /> : null}
            {!loading && !error && !reviews.length ? (
                <EmptyState icon={<ShieldAlert size={28} />} title="No reviews in this view"
                    description="Only reviews within your current reviewer permissions appear here. Administrator scan permissions do not grant access to private evidence." />
            ) : null}
            <ul className="space-y-2">
                {reviews.map((review) => (
                    <li key={review.id}>
                        <GlassPanel elevation="flat" className="flex flex-wrap items-center justify-between gap-3 p-4">
                            <div className="min-w-0 space-y-1">
                                <p className="break-words text-sm font-medium text-text-1">Document {review.subject.document_id}</p>
                                <p className="text-xs text-text-3">{review.subject.scope_type} workspace · {review.id}</p>
                                <ReviewStatus review={review} />
                            </div>
                            <GlassButton type="button" size="sm" variant="subtle" onClick={() => onOpen(review.id)}>
                                Review
                            </GlassButton>
                        </GlassPanel>
                    </li>
                ))}
            </ul>
            {continuation ? <GlassButton type="button" variant="subtle" disabled={loading}
                onClick={() => void loadMore()}>Load more reviews</GlassButton> : null}
        </div>
    );
}

function ReviewDetail({ scanId, onCandidate }: { scanId: string; onCandidate: (id: string) => void }) {
    const [review, setReview] = useState<ScreeningReviewMetadata | null>(null);
    const [units, setUnits] = useState<ScreeningUnitView[]>([]);
    const [unitContinuation, setUnitContinuation] = useState<string | null>(null);
    const [findings, setFindings] = useState<Array<Record<string, unknown>>>([]);
    const [findingContinuation, setFindingContinuation] = useState<string | null>(null);
    const [selectedKey, setSelectedKey] = useState('');
    const [edits, setEdits] = useState<ScreeningEdit[]>([]);
    const [preview, setPreview] = useState<ScreeningCandidatePreview | null>(null);
    const [reason, setReason] = useState('');
    const [acknowledged, setAcknowledged] = useState(false);
    const [deleteOpen, setDeleteOpen] = useState(false);
    const [deleteConfirmation, setDeleteConfirmation] = useState('');
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [stale, setStale] = useState(false);
    const [evidenceUnavailable, setEvidenceUnavailable] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [refresh, setRefresh] = useState(0);
    const inFlight = useRef(false);
    const activeId = useRef(scanId);
    activeId.current = scanId;
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setReview(null);
        setUnits([]);
        setFindings([]);
        setUnitContinuation(null);
        setFindingContinuation(null);
        setEdits([]);
        setPreview(null);
        setReason('');
        setAcknowledged(false);
        setDeleteOpen(false);
        setDeleteConfirmation('');
        setError(null);
        setStale(false);
        setEvidenceUnavailable(false);
        void (async () => {
            try {
                const detail = await fetchScreeningReview(scanId, controller.signal);
                if (!detail.id || !detail.etag || !Array.isArray(detail.allowed_actions) || !Object.hasOwn(SCREENING_STATES, detail.state)) {
                    throw new Error('Invalid review response.');
                }
                if (controller.signal.aborted) return;
                setReview(detail);
                if (detail.state === 'deleting' || detail.state === 'deleted') {
                    setSelectedKey('');
                    return;
                }
                setEvidenceUnavailable(detail.evidence?.units_available !== true);
                try {
                    const [evidence, results] = await Promise.all([
                        detail.evidence?.units_available === true
                            ? fetchScreeningUnits(scanId, null, controller.signal)
                            : Promise.resolve({ items: [], continuation: null }),
                        detail.evidence?.findings_available === true
                            ? fetchScreeningFindings(scanId, null, controller.signal)
                            : Promise.resolve({ items: [], continuation: null }),
                    ]);
                    if (controller.signal.aborted) return;
                    const loaded = evidence.items.map(screeningUnitView);
                    setUnits(loaded);
                    setSelectedKey(loaded.length ? screeningUnitKey(loaded[0]) : '');
                    setUnitContinuation(evidence.continuation);
                    setFindings(results.items);
                    setFindingContinuation(results.continuation);
                } catch (failure) {
                    const missingEvidence = failure instanceof ApiError && failure.status === 404
                        && (failure.payload as { code?: string } | null)?.code === 'screening_evidence_unavailable';
                    if (failure instanceof ApiError && (failure.isAuthError || failure.status === 404 && !missingEvidence)) throw failure;
                    if (!controller.signal.aborted) setEvidenceUnavailable(true);
                }
            } catch (failure) {
                if (!controller.signal.aborted) {
                    setReview(null);
                    setError(screeningErrorMessage(failure));
                    setStale(isStaleScreeningError(failure));
                }
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        })();
        return () => controller.abort();
    }, [scanId, refresh]);

    useEffect(() => {
        if (!review || loading || busy || stale
            || !['pending_scan', 'scanning', 'remediating', 'publishing'].includes(review.state)) return;
        const timer = window.setInterval(() => {
            if (!document.hidden) setRefresh((value) => value + 1);
        }, 4000);
        return () => window.clearInterval(timer);
    }, [review, loading, busy, stale]);

    const selected = units.find((unit) => screeningUnitKey(unit) === selectedKey);
    const editable = Boolean(review && !evidenceUnavailable && screeningReviewAllows(review, 'remediate'));
    const allowedEdits: ScreeningEditType[] = editable ? ['remove_unit', 'remove_span', 'replace_cell', 'clear_cell'] : [];
    const blocked = busy || stale || loading;
    const differences = useMemo(() => {
        try {
            return previewScreeningEdits(units, edits);
        } catch {
            return [];
        }
    }, [units, edits]);

    async function run<T>(operation: () => Promise<T>, onSuccess: (result: T) => void) {
        if (inFlight.current || stale) return;
        inFlight.current = true;
        setBusy(true);
        setError(null);
        try {
            const result = await operation();
            if (mounted.current && activeId.current === scanId) onSuccess(result);
        } catch (failure) {
            if (mounted.current && activeId.current === scanId) {
                setError(screeningErrorMessage(failure));
                if (failure instanceof ApiError && (failure.isAuthError || failure.status === 404)) {
                    setStale(true);
                    setReview(null);
                    setUnits([]);
                    setFindings([]);
                    setPreview(null);
                    setEdits([]);
                    setReason('');
                    setAcknowledged(false);
                }
                if (isStaleScreeningError(failure)) {
                    setStale(true);
                    setPreview(null);
                    setEdits([]);
                }
            }
        } finally {
            inFlight.current = false;
            if (mounted.current) setBusy(false);
        }
    }

    function addEdit(edit: ScreeningEdit) {
        try {
            const next = appendScreeningEdit(edits, edit);
            previewScreeningEdits(units, next);
            setEdits(next);
            setPreview(null);
            setError(null);
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'The edit could not be staged.');
        }
    }

    function decision(action: ScreeningDecision) {
        if (!review || !screeningReviewAllows(review, action) ||
            (action !== 'retry_publication' && !reason.trim()) ||
            (action.startsWith('approve') && evidenceUnavailable) ||
            (action === 'approve_with_flags' && !acknowledged)) return;
        void run(
            () => decideScreeningReview(scanId, review.etag, action,
                action === 'retry_publication' ? review.decision?.reason ?? '' : reason.trim()),
            (next) => {
                setDeleteOpen(false);
                setDeleteConfirmation('');
                setReason('');
                setAcknowledged(false);
                setEdits([]);
                setPreview(null);
                if (next.id !== scanId) onCandidate(next.id);
                else {
                    setReview(next);
                    if (next.state === 'deleting' || next.state === 'deleted') {
                        setUnits([]);
                        setFindings([]);
                        setSelectedKey('');
                        setUnitContinuation(null);
                        setFindingContinuation(null);
                    }
                }
            },
        );
    }

    function download(kind: ScreeningAttachmentKind) {
        if (!review || blocked || !screeningAttachment(review, kind)) return;
        void run(() => fetchScreeningAttachment(review, kind), ({ content, fileName }) => {
            const url = URL.createObjectURL(new Blob([content], { type: 'application/octet-stream' }));
            const link = document.createElement('a');
            link.href = url;
            link.download = fileName;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 60000);
        });
    }

    const loadMoreUnits = () => {
        if (!unitContinuation) return;
        void run(() => fetchScreeningUnits(scanId, unitContinuation), (page) => {
            const loaded = page.items.map(screeningUnitView);
            setUnits((current) => [...current, ...loaded.filter((unit) => !current.some((item) => screeningUnitKey(item) === screeningUnitKey(unit)))]);
            setUnitContinuation(page.continuation);
        });
    };

    return (
        <div className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Link to="/content-review" className="text-sm text-accent hover:underline">Back to review queue</Link>
                <GlassButton type="button" size="sm" variant="subtle" disabled={busy || loading}
                    onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={14} />Refresh review</GlassButton>
            </div>
            {error ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
            {busy ? <p role="status" className="flex items-center gap-2 text-sm text-text-3"><Loader2 size={15} className="animate-spin" />Completing the requested screening operation…</p> : null}
            {loading ? <Skeleton className="h-40" /> : null}
            {review ? <>
                <GlassPanel elevation="flat" className="space-y-3 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                            <h2 className="break-words text-base font-semibold text-text-1">Document {review.subject.document_id}</h2>
                            <p className="break-all text-xs text-text-3">Scan {review.id} · {review.subject.scope_type} workspace</p>
                        </div>
                        <ReviewStatus review={review} />
                    </div>
                    <p className={review.coverage?.complete ? 'text-xs text-text-3' : 'text-xs text-danger'}>
                        {review.coverage?.complete ? 'Complete coverage' : 'Incomplete coverage — approval is unavailable'}
                        {' · '}{review.coverage?.units_total ?? 0} source units · {review.finding_count} findings
                    </p>
                    {review.candidate_of ? (
                        <p role="status" className="text-xs text-text-3">
                            {['pending_scan', 'scanning', 'remediating'].includes(review.state)
                                ? `Candidate of ${review.candidate_of} is queued or scanning and remains held. This review refreshes automatically until the scan completes.`
                                : `Rescanned candidate of ${review.candidate_of}. A clean result still requires explicit clean approval.`}
                        </p>
                    ) : null}
                    {evidenceUnavailable ? <p role="status" className="rounded-lg bg-warn-soft p-2 text-xs text-warn">
                        Canonical evidence is unavailable. Approval and editing require verified evidence; authorized Reject/Delete actions remain available.
                    </p> : null}
                    <p className="text-xs leading-relaxed text-text-3">
                        {review.original_retained
                            ? 'Retained originals are reviewer-only. This page displays canonical extracted evidence, not an active native-file preview.'
                            : 'No retained original is available. Review covers the extracted knowledge, not lost source bytes or formatting.'}
                        {' '}Released derivatives are clean text or structured files, not layout-preserving PDF or Office edits.
                    </p>
                    {review.warning ? <p className="rounded-lg bg-warn-soft p-2 text-xs text-warn">{review.warning}</p> : null}
                    {review.decision?.reason ? <p className="break-words text-xs text-text-2">
                        Recorded decision: {review.decision.action.replaceAll('_', ' ')}. {review.decision.reason}
                    </p> : null}
                    {stale ? <p className="text-sm font-medium text-danger">Refresh is required before another action.</p> : null}
                    <ScreeningWorkspaceControls scope={{
                        scope_type: review.subject.scope_type, scope_id: review.subject.scope_id,
                    }} documentIds={[review.subject.document_id]} label="Scan this document" />
                </GlassPanel>

                <GlassPanel elevation="flat" className="space-y-3 p-4">
                    <h3 className="text-sm font-semibold text-text-1">Review downloads</h3>
                    <p className="text-xs text-text-3">
                        Originals remain reviewer-only, including after clean approval. Downloads are attachment-only;
                        active HTML and native files are never embedded in this page. A clean derivative is available only for the current released scan.
                    </p>
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" variant="subtle"
                            disabled={blocked || !screeningAttachment(review, 'original')}
                            onClick={() => download('original')}><Download size={14} />Download reviewer-only original</GlassButton>
                        <GlassButton type="button" size="sm" variant="subtle"
                            disabled={blocked || !screeningAttachment(review, 'clean')}
                            onClick={() => download('clean')}><Download size={14} />Download clean derivative</GlassButton>
                    </div>
                </GlassPanel>

                <div className="grid min-w-0 gap-4 xl:grid-cols-[17rem_minmax(0,1fr)]">
                    <GlassPanel elevation="flat" className="min-w-0 space-y-3 p-3">
                        <h3 className="text-sm font-semibold text-text-1">Evidence units</h3>
                        <ul className="max-h-80 space-y-1 overflow-y-auto">
                            {units.map((unit) => (
                                <li key={screeningUnitKey(unit)}>
                                    <button type="button" disabled={busy} aria-pressed={selectedKey === screeningUnitKey(unit)}
                                        className={`w-full break-words rounded-lg px-2 py-2 text-left text-xs ${selectedKey === screeningUnitKey(unit) ? 'bg-accent-soft text-accent' : 'text-text-2 hover:bg-surface-2'}`}
                                        onClick={() => setSelectedKey(screeningUnitKey(unit))}>
                                        {unit.location.label}
                                        {unit.text_offset ? ` · offset ${unit.text_offset}` : ''}
                                    </button>
                                </li>
                            ))}
                        </ul>
                        {!units.length ? <p className="text-xs text-text-3">No evidence units in this page.</p> : null}
                        {unitContinuation ? <GlassButton type="button" size="sm" variant="subtle" disabled={blocked} onClick={loadMoreUnits}>Load more evidence</GlassButton> : null}
                    </GlassPanel>
                    <GlassPanel elevation="flat" className="min-w-0 p-4">
                        {selected ? <ProtectedEvidence key={screeningUnitKey(selected)} unit={selected}
                            allowedEdits={allowedEdits} disabled={blocked} onAddEdit={addEdit} /> : (
                            <p className="text-sm text-text-3">Select a source unit to inspect canonical text.</p>
                        )}
                    </GlassPanel>
                </div>

                <GlassPanel elevation="flat" className="min-w-0 space-y-3 p-4">
                    <ScreeningFindings findings={findings} />
                    {findingContinuation ? <GlassButton type="button" size="sm" variant="subtle" disabled={blocked}
                        onClick={() => void run(() => fetchScreeningFindings(scanId, findingContinuation), (page) => {
                            setFindings((current) => [...current, ...page.items]);
                            setFindingContinuation(page.continuation);
                        })}>Load more findings</GlassButton> : null}
                </GlassPanel>

                {editable ? <GlassPanel elevation="flat" className="min-w-0 space-y-4 p-4">
                    <h3 className="text-sm font-semibold text-text-1">Staged remediation</h3>
                    <p className="text-xs text-text-3">Nothing is changed until you create a candidate. Preview and candidate creation use this exact review ETag and each original unit hash.</p>
                    <ul className="space-y-1">
                        {edits.map((edit, index) => <li key={index} className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-2">
                            <span>{edit.type.replaceAll('_', ' ')} · {edit.unit_id}
                                {edit.type === 'remove_span' ? ` · code points ${edit.start}–${edit.end}` : ''}
                            </span>
                            <GlassButton type="button" size="sm" disabled={blocked} aria-label={`Discard edit ${index + 1}`}
                                onClick={() => { setEdits((current) => current.filter((_, item) => item !== index)); setPreview(null); }}>Discard edit</GlassButton>
                        </li>)}
                    </ul>
                    {differences.length ? <ScreeningDiffPreview differences={differences} /> : null}
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" variant="subtle" disabled={blocked || !edits.length || !differences.length}
                            onClick={() => void run(
                                () => previewScreeningCandidate(scanId, review.etag, screeningWireEdits(edits, units, !unitContinuation)),
                                setPreview,
                            )}>Validate edit preview</GlassButton>
                        <GlassButton type="button" size="sm" variant="primary" disabled={blocked || !preview || !edits.length}
                            onClick={() => void run(
                                () => remediateScreeningReview(scanId, review.etag, screeningWireEdits(edits, units, !unitContinuation)),
                                (candidate) => {
                                    setEdits([]);
                                    setPreview(null);
                                    if (candidate.id === scanId) setRefresh((value) => value + 1);
                                    else onCandidate(candidate.id);
                                },
                            )}>Create candidate and rescan</GlassButton>
                    </div>
                    {preview ? <div className="min-w-0 space-y-2 rounded-lg border border-edge p-3" data-testid="screening-server-preview">
                        <p className="text-xs font-medium text-text-2">
                            Server preview: {preview.total_units} remaining units · {preview.removed_unit_count} removed
                        </p>
                        {preview.preview_truncated ? <p className="text-xs text-warn">This preview is bounded. Candidate screening still covers the entire content, not only the displayed prefix.</p> : null}
                        {preview.warnings.map((warning, index) => <p key={index} className="text-xs text-warn">{warning}</p>)}
                        {preview.units.map((unit, index) => <details key={`${unit.unit_id}:${index}`} className="min-w-0">
                            <summary className="cursor-pointer break-words text-xs text-text-2">{screeningUnitView(unit).location.label}</summary>
                            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-2 font-mono text-xs text-text-1">{unit.text}</pre>
                        </details>)}
                    </div> : null}
                </GlassPanel> : null}

                <GlassPanel elevation="flat" className="space-y-3 p-4">
                    <h3 className="text-sm font-semibold text-text-1">Reviewer decision</h3>
                    <p className="text-xs text-text-3">Only actions authorized by the current server response are offered. Self-review is permitted within your workspace role; administrator-wide scanning alone is not review authority.</p>
                    {review.allowed_actions.some((action) => ['approve_with_flags', 'approve_clean', 'reject', 'delete'].includes(action)) ? (
                        <ScreeningField label="Decision reason" help="Required for the audit trail. Explain the decision without unnecessarily repeating sensitive evidence.">
                            {(id) => <textarea id={id} rows={3} disabled={blocked} className={screeningInputClass}
                                value={reason} onChange={(event) => setReason(event.target.value)} />}
                        </ScreeningField>
                    ) : null}
                    {review.allowed_actions.includes('approve_with_flags') ? <label className="flex items-start gap-2 text-xs text-text-2">
                        <input type="checkbox" className="mt-0.5 accent-[var(--accent)]" checked={acknowledged} disabled={blocked}
                            onChange={(event) => setAcknowledged(event.target.checked)} />
                        I have reviewed the findings and accept releasing this exact revision with persistent flags.
                    </label> : null}
                    <div className="flex flex-wrap gap-2">
                        {review.allowed_actions.includes('approve_with_flags') ? <GlassButton type="button" size="sm" variant="subtle"
                            disabled={blocked || evidenceUnavailable || !reason.trim() || !acknowledged || !screeningReviewAllows(review, 'approve_with_flags')}
                            onClick={() => decision('approve_with_flags')}>Approve with flags</GlassButton> : null}
                        {review.allowed_actions.includes('approve_clean') ? <GlassButton type="button" size="sm" variant="primary"
                            disabled={blocked || evidenceUnavailable || !reason.trim() || !screeningReviewAllows(review, 'approve_clean')}
                            onClick={() => decision('approve_clean')}>Approve clean candidate</GlassButton> : null}
                        {review.allowed_actions.includes('reject') ? <GlassButton type="button" size="sm" variant="subtle"
                            disabled={blocked || !reason.trim()} onClick={() => decision('reject')}>Reject and keep held</GlassButton> : null}
                        {review.allowed_actions.includes('delete') ? <GlassButton type="button" size="sm" variant="danger"
                            disabled={blocked || !reason.trim()} onClick={() => setDeleteOpen(true)}><Trash2 size={13} />
                            {review.state === 'deleting' ? 'Retry document deletion' : 'Delete document'}</GlassButton> : null}
                        {review.allowed_actions.includes('retry_publication') ? <GlassButton type="button" size="sm" variant="subtle"
                            disabled={blocked} onClick={() => decision('retry_publication')}>Retry publishing existing decision</GlassButton> : null}
                    </div>
                    {!review.coverage?.complete || review.outcome === 'error' || review.outcome === 'incomplete' ? (
                        <p className="text-xs text-danger">Scan errors or incomplete coverage cannot be approved. Retry through authorized workspace scan controls; the hold remains enforced.</p>
                    ) : null}
                    {!review.allowed_actions.length ? <p className="text-xs text-text-3">No decision or remediation action is currently authorized.</p> : null}
                </GlassPanel>
            </> : null}
            {deleteOpen && review ? (
                <AdminModal title="Delete screened document?"
                    description={review.state === 'deleting'
                        ? 'Retry the already-started deletion to finish cleanup. The document remains held throughout.'
                        : 'This permanently deletes the document and its screening artifacts. Reject instead if it should remain held.'}
                    onClose={() => !busy && setDeleteOpen(false)}
                    footer={<>
                        <GlassButton type="button" disabled={busy} onClick={() => setDeleteOpen(false)}>Keep document</GlassButton>
                        <GlassButton type="button" variant="danger" disabled={blocked || deleteConfirmation !== 'DELETE' || !reason.trim()}
                            onClick={() => decision('delete')}>Confirm document deletion</GlassButton>
                    </>}>
                    <ScreeningField label="Type DELETE to confirm">
                        {(id) => <input id={id} className={screeningInputClass} value={deleteConfirmation} disabled={busy}
                            autoComplete="off" onChange={(event) => setDeleteConfirmation(event.target.value)} />}
                    </ScreeningField>
                </AdminModal>
            ) : null}
        </div>
    );
}

export function ContentReviewPage() {
    const [params, setParams] = useSearchParams();
    const scanId = params.get('scan_id')?.trim() ?? '';
    const openReview = (id: string) => setParams((current) => {
        const next = new URLSearchParams(current);
        next.set('scan_id', id);
        return next;
    });
    return (
        <div className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
            <div className="mx-auto max-w-6xl space-y-5">
                <header>
                    <h1 className="text-xl font-semibold text-text-1">Content review</h1>
                    <p className="mt-1 text-sm text-text-3">
                        Inspect held knowledge, stage precise edits, and make an explicit decision.
                        Existing holds remain enforceable even when new scanning is disabled.
                    </p>
                </header>
                {scanId ? <ReviewDetail scanId={scanId} onCandidate={openReview} /> : <ReviewQueue onOpen={openReview} />}
            </div>
        </div>
    );
}
