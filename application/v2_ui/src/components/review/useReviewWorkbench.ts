// useReviewWorkbench.ts
// The state a Review center workbench keeps: the page of records its filters address, the
// records checked for a bulk action, and the bulk run in progress with its report.
//
// The filters, the page and the open record live in the address, so a workbench can be
// linked to, reloaded and returned to from a record's editor exactly as it was left. The
// checked records do not: they are a working set, pruned to the rows still shown after
// every reload.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { errorText, type BulkOperation, type MatchingIds, type ReviewPage } from '../../lib/reviewCenterApi';
import {
    buildBulkReport,
    readReviewPaging,
    type ReviewBulkResult,
} from '../../lib/reviewCenter';
import {
    checkedIds,
    EMPTY_REVIEW_SELECTION,
    keepFailures,
    matchingSelection,
    pruneReviewSelection,
    selectionSummary,
    selectMatching,
    toggleChecked,
    togglePageChecked,
    type ReviewSelection,
} from '../../lib/reviewSelection';
import type { BulkRunProgress, BulkRunReport } from './ReviewBulkBar';

export interface ReviewNoun {
    singular: string;
    plural: string;
}

export function useReviewWorkbench<T extends { id: string }>({
    filterKey,
    reloadKey,
    loadPage,
    loadMatchingIds,
    runBulk,
    noun,
    describe,
}: {
    /** The filters as their query string: a change reloads the list and drops "every matching". */
    filterKey: string;
    /** Bumped by the page's Refresh. */
    reloadKey: number;
    loadPage: (page: number, pageSize: number, signal: AbortSignal) => Promise<ReviewPage<T>>;
    loadMatchingIds: () => Promise<MatchingIds>;
    runBulk: (
        operations: readonly BulkOperation[],
        onProgress: (done: number, total: number) => void,
    ) => Promise<ReviewBulkResult[]>;
    noun: ReviewNoun;
    /** How a record is named in a bulk report. */
    describe: (id: string, items: readonly T[]) => string;
}) {
    const [searchParams, setSearchParams] = useSearchParams();
    const paging = readReviewPaging(searchParams);
    const [items, setItems] = useState<T[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [reload, setReload] = useState(0);
    const [selection, setSelection] = useState<ReviewSelection>(EMPTY_REVIEW_SELECTION);
    const [matchingBusy, setMatchingBusy] = useState(false);
    const [progress, setProgress] = useState<BulkRunProgress | null>(null);
    const [report, setReport] = useState<BulkRunReport | null>(null);
    const loadRef = useRef(loadPage);
    loadRef.current = loadPage;

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        loadRef.current(paging.page, paging.pageSize, controller.signal)
            .then((result) => {
                if (controller.signal.aborted) return;
                setItems(result.items);
                setTotal(result.total);
                setSelection((current) => pruneReviewSelection(
                    current,
                    result.items.map((item) => item.id),
                    filterKey,
                ));
            })
            .catch((cause) => {
                if (!controller.signal.aborted) setError(errorText(cause, `The ${noun.plural} could not be loaded.`));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
        // The noun only words the error.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterKey, paging.page, paging.pageSize, reloadKey, reload]);

    const orderedIds = useMemo(() => items.map((item) => item.id), [items]);
    const checked = checkedIds(selection, filterKey);
    const matching = matchingSelection(selection, filterKey);
    const pageFullyChecked = orderedIds.length > 0 && orderedIds.every((id) => checked.includes(id));

    /** Change address parameters, leaving the rest as they are. */
    const updateParams = useCallback((changes: Record<string, string | null>, options?: { keepPage?: boolean }) => {
        setSearchParams((current) => {
            const next = new URLSearchParams(current);
            for (const [key, value] of Object.entries(changes)) {
                if (value === null || value === '') next.delete(key);
                else next.set(key, value);
            }
            if (!options?.keepPage) next.delete('page');
            return next;
        }, { replace: true });
    }, [setSearchParams]);

    const toggle = (id: string, range: boolean) =>
        setSelection((current) => toggleChecked(current, id, range, orderedIds, filterKey));
    const togglePage = () => setSelection((current) => togglePageChecked(current, orderedIds, filterKey));
    const clearSelection = () => setSelection(EMPTY_REVIEW_SELECTION);

    const chooseMatching = async () => {
        setMatchingBusy(true);
        setReport(null);
        try {
            const result = await loadMatchingIds();
            setSelection(selectMatching(result, filterKey));
        } catch (cause) {
            setReport({ summary: errorText(cause, `Every matching ${noun.singular} could not be selected.`), failures: [] });
        } finally {
            setMatchingBusy(false);
        }
    };

    /**
     * Run one bulk operation, in batches, then report on each record and reload. Without
     * `ids` it runs over the checked records, and only those it could not change stay
     * checked; with `ids`, such as one record's own Archive, the checked records are left
     * as they are.
     */
    const runBulkOperation = async (
        label: string,
        verb: string,
        build: (id: string) => BulkOperation,
        ids?: readonly string[],
    ): Promise<ReviewBulkResult[]> => {
        const targets = ids ? [...ids] : [...checked];
        if (!targets.length) return [];
        setReport(null);
        setProgress({ label, done: 0, total: targets.length });
        const snapshot = items;
        try {
            const results = await runBulk(targets.map(build), (done, all) => setProgress({ label, done, total: all }));
            const built = buildBulkReport(results, verb, noun, (id) => describe(id, snapshot));
            setReport(built);
            if (!ids) setSelection(keepFailures(built.failures.map((failure) => failure.id)));
            return results;
        } finally {
            setProgress(null);
            setReload((value) => value + 1);
        }
    };

    return {
        searchParams,
        paging,
        updateParams,
        items,
        total,
        loading,
        error,
        reload: () => setReload((value) => value + 1),
        orderedIds,
        checked,
        matching,
        pageFullyChecked,
        toggle,
        togglePage,
        clearSelection,
        chooseMatching,
        matchingBusy,
        runBulkOperation,
        progress,
        report,
        setReport,
        summary: selectionSummary(selection, filterKey, noun),
    };
}
