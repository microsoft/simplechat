// GroupMembersSection.tsx
// The group workspace Members section (M7B): who belongs to the group, their roles, and who is
// asking to join, managed natively through the /api/groups/<g>/membership/... routes.
//
// Every control comes from the server, with no fallback: the group-level operations (add,
// review requests) from the member list's `membership_management` hint, and each row's controls
// from its own `member_actions`. Nothing is kept optimistically. A write shows the server's own
// outcome and the list is read again, so a row, a role and the offered controls always show what
// the server holds. A refusal shows the server's reviewed message. A write conflict keeps the
// state so the same action can simply be tried again. A refusal that means the caller's own
// standing changed also re-reads the workspace context, so the header and every other section
// follow. Leaving the group goes back to /groups, because the group is no longer the caller's.
//
// The search, role filter and page live in the URL, so back, forward and a shared link reopen
// the same view.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Check, Crown, FileUp, Loader2, LogOut, UserMinus, UserPlus, Users, X } from 'lucide-react';
import { clsx } from 'clsx';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../../components/ui/primitives';
import { Pill, SectionIntro, SectionSearch } from '../../components/workspace/primitives';
import { AddMemberDialog } from '../../components/membership/AddMemberDialog';
import { ImportMembersDialog, type ImportRowOutcome } from '../../components/membership/ImportMembersDialog';
import { codePointLength } from '../../lib/groupDirectory';
import { groupRoleLabel } from '../../lib/groupWorkspaceNavigation';
import {
    ASSIGNABLE_ROLE_OPTIONS, GROUP_MEMBER_ROLES, MEMBERS_MAX_PAGE, MEMBERS_PAGE_SIZE, MEMBER_SEARCH_MAX_LENGTH,
    MembershipResponseError, createGroupMembershipClient, fallbackMemberText, isAccessChangedError,
    isAssignableMemberRole, isGroupMemberRole, isTerminalMembershipError, memberDisplayName, membershipErrorCode,
    membershipErrorMessage,
    type AssignableMemberRole, type DirectoryUser, type GroupMember, type GroupMemberRole, type JoinRequest,
    type JoinRequestList, type MemberCsvRow, type MemberListPage,
} from '../../lib/groupMembership';

type Confirmation =
    | { kind: 'remove'; member: GroupMember }
    | { kind: 'leave'; member: GroupMember }
    | { kind: 'transfer'; member: GroupMember }
    | { kind: 'demote'; member: GroupMember; role: AssignableMemberRole }
    | { kind: 'bulk-remove'; members: GroupMember[] };

interface Notice {
    tone: 'status' | 'alert';
    text: string;
}

interface BulkReport {
    summary: string;
    failures: { name: string; message: string }[];
}

const SELECT_CLASS = 'min-w-0 rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';
const NOT_ATTEMPTED = 'Not attempted: the change stopped at an earlier member.';
const MAX_LISTED = 10;

function readRole(value: string | null): GroupMemberRole | null {
    return isGroupMemberRole(value) ? value : null;
}

function readPage(value: string | null): number {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 1) return 1;
    return Math.min(parsed, MEMBERS_MAX_PAGE);
}

