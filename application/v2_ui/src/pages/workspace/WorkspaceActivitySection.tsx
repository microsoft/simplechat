// WorkspaceActivitySection.tsx
// The shared native Activity section: a read-only feed of a workspace's recent events. The group
// workspace (M7C, GroupActivitySection) reads /api/groups/<g>/insights/activity and the public
// workspace (M10C, PublicActivitySection) /api/public-workspaces/<w>/insights/activity, each through
// its own client; their wording, actor labels and test ids are values on the scope.
//
// The feed is a projection the server owns: each record already carries a written summary, the actor
// as the server chose to attribute it (a current member by name, a former member of a group, a
// signed-in reader who holds no role in a public workspace, or the system) and when it happened. The section neither reshapes nor re-attributes it; it lists what the server sends
// and lets the viewer widen the window through the limits the server accepts. A read that the server
// declines (a 503 while the store is unavailable) is shown as a retryable load error, never a blank
// feed that reads as "nothing has happened".

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Activity, History } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../../components/ui/primitives';
import { SectionIntro } from '../../components/workspace/primitives';
import { formatRelativeTime } from '../../lib/userStats';
import {
    GROUP_ACTIVITY_DEFAULT_LIMIT, GROUP_ACTIVITY_LIMITS,
    type GroupActivityRecord, type WorkspaceSettingsAdapter,
} from '../../lib/groupSettings';

/**
 * Everything that differs between the group's Activity section and the public workspace's. Every
 * data-testid is `${testIdPrefix}-<control>`.
 */
export interface WorkspaceActivitySectionScope {
    testIdPrefix: string;
    description: string;
    /** The load error when a read fails without a message of its own. */
    loadFailed: string;
    emptyDescription: string;
    /** How each actor kind the server reports is named. */
    actorLabels: {
        /** A current member whose name the workspace doesn't hold. */
        memberFallback: string;
        formerMember: string;
        nonMember: string;
        system: string;
    };
}

function readLimit(value: string | null): number {
    const parsed = Number(value);
    return (GROUP_ACTIVITY_LIMITS as readonly number[]).includes(parsed) ? parsed : GROUP_ACTIVITY_DEFAULT_LIMIT;
}

function actorLabel(record: GroupActivityRecord, labels: WorkspaceActivitySectionScope['actorLabels']): string {
    if (record.actor.kind === 'member') {
        return record.actor.display_name || labels.memberFallback;
    }
    if (record.actor.kind === 'former_member') {
        return labels.formerMember;
    }
    if (record.actor.kind === 'non_member') {
        return labels.nonMember;
    }
    return labels.system;
}

/** The absolute local date and time an event happened, the primary timestamp the feed shows. */
function absoluteLabel(occurredAt: string | null): string {
    if (!occurredAt) {
        return 'Time unknown';
    }
    const when = new Date(occurredAt);
    return Number.isNaN(when.getTime()) ? 'Time unknown' : when.toLocaleString();
}

/** The relative time, shown alongside the absolute one, or empty when it can't be resolved. */
function relativeLabel(record: GroupActivityRecord): string {
    if (!record.occurred_at) {
        return '';
    }
    return formatRelativeTime(record.occurred_at) || '';
}

export function WorkspaceActivitySection({
    scope, adapter,
}: {
    scope: WorkspaceActivitySectionScope;
    adapter: WorkspaceSettingsAdapter;
}) {
    const [searchParams, setSearchParams] = useSearchParams();
    const limit = readLimit(searchParams.get('limit'));

    const [records, setRecords] = useState<GroupActivityRecord[] | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [reloadToken, setReloadToken] = useState(0);
    const liveRef = useRef<HTMLParagraphElement>(null);
    // The load effect keeps its original dependencies, so it reads the scope's fallback through a ref.
    const loadFailedRef = useRef(scope.loadFailed);
    loadFailedRef.current = scope.loadFailed;

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        void adapter.readActivity(limit, controller.signal)
            .then((feed) => { if (!controller.signal.aborted) setRecords(feed.activity); })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setRecords(null);
                setLoadError(cause instanceof Error ? cause.message : loadFailedRef.current);
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [adapter, limit, reloadToken]);

    const setLimit = (next: number) => {
        const params = new URLSearchParams(searchParams);
        if (next === GROUP_ACTIVITY_DEFAULT_LIMIT) params.delete('limit'); else params.set('limit', String(next));
        setSearchParams(params, { replace: true });
    };

    const summary = useMemo(() => {
        if (!records) return '';
        return `Showing the ${records.length} most recent event${records.length === 1 ? '' : 's'}.`;
    }, [records]);

    return (
        <div className="space-y-4" data-testid={`${scope.testIdPrefix}-section`}>
            <SectionIntro title="Activity"
                description={scope.description}
                actions={(
                    <div className="flex items-center gap-1.5" role="group" aria-label="How many events to show">
                        {GROUP_ACTIVITY_LIMITS.map((option) => (
                            <button key={option} type="button" aria-pressed={limit === option}
                                data-testid={`${scope.testIdPrefix}-limit-${option}`}
                                onClick={() => setLimit(option)}
                                className={clsx(
                                    'rounded-lg border px-3 py-1.5 text-xs transition-colors',
                                    limit === option
                                        ? 'border-accent bg-accent-soft font-medium text-accent'
                                        : 'border-edge text-text-2 hover:bg-surface-2',
                                )}>
                                {option}
                            </button>
                        ))}
                    </div>
                )} />

            {loadError ? (
                <EmptyState icon={<Activity size={28} />} title="Activity unavailable" description={loadError}
                    action={<GlassButton size="sm" onClick={() => setReloadToken((value) => value + 1)}>Retry</GlassButton>} />
            ) : loading ? (
                <div className="space-y-2" aria-busy="true">
                    <Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" />
                </div>
            ) : records && records.length === 0 ? (
                <EmptyState icon={<History size={28} />} title="No recent activity"
                    description={scope.emptyDescription} />
            ) : (
                <>
                    <p ref={liveRef} role="status" className="text-xs text-text-3">{summary}</p>
                    <ul className="space-y-2">
                        {(records ?? []).map((record, index) => (
                            <li key={record.id ?? `activity-${index}`}>
                                <GlassPanel elevation="flat" className="flex items-start gap-3 p-3">
                                    <span aria-hidden="true"
                                        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-2">
                                        <Activity size={15} />
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <p className="min-w-0 break-words text-sm text-text-1">{record.summary}</p>
                                        <p className="mt-0.5 text-xs text-text-3">
                                            {actorLabel(record, scope.actorLabels)} &middot; {absoluteLabel(record.occurred_at)}
                                            {relativeLabel(record) ? <span className="text-text-4"> &middot; {relativeLabel(record)}</span> : null}
                                        </p>
                                    </div>
                                </GlassPanel>
                            </li>
                        ))}
                    </ul>
                </>
            )}
        </div>
    );
}
