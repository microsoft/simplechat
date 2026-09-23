// DocumentCollaborationDialog.tsx

import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw, Search, Users } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    collaborationFailure, isCollaborationRepair, type CollaborationGroup, type CollaborationMutation,
    type CollaborationReceipt, type CollaborationTargets, type DocumentCollaborationAdapter,
    type DocumentCollaborationState,
} from '../../lib/documentCollaboration';
import type { DocumentReadAdapter } from '../../lib/documentReadAdapter';
import type { WorkspaceDocument } from '../../lib/types';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

interface ReviewSnapshot {
    document: WorkspaceDocument | null;
    state: DocumentCollaborationState;
}

interface Decision {
    operation: CollaborationMutation;
    target?: CollaborationGroup;
    reviewed: ReviewSnapshot;
    repairReceipt?: CollaborationReceipt;
}

const DANGEROUS = new Set<CollaborationMutation>([
    'unshare', 'remove_share', 'reject_artifact', 'cancel_artifact',
]);

function decisionLabel(operation: CollaborationMutation, state: DocumentCollaborationState): string {
    switch (operation) {
        case 'share': return 'Share with group';
        case 'unshare': return 'Stop sharing';
        case 'approve_share': return state.relationship === 'approved' ? 'Complete access approval' : 'Approve access';
        case 'remove_share': return isCollaborationRepair(state) ? 'Retry access cleanup' : state.relationship === 'not_approved' ? 'Deny request' : 'Remove from group';
        case 'approve_artifact': return state.publication?.status === 'approval_failed' ? 'Resume approved publication' : 'Approve publication';
        case 'reject_artifact': return 'Reject publication';
        case 'cancel_artifact': return 'Cancel publication request';
    }
}

function decisionEffect(decision: Decision, groupName: string): string {
    if (decision.repairReceipt) return `Access for ${decision.target?.name || decision.target?.id} was already withdrawn. Finish only the outstanding cleanup; no grant will be restored and the source document is not deleted.`;
    switch (decision.operation) {
        case 'unshare':
            return `Withdraw ${decision.target?.name || decision.target?.id}'s access to this revision. The source document and other recipients are not deleted.`;
        case 'remove_share':
            return isCollaborationRepair(decision.reviewed.state)
                ? `Finish only the outstanding access-removal cleanup for ${groupName}. This cannot restore access or delete the source owner's content.`
                : decision.reviewed.state.relationship === 'not_approved'
                ? `Deny this pending request for ${groupName}. The source owner's document is not deleted.`
                : `Withdraw ${groupName}'s access to this shared document. The source owner's content and other recipients are not deleted.`;
        case 'reject_artifact':
            return `Reject this publication request and remove its destination copy from ${groupName}. This is not a screening approval.`;
        case 'cancel_artifact':
            return `Cancel your publication request and remove its destination copy from ${groupName}.`;
        default:
            return 'This decision applies only to the document and revision shown.';
    }
}

