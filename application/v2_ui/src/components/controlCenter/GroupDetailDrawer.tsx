// GroupDetailDrawer.tsx
// Group administration reuses classic governed actions and native membership permissions.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../../lib/apiClient';
import { ASSIGNABLE_MEMBER_ROLES, ASSIGNABLE_ROLE_OPTIONS, type AssignableMemberRole, type DirectoryUser, type MemberCsvRow } from '../../lib/groupMembership';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { AddMemberDialog } from '../membership/AddMemberDialog';
import { ImportMembersDialog, type ImportRowOutcome } from '../membership/ImportMembersDialog';
import { ApprovalSubmittedNotice, DetailDrawer, KpiCard, ReasonConfirmDialog, StatusBadge } from './ControlCenterPrimitives';
import { EntityActivity, EntityDetailTabs, entityDate, type EntityActivityItem } from './EntityDetailSections';

export interface GroupRow {
    id: string;
    name: string;
    description: string;
    owner: { id: string | null; email: string; display_name: string };
    status: string;
    members: number;
    documents: number;
    tokens: number;
    created_at: string | null;
    last_activity: string | null;
    metrics_calculated_at: string | null;
}

interface GroupMember {
    id: string;
    display_name: string;
    email: string;
    role: 'Owner' | AssignableMemberRole;
}

interface GroupDetail {
    group: GroupRow;
    members: GroupMember[];
    status_history: { old_status: string; new_status: string; changed_by_email: string; changed_at: string; reason: string | null }[];
    retention: {
        enabled: boolean;
        can_edit: boolean;
        conversation_retention_days: string | number;
        document_retention_days: string | number;
    };
    permissions: { can_edit_members: boolean; current_role: string | null };
    documents_summary: {
        count: number;
        cached_metrics: Record<string, number>;
        metrics_calculated_at: string | null;
    };
    tokens: number;
    activity: EntityActivityItem[];
    metrics_calculated_at: string;
}

const TABS = ['overview', 'members', 'ownership', 'status', 'retention', 'activity', 'documents'] as const;
const STATUSES = ['active', 'locked', 'upload_disabled', 'inactive'] as const;
export const GROUP_INPUT = 'rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';
type Action = { kind: 'status'; status: string } | { kind: 'remove'; member: GroupMember }
    | { kind: 'delete-group' | 'delete-documents' | 'take-ownership' }
    | { kind: 'transfer-ownership'; memberId: string };

function roleForAdminApi(role: AssignableMemberRole) {
    return role === 'DocumentManager' ? 'document_manager' : role.toLowerCase();
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : 'The request could not be completed.';
}

