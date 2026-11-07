// GovernanceItemPolicyManager.tsx
// A searchable, paged list of delegated item policies with their row actions.
//
// One list serves every place item policies appear: the Delegated Item Policies section
// shows every type; the MCP destination and Inbound MCP cards show only their own types; an
// AI connection's access dialog shows only the policies on that one connection. The editor
// is shared through the governance store, and every list refetches when a policy is saved
// anywhere on the page.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import {
    AlertCircle,
    ArrowLeftRight,
    ChevronDown,
    Copy,
    Lock,
    Pencil,
    Plus,
    RotateCw,
    Search,
    Trash2,
} from 'lucide-react';
import {
    GOVERNANCE_ENTITY_TYPES,
    ITEM_POLICY_PAGE_SIZES,
    actionTypeLabel,
    allowsNobody,
    deleteItemPolicy,
    draftFromItemPolicy,
    duplicateItemPolicy,
    entityTypeLabel,
    fetchItemPolicyPage,
    governanceErrorMessage,
    inverseItemPolicy,
    summarizeAllowed,
    summarizeBlocked,
    type GovernanceEntityType,
    type GovernanceItemPolicy,
    type ItemPolicyDraft,
    type ItemPolicyPage,
    type PrincipalKind,
} from '../../../lib/governance';
import {
    governancePoliciesChanged,
    openGovernanceEditor,
    useGovernanceStore,
    type GovernanceResourceTarget,
} from '../../../stores/governanceStore';
import { toast } from '../../../stores/toastStore';
import { GlassButton, Skeleton } from '../../ui/primitives';
import { ConfirmAction, RowAction } from '../../workspace/primitives';
import { usePrincipalLabels } from './usePrincipalLabels';

const SEARCH_DEBOUNCE_MS = 300;

const ACTION_TYPE_ENTITY_TYPES = new Set(['personal_action_type', 'group_action_type', 'global_action_type']);

function itemLabel(policy: GovernanceItemPolicy): string {
    if (ACTION_TYPE_ENTITY_TYPES.has(policy.entity_type)) {
        return actionTypeLabel(policy.item_id, policy.resource_label);
    }
    return policy.resource_label || policy.item_id;
}

function PrincipalChips({ kind, ids, label }: { kind: PrincipalKind; ids: string[]; label: string }) {
    const labels = usePrincipalLabels(kind, ids);
    return (
        <div className="min-w-0">
            <p className="mb-1 text-xs font-medium text-text-2">{label}</p>
            {ids.length ? (
                <ul className="flex flex-wrap gap-1.5" aria-label={label}>
                    {ids.map((id) => {
                        const lookup = labels.lookup(id);
                        const entry = lookup?.status === 'found' ? lookup.entry : undefined;
                        return (
                            <li
                                key={id}
                                title={entry?.detail ? `${entry.detail} · ${id}` : id}
                                className={clsx(
                                    'max-w-full truncate rounded-full border px-2 py-0.5 text-xs',
                                    lookup?.status === 'missing'
                                        ? 'border-warn/40 bg-warn-soft text-warn'
                                        : 'border-edge bg-surface-2 text-text-1',
                                    !entry?.name && 'font-mono text-[11px]',
                                )}
                            >
                                {entry?.name || id}
                                {entry?.kind === 'public_workspace' ? <span className="ml-1 text-text-3">(public)</span> : null}
                            </li>
                        );
                    })}
                </ul>
            ) : (
                <p className="text-xs text-text-3">None</p>
            )}
        </div>
    );
}

