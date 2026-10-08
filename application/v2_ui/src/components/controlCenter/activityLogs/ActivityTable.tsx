// ActivityTable.tsx
// The log itself. Each row reads as a sentence: when, who, what happened and where. A
// person, activity type or workspace in a row is a one-click filter; the rest of the row
// opens the record's details.

import type { MouseEvent, ReactNode } from 'react';
import { clsx } from 'clsx';
import {
    Activity, Bot, Coins, Database, FileText, Filter, Globe, LogIn, MessageSquare, ShieldCheck, Users,
    type LucideIcon,
} from 'lucide-react';
import {
    WORKSPACE_TYPE_LABELS, formatActivityTime, personName, shortId, workspaceName,
    type ActivityLogPrefs, type ActivityPresentation, type ActivityRecord, type ActivityWorkspaceRef,
} from '../../../lib/activityLogs';
import { GlassButton, Skeleton } from '../../ui/primitives';
import { StatusBadge } from '../ControlCenterPrimitives';

export const CATEGORY_ICONS: Record<string, LucideIcon> = {
    sign_in: LogIn,
    chat: MessageSquare,
    documents: FileText,
    tokens: Coins,
    groups: Users,
    public_workspaces: Globe,
    administration: ShieldCheck,
    agents: Bot,
    data: Database,
};

export function categoryIcon(category: string): LucideIcon {
    return CATEGORY_ICONS[category] ?? Activity;
}

/** A presentation for records the server did not describe (older API or failed lookup). */
export function fallbackPresentation(record: ActivityRecord): ActivityPresentation {
    const type = typeof record.activity_type === 'string' ? record.activity_type : '';
    const userId = typeof record.user_id === 'string' ? record.user_id : '';
    const label = type ? type.replaceAll('_', ' ') : 'Unknown activity';
    return {
        activity_type: type,
        label: label.charAt(0).toUpperCase() + label.slice(1),
        category: 'other',
        summary: typeof record.description === 'string' && record.description ? record.description : 'Open details for the recorded fields.',
        detail: '',
        facts: [],
        status: null,
        actor: { id: userId, name: '', email: '', kind: userId ? 'user' : 'system', resolved: false },
        workspace: { type: typeof record.workspace_type === 'string' ? record.workspace_type : '', id: '', name: '', resolved: false },
    };
}

export interface ActivityRowHandlers {
    onOpen: (index: number) => void;
    onFilterPerson: (id: string) => void;
    onFilterWorkspace: (workspace: ActivityWorkspaceRef) => void;
    onToggleType: (type: string) => void;
}

function stop(event: MouseEvent) {
    event.stopPropagation();
}

function FilterButton({ label, onClick, children, className }: {
    label: string;
    onClick: () => void;
    children: ReactNode;
    className?: string;
}) {
    return (
        <button type="button" aria-label={label} title={label}
            onClick={(event) => { stop(event); onClick(); }}
            className={clsx('group/filter inline-flex max-w-full items-start gap-1 rounded-md text-left transition-colors',
                'hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent', className)}>
            <span className="min-w-0">{children}</span>
            <Filter size={11} aria-hidden="true"
                className="mt-1 shrink-0 text-accent opacity-0 transition-opacity group-hover/filter:opacity-100 group-focus-visible/filter:opacity-100" />
        </button>
    );
}

function PersonCell({ view, onFilterPerson }: { view: ActivityPresentation; onFilterPerson: (id: string) => void }) {
    const actor = view.actor;
    const name = personName(actor);
    const secondary = actor.name && actor.email ? actor.email : actor.id && !actor.resolved ? shortId(actor.id) : '';
    if (actor.kind === 'system') return <span className="text-text-3">System</span>;
    const body = <>
        <span className={clsx('block truncate', actor.resolved || actor.email ? 'font-medium text-text-1' : 'text-text-2')}>{name}</span>
        {secondary ? <span className="block truncate text-xs text-text-3">{secondary}</span> : null}
    </>;
    if (!actor.id) return <span className="block min-w-0">{body}</span>;
    return <FilterButton label={`Show only activity by ${name}`} onClick={() => onFilterPerson(actor.id)}>{body}</FilterButton>;
}