export function DocumentCollaborationDialog({
    document, targetDocumentId: id, adapter, reader, interactionDisabled, onClose, onDirtyChange, onBusyChange, onChanged,
}: {
    document: WorkspaceDocument | null;
    targetDocumentId: string;
    adapter: DocumentCollaborationAdapter;
    reader: DocumentReadAdapter;
    interactionDisabled: boolean;
    onClose: () => void;
    onDirtyChange: (dirty: boolean) => void;
    onBusyChange: (busy: boolean) => void;
    onChanged: (receipt: CollaborationReceipt) => Promise<void>;
}) {
    const scopeKind = adapter.scope.kind;
    const isGroupScope = scopeKind === 'group';
    const scopeNoun = isGroupScope ? 'group' : 'workspace';
    const [review, setReview] = useState<ReviewSnapshot | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [needsRefresh, setNeedsRefresh] = useState(false);
    const [gone, setGone] = useState(false);
    const [busy, setBusy] = useState(false);
    const [receipt, setReceipt] = useState<CollaborationReceipt | null>(null);
    const [receiptTarget, setReceiptTarget] = useState<CollaborationGroup | null>(null);
    const [receiptVersion, setReceiptVersion] = useState<number | null>(null);
    const [searchDraft, setSearchDraft] = useState('');
    const [query, setQuery] = useState({ search: '', page: 1, pageSize: 25 });
    const [targets, setTargets] = useState<CollaborationTargets | null>(null);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState('');
    const [selected, setSelected] = useState<CollaborationGroup | null>(null);
    const [decision, setDecision] = useState<Decision | null>(null);
    const [searchRetry, setSearchRetry] = useState(0);
    const mounted = useRef(true);
    const busyRef = useRef(false);
    const readRequest = useRef<AbortController | null>(null);
    const targetRequest = useRef<AbortController | null>(null);
    const receiptRef = useRef<CollaborationReceipt | null>(null);
    receiptRef.current = receipt;

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            readRequest.current?.abort();
            targetRequest.current?.abort();
        };
    }, []);
    useEffect(() => {
        onDirtyChange(Boolean(searchDraft.trim() || selected || decision));
        return () => onDirtyChange(false);
    }, [searchDraft, selected, decision, onDirtyChange]);
    useEffect(() => () => onBusyChange(false), [onBusyChange]);

    const loadReview = useCallback(async (): Promise<ReviewSnapshot | null> => {
        readRequest.current?.abort();
        targetRequest.current?.abort();
        if (interactionDisabled || !mounted.current) return null;
        const controller = new AbortController();
        readRequest.current = controller;
        setLoading(true);
        setError('');
        setNeedsRefresh(true);
        try {
            let fresh: WorkspaceDocument | null;
            let state: DocumentCollaborationState;
            try {
                fresh = await reader.detail(id, controller.signal);
            } catch (cause) {
                if (!(cause instanceof ApiError) || cause.status !== 404) throw cause;
                fresh = null;
            }
            if (controller.signal.aborted || !mounted.current) return null;
            state = fresh ? await adapter.read(fresh, controller.signal) : await adapter.readRepair(id, controller.signal);
            if (controller.signal.aborted || !mounted.current) return null;
            const next = { document: isCollaborationRepair(state) ? null : fresh, state };
            setReview(next);
            setGone(false);
            setNeedsRefresh(false);
            return next;
        } catch (cause) {
            if (controller.signal.aborted || !mounted.current) return null;
            setReview(null);
            if (cause instanceof ApiError && cause.status === 404) {
                setGone(true);
                if (!receiptRef.current) setError(`The requested document or review no longer exists, or is not available in this ${scopeNoun}.`);
            } else setError(collaborationFailure(cause, scopeKind));
            return null;
        } finally {
            if (!controller.signal.aborted && mounted.current) setLoading(false);
        }
    }, [adapter, reader, id, interactionDisabled]);

    useEffect(() => {
        if (!busyRef.current) void loadReview();
        return () => readRequest.current?.abort();
    }, [loadReview]);

    const mayShare = Boolean(review && adapter.allows('share', review.document, review.state));
    useEffect(() => {
        targetRequest.current?.abort();
        if (!review?.document || !mayShare || loading || needsRefresh || interactionDisabled || busy) {
            setSearching(false);
            return;
        }
        const controller = new AbortController();
        targetRequest.current = controller;
        setSearching(true);
        setSearchError('');
        void adapter.targets(review.document, review.state, query, controller.signal).then((result) => {
            if (!controller.signal.aborted && mounted.current) setTargets(result);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted && mounted.current) {
                setTargets(null);
                setSearchError(collaborationFailure(cause, scopeKind));
            }
        }).finally(() => {
            if (!controller.signal.aborted && mounted.current) setSearching(false);
        });
        return () => controller.abort();
    }, [adapter, review, mayShare, query, searchRetry, loading, needsRefresh, interactionDisabled, busy]);

    const allows = (operation: CollaborationMutation, snapshot = review) => Boolean(
        snapshot && !loading && !needsRefresh && !busy && !interactionDisabled
        && adapter.allows(operation, snapshot.document, snapshot.state),
    );
    const close = () => {
        if (busyRef.current) {
            setError('The decision is still being saved. Closing this dialog would not cancel server work.');
            return;
        }
        onClose();
    };

    const execute = async (intent: Decision) => {
        if (busyRef.current || !allows(intent.operation) || !review
            || intent.reviewed.state.etag !== review.state.etag
            || (intent.repairReceipt && (receiptVersion !== review.state.document_version
                || review.state.recipients.some((recipient) => recipient.id === intent.target?.id)))) {
            setError('Review details or permissions changed. Your input is kept; refresh before deciding.');
            setNeedsRefresh(true);
            return;
        }
        busyRef.current = true;
        setBusy(true);
        onBusyChange(true);
        readRequest.current?.abort();
        targetRequest.current?.abort();
        setError('');
        try {
            let confirmed: CollaborationReceipt;
            try {
                confirmed = await adapter.mutate(
                    intent.reviewed.document, intent.reviewed.state, intent.operation, intent.target?.id, intent.repairReceipt,
                );
            } catch (cause) {
                if (mounted.current) {
                    setError(collaborationFailure(cause, scopeKind));
                    setNeedsRefresh(true);
                }
                return;
            }
            if (!mounted.current) return;
            receiptRef.current = confirmed;
            setReceipt(confirmed);
            setReceiptTarget(intent.target ?? null);
            setReceiptVersion(intent.reviewed.state.document_version);
            setDecision(null);
            setNeedsRefresh(true);
            if (confirmed.status !== 'partial') setSelected(null);
            const terminal = intent.operation === 'remove_share'
                || intent.operation === 'reject_artifact' || intent.operation === 'cancel_artifact';
            try {
                await onChanged(confirmed);
                if (!mounted.current) return;
                if (terminal) setReview(null);
                await loadReview();
            } catch {
                if (mounted.current) setError('The decision was confirmed, but the document list could not be refreshed. Refresh before another action.');
            }
            if (mounted.current && confirmed.status === 'partial') setNeedsRefresh(true);
        } finally {
            busyRef.current = false;
            if (mounted.current) {
                setBusy(false);
                onBusyChange(false);
            }
        }
    };

    const choose = (operation: CollaborationMutation, target?: CollaborationGroup, repairReceipt?: CollaborationReceipt) => {
        if (!allows(operation) || !review || (repairReceipt && receiptVersion !== review.state.document_version)) {
            setError('This action is not currently available. Refresh review details before continuing.');
            return;
        }
        const intent = { operation, target, reviewed: review, repairReceipt };
        if (DANGEROUS.has(operation)) setDecision(intent);
        else void execute(intent);
    };

    const refreshDecision = async () => {
        const current = decision;
        const refreshed = await loadReview();
        if (mounted.current && current && refreshed) setDecision({ ...current, reviewed: refreshed });
    };
    const decisionChanged = Boolean(decision && (!review || decision.reviewed.state.etag !== review.state.etag));
    const repairChanged = Boolean(decision?.repairReceipt && review && (
        receiptVersion !== review.state.document_version
        || review.state.recipients.some((recipient) => recipient.id === decision.target?.id)
    ));
    const fileName = review?.document?.file_name || document?.file_name || id;
    const state = review?.state;

    const outcome = receipt ? (
        <div role={receipt.status === 'partial' ? 'alert' : 'status'}
            className={`space-y-1 rounded-lg border p-3 text-sm ${receipt.status === 'partial' ? 'border-warn/30 bg-warn-soft text-text-1' : 'border-edge bg-surface-2 text-text-2'}`}>
            <p className="font-medium">
                {receipt.status === 'partial' ? 'Decision partly completed; follow-up is required.'
                    : receipt.status === 'queued' ? 'Approval recorded. Processing is queued, not complete.'
                        : receipt.status === 'unchanged' ? 'The requested state was already recorded.' : 'Decision confirmed.'}
            </p>
            <p>Result: {receipt.state.replaceAll('_', ' ')}. {receipt.target_group_id ? `Recipient: ${receipt.target_group_id}.` : ''}</p>
            {receipt.errors.length ? <ul className="max-h-36 space-y-1 overflow-y-auto text-xs">
                {receipt.errors.map((entry, index) => <li key={`${entry.stage}:${entry.code}:${index}`}>
                    {entry.stage}: {entry.message} ({entry.code})
                </li>)}
            </ul> : null}
            {receipt.status === 'partial' ? <p className="text-xs">No decision has been replayed automatically. Refresh to see which recovery actions are still permitted.</p> : null}
        </div>
    ) : null;

    return <>
        <Modal title={isGroupScope ? 'Document sharing and review' : 'Document review'} size="lg" onClose={close}
            description={`${adapter.scope.name}: ${fileName}`}
            footer={<GlassButton size="sm" variant="ghost" disabled={busy} onClick={close}>Done</GlassButton>}>
            <div className="space-y-4">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-text-2">
                    <dt>Selected {scopeNoun}</dt><dd className="break-words">{adapter.scope.name} ({adapter.scope.id})</dd>
                    <dt>Document</dt><dd className="break-all">{id}</dd>
                    {state ? <>
                        {isGroupScope ? <>
                            <dt>Source owner</dt><dd className="break-words">{state.owner_group.name} ({state.owner_group.id})</dd>
                        </> : null}
                        <dt>Revision</dt><dd>{state.document_version}</dd>
                        {isGroupScope ? <>
                            <dt>Relationship</dt><dd>{state.relationship === 'owner' ? 'Owned by this group' : state.relationship === 'not_approved' ? 'Incoming share awaiting approval'
                                : state.relationship === 'approved' ? 'Approved incoming share' : `Access ${state.relationship}; cleanup review only`}</dd>
                        </> : null}
                    </> : null}
                </dl>
                <p className="text-xs text-text-3">{isGroupScope
                    ? 'Sharing and approval apply to this exact document and revision. They do not clear content-screening holds or promise immediately searchable content.'
                    : 'Publication approval applies to this exact document and revision. It does not clear content-screening holds or promise immediately searchable content.'}</p>
                {outcome}
                {error ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
                {gone ? <p role="status" className="text-sm text-text-2">This document or request is no longer available in this {scopeNoun}.{receipt ? ' The confirmed outcome above is retained.' : ''}</p> : null}
                {interactionDisabled ? <p role="status" className="text-sm text-text-3">Workspace access is being confirmed. Your input is kept; decisions are paused.</p> : null}
                <GlassButton size="sm" disabled={busy || loading || interactionDisabled} onClick={() => void loadReview()}>
                    <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />Refresh review details
                </GlassButton>
                {loading ? <p role="status" className="flex items-center gap-2 text-sm text-text-3"><Loader2 size={14} className="animate-spin" />Loading current sharing and review permissions...</p> : null}
                {state && !gone ? <>
                    {state.publication ? <section className="space-y-2 border-t border-edge pt-3">
                        <h3 className="text-sm font-semibold text-text-1">Publication request</h3>
                        <p className="text-sm text-text-2">{state.publication.status === 'approval_failed'
                            ? 'Approval was recorded, but its processing handoff needs reconciliation.'
                            : `Status: ${state.publication.status.replaceAll('_', ' ')}`}</p>
                        <p className="break-words text-xs text-text-3">
                            Requester: {state.publication.requested_by_display_name || state.publication.requested_by_user_id || 'Not recorded'}
                            {state.publication.is_requester ? ' (you)' : ''}
                            {state.publication.requested_at ? ` · Requested ${state.publication.requested_at}` : ''}
                        </p>
                        <div className="flex flex-wrap gap-2">
                            {(['approve_artifact', 'reject_artifact', 'cancel_artifact'] as const).filter((operation) =>
                                adapter.allows(operation, review!.document, state)).map((operation) => (
                                <GlassButton key={operation} size="sm" variant={operation === 'approve_artifact' ? 'primary' : 'danger'}
                                    disabled={!allows(operation)} onClick={() => choose(operation)}>
                                    {decisionLabel(operation, state)}
                                </GlassButton>
                            ))}
                        </div>
                    </section> : null}
                    {isGroupScope && (state.relationship !== 'owner' ? <section className="space-y-2 border-t border-edge pt-3">
                        <h3 className="text-sm font-semibold text-text-1">Access for {adapter.scope.name}</h3>
                        <p className="text-xs text-text-3">A recipient decision changes only this group's access, not the source owner's files or other groups' grants.</p>
                        <div className="flex flex-wrap gap-2">
                            {(['approve_share', 'remove_share'] as const).filter((operation) =>
                                adapter.allows(operation, review!.document, state)).map((operation) => (
                                <GlassButton key={operation} size="sm" variant={operation === 'approve_share' ? 'primary' : 'danger'}
                                    disabled={!allows(operation)} onClick={() => choose(operation)}>
                                    {decisionLabel(operation, state)}
                                </GlassButton>
                            ))}
                        </div>
                    </section> : <>
                        {receipt?.action === 'unshare' && receipt.status === 'partial' && receiptTarget
                            && !state.recipients.some((recipient) => recipient.id === receiptTarget.id)
                            && state.document_version === receiptVersion
                            && adapter.allows('unshare', review!.document, state) ? (
                            <section className="space-y-2 border-t border-edge pt-3">
                                <h3 className="text-sm font-semibold text-text-1">Unfinished access cleanup</h3>
                                <p className="break-words text-xs text-text-3">Access for {receiptTarget.name} ({receiptTarget.id}) was removed. Only the reported cleanup remains; no share will be recreated.</p>
                                <GlassButton size="sm" variant="danger" disabled={!allows('unshare')}
                                    onClick={() => choose('unshare', receiptTarget, receipt)}>Retry access cleanup</GlassButton>
                            </section>
                        ) : null}
                        <section className="space-y-2 border-t border-edge pt-3">
                            <h3 className="text-sm font-semibold text-text-1">Recipient groups</h3>
                            {!state.recipients.length ? <p className="text-xs text-text-3">No recipient groups are recorded for this revision.</p> : (
                                <ul className="max-h-56 space-y-2 overflow-y-auto">
                                    {state.recipients.map((recipient) => <li key={recipient.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-edge p-2">
                                        <div className="min-w-0 flex-1 basis-40">
                                            <p className="break-words text-sm text-text-1">{recipient.name || recipient.id}</p>
                                            <p className="break-words text-xs text-text-3">{recipient.id} · {recipient.approval_status === 'approved' ? 'Approved' : 'Pending approval'}</p>
                                        </div>
                                        {adapter.allows('unshare', review!.document, state) ? <GlassButton size="sm" variant="danger"
                                            disabled={!allows('unshare')} onClick={() => choose('unshare', recipient)}>Stop sharing</GlassButton> : null}
                                    </li>)}
                                </ul>
                            )}
                        </section>
                        {mayShare ? <section className="space-y-3 border-t border-edge pt-3">
                            <h3 className="flex items-center gap-2 text-sm font-semibold text-text-1"><Users size={15} />Share this revision</h3>
                            <form className="flex flex-wrap gap-2" onSubmit={(event) => {
                                event.preventDefault();
                                if (!busy && !interactionDisabled) setQuery((current) => ({ ...current, search: searchDraft, page: 1 }));
                            }}>
                                <label className="min-w-0 flex-1 basis-48">
                                    <span className="sr-only">Search recipient groups</span>
                                    <input type="search" value={searchDraft} disabled={busy || interactionDisabled}
                                        onChange={(event) => setSearchDraft(event.target.value)}
                                        className="w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
                                        placeholder="Search groups by name or description" />
                                </label>
                                <GlassButton type="submit" size="sm" disabled={busy || interactionDisabled || needsRefresh}>
                                    <Search size={14} />Search groups
                                </GlassButton>
                            </form>
                            {searchError ? <div role="alert" className="space-y-1 text-sm text-danger">
                                <p>{searchError}</p><GlassButton size="sm" disabled={busy || needsRefresh || interactionDisabled}
                                    onClick={() => setSearchRetry((value) => value + 1)}>Retry recipient search</GlassButton>
                            </div> : searching ? <p role="status" className="text-xs text-text-3">Loading recipient groups...</p> : targets ? <>
                                <ul className="max-h-56 space-y-1 overflow-y-auto">
                                    {targets.groups.map((group) => <li key={group.id}>
                                        <label className="flex items-start gap-2 rounded-lg border border-edge p-2">
                                            <input type="radio" name="recipient-group" aria-label={`Select ${group.name || group.id}`}
                                                checked={selected?.id === group.id} disabled={!allows('share')}
                                                onChange={() => setSelected(group)} className="mt-1" />
                                            <span className="min-w-0">
                                                <span className="block break-words text-sm text-text-1">{group.name || group.id}</span>
                                                <span className="block break-words text-xs text-text-3">{group.description}</span>
                                            </span>
                                        </label>
                                    </li>)}
                                </ul>
                                {!targets.groups.length ? <p className="text-xs text-text-3">No eligible recipient groups match this search.</p> : null}
                                <div className="flex flex-wrap items-center gap-2 text-xs text-text-3">
                                    <span>{targets.total_count} eligible groups · Page {targets.page}</span>
                                    <GlassButton size="sm" disabled={targets.page <= 1 || busy || needsRefresh || interactionDisabled}
                                        onClick={() => setQuery((current) => ({ ...current, page: current.page - 1 }))}>Previous groups</GlassButton>
                                    <GlassButton size="sm" disabled={targets.page * targets.page_size >= targets.total_count || busy || needsRefresh || interactionDisabled}
                                        onClick={() => setQuery((current) => ({ ...current, page: current.page + 1 }))}>Next groups</GlassButton>
                                </div>
                            </> : null}
                            {selected ? <p className="break-words text-xs text-text-2">Selected recipient: {selected.name} ({selected.id}). Only revision {state.document_version} of this document will be shared.</p> : null}
                            <GlassButton size="sm" variant="primary" disabled={!selected || !allows('share')}
                                onClick={() => { if (selected) choose('share', selected); }}>Share with group</GlassButton>
                        </section> : null}
                    </>)}
                    {!state.actions.some((operation) => operation !== 'inspect') ? <p className="text-xs text-text-3">
                        No collaboration decision is currently available. Use classic review if reconciliation is required.
                    </p> : null}
                </> : null}
            </div>
        </Modal>
        {decision ? <ConfirmDialog title={`Confirm ${decision.repairReceipt ? 'access cleanup' : decisionLabel(decision.operation, decision.reviewed.state).toLowerCase()}`}
            confirmLabel={decision.repairReceipt ? 'Retry access cleanup' : decisionLabel(decision.operation, decision.reviewed.state)} busy={busy}
            confirmDisabled={decisionChanged || repairChanged || !allows(decision.operation)}
            description={`${adapter.scope.name} · ${fileName} · Revision ${decision.reviewed.state.document_version}${decision.target ? ` · ${decision.target.name} (${decision.target.id})` : ''}`}
            onClose={() => { if (!busyRef.current) setDecision(null); }}
            onConfirm={() => void execute(decision)}>
            <div className="space-y-3">
                <p className="text-sm text-text-2">{decisionEffect(decision, adapter.scope.name)}</p>
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
                {decisionChanged || needsRefresh ? <p className="text-xs text-text-3">Review details changed or the previous outcome was not confirmed. Refresh and review before another attempt.</p> : null}
                {repairChanged ? <p role="alert" className="text-xs text-danger">The revision or recipient relationship has changed. This earlier cleanup cannot act on the new grant; return to sharing details and review it separately.</p> : null}
                <GlassButton size="sm" disabled={busy || loading || interactionDisabled} onClick={() => void refreshDecision()}>
                    Refresh and review
                </GlassButton>
            </div>
        </ConfirmDialog> : null}
    </>;
}
