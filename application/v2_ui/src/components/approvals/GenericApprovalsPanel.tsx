// GenericApprovalsPanel.tsx
// The list and detail for control-center approval requests: group actions, user
// moderation, content screening, and the Microsoft 365 data-user approvals that ride the
// same list.
//
// One fetch per status covers every category; the category only narrows which request
// types the list shows. Microsoft 365 items open the dedicated Microsoft 365 detail, and
// content screening items point at Content Review, the same as the classic page.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Check, ExternalLink, Loader2, X } from 'lucide-react';
import {
    CONTENT_SCREENING_TYPE,
    approveApprovalRequest,
    contentReviewPath,
    denyApprovalRequest,
    errorMessage,
    fetchApprovalRequest,
    fetchApprovalRequests,
    formatDateTime,
    isM365RequestType,
    requestTypeLabel,
    textList,
    type ApprovalRequest,
    type ApprovalStatusFilter,
} from '../../lib/approvalsApi';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { GlassButton, Skeleton } from '../ui/primitives';
import {
    ApprovalSplit,
    DetailEmpty,
    DetailShell,
    Fact,
    Facts,
    ListMessage,
    ListPager,
    ListRow,
    ListSelect,
    ListToolbar,
    Notice,
    StatusBadge,
    fieldClass,
} from './ApprovalParts';
import { M365ApprovalDetail } from './M365ApprovalDetail';

const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<[ApprovalStatusFilter, string]> = [
    ['pending', 'Pending'],
    ['all', 'All statuses'],
    ['approved', 'Approved'],
    ['denied', 'Denied'],
    ['executed', 'Executed'],
];

type ShowFilter = 'all' | 'mine' | 'requested';

const SHOW_OPTIONS: Array<[ShowFilter, string]> = [
    ['all', 'Everything I can see'],
    ['mine', 'Waiting on me'],
    ['requested', 'My requests'],
];

/** The list filters a link can carry, so a dashboard figure opens the requests it counted. */
const FILTER_PARAMS = ['status', 'type', 'show', 'expiring'] as const;
const DAY_MS = 24 * 60 * 60 * 1000;

function readStatus(value: string | null): ApprovalStatusFilter {
    return STATUS_OPTIONS.some(([option]) => option === value) ? (value as ApprovalStatusFilter) : 'pending';
}

function readShow(value: string | null): ShowFilter {
    return SHOW_OPTIONS.some(([option]) => option === value) ? (value as ShowFilter) : 'all';
}

function expiresWithinADay(approval: ApprovalRequest): boolean {
    if (approval.status !== 'pending' || !approval.expires_at) return false;
    const expires = new Date(approval.expires_at).getTime();
    return Number.isFinite(expires) && expires - Date.now() <= DAY_MS;
}

function statusLabel(approval: ApprovalRequest): string {
    if (approval.status === 'denied' && approval.auto_denied) return 'Auto-denied';
    return approval.status;
}