function PolicyPrincipals({ policy }: { policy: GovernanceItemPolicy }) {
    return (
        <div className="mt-3 grid gap-3 border-t border-edge pt-3 @min-[44rem]:grid-cols-2">
            {policy.allow_all ? (
                <p className="text-xs text-text-2 @min-[44rem]:col-span-2">
                    Allows everyone who passes the matching feature policy.
                </p>
            ) : (
                <>
                    <PrincipalChips kind="users" ids={policy.allowed_users} label="Allowed people" />
                    <PrincipalChips kind="groups" ids={policy.allowed_groups} label="Allowed groups" />
                </>
            )}
            <PrincipalChips kind="users" ids={policy.denied_users} label="Blocked people" />
            <PrincipalChips kind="groups" ids={policy.denied_groups} label="Blocked groups" />
            {policy.policy_id ? (
                <p className="text-[11px] text-text-3 @min-[44rem]:col-span-2">
                    Policy ID <span className="font-mono">{policy.policy_id}</span>
                </p>
            ) : null}
        </div>
    );
}

export interface GovernanceItemPolicyManagerProps {
    /** Types this list covers. Absent means every type. */
    entityTypes?: readonly GovernanceEntityType[];
    /** Only the policies on this one item, matched exactly. */
    itemId?: string;
    /** The draft New policy starts from. */
    newPolicy: () => ItemPolicyDraft;
    newPolicyLabel?: string;
    /** Set when the list sits inside a resource's access dialog. */
    returnTo?: GovernanceResourceTarget;
    /** Taught when nothing is listed and no filter is narrowing the list. */
    emptyText: string;
    /** Accessible name for the list. */
    label: string;
    onTotalChange?: (total: number) => void;
    /** Extra controls beside New policy, such as quick-create shortcuts. */
    actions?: React.ReactNode;
    /** Leave New policy to the shortcuts in `actions`. */
    hideNewButton?: boolean;
}