function isSelectable(member: GroupMember, viewerId: string): boolean {
    return member.userId !== viewerId
        && (member.actions.includes('change_role') || member.actions.includes('remove'));
}

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`;
}

function MemberAvatar({ name }: { name: string }) {
    // Decorative, so it gives way on a narrow screen rather than pushing the name onto its own line.
    return (
        <span aria-hidden="true"
            className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-sm font-semibold text-text-2 sm:flex">
            {(name.trim()[0] ?? '?').toUpperCase()}
        </span>
    );
}

function MemberRow({
    member, isSelf, selectable, selected, pendingRole, disabled, busy,
    onSelect, onRoleChange, onRemove, onLeave, onTransfer,
}: {
    member: GroupMember;
    isSelf: boolean;
    selectable: boolean;
    selected: boolean;
    pendingRole: AssignableMemberRole | undefined;
    disabled: boolean;
    busy: boolean;
    onSelect: (selected: boolean) => void;
    onRoleChange: (role: AssignableMemberRole) => void;
    onRemove: () => void;
    onLeave: () => void;
    onTransfer: () => void;
}) {
    const name = memberDisplayName(member);
    const canChangeRole = member.actions.includes('change_role') && isAssignableMemberRole(member.role);
    return (
        <GlassPanel elevation="flat" className="flex flex-wrap items-center gap-3 p-3" data-member-id={member.userId}>
            <span className="flex w-4 shrink-0 justify-center">
                {selectable ? (
                    <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={selected} disabled={disabled}
                        aria-label={`Select ${name}`} onChange={(event) => onSelect(event.target.checked)} />
                ) : null}
            </span>
            <MemberAvatar name={name} />
            <div className="min-w-0 flex-1 basis-32">
                <p className="flex min-w-0 flex-wrap items-center gap-1.5 text-sm font-medium text-text-1">
                    <span className="min-w-0 break-words">{name}</span>
                    {isSelf ? <Pill tone="accent">You</Pill> : null}
                </p>
                {member.email && member.email !== name ? <p className="mt-0.5 break-all text-xs text-text-3">{member.email}</p> : null}
            </div>
            <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2">
                {busy ? <Loader2 size={15} className="animate-spin text-text-3" aria-hidden="true" /> : null}
                {canChangeRole ? (
                    <select className={SELECT_CLASS} value={pendingRole ?? member.role} disabled={disabled}
                        aria-label={`Role for ${name}`}
                        onChange={(event) => {
                            const role = event.target.value;
                            if (isAssignableMemberRole(role) && role !== member.role) onRoleChange(role);
                        }}>
                        {ASSIGNABLE_ROLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                ) : <Pill tone={member.role === 'Owner' ? 'accent' : 'neutral'}>{groupRoleLabel(member.role)}</Pill>}
                {member.actions.includes('transfer_ownership') ? (
                    <GlassButton size="sm" variant="subtle" disabled={disabled} aria-label={`Make ${name} the owner`} onClick={onTransfer}>
                        <Crown size={14} />Make owner
                    </GlassButton>
                ) : null}
                {member.actions.includes('remove') ? (
                    <GlassButton size="sm" variant="ghost" disabled={disabled}
                        aria-label={`Remove ${name}`} onClick={onRemove}>
                        <UserMinus size={14} />Remove
                    </GlassButton>
                ) : null}
                {member.actions.includes('leave') && isSelf ? (
                    <GlassButton size="sm" variant="subtle" disabled={disabled} aria-label="Leave this group" onClick={onLeave}>
                        <LogOut size={14} />Leave group
                    </GlassButton>
                ) : null}
            </div>
        </GlassPanel>
    );
}

function JoinRequestsPanel({
    requests, loading, error, busyKey, disabled, onApprove, onReject, onRetry,
}: {
    requests: JoinRequestList | null;
    loading: boolean;
    error: string;
    busyKey: string | null;
    disabled: boolean;
    onApprove: (request: JoinRequest) => void;
    onReject: (request: JoinRequest) => void;
    onRetry: () => void;
}) {
    const count = requests?.totalCount ?? 0;
    return (
        <GlassPanel elevation="flat" className="space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-text-1">Requests to join</h3>
                {requests ? <Pill tone={count ? 'warn' : 'neutral'}>{plural(count, 'waiting', 'waiting')}</Pill> : null}
            </div>
            {error ? (
                <div role="alert" className="space-y-2 text-sm text-danger">
                    <p>{error}</p>
                    <GlassButton size="sm" disabled={loading} onClick={onRetry}>Retry requests</GlassButton>
                </div>
            ) : !requests ? (
                <Skeleton className="h-10 w-full" />
            ) : requests.requests.length === 0 ? (
                <p className="text-xs text-text-3">No one is waiting to join.</p>
            ) : (
                <ul aria-label="Requests to join" className="space-y-2">
                    {requests.requests.map((request) => {
                        const name = memberDisplayName(request);
                        const busy = busyKey === `approve:${request.userId}` || busyKey === `reject:${request.userId}`;
                        return (
                            <li key={request.userId} className="flex flex-wrap items-center gap-3 rounded-xl border border-edge p-2.5">
                                <MemberAvatar name={name} />
                                <div className="min-w-0 flex-1 basis-32">
                                    <p className="break-words text-sm font-medium text-text-1">{name}</p>
                                    {request.email && request.email !== name ? <p className="break-all text-xs text-text-3">{request.email}</p> : null}
                                </div>
                                <div className="ml-auto flex flex-wrap items-center gap-2">
                                    {busy ? <Loader2 size={15} className="animate-spin text-text-3" aria-hidden="true" /> : null}
                                    <GlassButton size="sm" variant="primary" disabled={disabled} aria-label={`Approve ${name}`}
                                        onClick={() => onApprove(request)}>
                                        <Check size={14} />Approve
                                    </GlassButton>
                                    <GlassButton size="sm" variant="ghost" disabled={disabled} aria-label={`Reject ${name}`}
                                        onClick={() => onReject(request)}>
                                        <X size={14} />Reject
                                    </GlassButton>
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}
        </GlassPanel>
    );
}

export function GroupMembersSection({
    groupId, groupName, viewerId, interactionDisabled, onBusyChange, onAccessChanged, onLeft,
}: {
    groupId: string;
    groupName: string;
    viewerId: string;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    /** Re-read the workspace context after the caller's own role or access changed. */
    onAccessChanged: () => void;
    /** Leave the page after the caller left the group. */
    onLeft: () => void | Promise<void>;
}) {
    const client = useMemo(() => createGroupMembershipClient(groupId), [groupId]);
    const [searchParams, setSearchParams] = useSearchParams();
    const urlSearch = searchParams.get('search') ?? '';
    const urlRole = readRole(searchParams.get('role'));
    const page = readPage(searchParams.get('page'));

    const [searchInput, setSearchInput] = useState(urlSearch);
    const [searchError, setSearchError] = useState('');
    const [list, setList] = useState<MemberListPage | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [listToken, setListToken] = useState(0);
    const [requests, setRequests] = useState<JoinRequestList | null>(null);
    const [requestsLoading, setRequestsLoading] = useState(false);
    const [requestsError, setRequestsError] = useState('');
    const [requestsToken, setRequestsToken] = useState(0);
    const [busyKey, setBusyKey] = useState<string | null>(null);
    const [importing, setImporting] = useState(false);
    const [notice, setNotice] = useState<Notice | null>(null);
    const [selection, setSelection] = useState<string[]>([]);
    const [pendingRoles, setPendingRoles] = useState<Record<string, AssignableMemberRole>>({});
    const [bulkRole, setBulkRole] = useState<AssignableMemberRole>('User');
    const [bulkReport, setBulkReport] = useState<BulkReport | null>(null);
    const [addOpen, setAddOpen] = useState(false);
    const [addError, setAddError] = useState('');
    const [importOpen, setImportOpen] = useState(false);
    const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
    const [confirmError, setConfirmError] = useState('');

    // Busy is reported to the page synchronously, so its navigation guard and the context refresh
    // after a write see the settled value rather than the one from before the last render.
    const busyRef = useRef<string | null>(null);
    const importingRef = useRef(false);
    const onBusyChangeRef = useRef(onBusyChange);
    onBusyChangeRef.current = onBusyChange;
    const onAccessChangedRef = useRef(onAccessChanged);
    onAccessChangedRef.current = onAccessChanged;
    const setBusy = useCallback((key: string | null) => {
        busyRef.current = key;
        setBusyKey(key);
        onBusyChangeRef.current(key !== null || importingRef.current);
    }, []);
    const setImportRunning = useCallback((running: boolean) => {
        importingRef.current = running;
        setImporting(running);
        onBusyChangeRef.current(running || busyRef.current !== null);
    }, []);
    useEffect(() => () => onBusyChangeRef.current(false), []);

    const reloadList = useCallback(() => setListToken((value) => value + 1), []);
    const reloadRequests = useCallback(() => setRequestsToken((value) => value + 1), []);
    // After a write the request list is read again only once the member list has been, and under
    // the hint that read carried, so a write that ended the caller's management (a transfer, a
    // self-demotion) never sends a request list read the server would refuse.
    const requestsAfterList = useRef(false);
    const reloadAll = useCallback(() => {
        requestsAfterList.current = true;
        reloadList();
    }, [reloadList]);

    useEffect(() => { setSearchInput(urlSearch); }, [urlSearch]);

    // A debounced commit of the typed term; a new term starts again at the first page. A term
    // over the server's limit is never sent. Nothing is committed while a write runs, because a
    // URL change then would meet the page's save guard.
    useEffect(() => {
        const handle = window.setTimeout(() => {
            const trimmed = searchInput.trim();
            if (codePointLength(trimmed) > MEMBER_SEARCH_MAX_LENGTH) {
                setSearchError(`Search terms can be at most ${MEMBER_SEARCH_MAX_LENGTH} characters.`);
                return;
            }
            setSearchError('');
            if (trimmed === urlSearch || busyRef.current !== null || importingRef.current) return;
            const next = new URLSearchParams(searchParams);
            if (trimmed) next.set('search', trimmed); else next.delete('search');
            next.delete('page');
            setSearchParams(next, { replace: true });
        }, 300);
        return () => window.clearTimeout(handle);
    }, [searchInput, urlSearch, searchParams, setSearchParams, busyKey, importing]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        void client.list({ search: urlSearch, role: urlRole, page, pageSize: MEMBERS_PAGE_SIZE }, controller.signal)
            .then((next) => {
                if (controller.signal.aborted) return;
                setList(next);
                // A selection only ever names rows on the page that can still be acted on.
                setSelection((current) => current.filter((id) => next.members.some(
                    (member) => member.userId === id && isSelectable(member, viewerId),
                )));
                if (requestsAfterList.current) {
                    requestsAfterList.current = false;
                    reloadRequests();
                }
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setList(null);
                setSelection([]);
                setLoadError(membershipErrorMessage(cause, 'The member list could not be loaded. Please retry.'));
                if (isAccessChangedError(cause)) onAccessChangedRef.current();
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [client, urlSearch, urlRole, page, listToken, viewerId, reloadRequests]);

    const operations = list?.operations ?? [];
    const canAdd = operations.includes('add_member');
    const canReview = operations.includes('review_requests');

    useEffect(() => {
        if (!canReview) {
            setRequests(null);
            setRequestsError('');
            return undefined;
        }
        const controller = new AbortController();
        setRequestsLoading(true);
        setRequestsError('');
        void client.requests(controller.signal)
            .then((next) => { if (!controller.signal.aborted) setRequests(next); })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setRequests(null);
                setRequestsError(membershipErrorMessage(cause, 'The requests to join could not be loaded. Please retry.'));
                if (isAccessChangedError(cause)) onAccessChangedRef.current();
            })
            .finally(() => { if (!controller.signal.aborted) setRequestsLoading(false); });
        return () => controller.abort();
    }, [client, canReview, requestsToken]);

    const updateParams = useCallback((change: (params: URLSearchParams) => void) => {
        const next = new URLSearchParams(searchParams);
        change(next);
        setSearchParams(next);
    }, [searchParams, setSearchParams]);

    /** Show a refusal and bring the page back to the server's truth, as the refusal requires. */
    const refuse = useCallback((error: unknown, fallback: string) => {
        setNotice({ tone: 'alert', text: membershipErrorMessage(error, fallback) });
        const code = membershipErrorCode(error);
        // A conflict changed nothing: the state is kept, so the same action can simply be retried.
        if (code === 'group_write_conflict') return;
        if (code !== null || error instanceof MembershipResponseError) reloadAll();
        if (isAccessChangedError(error)) onAccessChangedRef.current();
    }, [reloadAll]);

    async function attempt<T>(key: string, action: () => Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> {
        setBusy(key);
        setNotice(null);
        try {
            return { ok: true, value: await action() };
        } catch (error) {
            return { ok: false, error };
        } finally {
            setBusy(null);
        }
    }

    const changeRole = async (member: GroupMember, role: AssignableMemberRole) => {
        const self = member.userId === viewerId;
        setPendingRoles((current) => ({ ...current, [member.userId]: role }));
        const result = await attempt(`role:${member.userId}`, () => client.changeRole(member.userId, role));
        setPendingRoles((current) => {
            const next = { ...current };
            delete next[member.userId];
            return next;
        });
        if (!result.ok) {
            refuse(result.error, 'The role could not be changed. Please retry.');
            return false;
        }
        // A role it already had is a quiet no-op; there is nothing to report or reload.
        if (!result.value.changed) return true;
        const name = memberDisplayName(result.value.member);
        setNotice({
            tone: 'status',
            text: self ? `Your role is now ${groupRoleLabel(result.value.member.role)}.`
                : `${name}'s role is now ${groupRoleLabel(result.value.member.role)}.`,
        });
        reloadList();
        if (self) onAccessChangedRef.current();
        return true;
    };

    const requestRoleChange = (member: GroupMember, role: AssignableMemberRole) => {
        // Demoting yourself from Admin takes away member management, so it is confirmed first.
        if (member.userId === viewerId && member.role === 'Admin' && role !== 'Admin') {
            setConfirmError('');
            setConfirmation({ kind: 'demote', member, role });
            return;
        }
        void changeRole(member, role);
    };

    /** A confirmed single write: a conflict keeps the dialog for a retry, anything else closes it. */
    const confirmedRefusal = (error: unknown, fallback: string) => {
        if (membershipErrorCode(error) === 'group_write_conflict') {
            setConfirmError(membershipErrorMessage(error, fallback));
            return;
        }
        setConfirmation(null);
        refuse(error, fallback);
    };

    const removeMember = async (member: GroupMember) => {
        const result = await attempt(`remove:${member.userId}`, () => client.remove(member.userId));
        if (!result.ok) {
            confirmedRefusal(result.error, 'The member could not be removed. Please retry.');
            return;
        }
        setConfirmation(null);
        setNotice({ tone: 'status', text: `${memberDisplayName(member)} was removed from the group.` });
        reloadAll();
    };

    const leaveGroup = async (member: GroupMember) => {
        const result = await attempt('leave', () => client.remove(member.userId));
        if (!result.ok) {
            confirmedRefusal(result.error, 'You could not leave the group. Please retry.');
            return;
        }
        setConfirmation(null);
        await onLeft();
    };

    const transferOwnership = async (member: GroupMember) => {
        const result = await attempt('transfer', () => client.transfer(member.userId));
        if (!result.ok) {
            confirmedRefusal(result.error, 'Ownership could not be transferred. Please retry.');
            return;
        }
        setConfirmation(null);
        // A transfer to the current owner is a quiet success; either way the hints are re-read.
        if (result.value.changed) {
            setNotice({ tone: 'status', text: `${memberDisplayName(result.value.owner)} is now the owner. You're now a ${groupRoleLabel('User')}.` });
        }
        reloadAll();
        onAccessChangedRef.current();
    };

    const confirmDemotion = async (member: GroupMember, role: AssignableMemberRole) => {
        setConfirmation(null);
        await changeRole(member, role);
    };

    const approveRequest = async (request: JoinRequest) => {
        const name = memberDisplayName(request);
        const result = await attempt(`approve:${request.userId}`, () => client.approve(request.userId));
        if (result.ok) {
            setNotice({
                tone: 'status',
                text: result.value.alreadyMember ? `${name} was already a member. Their request to join was cleared.`
                    : `${name} was added to the group.`,
            });
            reloadAll();
            return;
        }
        // Someone else settled it, or an earlier approve committed and only its answer was lost.
        if (membershipErrorCode(result.error) === 'no_pending_request') {
            setNotice({ tone: 'status', text: `${name}'s request was already handled.` });
            reloadAll();
            return;
        }
        refuse(result.error, 'The request could not be approved. Please retry.');
    };

    const rejectRequest = async (request: JoinRequest) => {
        const name = memberDisplayName(request);
        const result = await attempt(`reject:${request.userId}`, () => client.reject(request.userId));
        if (result.ok) {
            setNotice({ tone: 'status', text: `${name}'s request to join was rejected.` });
            reloadRequests();
            return;
        }
        if (membershipErrorCode(result.error) === 'no_pending_request') {
            setNotice({ tone: 'status', text: `${name}'s request was already handled.` });
            reloadAll();
            return;
        }
        refuse(result.error, 'The request could not be rejected. Please retry.');
    };

    const addMember = async (user: DirectoryUser, role: AssignableMemberRole) => {
        setAddError('');
        const result = await attempt('add', () => client.add({
            userId: user.id,
            displayName: fallbackMemberText(user.displayName),
            email: fallbackMemberText(user.email),
            role,
        }));
        if (result.ok) {
            setAddOpen(false);
            setNotice({ tone: 'status', text: `${memberDisplayName(result.value)} was added as ${groupRoleLabel(result.value.role)}.` });
            reloadAll();
            return;
        }
        const code = membershipErrorCode(result.error);
        const message = membershipErrorMessage(result.error, 'The member could not be added. Please retry.');
        // No one can be added here any more: close the dialog and bring the page up to date.
        if (code === 'group_status_unavailable' || isAccessChangedError(result.error)) {
            setAddOpen(false);
            refuse(result.error, message);
            return;
        }
        setAddError(message);
        if (code === 'already_member' || result.error instanceof MembershipResponseError) reloadList();
    };

    const addCsvRow = async (row: MemberCsvRow): Promise<ImportRowOutcome> => {
        try {
            const member = await client.add({ userId: row.userId, displayName: row.displayName, email: row.email, role: row.role });
            return { status: 'added', name: memberDisplayName(member) };
        } catch (error) {
            if (membershipErrorCode(error) === 'already_member') {
                return { status: 'already_member', message: membershipErrorMessage(error, 'Already a member.') };
            }
            if (isAccessChangedError(error)) onAccessChangedRef.current();
            return {
                status: 'failed',
                message: membershipErrorMessage(error, 'The member could not be added.'),
                stop: isTerminalMembershipError(error),
            };
        }
    };

    const members = list?.members ?? [];
    const selectedMembers = members.filter((member) => selection.includes(member.userId));
    const selectable = members.filter((member) => isSelectable(member, viewerId));
    const allSelected = selectable.length > 0 && selectable.every((member) => selection.includes(member.userId));
    const bulkRoleTargets = selectedMembers.filter((member) => member.actions.includes('change_role'));
    const bulkRemoveTargets = selectedMembers.filter((member) => member.actions.includes('remove'));
    const writesDisabled = interactionDisabled || busyKey !== null || importing || loading;

    const runBulk = async (kind: 'role' | 'remove', targets: GroupMember[], role: AssignableMemberRole) => {
        if (!targets.length) return;
        setConfirmation(null);
        setBusy('bulk');
        setNotice(null);
        setBulkReport(null);
        const failures: { member: GroupMember; message: string }[] = [];
        let changed = 0;
        let unchanged = 0;
        let stopped = false;
        let accessChanged = false;
        for (const member of targets) {
            if (stopped) {
                failures.push({ member, message: NOT_ATTEMPTED });
                continue;
            }
            try {
                if (kind === 'role') {
                    const result = await client.changeRole(member.userId, role);
                    if (result.changed) changed += 1; else unchanged += 1;
                } else {
                    await client.remove(member.userId);
                    changed += 1;
                }
            } catch (error) {
                failures.push({ member, message: membershipErrorMessage(error, 'The change could not be completed.') });
                stopped = isTerminalMembershipError(error);
                accessChanged = accessChanged || isAccessChangedError(error);
            }
        }
        setBusy(null);
        const summary = kind === 'role'
            ? [
                `Changed ${plural(changed, 'member', 'members')} to ${groupRoleLabel(role)}.`,
                unchanged ? `${plural(unchanged, 'member', 'members')} already had that role.` : '',
                failures.length ? `${failures.length} failed.` : '',
            ].filter(Boolean).join(' ')
            : [
                `Removed ${plural(changed, 'member', 'members')}.`,
                failures.length ? `${failures.length} failed.` : '',
            ].filter(Boolean).join(' ');
        setBulkReport({
            summary,
            failures: failures.map(({ member, message }) => ({ name: memberDisplayName(member), message })),
        });
        // The failed rows stay selected, so they can be tried again.
        setSelection(failures.map(({ member }) => member.userId));
        reloadAll();
        if (accessChanged) onAccessChangedRef.current();
    };

    const toggleAll = () => {
        setSelection(allSelected ? [] : selectable.map((member) => member.userId));
    };

    const totalCount = list?.totalCount ?? 0;
    const totalPages = Math.max(1, Math.ceil(totalCount / MEMBERS_PAGE_SIZE));
    const pastTheEnd = Boolean(list && list.members.length === 0 && totalCount > 0 && page > 1);

    const confirmationDialog = (() => {
        if (!confirmation) return null;
        const busy = busyKey !== null;
        const close = () => { if (!busy) { setConfirmation(null); setConfirmError(''); } };
        const errorLine = confirmError ? <p role="alert" className="text-sm text-danger">{confirmError}</p> : null;
        if (confirmation.kind === 'remove') {
            const name = memberDisplayName(confirmation.member);
            return (
                <ConfirmDialog title={`Remove ${name}?`} confirmLabel="Remove member" confirmIcon={<UserMinus size={14} />}
                    description={`${name} will lose access to ${groupName} and everything shared in it.`}
                    busy={busy} onClose={close} onConfirm={() => void removeMember(confirmation.member)}>
                    <div className="space-y-2">
                        <p className="text-xs text-text-2">You can add them again later.</p>
                        {errorLine}
                    </div>
                </ConfirmDialog>
            );
        }
        if (confirmation.kind === 'leave') {
            return (
                <ConfirmDialog title={`Leave ${groupName}?`} confirmLabel="Leave group" confirmIcon={<LogOut size={14} />}
                    description="You'll lose access to this group and everything shared in it."
                    busy={busy} onClose={close} onConfirm={() => void leaveGroup(confirmation.member)}>
                    <div className="space-y-2">
                        <p className="text-xs text-text-2">To come back, ask an owner or admin, or request to join from the group directory.</p>
                        {errorLine}
                    </div>
                </ConfirmDialog>
            );
        }
        if (confirmation.kind === 'transfer') {
            const name = memberDisplayName(confirmation.member);
            return (
                <ConfirmDialog title={`Make ${name} the owner?`} confirmLabel="Transfer ownership" confirmIcon={<Crown size={14} />}
                    tone="primary" description="Ownership moves to one person, and it can't be undone from your side."
                    busy={busy} onClose={close} onConfirm={() => void transferOwnership(confirmation.member)}>
                    <div className="space-y-2">
                        <ul className="list-disc space-y-1 pl-5 text-xs text-text-2">
                            <li className="break-words">{name} becomes the owner of {groupName}.</li>
                            <li>You become a {groupRoleLabel('User')}. You lose the owner's abilities, including managing members and transferring ownership, unless the new owner gives you a role.</li>
                            <li>Only the new owner can transfer ownership back.</li>
                        </ul>
                        {errorLine}
                    </div>
                </ConfirmDialog>
            );
        }
        if (confirmation.kind === 'demote') {
            const label = groupRoleLabel(confirmation.role);
            return (
                <ConfirmDialog title="Change your own role?" confirmLabel="Change my role"
                    description={`You're changing your role to ${label}.`}
                    busy={busy} onClose={close} onConfirm={() => void confirmDemotion(confirmation.member, confirmation.role)}>
                    <p className="text-xs text-text-2">You'll no longer be able to manage this group's members. Only the owner or another admin can make you an admin again.</p>
                </ConfirmDialog>
            );
        }
        const targets = confirmation.members;
        return (
            <ConfirmDialog title={`Remove ${plural(targets.length, 'member', 'members')}?`}
                confirmLabel={`Remove ${plural(targets.length, 'member', 'members')}`} confirmIcon={<UserMinus size={14} />}
                description={`They'll lose access to ${groupName} and everything shared in it.`}
                busy={busy} onClose={close} onConfirm={() => void runBulk('remove', targets, bulkRole)}>
                <ul className="list-disc space-y-0.5 pl-5 text-xs text-text-2">
                    {targets.slice(0, MAX_LISTED).map((member) => <li key={member.userId} className="break-words">{memberDisplayName(member)}</li>)}
                    {targets.length > MAX_LISTED ? <li>... and {targets.length - MAX_LISTED} more</li> : null}
                </ul>
            </ConfirmDialog>
        );
    })();

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <SectionIntro title="Members"
                    description={`Everyone in ${groupName}, and what each person can do here. The owner and admins manage membership; anyone else can leave.`} />
                {canAdd ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <GlassButton size="sm" disabled={writesDisabled} onClick={() => setImportOpen(true)}>
                            <FileUp size={14} />Import CSV
                        </GlassButton>
                        <GlassButton size="sm" variant="primary" disabled={writesDisabled}
                            onClick={() => { setAddError(''); setAddOpen(true); }}>
                            <UserPlus size={14} />Add member
                        </GlassButton>
                    </div>
                ) : null}
            </div>

            {notice ? (
                notice.tone === 'alert' ? (
                    <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm break-words text-danger">{notice.text}</div>
                ) : (
                    <p role="status" className="rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm break-words text-text-2">{notice.text}</p>
                )
            ) : null}

            {canReview ? (
                <JoinRequestsPanel requests={requests} loading={requestsLoading} error={requestsError} busyKey={busyKey}
                    disabled={writesDisabled} onRetry={reloadRequests}
                    onApprove={(request) => void approveRequest(request)} onReject={(request) => void rejectRequest(request)} />
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-0 flex-1 basis-56">
                    <SectionSearch value={searchInput} onChange={setSearchInput} placeholder="Search members by name or email" />
                </div>
                <select className={clsx(SELECT_CLASS, 'py-2')} aria-label="Filter by role" value={urlRole ?? ''}
                    disabled={busyKey !== null || importing}
                    onChange={(event) => updateParams((params) => {
                        if (isGroupMemberRole(event.target.value)) params.set('role', event.target.value); else params.delete('role');
                        params.delete('page');
                    })}>
                    <option value="">All roles</option>
                    {GROUP_MEMBER_ROLES.map((role) => <option key={role} value={role}>{groupRoleLabel(role)}</option>)}
                </select>
            </div>
            {searchError ? <p role="alert" className="text-xs text-danger">{searchError}</p> : null}

            {selectedMembers.length ? (
                <GlassPanel elevation="flat" role="region" aria-label="Selected members" className="flex flex-wrap items-center gap-2 p-3">
                    <span className="text-sm font-medium text-text-1">{selectedMembers.length} selected</span>
                    {bulkRoleTargets.length ? (
                        <>
                            <select className={SELECT_CLASS} aria-label="New role for the selected members" value={bulkRole}
                                disabled={writesDisabled} onChange={(event) => {
                                    if (isAssignableMemberRole(event.target.value)) setBulkRole(event.target.value);
                                }}>
                                {ASSIGNABLE_ROLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                            </select>
                            <GlassButton size="sm" variant="subtle" disabled={writesDisabled}
                                onClick={() => void runBulk('role', bulkRoleTargets, bulkRole)}>Change role</GlassButton>
                        </>
                    ) : null}
                    {bulkRemoveTargets.length ? (
                        <GlassButton size="sm" variant="ghost" disabled={writesDisabled}
                            onClick={() => { setConfirmError(''); setConfirmation({ kind: 'bulk-remove', members: bulkRemoveTargets }); }}>
                            <UserMinus size={14} />Remove selected
                        </GlassButton>
                    ) : null}
                    <GlassButton size="sm" variant="ghost" disabled={busyKey !== null} onClick={() => setSelection([])}>Clear selection</GlassButton>
                </GlassPanel>
            ) : null}

            {bulkReport ? (
                <div role="status" aria-label="Bulk results" className="space-y-1 rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-2">
                    <p className="text-text-1">{bulkReport.summary}</p>
                    {bulkReport.failures.length ? (
                        <ul className="list-disc space-y-0.5 pl-5 text-xs text-danger">
                            {bulkReport.failures.slice(0, MAX_LISTED).map((failure) => (
                                <li key={`${failure.name}:${failure.message}`} className="break-words">{failure.name}: {failure.message}</li>
                            ))}
                            {bulkReport.failures.length > MAX_LISTED ? <li>... and {bulkReport.failures.length - MAX_LISTED} more</li> : null}
                        </ul>
                    ) : null}
                </div>
            ) : null}

            {!list && loading ? (
                <div role="status" className="space-y-2">
                    <p className="flex items-center gap-2 text-sm text-text-2"><Loader2 size={16} className="animate-spin" />Loading members...</p>
                    <Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" />
                </div>
            ) : !list ? (
                <div role="alert" className="space-y-2 rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
                    <p>{loadError || 'The member list could not be loaded. Please retry.'}</p>
                    <GlassButton size="sm" disabled={loading} onClick={reloadList}>Retry members</GlassButton>
                </div>
            ) : pastTheEnd ? (
                <EmptyState icon={<Users size={28} />} title="No members on this page"
                    description="This page is past the end of the list."
                    action={<GlassButton size="sm" onClick={() => updateParams((params) => params.delete('page'))}>Go to the first page</GlassButton>} />
            ) : members.length === 0 ? (
                <EmptyState icon={<Users size={28} />} title="No members to show"
                    description={urlSearch || urlRole ? 'No members match your search.' : 'This group has no members yet.'} />
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                        {selectable.length ? (
                            <label className="flex items-center gap-2">
                                <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={allSelected}
                                    disabled={writesDisabled} aria-label="Select all members on this page" onChange={toggleAll} />
                                Select all on this page
                            </label>
                        ) : <span />}
                        <span>Showing {members.length} of {plural(totalCount, 'member', 'members')}{loading ? ' · Refreshing...' : ''}</span>
                    </div>
                    <ul aria-label="Members" className="space-y-2">
                        {members.map((member) => {
                            const isSelf = member.userId === viewerId;
                            return (
                                <li key={member.userId}>
                                    <MemberRow member={member} isSelf={isSelf}
                                        selectable={isSelectable(member, viewerId)} selected={selection.includes(member.userId)}
                                        pendingRole={pendingRoles[member.userId]} disabled={writesDisabled}
                                        busy={busyKey === `role:${member.userId}` || busyKey === `remove:${member.userId}`}
                                        onSelect={(checked) => setSelection((current) => (checked
                                            ? [...current.filter((id) => id !== member.userId), member.userId]
                                            : current.filter((id) => id !== member.userId)))}
                                        onRoleChange={(role) => requestRoleChange(member, role)}
                                        onRemove={() => { setConfirmError(''); setConfirmation({ kind: 'remove', member }); }}
                                        onLeave={() => { setConfirmError(''); setConfirmation({ kind: 'leave', member }); }}
                                        onTransfer={() => { setConfirmError(''); setConfirmation({ kind: 'transfer', member }); }} />
                                </li>
                            );
                        })}
                    </ul>
                </>
            )}

            {list && (totalCount > MEMBERS_PAGE_SIZE || page > 1) ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                    <span>Page {page} of {totalPages}</span>
                    <div className="flex gap-2">
                        <GlassButton size="sm" disabled={loading || busyKey !== null || importing || page <= 1}
                            onClick={() => updateParams((params) => {
                                if (page - 1 <= 1) params.delete('page'); else params.set('page', String(page - 1));
                            })}>Previous page</GlassButton>
                        <GlassButton size="sm" disabled={loading || busyKey !== null || importing || page * MEMBERS_PAGE_SIZE >= totalCount}
                            onClick={() => updateParams((params) => params.set('page', String(page + 1)))}>Next page</GlassButton>
                    </div>
                </div>
            ) : null}

            {addOpen ? (
                <AddMemberDialog submitting={busyKey === 'add'} serverError={addError}
                    onSubmit={(user, role) => void addMember(user, role)}
                    onClose={() => { setAddOpen(false); setAddError(''); }} />
            ) : null}
            {importOpen ? (
                <ImportMembersDialog onAddRow={addCsvRow} onRunningChange={setImportRunning} onFinished={reloadAll}
                    onClose={() => setImportOpen(false)} />
            ) : null}
            {confirmationDialog}
        </div>
    );
}
