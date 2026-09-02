// ViolationsTab.tsx
// Content-safety violations recorded against this user.
//
// Almost everything here is read-only. The route lets a user edit `user_notes` on their own
// records and nothing else — status, action and the reviewer's notes are set by an
// administrator, and PATCHing a record belonging to someone else is refused with a 403. The
// interface reflects that rather than offering controls the server will reject.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Loader2 } from 'lucide-react';
import { api, apiUrl, ApiError } from '../../lib/apiClient';
import { GlassPanel, Skeleton } from '../ui/primitives';

const PAGE_SIZE = 10;

/** Statuses an administrator can set, used to filter. */
const STATUSES = ['New', 'In-Review', 'Resolved', 'Dismissed'];

/** Actions an administrator can record against a violation. */
const ACTIONS = ['None', 'WarnUser', 'SuspendUser', 'Escalate', 'BlockUser'];

interface TriggeredCategory {
    category?: string;
    severity?: number;
}

interface SafetyLog {
    id: string;
    message?: string;
    triggered_categories?: TriggeredCategory[];
    status?: string;
    action?: string;
    user_notes?: string;
    admin_notes?: string;
    created_at?: string;
    last_updated?: string;
}

interface LogsResponse {
    logs?: SafetyLog[];
    page?: number;
    page_size?: number;
    total_count?: number;
}

interface StatsResponse {
    total_count?: number;
    new_count?: number;
    in_review_count?: number;
    resolved_count?: number;
    recent_30_day_count?: number;
}

const STATUS_TONE: Record<string, string> = {
    New: 'bg-warn-soft text-warn',
    'In-Review': 'bg-info-soft text-info',
    Resolved: 'bg-ok-soft text-ok',
    Dismissed: 'bg-surface-2 text-text-3',
};

function StatCard({ label, value }: { label: string; value: number }) {
    return (
        <GlassPanel className="p-3">
            <div className="text-lg font-semibold text-text-1">{value}</div>
            <div className="text-xs text-text-3">{label}</div>
        </GlassPanel>
    );
}

/** The user's own notes, the one field they may change. */
function UserNotes({ log, onSaved }: { log: SafetyLog; onSaved: () => void }) {
    const [draft, setDraft] = useState(log.user_notes ?? '');
    const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle');
    const [error, setError] = useState<string | null>(null);

    const dirty = draft !== (log.user_notes ?? '');

    const save = async () => {
        setState('saving');
        setError(null);
        try {
            await api.patch(`/api/safety/logs/my/${encodeURIComponent(log.id)}`, {
                user_notes: draft,
            });
            setState('saved');
            onSaved();
            window.setTimeout(() => setState('idle'), 1500);
        } catch (caught) {
            setState('idle');
            setError(
                caught instanceof ApiError ? caught.message : 'Your note could not be saved.',
            );
        }
    };

    return (
        <div className="mt-2">
            <label className="block text-xs font-medium text-text-2">Your notes</label>
            <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={2}
                placeholder="Add context an administrator should know."
                className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1 outline-none focus:border-accent"
            />
            <div className="mt-1 flex items-center gap-2">
                <button
                    type="button"
                    onClick={() => void save()}
                    disabled={!dirty || state === 'saving'}
                    className="rounded-lg border border-edge px-2.5 py-1 text-xs font-medium text-text-1 hover:bg-surface-2 disabled:opacity-50"
                >
                    {state === 'saving' ? (
                        <Loader2 size={12} className="animate-spin" />
                    ) : (
                        'Save note'
                    )}
                </button>
                {state === 'saved' && (
                    <span className="flex items-center gap-1 text-xs text-ok">
                        <Check size={12} /> Saved
                    </span>
                )}
                {error && <span className="text-xs text-danger">{error}</span>}
            </div>
        </div>
    );
}