export function GovernanceItemPolicyManager({
    entityTypes,
    itemId,
    newPolicy,
    newPolicyLabel = 'New policy',
    returnTo,
    emptyText,
    label,
    onTotalChange,
    actions,
    hideNewButton = false,
}: GovernanceItemPolicyManagerProps) {
    const revision = useGovernanceStore((state) => state.revision);
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [typeFilter, setTypeFilter] = useState<string>('');
    const [page, setPage] = useState(1);
    const [perPage, setPerPage] = useState<number>(25);
    const [data, setData] = useState<ItemPolicyPage | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expanded, setExpanded] = useState<string | null>(null);
    const [busyKey, setBusyKey] = useState<string | null>(null);
    const [reload, setReload] = useState(0);

    const typeOptions = useMemo(
        () => GOVERNANCE_ENTITY_TYPES.filter((type) => !entityTypes?.length || entityTypes.includes(type.value)),
        [entityTypes],
    );
    const entityTypesKey = (entityTypes ?? []).join(',');
    const queryTypes = useMemo(
        () => (typeFilter ? [typeFilter] : entityTypesKey ? entityTypesKey.split(',') : []),
        [typeFilter, entityTypesKey],
    );

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebouncedSearch(search);
            setPage(1);
        }, SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [search]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        void fetchItemPolicyPage(
            { entityTypes: queryTypes, itemId, search: debouncedSearch, page, perPage },
            controller.signal,
        )
            .then((result) => {
                if (!controller.signal.aborted) {
                    setData(result);
                    setError(null);
                    // The server clamps a page past the end, so follow it rather than
                    // asking again for a page that no longer exists after a delete.
                    if (result.pagination.page !== page) {
                        setPage(result.pagination.page);
                    }
                }
            })
            .catch((loadError) => {
                if (!controller.signal.aborted) {
                    setError(governanceErrorMessage(loadError, 'Policies could not be loaded.'));
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setLoading(false);
                }
            });
        return () => controller.abort();
    }, [queryTypes, itemId, debouncedSearch, page, perPage, revision, reload]);

    const total = data?.pagination.total_items ?? 0;
    const filtered = Boolean(debouncedSearch.trim() || typeFilter);
    useEffect(() => {
        if (data && !filtered) {
            onTotalChange?.(data.pagination.total_items);
        }
    }, [data, filtered, onTotalChange]);

    const openEditor = useCallback((draft: ItemPolicyDraft) => {
        openGovernanceEditor({ draft, entityTypes, returnTo });
    }, [entityTypes, returnTo]);

    const remove = async (policy: GovernanceItemPolicy) => {
        const key = `${policy.entity_type}:${policy.item_id}:${policy.policy_id}`;
        setBusyKey(key);
        try {
            await deleteItemPolicy(policy);
            toast.success(`Deleted ${policy.policy_name}.`);
            governancePoliciesChanged();
        } catch (deleteError) {
            toast.error(governanceErrorMessage(deleteError, 'The policy could not be deleted.'));
        } finally {
            setBusyKey(null);
        }
    };

    const policies = data?.policies ?? [];
    const pagination = data?.pagination;
    const firstShown = pagination && total ? (pagination.page - 1) * pagination.per_page + 1 : 0;
    const lastShown = pagination ? Math.min(total, pagination.page * pagination.per_page) : 0;

    return (
        <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-end gap-2">
                <div className="relative min-w-[16rem] flex-1">
                    <Search size={14} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3" />
                    <input
                        type="search"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search names, items, people, or group IDs"
                        aria-label={`Search ${label.toLowerCase()}`}
                        className="w-full rounded-lg border border-edge bg-surface-1 py-2 pr-3 pl-9 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                </div>
                {typeOptions.length > 1 ? (
                    <select
                        value={typeFilter}
                        onChange={(event) => {
                            setTypeFilter(event.target.value);
                            setPage(1);
                        }}
                        aria-label="Filter by what the policy applies to"
                        className="rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none"
                    >
                        <option value="">{entityTypes?.length ? 'All of these' : 'Everything'}</option>
                        {typeOptions.map((type) => (
                            <option key={type.value} value={type.value}>{type.label}</option>
                        ))}
                    </select>
                ) : null}
                <div className="flex flex-wrap gap-2">
                    {actions}
                    {hideNewButton ? null : (
                        <GlassButton type="button" size="md" variant="primary" onClick={() => openEditor(newPolicy())}>
                            <Plus size={15} aria-hidden="true" />
                            {newPolicyLabel}
                        </GlassButton>
                    )}
                </div>
            </div>

            {error ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-text-2">
                    <AlertCircle size={13} className="shrink-0 text-danger" aria-hidden="true" />
                    <span className="min-w-0 flex-1">{error}</span>
                    <GlassButton type="button" size="sm" variant="ghost" onClick={() => setReload((value) => value + 1)}>
                        <RotateCw size={13} aria-hidden="true" />
                        Try again
                    </GlassButton>
                </div>
            ) : null}

            {loading && !data ? (
                <div className="space-y-2" aria-hidden="true">
                    {[0, 1, 2].map((index) => <Skeleton key={index} className="h-14 w-full" />)}
                </div>
            ) : policies.length === 0 && !error ? (
                <p className="rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    {filtered ? 'No policies match this search.' : emptyText}
                </p>
            ) : policies.length ? (
                <ul
                    aria-label={label}
                    aria-busy={loading}
                    className={clsx('divide-y divide-edge rounded-xl border border-edge-strong bg-surface-solid', loading && 'opacity-70')}
                >
                    {policies.map((policy) => {
                        const key = `${policy.entity_type}:${policy.item_id}:${policy.policy_id}`;
                        const blocked = summarizeBlocked(policy);
                        const isExpanded = expanded === key;
                        const locked = policy.system_managed;
                        return (
                            <li key={key} className="px-3 py-3 sm:px-4" data-item-policy={policy.policy_id}>
                                <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
                                    <div className="min-w-0 flex-[2_1_16rem]">
                                        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-text-1">
                                            <span className="min-w-0 break-words">{policy.policy_name}</span>
                                            {locked ? (
                                                <span className="inline-flex items-center gap-1 rounded-full border border-edge-strong px-1.5 py-0.5 text-[10px] font-medium text-text-3">
                                                    <Lock size={10} aria-hidden="true" />
                                                    System-managed
                                                </span>
                                            ) : null}
                                        </p>
                                        <p className="mt-0.5 text-xs text-text-3">
                                            {entityTypeLabel(policy.entity_type)}
                                            <span aria-hidden="true"> · </span>
                                            <span className="text-text-2" title={policy.item_id}>{itemLabel(policy)}</span>
                                        </p>
                                        {locked && policy.managed_reason ? (
                                            <p className="mt-1 text-xs text-text-3">{policy.managed_reason}</p>
                                        ) : null}
                                    </div>
                                    <div className="min-w-0 flex-[1_1_10rem] text-xs">
                                        <p className={clsx(allowsNobody(policy) ? 'text-warn' : 'text-text-2')}>
                                            <span className="text-text-3">Allows </span>
                                            {summarizeAllowed(policy)}
                                        </p>
                                        {blocked ? (
                                            <p className="mt-0.5 text-text-2">
                                                <span className="text-text-3">Blocks </span>
                                                {blocked}
                                            </p>
                                        ) : null}
                                    </div>
                                    <div className="flex shrink-0 items-center gap-0.5">
                                        <button
                                            type="button"
                                            aria-expanded={isExpanded}
                                            aria-label={`${isExpanded ? 'Hide' : 'Show'} who ${policy.policy_name} applies to`}
                                            title={isExpanded ? 'Hide people and groups' : 'Show people and groups'}
                                            onClick={() => setExpanded(isExpanded ? null : key)}
                                            className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                                        >
                                            <ChevronDown size={15} className={clsx('transition-transform', isExpanded && 'rotate-180')} />
                                        </button>
                                        <RowAction
                                            icon={<Copy size={15} />}
                                            label={`Duplicate ${policy.policy_name}`}
                                            onClick={() => openEditor(duplicateItemPolicy(policy))}
                                        />
                                        <RowAction
                                            icon={<ArrowLeftRight size={15} />}
                                            label={`Inverse of ${policy.policy_name}: swap allowed and blocked`}
                                            onClick={() => openEditor(inverseItemPolicy(policy))}
                                        />
                                        <RowAction
                                            icon={<Pencil size={15} />}
                                            label={locked ? 'System-managed policies cannot be edited' : `Edit ${policy.policy_name}`}
                                            disabled={locked}
                                            onClick={() => openEditor(draftFromItemPolicy(policy))}
                                        />
                                        <ConfirmAction
                                            icon={<Trash2 size={15} />}
                                            label={locked ? 'System-managed policies cannot be deleted' : `Delete ${policy.policy_name}`}
                                            confirmLabel="Confirm delete"
                                            busy={busyKey === key}
                                            disabled={locked}
                                            onConfirm={() => void remove(policy)}
                                        />
                                    </div>
                                </div>
                                {isExpanded ? <PolicyPrincipals policy={policy} /> : null}
                            </li>
                        );
                    })}
                </ul>
            ) : null}

            {pagination && total > 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                    <span role="status">
                        Showing {firstShown}–{lastShown} of {total}
                    </span>
                    <div className="flex items-center gap-2">
                        <label className="flex items-center gap-1.5">
                            <span>Per page</span>
                            <select
                                value={perPage}
                                onChange={(event) => {
                                    setPerPage(Number(event.target.value));
                                    setPage(1);
                                }}
                                className="rounded-lg border border-edge bg-surface-1 px-2 py-1 text-xs text-text-1 focus:border-accent focus:outline-none"
                            >
                                {ITEM_POLICY_PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
                            </select>
                        </label>
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="subtle"
                            disabled={!pagination.has_prev || loading}
                            onClick={() => setPage((current) => Math.max(1, current - 1))}
                        >
                            Previous
                        </GlassButton>
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="subtle"
                            disabled={!pagination.has_next || loading}
                            onClick={() => setPage((current) => current + 1)}
                        >
                            Next
                        </GlassButton>
                    </div>
                </div>
            ) : null}
        </div>
    );
}
