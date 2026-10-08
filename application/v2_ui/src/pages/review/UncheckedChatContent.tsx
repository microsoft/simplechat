// UncheckedChatContent.tsx
// Chat messages allowed through when a required content check could not finish, and the
// way to check them again under the current rules.
//
// Moved out of the Safety Violations page into its own Review center page. A recheck can
// remove an AI reply from saved and shared chat, so every recheck is confirmed first, one
// message or many. Several run one after another, never at once, with progress, and the
// report says what happened to each message: passed, removed, flagged, or still not
// checked. Message bodies are never shown here; only the check metadata is.

import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { ReviewBulkBar, type BulkRunProgress, type BulkRunReport } from '../../components/review/ReviewBulkBar';
import { FilterSelect, ReviewNotice, useIndeterminate } from '../../components/review/ReviewParts';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { GlassButton, Skeleton } from '../../components/ui/primitives';
import { applySelection, EMPTY_SELECTION, pruneSelection, toggleSelectAll, type SelectionState } from '../../lib/listSelection';
import { countLabel, formatReviewDate } from '../../lib/reviewCenter';
import {
    errorText,
    fetchUncheckedChat,
    recheckChatMessage,
    recheckOutcomeText,
    uncheckedKey,
    type UncheckedChatFilters,
    type UncheckedChatItem,
} from '../../lib/reviewCenterApi';

const NOUN = { singular: 'message', plural: 'messages' };
const SOURCES: readonly UncheckedChatFilters['source'][] = ['all', 'chat', 'shared'];
const CHECKPOINTS: readonly UncheckedChatFilters['checkpoint'][] = ['', 'chat_input', 'chat_output'];
const SCANNERS: readonly UncheckedChatFilters['scanner'][] = ['', 'content_screening', 'content_safety'];

function readFilters(params: URLSearchParams): UncheckedChatFilters {
    const source = params.get('source') ?? 'all';
    const checkpoint = params.get('checkpoint') ?? '';
    const scanner = params.get('scanner') ?? '';
    return {
        source: SOURCES.find((value) => value === source) ?? 'all',
        checkpoint: CHECKPOINTS.find((value) => value === checkpoint) ?? '',
        scanner: SCANNERS.find((value) => value === scanner) ?? '',
    };
}

function incompleteChecks(item: UncheckedChatItem): string {
    return (item.check?.scanners ?? [])
        .filter((entry) => !entry.complete)
        .map((entry) => `${entry.scanner === 'content_safety' ? 'Content Safety' : 'Content Screening'}: ${entry.error_code || 'incomplete'}`)
        .join('; ') || 'Not recorded';
}