export function GroupDetailDrawer({ id, onClose, onChanged }: {
    id: string; onClose: () => void; onChanged: () => void;
}) {
    const [detail, setDetail] = useState<GroupDetail | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [tab, setTab] = useState<typeof TABS[number]>('overview');
    const [revision, setRevision] = useState(0);
    const [busy, setBusy] = useState(false);
    const [action, setAction] = useState<Action | null>(null);
    const [approval, setApproval] = useState<string | null>(null);
    const [newOwner, setNewOwner] = useState('');
    const [status, setStatus] = useState('active');
    const [conversationDays, setConversationDays] = useState('default');
    const [documentDays, setDocumentDays] = useState('default');
    const [addOpen, setAddOpen] = useState(false);
    const [importOpen, setImportOpen] = useState(false);
    const [addError, setAddError] = useState('');
    const adminBase = `/api/admin/control-center/groups/${encodeURIComponent(id)}`;
    const nativeBase = `/api/groups/${encodeURIComponent(id)}/members`;

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        api.get<GroupDetail>(`/api/v2/control-center/groups/${encodeURIComponent(id)}`, controller.signal)
            .then((data) => {
                if (controller.signal.aborted) return;
                setDetail(data);
                setStatus(data.group.status);
                setConversationDays(String(data.retention.conversation_retention_days));
                setDocumentDays(String(data.retention.document_retention_days));
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) {
                    setDetail(null);
                    setError(errorMessage(cause));
                }
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [id, revision]);

    const changed = () => { onChanged(); setRevision((value) => value + 1); };
    const confirmAction = async (reason: string) => {
        if (!action || busy) return;
        const target = action;
        setAction(null);
        setBusy(true);
        setError('');
        try {
            if (target.kind === 'status') {
                await api.put(`/api/v2/control-center/groups/${encodeURIComponent(id)}/status`, { status: target.status, reason });
                toast.success('Group status saved.');
                changed();
            } else if (target.kind === 'remove') {
                await api.delete(`${nativeBase}/${encodeURIComponent(target.member.id)}`);
                toast.success('Member removed.');
                changed();
            } else {
                const path = target.kind === 'delete-group' ? adminBase : `${adminBase}/${target.kind}`;
                const payload = target.kind === 'transfer-ownership' ? { reason, newOwnerId: target.memberId } : { reason };
                const result = target.kind === 'delete-group'
                    ? await api.delete<{ approval_id: string }>(path, payload)
                    : await api.post<{ approval_id: string }>(path, payload);
                setApproval(result.approval_id);
            }
        } catch (cause) {
            setError(errorMessage(cause));
        } finally {
            setBusy(false);
        }
    };

    const addMember = async (user: DirectoryUser, role: AssignableMemberRole, source = 'single') => {
        return api.post<{ skipped: boolean }>(`${adminBase}/add-member`, {
            userId: user.id, displayName: user.displayName, email: user.email,
            role: roleForAdminApi(role), source,
        });
    };
    const addSingle = async (user: DirectoryUser, role: AssignableMemberRole) => {
        setBusy(true);
        setAddError('');
        try {
            const result = await addMember(user, role);
            toast.success(result.skipped ? 'This person is already a member.' : 'Member added.');
            setAddOpen(false);
            changed();
        } catch (cause) {
            setAddError(errorMessage(cause));
        } finally { setBusy(false); }
    };
    const addCsvRow = async (row: MemberCsvRow): Promise<ImportRowOutcome> => {
        try {
            const result = await addMember({ id: row.userId, displayName: row.displayName, email: row.email }, row.role, 'csv');
            return result.skipped ? { status: 'already_member', message: 'Already a member' } : { status: 'added', name: row.displayName };
        } catch (cause) {
            return { status: 'failed', message: errorMessage(cause),
                stop: cause instanceof ApiError && [401, 403, 404].includes(cause.status) };
        }
    };
    const changeRole = async (memberId: string, role: string) => {
        setBusy(true);
        setError('');
        try {
            await api.patch(`${nativeBase}/${encodeURIComponent(memberId)}`, { role });
            toast.success('Member role saved.');
            changed();
        } catch (cause) { setError(errorMessage(cause)); }
        finally { setBusy(false); }
    };
    const saveRetention = async () => {
        setBusy(true);
        setError('');
        try {
            await api.post(`/api/retention-policy/group/${encodeURIComponent(id)}`, {
                conversation_retention_days: conversationDays, document_retention_days: documentDays,
            });
            toast.success('Retention policy saved.');
            changed();
        } catch (cause) { setError(errorMessage(cause)); }
        finally { setBusy(false); }
    };
    const ownerLink = detail?.group.owner.id
        ? <Link className="text-accent underline" to={`/control-center/users?user_id=${encodeURIComponent(detail.group.owner.id)}`}>
            {detail.group.owner.display_name || detail.group.owner.email || detail.group.owner.id}
        </Link> : 'No owner recorded';

    return <DetailDrawer title={detail?.group.name || 'Group details'} onClose={() => { if (!busy) onClose(); }}>
        <div className="space-y-4">
            {loading ? <p role="status" className="text-sm text-text-3">Loading group details...</p> : null}
            {error ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
            {approval ? <ApprovalSubmittedNotice>Request {approval} submitted for approval. No group or documents have been deleted, and ownership has not changed.</ApprovalSubmittedNotice> : null}
            {detail && !loading ? <>
                <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={detail.group.status} />
                    <span className="break-all text-xs text-text-3">Group ID: {id}</span>
                </div>
                <Link className="inline-block text-sm text-accent underline"
                    to={`/control-center/activity-logs?workspace_type=group&workspace_id=${encodeURIComponent(id)}&group_id=${encodeURIComponent(id)}`}>
                    View in Activity Logs
                </Link>
                <EntityDetailTabs tabs={TABS} selected={tab} onSelect={setTab}>
                    {tab === 'overview' ? <>
                        <p className="break-words text-sm text-text-2">{detail.group.description || 'No description recorded.'}</p>
                        <dl className="space-y-2 text-sm text-text-2">
                            <div><dt className="text-xs text-text-3">Owner</dt><dd>{ownerLink}</dd></div>
                            <div><dt className="text-xs text-text-3">Created</dt><dd>{entityDate(detail.group.created_at)}</dd></div>
                            <div><dt className="text-xs text-text-3">Last activity</dt><dd>{entityDate(detail.group.last_activity)}</dd></div>
                        </dl>
                        <div className="grid grid-cols-2 gap-3">
                            <KpiCard label="Members" value={detail.group.members.toLocaleString()} />
                            <KpiCard label="Documents" value={detail.documents_summary.count.toLocaleString()} />
                            <KpiCard label="All-time tokens" value={detail.tokens.toLocaleString()} />
                        </div>
                        <p className="text-xs text-text-3">Totals calculated: {entityDate(detail.metrics_calculated_at)}</p>
                        <GlassButton variant="danger" disabled={busy} onClick={() => setAction({ kind: 'delete-group' })}>Request group deletion</GlassButton>
                    </> : null}
                    {tab === 'members' ? <>
                        <div className="flex flex-wrap gap-2">
                            <GlassButton disabled={busy} onClick={() => { setAddError(''); setAddOpen(true); }}>Add member</GlassButton>
                            <GlassButton disabled={busy} onClick={() => setImportOpen(true)}>Import CSV</GlassButton>
                        </div>
                        {!detail.permissions.can_edit_members ? <p className="text-xs text-text-3">Removing members and changing roles require group Owner or Admin membership. Use Ownership to request a change.</p> : null}
                        <ul className="space-y-3">
                            {detail.members.map((member) => <li key={member.id} className="space-y-2 border-b border-edge pb-3">
                                <Link className="break-words text-sm text-accent underline" to={`/control-center/users?user_id=${encodeURIComponent(member.id)}`}>
                                    {member.display_name || member.email || member.id}
                                </Link>
                                <p className="break-all text-xs text-text-3">{member.email}</p>
                                <div className="flex flex-wrap items-center gap-2">
                                    <StatusBadge status={member.role} />
                                    {member.role !== 'Owner' && detail.permissions.can_edit_members ? <>
                                        <select aria-label={`Role for ${member.display_name || member.id}`} className={GROUP_INPUT}
                                            value={member.role} disabled={busy} onChange={(event) => void changeRole(member.id, event.target.value)}>
                                            {ASSIGNABLE_ROLE_OPTIONS.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
                                        </select>
                                        <GlassButton size="sm" variant="danger" disabled={busy} onClick={() => setAction({ kind: 'remove', member })}>Remove member</GlassButton>
                                    </> : null}
                                </div>
                            </li>)}
                        </ul>
                    </> : null}
                    {tab === 'ownership' ? <>
                        <p className="text-sm text-text-2">Current owner: {ownerLink}</p>
                        <p className="text-sm text-text-3">Ownership changes require approval from the owner or another administrator.</p>
                        <GlassButton disabled={busy} onClick={() => setAction({ kind: 'take-ownership' })}>Request to take ownership</GlassButton>
                        <label className="grid gap-1 text-xs text-text-3">Transfer to a member
                            <select aria-label="Transfer to a member" className={GROUP_INPUT} value={newOwner} onChange={(event) => setNewOwner(event.target.value)}>
                                <option value="">Choose a member</option>
                                {detail.members.filter((member) => member.role !== 'Owner').map((member) =>
                                    <option key={member.id} value={member.id}>{member.display_name || member.email || member.id}</option>)}
                            </select>
                        </label>
                        <GlassButton disabled={busy || !newOwner} onClick={() => setAction({ kind: 'transfer-ownership', memberId: newOwner })}>Request ownership transfer</GlassButton>
                    </> : null}
                    {tab === 'status' ? <>
                        <p className="text-sm text-text-3">Locked makes documents read-only while viewing and chat remain available; upload disabled blocks uploads; inactive makes the group unavailable. Locking and inactivation require a reason.</p>
                        <label className="grid gap-1 text-xs text-text-3">Group status
                            <select aria-label="Group status" className={GROUP_INPUT} value={status} onChange={(event) => setStatus(event.target.value)}>
                                {STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                            </select>
                        </label>
                        <GlassButton disabled={busy || status === detail.group.status} onClick={() => setAction({ kind: 'status', status })}>Change status</GlassButton>
                        <h3 className="text-sm font-medium text-text-1">Status history</h3>
                        {!detail.status_history.length ? <p className="text-sm text-text-3">No status changes recorded.</p> : null}
                        <ol className="space-y-3">{[...detail.status_history].reverse().map((entry, index) => <li key={`${entry.changed_at}-${index}`} className="text-sm text-text-2">
                            <p>{entry.old_status} to {entry.new_status}</p>
                            <p className="text-xs text-text-3">{entityDate(entry.changed_at)} by {entry.changed_by_email}</p>
                            {entry.reason ? <p className="break-words">{entry.reason}</p> : null}
                        </li>)}</ol>
                    </> : null}
                    {tab === 'retention' ? <>
                        <p className="text-sm text-text-3">Retention automatically deletes aged content. Enter default to inherit organization policy, none to keep content, or a whole number of days.</p>
                        {!detail.retention.enabled ? <p className="text-sm text-text-3">Group retention is not enabled.</p> : null}
                        {!detail.retention.can_edit ? <p className="text-xs text-text-3">Editing requires group Owner or Admin membership and enabled group retention.</p> : null}
                        <label className="grid gap-1 text-xs text-text-3">Conversation retention days
                            <input className={GROUP_INPUT} value={conversationDays} disabled={busy || !detail.retention.can_edit}
                                onChange={(event) => setConversationDays(event.target.value)} />
                        </label>
                        <label className="grid gap-1 text-xs text-text-3">Document retention days
                            <input className={GROUP_INPUT} value={documentDays} disabled={busy || !detail.retention.can_edit}
                                onChange={(event) => setDocumentDays(event.target.value)} />
                        </label>
                        <GlassButton disabled={busy || !detail.retention.can_edit || ![conversationDays, documentDays].every((value) => /^(default|none|[1-9]\d*)$/.test(value))}
                            onClick={() => void saveRetention()}>Save retention</GlassButton>
                    </> : null}
                    {tab === 'activity' ? <EntityActivity items={detail.activity} /> : null}
                    {tab === 'documents' ? <>
                        <p className="text-sm text-text-2">{detail.documents_summary.count.toLocaleString()} document metadata records in this group.</p>
                        <dl className="space-y-2 text-sm text-text-2">
                            {Object.entries(detail.documents_summary.cached_metrics).map(([key, value]) => <div key={key}>
                                <dt className="text-xs text-text-3">{key.replaceAll('_', ' ')}</dt><dd>{Number(value).toLocaleString()}</dd>
                            </div>)}
                        </dl>
                        <p className="text-xs text-text-3">Storage estimates refreshed: {entityDate(detail.documents_summary.metrics_calculated_at)}. These estimates can be older than the document count.</p>
                        <GlassButton variant="danger" disabled={busy} onClick={() => setAction({ kind: 'delete-documents' })}>Request deletion of all documents</GlassButton>
                    </> : null}
                </EntityDetailTabs>
            </> : null}
        </div>
        {action ? <ReasonConfirmDialog
            title={action.kind === 'status' ? `Change group status to ${action.status}?` : action.kind === 'remove'
                ? `Remove ${action.member.display_name || action.member.email}?` : `Submit ${action.kind.replaceAll('-', ' ')} request?`}
            description={action.kind === 'status' ? 'This applies immediately and records the transition in the group audit history.'
                : action.kind === 'remove' ? 'This removes membership immediately; it does not delete this person or their documents.'
                    : 'This creates an approval request only. The action does not run until it is approved.'}
            reasonRequired={action.kind !== 'status' && action.kind !== 'remove' || action.kind === 'status' && ['locked', 'inactive'].includes(action.status)}
            confirmLabel={action.kind === 'status' ? 'Apply status' : action.kind === 'remove' ? 'Remove member' : 'Submit approval request'}
            onClose={() => setAction(null)} onConfirm={(reason) => void confirmAction(reason)} /> : null}
        {addOpen ? <AddMemberDialog submitting={busy} serverError={addError} onClose={() => setAddOpen(false)}
            onSubmit={(user, role) => void addSingle(user, role)} /> : null}
        {importOpen ? <ImportMembersDialog roles={ASSIGNABLE_MEMBER_ROLES} onAddRow={addCsvRow}
            identityDescription="Control Center imports the IDs, names and emails in this file. Verify them before adding members."
            onRunningChange={setBusy} onFinished={changed} onClose={() => setImportOpen(false)} /> : null}
    </DetailDrawer>;
}