function searchText(approval: ApprovalRequest): string {
    return [
        requestTypeLabel(approval.request_type),
        approval.group_name,
        approval.requester_name,
        approval.requester_email,
        approval.reason,
        textList(approval.context?.workflow_id),
        textList(approval.context?.conversation_id),
    ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
}

function rowScope(approval: ApprovalRequest): string {
    if (isM365RequestType(approval.request_type)) {
        return textList(approval.context?.workflow_id) || textList(approval.context?.conversation_id) || 'Your Microsoft 365 data';
    }
    return approval.group_name || approval.group_id || '';
}

export function GenericApprovalsPanel({
    category,
    types,
    selectedId,
    selectedGroupId,
    emptyTitle,
    reloadKey,
    onCountChange,
}: {
    category: string;
    /** The request types this category shows; null shows every type. */
    types: readonly string[] | null;
    selectedId?: string;
    selectedGroupId?: string;
    emptyTitle: string;
    reloadKey: number;
    onCountChange?: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const userId = useBootstrapStore((state) => state.data?.user?.id);
    const status = readStatus(searchParams.get('status'));
    const typeFilter = searchParams.get('type') || 'all';
    const show = readShow(searchParams.get('show'));
    const expiring = searchParams.get('expiring') === '1';
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [items, setItems] = useState<ApprovalRequest[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [localReload, setLocalReload] = useState(0);

    useEffect(() => {
        setPage(1);
    }, [category]);

    /** The list filters in the address, without the selected request's group. */
    const filterQuery = (extra?: Record<string, string>) => {
        const params = new URLSearchParams(extra);
        for (const key of FILTER_PARAMS) {
            const value = searchParams.get(key);
            if (value) params.set(key, value);
        }
        const query = params.toString();
        return query ? `?${query}` : '';
    };

    const updateFilter = (key: (typeof FILTER_PARAMS)[number], value: string, defaultValue: string) => {
        const next = new URLSearchParams(searchParams);
        if (value === defaultValue) next.delete(key);
        else next.set(key, value);
        setSearchParams(next, { replace: true });
        setPage(1);
    };

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        fetchApprovalRequests(status, controller.signal)
            .then((next) => setItems(next))
            .catch((error) => {
                if (controller.signal.aborted) return;
                setItems([]);
                setLoadError(errorMessage(error, 'Approval requests could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [status, reloadKey, localReload]);

    const inCategory = useMemo(
        () => (types ? items.filter((item) => types.includes(item.request_type)) : items),
        [items, types],
    );

    useEffect(() => {
        if (status === 'pending') onCountChange?.(inCategory.length);
    }, [inCategory, onCountChange, status]);

    const typeOptions = useMemo(() => {
        const present = Array.from(new Set(inCategory.map((item) => item.request_type)));
        const known = types ? [...types] : present;
        const ordered = Array.from(new Set([...known, ...present]));
        return [['all', 'All types'] as [string, string], ...ordered.map((type) => [type, requestTypeLabel(type)] as [string, string])];
    }, [inCategory, types]);

    const filtered = useMemo(() => {
        const query = search.trim().toLowerCase();
        return inCategory.filter(
            (item) => (typeFilter === 'all' || item.request_type === typeFilter)
                && (show === 'all'
                    || (show === 'mine' ? item.status === 'pending' && item.can_approve === true : item.requester_id === userId))
                && (!expiring || expiresWithinADay(item))
                && (!query || searchText(item).includes(query)),
        );
    }, [expiring, inCategory, search, show, typeFilter, userId]);

    const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    const safePage = Math.min(page, pageCount);
    const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

    const select = (approval: ApprovalRequest) => {
        const group = approval.group_id && !isM365RequestType(approval.request_type)
            ? { group_id: approval.group_id }
            : undefined;
        navigate(`/approvals/${category}/${encodeURIComponent(approval.id)}${filterQuery(group)}`);
    };

    const selectedSummary = selectedId ? items.find((item) => item.id === selectedId) : undefined;
    const refreshList = useCallback(() => setLocalReload((value) => value + 1), []);
    const filtersApplied = typeFilter !== 'all' || show !== 'all' || expiring;

    const list = (
        <>
            <ListToolbar search={search} onSearch={(value) => { setSearch(value); setPage(1); }} searchLabel="Search requests">
                <ListSelect
                    label="Status"
                    value={status}
                    testId="v2-approvals-status-filter"
                    onChange={(value) => updateFilter('status', value, 'pending')}
                    options={STATUS_OPTIONS}
                />
                <ListSelect
                    label="Show"
                    value={show}
                    testId="v2-approvals-show-filter"
                    onChange={(value) => updateFilter('show', value, 'all')}
                    options={SHOW_OPTIONS}
                />
                {typeOptions.length > 2 ? (
                    <ListSelect
                        label="Request type"
                        value={typeFilter}
                        testId="v2-approvals-type-filter"
                        onChange={(value) => updateFilter('type', value, 'all')}
                        options={typeOptions}
                    />
                ) : null}
            </ListToolbar>
            {expiring ? (
                <div className="flex items-center justify-between gap-2 border-b border-edge bg-warn-soft px-4 py-2 text-xs text-text-1" data-testid="v2-approvals-expiring-filter">
                    <span>Only pending requests that expire within 24 hours.</span>
                    <button type="button" className="font-semibold text-accent underline" onClick={() => updateFilter('expiring', '', '')}>
                        Show all
                    </button>
                </div>
            ) : null}
            {loading ? (
                <div className="space-y-2 p-4" aria-busy="true">
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                </div>
            ) : loadError ? (
                <div className="p-4">
                    <Notice tone="danger">{loadError}</Notice>
                </div>
            ) : visible.length ? (
                <>
                    <ul>
                        {visible.map((approval) => (
                            <ListRow
                                key={`${approval.group_id ?? ''}:${approval.id}`}
                                active={approval.id === selectedId}
                                onSelect={() => select(approval)}
                                title={requestTypeLabel(approval.request_type)}
                                testId={`v2-approval-row-${approval.id}`}
                                meta={[rowScope(approval), approval.requester_name, formatDateTime(approval.created_at)]
                                    .filter(Boolean)
                                    .join(' · ')}
                                badge={<StatusBadge status={approval.status} label={statusLabel(approval)} />}
                            />
                        ))}
                    </ul>
                    <ListPager page={safePage} pageCount={pageCount} total={filtered.length} onPage={setPage} />
                </>
            ) : (
                <ListMessage>{search || filtersApplied ? 'No requests match these filters.' : emptyTitle}</ListMessage>
            )}
        </>
    );

    let detail;
    if (!selectedId) {
        detail = <DetailEmpty title="Select a request" description="Choose a request from the list to review it here." />;
    } else if (selectedSummary && isM365RequestType(selectedSummary.request_type)) {
        detail = <M365ApprovalDetail key={selectedId} approvalId={selectedId} onChanged={refreshList} />;
    } else {
        detail = (
            <GenericApprovalDetail
                key={`${selectedGroupId ?? selectedSummary?.group_id ?? ''}:${selectedId}`}
                approvalId={selectedId}
                groupId={selectedGroupId || selectedSummary?.group_id}
                onChanged={refreshList}
            />
        );
    }

    return (
        <ApprovalSplit
            listLabel="Approval requests"
            hasSelection={Boolean(selectedId)}
            onBack={() => navigate(`/approvals/${category}${filterQuery()}`)}
            list={list}
            detail={detail}
        />
    );
}

function GenericApprovalDetail({
    approvalId,
    groupId,
    onChanged,
}: {
    approvalId: string;
    groupId?: string;
    onChanged: () => void;
}) {
    const navigate = useNavigate();
    const [approval, setApproval] = useState<ApprovalRequest | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [comment, setComment] = useState('');
    const [busy, setBusy] = useState<'' | 'approve' | 'deny'>('');
    const [actionError, setActionError] = useState('');

    const load = useCallback(
        async (signal?: AbortSignal) => {
            setLoading(true);
            setLoadError('');
            try {
                setApproval(await fetchApprovalRequest(approvalId, groupId, signal));
            } catch (error) {
                if (signal?.aborted) return;
                setApproval(null);
                setLoadError(errorMessage(error, 'The approval request could not be loaded.'));
            } finally {
                if (!signal?.aborted) setLoading(false);
            }
        },
        [approvalId, groupId],
    );

    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal);
        return () => controller.abort();
    }, [load]);

    if (loading && !approval) {
        return (
            <div className="space-y-3 p-6" aria-busy="true">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-24 w-full" />
            </div>
        );
    }
    if (!approval) {
        return (
            <div className="p-6">
                <Notice tone="danger" testId="v2-approval-detail-error">
                    {loadError || 'The approval request could not be loaded.'}
                </Notice>
            </div>
        );
    }
    if (isM365RequestType(approval.request_type)) {
        return <M365ApprovalDetail approvalId={approval.id} onChanged={onChanged} />;
    }

    const isPending = approval.status === 'pending';
    const canApprove = isPending && approval.can_approve === true;
    const canDeny = isPending && approval.can_deny === true;
    const reviewPath = approval.request_type === CONTENT_SCREENING_TYPE ? contentReviewPath(approval) : null;

    const decide = async (decision: 'approve' | 'deny') => {
        if (decision === 'deny' && !comment.trim()) {
            setActionError('Provide a reason for denying this request.');
            return;
        }
        setBusy(decision);
        setActionError('');
        try {
            if (decision === 'approve') {
                await approveApprovalRequest(approval.id, approval.group_id ?? groupId, comment);
                toast.success('Request approved. The action has been executed.');
            } else {
                await denyApprovalRequest(approval.id, approval.group_id ?? groupId, comment);
                toast.success('Request denied.');
            }
            setComment('');
            await load();
            onChanged();
        } catch (error) {
            setActionError(errorMessage(error, decision === 'approve' ? 'The request could not be approved.' : 'The request could not be denied.'));
        } finally {
            setBusy('');
        }
    };

    const requester = [approval.requester_name || 'Unknown', approval.requester_email ? `(${approval.requester_email})` : '']
        .filter(Boolean)
        .join(' ');
    const decidedBy = [approval.approved_by_name || 'Unknown', approval.approved_by_email ? `(${approval.approved_by_email})` : '']
        .filter(Boolean)
        .join(' ');
    const execution = textList(approval.execution_result) || (approval.execution_result ? JSON.stringify(approval.execution_result) : '');

    return (
        <DetailShell
            title={requestTypeLabel(approval.request_type)}
            subtitle={approval.group_name || undefined}
            badge={<StatusBadge status={approval.status} label={statusLabel(approval)} />}
        >
            <Facts>
                <Fact label="Group">{approval.group_name || approval.group_id}</Fact>
                <Fact label="Requested by">{requester}</Fact>
                <Fact label="Requested">{formatDateTime(approval.created_at)}</Fact>
                <Fact label="Expires">{isPending ? formatDateTime(approval.expires_at) : ''}</Fact>
                <Fact label="Reason">{approval.reason || 'No reason provided'}</Fact>
            </Facts>

            {reviewPath ? (
                <Notice tone="info">
                    <p>This content screening request is reviewed in Content Review, where the flagged content is shown.</p>
                    <GlassButton
                        size="sm"
                        variant="primary"
                        className="mt-2"
                        onClick={() => navigate(reviewPath)}
                        data-testid="v2-approval-open-content-review"
                    >
                        <ExternalLink size={14} />
                        Open Content Review
                    </GlassButton>
                </Notice>
            ) : null}

            {!isPending ? (
                <section className="space-y-3 rounded-xl border border-edge p-4" data-testid="v2-approval-result">
                    <h3 className="text-sm font-semibold text-text-1">Decision</h3>
                    <Facts>
                        <Fact label="Status">{statusLabel(approval)}</Fact>
                        <Fact label="By">{decidedBy}</Fact>
                        <Fact label="Date">{formatDateTime(approval.approved_at) || 'N/A'}</Fact>
                        <Fact label="Comment">{approval.approval_comment}</Fact>
                        <Fact label="Execution">{execution}</Fact>
                    </Facts>
                </section>
            ) : canApprove || canDeny ? (
                reviewPath ? null : (
                    <section className="space-y-3" data-testid="v2-approval-decision">
                        <label className="block space-y-1 text-sm">
                            <span className="font-medium text-text-1">
                                Comment {canDeny && !canApprove ? <span className="text-danger">(required)</span> : null}
                            </span>
                            <textarea
                                className={fieldClass}
                                rows={3}
                                value={comment}
                                disabled={Boolean(busy)}
                                onChange={(event) => setComment(event.target.value)}
                                placeholder={canApprove ? 'Optional comment for approval, required for denial...' : 'Required reason for denial...'}
                                data-testid="v2-approval-comment"
                            />
                            <span className="block text-xs text-text-3">
                                {canApprove ? 'Provide additional context for this decision.' : 'Provide a reason for denying this request.'}
                            </span>
                        </label>
                        {actionError ? <Notice tone="danger">{actionError}</Notice> : null}
                        <div className="flex flex-wrap justify-end gap-2">
                            {canDeny ? (
                                <GlassButton
                                    variant="danger"
                                    disabled={Boolean(busy)}
                                    onClick={() => void decide('deny')}
                                    data-testid="v2-approval-deny"
                                >
                                    {busy === 'deny' ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />}
                                    Deny request
                                </GlassButton>
                            ) : null}
                            {canApprove ? (
                                <GlassButton
                                    variant="success"
                                    disabled={Boolean(busy)}
                                    onClick={() => void decide('approve')}
                                    data-testid="v2-approval-approve"
                                >
                                    {busy === 'approve' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                                    Approve &amp; execute
                                </GlassButton>
                            ) : null}
                        </div>
                    </section>
                )
            ) : (
                <Notice tone="warn" testId="v2-approval-cannot-decide">
                    You are not an eligible reviewer for this request. Another eligible reviewer must approve it.
                </Notice>
            )}
        </DetailShell>
    );
}