export function UncheckedChatContent({ reloadKey }: { reloadKey: number }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const filters = readFilters(searchParams);
    const filterKey = `${filters.source}|${filters.checkpoint}|${filters.scanner}`;
    const [items, setItems] = useState<UncheckedChatItem[]>([]);
    const [continuation, setContinuation] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [moreLoading, setMoreLoading] = useState(false);
    const [error, setError] = useState('');
    const [reload, setReload] = useState(0);
    const [selection, setSelection] = useState<SelectionState>(EMPTY_SELECTION);
    const [pending, setPending] = useState<UncheckedChatItem[] | null>(null);
    const [progress, setProgress] = useState<BulkRunProgress | null>(null);
    const [report, setReport] = useState<BulkRunReport | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        fetchUncheckedChat(filters, null, controller.signal)
            .then((page) => {
                setItems(page.items);
                setContinuation(page.continuation);
                setSelection((current) => pruneSelection(current, page.items.map(uncheckedKey)));
            })
            .catch((cause) => {
                if (!controller.signal.aborted) {
                    setItems([]);
                    setContinuation(null);
                    setError(errorText(cause, 'Unchecked messages could not be loaded.'));
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
        // The filter key stands in for the filters object, rebuilt on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterKey, reloadKey, reload]);

    const orderedKeys = useMemo(() => items.map(uncheckedKey), [items]);
    const checkable = useMemo(() => new Set(items.filter((item) => item.etag).map(uncheckedKey)), [items]);
    const checkedKeys = selection.ids.filter((key) => checkable.has(key));
    const allChecked = checkable.size > 0 && [...checkable].every((key) => selection.ids.includes(key));
    const headerRef = useIndeterminate(allChecked, checkedKeys.length > 0);
    const busy = Boolean(progress);

    const setFilter = (key: keyof UncheckedChatFilters, value: string) => {
        setSearchParams((current) => {
            const next = new URLSearchParams(current);
            const defaults: Record<string, string> = { source: 'all', checkpoint: '', scanner: '' };
            if (value === defaults[key]) next.delete(key);
            else next.set(key, value);
            return next;
        }, { replace: true });
        setSelection(EMPTY_SELECTION);
    };

    const loadMore = async () => {
        if (!continuation || moreLoading) return;
        setMoreLoading(true);
        setError('');
        try {
            const page = await fetchUncheckedChat(filters, continuation);
            setItems((current) => {
                const seen = new Set(current.map(uncheckedKey));
                return [...current, ...page.items.filter((item) => !seen.has(uncheckedKey(item)))];
            });
            setContinuation(page.continuation);
        } catch (cause) {
            setError(errorText(cause, 'More unchecked messages could not be loaded.'));
        } finally {
            setMoreLoading(false);
        }
    };

    const toggle = (key: string, event: MouseEvent<HTMLInputElement>) => {
        setSelection((current) => applySelection(
            current,
            key,
            event.shiftKey ? 'range' : 'toggle',
            orderedKeys.filter((candidate) => checkable.has(candidate)),
        ));
    };

    /** Recheck one message after another, so the checkers and the store see one at a time. */
    const recheck = async (targets: UncheckedChatItem[]) => {
        setReport(null);
        const outcomes: { id: string; label: string; message: string }[] = [];
        const retry: string[] = [];
        const counts = { passed: 0, removed: 0, flagged: 0, unfinished: 0, failed: 0 };
        for (let index = 0; index < targets.length; index += 1) {
            const item = targets[index];
            const key = uncheckedKey(item);
            setProgress({ label: 'Rechecking', done: index, total: targets.length });
            try {
                const outcome = await recheckChatMessage(item);
                if (outcome.removed) counts.removed += 1;
                else if (outcome.check?.status === 'passed') counts.passed += 1;
                else if (outcome.check?.status === 'findings') counts.flagged += 1;
                else {
                    counts.unfinished += 1;
                    retry.push(key);
                }
                outcomes.push({ id: key, label: `Message ${item.message_id}`, message: recheckOutcomeText(outcome).message });
            } catch (cause) {
                counts.failed += 1;
                retry.push(key);
                outcomes.push({
                    id: key,
                    label: `Message ${item.message_id}`,
                    message: errorText(cause, 'The message could not be rechecked.'),
                });
            }
        }
        setProgress(null);
        const parts = [
            counts.passed ? `${counts.passed.toLocaleString()} passed` : '',
            counts.removed ? `${countLabel(counts.removed, 'AI reply', 'AI replies')} removed` : '',
            counts.flagged ? `${counts.flagged.toLocaleString()} flagged for review` : '',
            counts.unfinished ? `${counts.unfinished.toLocaleString()} could not finish` : '',
            counts.failed ? `${counts.failed.toLocaleString()} could not be rechecked` : '',
        ].filter(Boolean);
        setReport({
            summary: `Rechecked ${countLabel(targets.length, NOUN.singular, NOUN.plural)}: ${parts.join(', ')}.`,
            failures: outcomes,
            tone: counts.flagged || counts.unfinished || counts.failed ? 'warn' : 'ok',
        });
        // What can be retried stays selected; the reload drops any that left the queue.
        setSelection({ ids: retry, anchorId: retry[0] ?? null });
        setReload((value) => value + 1);
    };

    return (
        <section aria-label="Unchecked chat content" className="h-full overflow-y-auto" data-testid="v2-unchecked-chat">
            <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
                <p className="max-w-3xl text-sm text-text-2">
                    These messages were allowed through when a required check could not finish. Rechecking uses the current rules;
                    confirmed findings can remove AI replies from saved and shared chat, but cannot undo earlier views or external actions.
                </p>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <FilterSelect
                        label="Conversation source"
                        value={filters.source}
                        options={[['all', 'All sources'], ['chat', 'Chat and canonical AI messages'], ['shared', 'Shared user messages']]}
                        onChange={(value) => setFilter('source', value)}
                        testId="v2-unchecked-filter-source"
                    />
                    <FilterSelect
                        label="Message type"
                        value={filters.checkpoint}
                        options={[['', 'All message types'], ['chat_input', 'Submitted messages'], ['chat_output', 'AI replies']]}
                        onChange={(value) => setFilter('checkpoint', value)}
                        testId="v2-unchecked-filter-checkpoint"
                    />
                    <FilterSelect
                        label="Incomplete scanner"
                        value={filters.scanner}
                        options={[['', 'All scanners'], ['content_screening', 'Content Screening'], ['content_safety', 'Azure Content Safety']]}
                        onChange={(value) => setFilter('scanner', value)}
                        testId="v2-unchecked-filter-scanner"
                    />
                </div>
                {error ? <ReviewNotice tone="danger">{error}</ReviewNotice> : null}
                <ReviewBulkBar
                    count={checkedKeys.length}
                    summary={`${countLabel(checkedKeys.length, NOUN.singular, NOUN.plural)} selected`}
                    onClear={() => setSelection(EMPTY_SELECTION)}
                    progress={progress}
                    report={report}
                    onDismissReport={() => setReport(null)}
                    testIdPrefix="v2-unchecked"
                    actions={(
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="subtle"
                            data-testid="v2-unchecked-bulk-recheck"
                            onClick={() => setPending(items.filter((item) => checkedKeys.includes(uncheckedKey(item))))}
                        >
                            <RefreshCw size={14} aria-hidden="true" /> Recheck selected
                        </GlassButton>
                    )}
                />
                <div className="overflow-x-auto rounded-xl border border-edge-strong bg-surface-solid">
                    <table className="w-full min-w-[680px] text-left text-xs">
                        <caption className="sr-only">
                            Check metadata for messages whose required checks could not finish. Message bodies are not shown.
                        </caption>
                        <thead className="border-b border-edge-strong text-text-3">
                            <tr>
                                <th scope="col" className="w-10 p-2">
                                    <input
                                        ref={headerRef}
                                        type="checkbox"
                                        aria-label="Select every loaded message"
                                        checked={allChecked}
                                        disabled={!checkable.size || busy}
                                        onChange={() => setSelection((current) => toggleSelectAll(current, [...checkable]))}
                                        data-testid="v2-unchecked-select-all"
                                        className="h-4 w-4 accent-[var(--color-accent)]"
                                    />
                                </th>
                                <th scope="col" className="p-2">Message</th>
                                <th scope="col" className="p-2">Type</th>
                                <th scope="col" className="p-2">Incomplete checks</th>
                                <th scope="col" className="p-2">Last attempt</th>
                                <th scope="col" className="p-2"><span className="sr-only">Recheck</span></th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-edge">
                            {loading ? (
                                <tr>
                                    <td colSpan={6} className="p-3">
                                        <div role="status" className="space-y-2">
                                            <span className="sr-only">Loading unchecked messages</span>
                                            <Skeleton className="h-8 w-full" />
                                            <Skeleton className="h-8 w-full" />
                                        </div>
                                    </td>
                                </tr>
                            ) : items.length === 0 ? (
                                <tr><td colSpan={6} className="p-4 text-center text-text-3">No unchecked messages match these filters.</td></tr>
                            ) : items.map((item) => {
                                const key = uncheckedKey(item);
                                return (
                                    <tr key={key} data-testid={`v2-unchecked-row-${item.message_id}`}>
                                        <td className="p-2">
                                            <input
                                                type="checkbox"
                                                aria-label={`Select message ${item.message_id}`}
                                                checked={selection.ids.includes(key)}
                                                disabled={!item.etag || busy}
                                                onChange={() => undefined}
                                                onClick={(event) => toggle(key, event)}
                                                className="h-4 w-4 accent-[var(--color-accent)]"
                                            />
                                        </td>
                                        <td className="max-w-xs p-2 break-all">
                                            {item.message_id}
                                            <span className="mt-1 block text-text-3">Conversation: {item.conversation_id}</span>
                                        </td>
                                        <td className="p-2">{item.check?.checkpoint === 'chat_output' ? 'AI reply' : 'Submitted message'}</td>
                                        <td className="max-w-sm p-2">{incompleteChecks(item)}</td>
                                        <td className="p-2 whitespace-nowrap text-text-3">{formatReviewDate(item.check?.attempted_at)}</td>
                                        <td className="p-2">
                                            <GlassButton
                                                type="button"
                                                size="sm"
                                                variant="subtle"
                                                disabled={!item.etag || busy || moreLoading}
                                                onClick={() => setPending([item])}
                                                aria-label={`Recheck message ${item.message_id}`}
                                            >
                                                Recheck
                                            </GlassButton>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
                {continuation ? (
                    <GlassButton type="button" variant="ghost" size="sm" disabled={moreLoading || loading || busy} onClick={() => void loadMore()}>
                        {moreLoading ? 'Loading…' : 'Load more unchecked messages'}
                    </GlassButton>
                ) : null}
            </div>

            {pending ? (
                <ConfirmDialog
                    title={pending.length === 1 ? 'Recheck this message?' : `Recheck ${countLabel(pending.length, NOUN.singular, NOUN.plural)}?`}
                    description="The current rules will be applied. An AI reply with confirmed findings will be removed from saved and shared chat. A checker outage leaves a message available and marked for another attempt."
                    confirmLabel={pending.length === 1 ? 'Recheck and apply rules' : `Recheck ${countLabel(pending.length, NOUN.singular, NOUN.plural)}`}
                    confirmIcon={<RefreshCw size={14} />}
                    tone="primary"
                    onClose={() => setPending(null)}
                    onConfirm={() => {
                        const targets = pending;
                        setPending(null);
                        void recheck(targets);
                    }}
                >
                    <p className="text-xs text-text-2">
                        {pending.length === 1
                            ? <>Message ID: <span className="break-all">{pending[0].message_id}</span></>
                            : 'They are rechecked one at a time, and you see what happened to each.'}
                    </p>
                </ConfirmDialog>
            ) : null}
        </section>
    );
}
