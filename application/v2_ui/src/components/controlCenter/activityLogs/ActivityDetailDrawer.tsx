// ActivityDetailDrawer.tsx
// One record, read the way an investigation needs it: what happened, who did it, where, the
// recorded specifics, then the raw document. Previous and Next step through the page without
// closing the drawer.

import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Copy, Filter } from 'lucide-react';
import type { ReactNode } from 'react';
import {
    WORKSPACE_TYPE_LABELS, formatActivityTime, workspaceName,
    type ActivityPresentation, type ActivityRecord, type ActivityTimeZone, type ActivityWorkspaceRef,
} from '../../../lib/activityLogs';
import { toast } from '../../../stores/toastStore';
import { GlassButton } from '../../ui/primitives';
import { DetailDrawer, StatusBadge } from '../ControlCenterPrimitives';
import { categoryIcon } from './ActivityTable';

function text(record: ActivityRecord, ...path: string[]): string {
    let value: unknown = record;
    for (const part of path) {
        if (typeof value !== 'object' || value === null) return '';
        value = (value as Record<string, unknown>)[part];
    }
    return typeof value === 'string' ? value : '';
}

function DrawerSection({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
    return (
        <section className="space-y-2 border-t border-edge pt-4">
            <h3 className="text-sm font-semibold text-text-1">{title}</h3>
            {children}
            {actions ? <div className="flex flex-wrap gap-2 pt-1">{actions}</div> : null}
        </section>
    );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
    const shown = rows.filter(([, value]) => value !== '' && value !== null && value !== undefined);
    if (!shown.length) return <p className="text-sm text-text-3">Nothing further was recorded.</p>;
    return (
        <dl className="grid grid-cols-[minmax(7rem,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
            {shown.map(([label, value]) => (
                <div key={label} className="contents">
                    <dt className="text-text-3">{label}</dt>
                    <dd className="break-words text-text-1">{value}</dd>
                </div>
            ))}
        </dl>
    );
}

const LINK_CLASS = 'inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-sm font-medium text-accent hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent';

export function ActivityDetailDrawer({
    record, view, index, total, timeZone, onClose, onStep, onFilterPerson, onFilterWorkspace,
}: {
    record: ActivityRecord;
    view: ActivityPresentation;
    index: number;
    total: number;
    timeZone: ActivityTimeZone;
    onClose: () => void;
    onStep: (index: number) => void;
    onFilterPerson: (id: string) => void;
    onFilterWorkspace: (workspace: ActivityWorkspaceRef) => void;
}) {
    const Icon = categoryIcon(view.category);
    const time = formatActivityTime(record.timestamp, timeZone);
    const actor = view.actor;
    const workspace = view.workspace;
    const approval = text(record, 'approval_id') || text(record, 'approval', 'id');
    const approvalGroup = workspace.type === 'group' ? workspace.id : '';
    const json = JSON.stringify(record, null, 2);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(json);
            toast.success('Raw JSON copied.');
        } catch {
            toast.error('The browser blocked copying. Select the JSON and copy it instead.');
        }
    };

    return (
        <DetailDrawer title="Activity details" onClose={onClose}>
            <div className="space-y-5">
                <div className="flex items-center justify-between gap-3 text-xs text-text-3">
                    <span>Record {index + 1} of {total} on this page</span>
                    <div className="flex gap-1">
                        <GlassButton size="sm" disabled={index === 0} onClick={() => onStep(index - 1)} aria-label="Previous record">
                            <ChevronLeft size={14} aria-hidden="true" />Previous
                        </GlassButton>
                        <GlassButton size="sm" disabled={index >= total - 1} onClick={() => onStep(index + 1)} aria-label="Next record">
                            Next<ChevronRight size={14} aria-hidden="true" />
                        </GlassButton>
                    </div>
                </div>

                <div className="space-y-1">
                    <p className="flex items-center gap-2 text-sm text-text-2">
                        <Icon size={15} aria-hidden="true" className="text-text-3" />{view.label}
                        {view.status === 'failed' ? <StatusBadge status="Failed" /> : null}
                    </p>
                    <p className="break-words text-lg font-semibold text-text-1">{view.summary}</p>
                    {view.detail ? <p className="break-words text-sm text-text-2">{view.detail}</p> : null}
                    <p className="text-sm text-text-3">{time.primary}{time.secondary ? ` · ${time.secondary}` : ''}</p>
                </div>

                <DrawerSection title="Who" actions={actor.id ? <>
                    <GlassButton size="sm" variant="subtle" onClick={() => onFilterPerson(actor.id)}>
                        <Filter size={13} aria-hidden="true" />Show only this person's activity
                    </GlassButton>
                    <Link className={LINK_CLASS} to={`/control-center/users?user_id=${encodeURIComponent(actor.id)}`}>Open in Users</Link>
                </> : null}>
                    <Facts rows={[
                        ['Name', actor.kind === 'system' ? 'System' : actor.name || (actor.id ? 'Not found in SimpleChat users' : '')],
                        ['Email', actor.email],
                        ['User ID', actor.id ? <code className="text-xs">{actor.id}</code> : ''],
                    ]} />
                </DrawerSection>

                <DrawerSection title="Where" actions={workspace.id ? <>
                    <GlassButton size="sm" variant="subtle" onClick={() => onFilterWorkspace(workspace)}>
                        <Filter size={13} aria-hidden="true" />Show only this workspace
                    </GlassButton>
                    <Link className={LINK_CLASS}
                        to={workspace.type === 'group'
                            ? `/control-center/groups?id=${encodeURIComponent(workspace.id)}`
                            : `/control-center/public-workspaces?id=${encodeURIComponent(workspace.id)}`}>
                        {workspace.type === 'group' ? 'Open group' : 'Open workspace'}
                    </Link>
                </> : null}>
                    <Facts rows={[
                        ['Workspace', WORKSPACE_TYPE_LABELS[workspace.type] ?? (workspace.type || 'Not recorded')],
                        ['Name', workspace.id ? workspaceName(workspace) : ''],
                        ['ID', workspace.id ? <code className="text-xs">{workspace.id}</code> : ''],
                    ]} />
                </DrawerSection>

                <DrawerSection title="Details">
                    <Facts rows={view.facts.map((fact) => [fact.label, fact.value] as [string, ReactNode])} />
                </DrawerSection>

                <DrawerSection title="Record" actions={approval ? (
                    <Link className={LINK_CLASS}
                        to={`/approvals/all/${encodeURIComponent(approval)}${approvalGroup ? `?group_id=${encodeURIComponent(approvalGroup)}` : ''}`}>
                        View approval
                    </Link>
                ) : null}>
                    <Facts rows={[
                        ['Activity type', <code key="type" className="text-xs">{view.activity_type || 'Not recorded'}</code>],
                        ['Time (UTC)', time.utc],
                        ['Time (local)', time.local],
                        ['Record ID', <code key="id" className="text-xs">{record.id}</code>],
                    ]} />
                </DrawerSection>

                <details className="group border-t border-edge pt-4">
                    <summary className="cursor-pointer text-sm font-semibold text-text-1 focus-visible:outline-2 focus-visible:outline-accent">Raw JSON</summary>
                    <div className="mt-2 space-y-2">
                        <GlassButton size="sm" variant="subtle" onClick={() => void copy()}>
                            <Copy size={13} aria-hidden="true" />Copy JSON
                        </GlassButton>
                        <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-2 p-3 text-xs text-text-2">{json}</pre>
                    </div>
                </details>
            </div>
        </DetailDrawer>
    );
}