function WorkspaceCell({ view, onFilterWorkspace }: { view: ActivityPresentation; onFilterWorkspace: (workspace: ActivityWorkspaceRef) => void }) {
    const workspace = view.workspace;
    const typeLabel = WORKSPACE_TYPE_LABELS[workspace.type];
    if (!workspace.id) {
        return typeLabel ? <span className="text-text-2">{typeLabel}</span> : <span className="text-text-3"><span aria-hidden="true">—</span><span className="sr-only">No workspace</span></span>;
    }
    const name = workspaceName(workspace);
    return (
        <FilterButton label={`Show only activity in ${name} (${typeLabel ?? 'workspace'})`} onClick={() => onFilterWorkspace(workspace)}>
            <span className="block text-xs text-text-3">{typeLabel}</span>
            <span className={clsx('block truncate', workspace.name ? 'text-text-1' : 'text-text-2')}>{name}</span>
        </FilterButton>
    );
}

function ActivityTypeCell({ view, selected, onToggleType }: { view: ActivityPresentation; selected: boolean; onToggleType: (type: string) => void }) {
    const Icon = categoryIcon(view.category);
    const content = <span className="flex min-w-0 items-start gap-2">
        <Icon size={14} aria-hidden="true" className="mt-0.5 shrink-0 text-text-3" />
        <span className="break-words">{view.label}</span>
    </span>;
    if (!view.activity_type) return <span className="text-text-2">{content}</span>;
    return (
        <FilterButton label={selected ? `Remove the ${view.label} filter` : `Show only ${view.label} activity`}
            onClick={() => onToggleType(view.activity_type)} className={selected ? 'text-accent' : 'text-text-1'}>
            {content}
        </FilterButton>
    );
}

function DetailsButton({ view, timeLabel, onOpen }: { view: ActivityPresentation; timeLabel: string; onOpen: () => void }) {
    return (
        <button type="button" onClick={(event) => { stop(event); onOpen(); }}
            aria-label={`Open details: ${view.label}, ${personName(view.actor)}, ${timeLabel}`}
            className="block w-full min-w-0 rounded-md text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
            <span className="flex min-w-0 items-center gap-2">
                <span className="truncate text-text-1" title={view.summary}>{view.summary}</span>
                {view.status === 'failed' ? <span className="shrink-0"><StatusBadge status="Failed" /></span> : null}
            </span>
            {view.detail ? <span className="block truncate text-xs text-text-3" title={view.detail}>{view.detail}</span> : null}
        </button>
    );
}