export function ViolationsTab() {
    const [logs, setLogs] = useState<SafetyLog[]>([]);
    const [stats, setStats] = useState<StatsResponse | null>(null);
    const [page, setPage] = useState(1);
    const [totalCount, setTotalCount] = useState(0);
    const [status, setStatus] = useState('');
    const [action, setAction] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const params = useCallback(
        (targetPage: number) => {
            const search = new URLSearchParams({
                page: String(targetPage),
                page_size: String(PAGE_SIZE),
            });
            if (status) {
                search.set('status', status);
            }
            if (action) {
                search.set('action', action);
            }
            return search.toString();
        },
        [status, action],
    );

    const load = useCallback(
        async (targetPage: number) => {
            setLoading(true);
            setError(null);
            try {
                const [logsResponse, statsResponse] = await Promise.all([
                    api.get<LogsResponse>(`/api/safety/logs/my?${params(targetPage)}`),
                    // Advisory: the summary is a nicety, the list is the point.
                    api
                        .get<StatsResponse>(`/api/safety/logs/my/stats?${params(targetPage)}`)
                        .catch(() => null),
                ]);
                setLogs(logsResponse?.logs ?? []);
                setTotalCount(logsResponse?.total_count ?? 0);
                setPage(logsResponse?.page ?? targetPage);
                setStats(statsResponse);
            } catch (caught) {
                setError(
                    caught instanceof Error
                        ? caught.message
                        : 'Failed to load your violations.',
                );
            } finally {
                setLoading(false);
            }
        },
        [params],
    );

    useEffect(() => {
        void load(1);
    }, [load]);

    const lastPage = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

    return (
        <div className="space-y-3">
            {stats && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <StatCard label="Total" value={stats.total_count ?? 0} />
                    <StatCard label="New" value={stats.new_count ?? 0} />
                    <StatCard label="Resolved" value={stats.resolved_count ?? 0} />
                    <StatCard label="Last 30 days" value={stats.recent_30_day_count ?? 0} />
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
                <select
                    value={status}
                    onChange={(event) => setStatus(event.target.value)}
                    className="rounded-lg border border-edge bg-surface-solid px-2.5 py-1.5 text-sm text-text-1"
                >
                    <option value="">Any status</option>
                    {STATUSES.map((value) => (
                        <option key={value} value={value}>
                            {value}
                        </option>
                    ))}
                </select>
                <select
                    value={action}
                    onChange={(event) => setAction(event.target.value)}
                    className="rounded-lg border border-edge bg-surface-solid px-2.5 py-1.5 text-sm text-text-1"
                >
                    <option value="">Any action</option>
                    {ACTIONS.map((value) => (
                        <option key={value} value={value}>
                            {value}
                        </option>
                    ))}
                </select>
                <a
                    href={apiUrl(`/api/safety/logs/my/export?${params(1)}`)}
                    className="ml-auto rounded-lg border border-edge px-2.5 py-1.5 text-xs font-medium text-text-1 hover:bg-surface-2"
                >
                    Export CSV
                </a>
            </div>

            {error ? (
                <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
                    {error}
                </p>
            ) : loading ? (
                <div className="space-y-2">
                    <Skeleton className="h-24 w-full" />
                    <Skeleton className="h-24 w-full" />
                </div>
            ) : logs.length === 0 ? (
                <GlassPanel className="p-6 text-center">
                    <p className="text-sm text-text-2">
                        {status || action
                            ? 'No violations match these filters.'
                            : 'Nothing has been flagged on your account.'}
                    </p>
                </GlassPanel>
            ) : (
                <ul className="space-y-2">
                    {logs.map((log) => (
                        <li key={log.id}>
                            <GlassPanel className="p-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span
                                        className={clsx(
                                            'rounded-full px-2 py-0.5 text-[11px] font-medium',
                                            STATUS_TONE[log.status ?? ''] ??
                                                'bg-surface-2 text-text-3',
                                        )}
                                    >
                                        {log.status || 'Unknown'}
                                    </span>
                                    {log.action && log.action !== 'None' && (
                                        <span className="rounded-full border border-edge px-2 py-0.5 text-[11px] text-text-2">
                                            {log.action}
                                        </span>
                                    )}
                                    {log.created_at && (
                                        <span className="text-[11px] text-text-3">
                                            {new Date(log.created_at).toLocaleString()}
                                        </span>
                                    )}
                                </div>

                                {log.message && (
                                    <p className="mt-1.5 text-sm break-words text-text-1">
                                        {log.message}
                                    </p>
                                )}

                                {(log.triggered_categories ?? []).length > 0 && (
                                    <p className="mt-1 text-xs text-text-3">
                                        {(log.triggered_categories ?? [])
                                            .filter((entry) => entry?.category)
                                            .map(
                                                (entry) =>
                                                    `${entry.category} (severity ${entry.severity ?? '?'})`,
                                            )
                                            .join(', ')}
                                    </p>
                                )}

                                {log.admin_notes && (
                                    <p className="mt-1.5 rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs text-text-2">
                                        <span className="font-medium">Reviewer: </span>
                                        {log.admin_notes}
                                    </p>
                                )}

                                <UserNotes log={log} onSaved={() => void load(page)} />
                            </GlassPanel>
                        </li>
                    ))}
                </ul>
            )}

            {totalCount > PAGE_SIZE && (
                <div className="flex items-center justify-between text-xs text-text-3">
                    <span>
                        Page {page} of {lastPage} · {totalCount} records
                    </span>
                    <div className="flex gap-1.5">
                        <button
                            type="button"
                            disabled={page <= 1 || loading}
                            onClick={() => void load(page - 1)}
                            className="rounded-lg border border-edge px-2.5 py-1 text-text-1 hover:bg-surface-2 disabled:opacity-50"
                        >
                            Previous
                        </button>
                        <button
                            type="button"
                            disabled={page >= lastPage || loading}
                            onClick={() => void load(page + 1)}
                            className="rounded-lg border border-edge px-2.5 py-1 text-text-1 hover:bg-surface-2 disabled:opacity-50"
                        >
                            Next
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
