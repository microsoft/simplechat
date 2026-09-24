// GroupActivitySection.tsx
// The group workspace Activity section (M7C): a read-only feed of recent group events, read
// natively through /api/groups/<g>/insights/activity.
//
// The feed is a projection the server owns: each record already carries a written summary, the actor
// as the server chose to attribute it (a current member by name, a former member, or the system) and
// when it happened. The section neither reshapes nor re-attributes it; it lists what the server sends
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
    type GroupActivityRecord, type GroupSettingsAdapter,
} from '../../lib/groupSettings';

function readLimit(value: string | null): number {
    const parsed = Number(value);
    return (GROUP_ACTIVITY_LIMITS as readonly number[]).includes(parsed) ? parsed : GROUP_ACTIVITY_DEFAULT_LIMIT;
}

function actorLabel(record: GroupActivityRecord): string {
    if (record.actor.kind === 'member') {
        return record.actor.display_name || 'A group member';
    }
    if (record.actor.kind === 'former_member') {
        return 'A former member';
    }
    return 'System';
}

function occurredLabel(record: GroupActivityRecord): string {
    if (!record.occurred_at) {
        return 'Time unknown';
    }
    const label = formatRelativeTime(record.occurred_at);
    return label || 'Time unknown';
}

export function GroupActivitySection({ adapter }: { adapter: GroupSettingsAdapter }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const limit = readLimit(searchParams.get('limit'));

    const [records, setRecords] = useState<GroupActivityRecord[] | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [reloadToken, setReloadToken] = useState(0);
    const liveRef = useRef<HTMLParagraphElement>(null);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        void adapter.readActivity(limit, controller.signal)
            .then((feed) => { if (!controller.signal.aborted) setRecords(feed.activity); })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setRecords(null);
                setLoadError(cause instanceof Error ? cause.message : 'The group activity could not be loaded. Please retry.');
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
        <div className="space-y-4" data-testid="group-activity-section">
            <SectionIntro title="Activity"
                description="Recent changes in this group, most recent first."
                actions={(
                    <div className="flex items-center gap-1.5" role="group" aria-label="How many events to show">
                        {GROUP_ACTIVITY_LIMITS.map((option) => (
                            <button key={option} type="button" aria-pressed={limit === option}
                                data-testid={`group-activity-limit-${option}`}
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
                    description="Changes to this group's members, documents and settings will appear here." />
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
                                            {actorLabel(record)} &middot; {occurredLabel(record)}
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