export function ActivityTable({
    records, views, loading, error, prefs, selectedTypes, pageNumber, hasPrevious, hasNext, onPrevious, onNext,
    onRetry, emptyActions, onPrefsChange, ...handlers
}: {
    records: ActivityRecord[];
    views: ActivityPresentation[];
    loading: boolean;
    error: string;
    prefs: ActivityLogPrefs;
    selectedTypes: string[];
    pageNumber: number;
    hasPrevious: boolean;
    hasNext: boolean;
    onPrevious: () => void;
    onNext: () => void;
    onRetry: () => void;
    emptyActions: ReactNode;
    onPrefsChange: (prefs: Partial<ActivityLogPrefs>) => void;
} & ActivityRowHandlers) {
    const compact = prefs.density === 'compact';
    const cell = compact ? 'px-3 py-1.5' : 'px-3 py-2.5';
    const now = new Date();
    const segment = (selected: boolean) => clsx(
        'px-2.5 py-1 text-xs transition-colors first:rounded-l-md last:rounded-r-md focus-visible:outline-2 focus-visible:outline-accent',
        selected ? 'bg-accent-soft font-medium text-accent' : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
    );
    const rows = records.map((record, index) => ({ record, index, view: views[index], time: formatActivityTime(record.timestamp, prefs.timeZone, now) }));
    const status = loading ? 'Loading activity…' : error ? '' : `Page ${pageNumber} · ${records.length.toLocaleString()} ${records.length === 1 ? 'record' : 'records'}, newest first`;

    return (
        <div className="overflow-hidden rounded-2xl border border-edge bg-surface-1">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-3 py-2">
                <p className="text-xs text-text-3" role="status">{status}</p>
                <div className="flex flex-wrap items-center gap-2">
                    <div role="group" aria-label="Show times in" className="flex rounded-md border border-edge">
                        <button type="button" aria-pressed={prefs.timeZone === 'local'} className={segment(prefs.timeZone === 'local')}
                            onClick={() => onPrefsChange({ timeZone: 'local' })}>Local time</button>
                        <button type="button" aria-pressed={prefs.timeZone === 'utc'} className={segment(prefs.timeZone === 'utc')}
                            onClick={() => onPrefsChange({ timeZone: 'utc' })}>UTC</button>
                    </div>
                    <div role="group" aria-label="Row density" className="flex rounded-md border border-edge">
                        <button type="button" aria-pressed={!compact} className={segment(!compact)}
                            onClick={() => onPrefsChange({ density: 'comfortable' })}>Comfortable</button>
                        <button type="button" aria-pressed={compact} className={segment(compact)}
                            onClick={() => onPrefsChange({ density: 'compact' })}>Compact</button>
                    </div>
                </div>
            </div>

            {error ? (
                <div role="alert" className="px-4 py-10 text-center text-sm text-danger">
                    {error}{' '}
                    <button type="button" className="font-medium underline" onClick={onRetry}>Retry</button>
                </div>
            ) : loading ? (
                <div aria-hidden="true" className="space-y-2 p-3">
                    {Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className={compact ? 'h-7' : 'h-11'} />)}
                </div>
            ) : !records.length ? (
                <div className="px-4 py-12 text-center">
                    <p className="text-sm font-medium text-text-1">No activity matches these filters.</p>
                    <p className="mt-1 text-sm text-text-3">Widen the date range, or remove a filter to see more.</p>
                    <div className="mt-4 flex flex-wrap justify-center gap-2">{emptyActions}</div>
                </div>
            ) : (
                <>
                    <div className="hidden overflow-x-auto md:block">
                        <table className="w-full min-w-[46rem] table-fixed text-left text-sm">
                            <caption className="sr-only">Activity records, newest first. Select a person, activity or workspace to filter by it; select the details to open the record.</caption>
                            <colgroup>
                                {/* Details takes the remaining width: it carries the most information. */}
                                <col className={prefs.timeZone === 'utc' ? 'w-44' : 'w-36'} /><col className="w-44" /><col className="w-40" /><col /><col className="w-36" />
                            </colgroup>
                            <thead className="bg-surface-2 text-xs text-text-3">
                                <tr>
                                    {['Time', 'Person', 'Activity', 'Details', 'Workspace'].map((label) => (
                                        <th key={label} scope="col" className="px-3 py-2 font-medium">{label}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-edge text-text-2">
                                {rows.map(({ record, index, view, time }) => (
                                    <tr key={JSON.stringify([record.timestamp, record.id, record.user_id, 'user_id' in record])}
                                        onClick={() => {
                                            // Selecting text to copy it should not open the record.
                                            if (!window.getSelection()?.toString()) handlers.onOpen(index);
                                        }}
                                        className="cursor-pointer align-top transition-colors hover:bg-surface-2">
                                        <td className={cell} title={time.title}>
                                            <span className="block whitespace-nowrap tabular-nums text-text-1">{time.primary}</span>
                                            {!compact && time.secondary ? <span className="block text-xs text-text-3">{time.secondary}</span> : null}
                                        </td>
                                        <td className={cell}><PersonCell view={view} onFilterPerson={handlers.onFilterPerson} /></td>
                                        <td className={cell}>
                                            <ActivityTypeCell view={view} selected={selectedTypes.includes(view.activity_type)} onToggleType={handlers.onToggleType} />
                                        </td>
                                        <td className={cell}><DetailsButton view={view} timeLabel={time.primary} onOpen={() => handlers.onOpen(index)} /></td>
                                        <td className={cell}><WorkspaceCell view={view} onFilterWorkspace={handlers.onFilterWorkspace} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <ul className="divide-y divide-edge md:hidden" aria-label="Activity records, newest first">
                        {rows.map(({ record, index, view, time }) => (
                            <li key={JSON.stringify([record.timestamp, record.id, record.user_id, 'user_id' in record])}
                                className={clsx('space-y-1.5 px-3', compact ? 'py-2' : 'py-3')}>
                                <div className="flex items-start justify-between gap-3 text-xs">
                                    <ActivityTypeCell view={view} selected={selectedTypes.includes(view.activity_type)} onToggleType={handlers.onToggleType} />
                                    <span className="shrink-0 tabular-nums text-text-3" title={time.title}>{time.primary}</span>
                                </div>
                                <DetailsButton view={view} timeLabel={time.primary} onOpen={() => handlers.onOpen(index)} />
                                <div className="flex flex-wrap items-start gap-x-4 gap-y-1 text-xs">
                                    <PersonCell view={view} onFilterPerson={handlers.onFilterPerson} />
                                    <WorkspaceCell view={view} onFilterWorkspace={handlers.onFilterWorkspace} />
                                </div>
                            </li>
                        ))}
                    </ul>
                </>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-edge px-3 py-2">
                <GlassButton size="sm" disabled={loading || !hasPrevious} onClick={onPrevious}>Previous</GlassButton>
                <GlassButton size="sm" disabled={loading || !hasNext} onClick={onNext}>Next</GlassButton>
            </div>
        </div>
    );
}
