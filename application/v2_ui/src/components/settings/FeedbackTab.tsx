// FeedbackTab.tsx
// Feedback this user has submitted on assistant replies, and whether it has been reviewed.
//
// Entirely read-only: submitting happens from a message in the chat, and the review is an
// administrator's to write. Showing what became of a submission is the point — feedback
// that vanishes into a void does not get given twice.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { api, apiUrl } from '../../lib/apiClient';
import { GlassPanel, Skeleton } from '../ui/primitives';

const PAGE_SIZE = 10;

interface AdminReview {
    acknowledged?: boolean;
    analysisNotes?: string;
    responseToUser?: string;
    [key: string]: unknown;
}

interface FeedbackItem {
    id: string;
    prompt?: string;
    aiResponse?: string;
    /** Normalised server-side to Positive / Negative / Neutral. */
    feedbackType?: string;
    reason?: string;
    timestamp?: string;
    adminReview?: AdminReview;
}

interface FeedbackResponse {
    feedback?: FeedbackItem[];
    page?: number;
    page_size?: number;
    total_count?: number;
}

interface FeedbackStats {
    total_count?: number;
    positive_count?: number;
    negative_count?: number;
    acknowledged_count?: number;
}

function StatCard({ label, value }: { label: string; value: number }) {
    return (
        <GlassPanel className="p-3">
            <div className="text-lg font-semibold text-text-1">{value}</div>
            <div className="text-xs text-text-3">{label}</div>
        </GlassPanel>
    );
}

function TypeBadge({ type }: { type?: string }) {
    if (type === 'Positive') {
        return (
            <span className="flex items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-[11px] font-medium text-ok">
                <ThumbsUp size={11} /> Positive
            </span>
        );
    }
    if (type === 'Negative') {
        return (
            <span className="flex items-center gap-1 rounded-full bg-danger-soft px-2 py-0.5 text-[11px] font-medium text-danger">
                <ThumbsDown size={11} /> Negative
            </span>
        );
    }
    return (
        <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-text-3">
            {type || 'Neutral'}
        </span>
    );
}

export function FeedbackTab() {
    const [items, setItems] = useState<FeedbackItem[]>([]);
    const [stats, setStats] = useState<FeedbackStats | null>(null);
    const [page, setPage] = useState(1);
    const [totalCount, setTotalCount] = useState(0);
    const [type, setType] = useState('');
    const [ack, setAck] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const params = useCallback(
        (targetPage: number) => {
            const search = new URLSearchParams({
                page: String(targetPage),
                page_size: String(PAGE_SIZE),
            });
            if (type) {
                search.set('type', type);
            }
            if (ack) {
                search.set('ack', ack);
            }
            return search.toString();
        },
        [type, ack],
    );

    const load = useCallback(
        async (targetPage: number) => {
            setLoading(true);
            setError(null);
            try {
                const [listResponse, statsResponse] = await Promise.all([
                    api.get<FeedbackResponse>(`/feedback/my?${params(targetPage)}`),
                    // Advisory: the summary is a nicety, the list is the point.
                    api.get<FeedbackStats>(`/feedback/my/stats?${params(targetPage)}`).catch(
                        () => null,
                    ),
                ]);
                setItems(listResponse?.feedback ?? []);
                setTotalCount(listResponse?.total_count ?? 0);
                setPage(listResponse?.page ?? targetPage);
                setStats(statsResponse);
            } catch (caught) {
                setError(
                    caught instanceof Error ? caught.message : 'Failed to load your feedback.',
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
                    <StatCard label="Submitted" value={stats.total_count ?? 0} />
                    <StatCard label="Positive" value={stats.positive_count ?? 0} />
                    <StatCard label="Negative" value={stats.negative_count ?? 0} />
                    <StatCard label="Reviewed" value={stats.acknowledged_count ?? 0} />
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
                <select
                    value={type}
                    onChange={(event) => setType(event.target.value)}
                    className="rounded-lg border border-edge bg-surface-solid px-2.5 py-1.5 text-sm text-text-1"
                >
                    <option value="">Any rating</option>
                    <option value="Positive">Positive</option>
                    <option value="Negative">Negative</option>
                    <option value="Neutral">Neutral</option>
                </select>
                <select
                    value={ack}
                    onChange={(event) => setAck(event.target.value)}
                    className="rounded-lg border border-edge bg-surface-solid px-2.5 py-1.5 text-sm text-text-1"
                >
                    <option value="">Reviewed or not</option>
                    <option value="true">Reviewed</option>
                    <option value="false">Awaiting review</option>
                </select>
                <a
                    href={apiUrl(`/feedback/my/export?${params(1)}`)}
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
            ) : items.length === 0 ? (
                <GlassPanel className="p-6 text-center">
                    <p className="text-sm text-text-2">
                        {type || ack
                            ? 'No feedback matches these filters.'
                            : 'You have not rated any replies yet. Use the thumbs on an assistant message to send feedback.'}
                    </p>
                </GlassPanel>
            ) : (
                <ul className="space-y-2">
                    {items.map((item) => {
                        const acknowledged = Boolean(item.adminReview?.acknowledged);
                        return (
                            <li key={item.id}>
                                <GlassPanel className="p-3">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <TypeBadge type={item.feedbackType} />
                                        <span
                                            className={clsx(
                                                'rounded-full px-2 py-0.5 text-[11px]',
                                                acknowledged
                                                    ? 'bg-ok-soft text-ok'
                                                    : 'bg-surface-2 text-text-3',
                                            )}
                                        >
                                            {acknowledged ? 'Reviewed' : 'Awaiting review'}
                                        </span>
                                        {item.timestamp && (
                                            <span className="text-[11px] text-text-3">
                                                {new Date(item.timestamp).toLocaleString()}
                                            </span>
                                        )}
                                    </div>

                                    {item.prompt && (
                                        <p className="mt-1.5 line-clamp-2 text-xs text-text-3">
                                            <span className="font-medium">You asked: </span>
                                            {item.prompt}
                                        </p>
                                    )}
                                    {item.reason && (
                                        <p className="mt-1 text-sm text-text-1">{item.reason}</p>
                                    )}

                                    {item.adminReview?.responseToUser && (
                                        <p className="mt-1.5 rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs text-text-2">
                                            <span className="font-medium">Reply: </span>
                                            {item.adminReview.responseToUser}
                                        </p>
                                    )}
                                </GlassPanel>
                            </li>
                        );
                    })}
                </ul>
            )}

            {totalCount > PAGE_SIZE && (
                <div className="flex items-center justify-between text-xs text-text-3">
                    <span>
                        Page {page} of {lastPage} · {totalCount} submissions
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
