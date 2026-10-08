// useReviewTriage.ts
// The state of an AI triage run from a Review center workbench: progress, Cancel, and the report
// it leaves under the bulk bar.
//
// A triage asks the assistant for a suggested review of each checked record, ten records per
// request, one request after another, and stores the suggestions on the records. Each user's
// records travel together, because the server never asks the model about two users' records at
// once; records the server didn't reach in time are sent again. Nothing about a review changes:
// the report links to the AI suggestions queue, where a reviewer approves or dismisses them.
// Leaving the page cancels a run still going.

import { useEffect, useRef, useState } from 'react';
import type { ReviewSectionId } from '../../lib/reviewAccess';
import { postReviewAssist } from '../../lib/reviewAssistApi';
import { buildTriageReport, runTriage, type TriageRun } from '../../lib/reviewSuggestions';
import type { BulkRunProgress, BulkRunReport } from './ReviewBulkBar';

export function useReviewTriage({
    section,
    noun,
    onFinished,
}: {
    section: ReviewSectionId;
    noun: { singular: string; plural: string };
    /** Called once a run ends, however it ended, so the workbench can reload its rows. */
    onFinished?: (run: TriageRun) => void;
}) {
    const [progress, setProgress] = useState<BulkRunProgress | null>(null);
    const [report, setReport] = useState<BulkRunReport | null>(null);
    const controllerRef = useRef<AbortController | null>(null);

    useEffect(() => () => controllerRef.current?.abort(), []);

    /**
     * Triage `ids`, naming each record in the report with `describe`, as the list named it when the
     * run began. `ownerOf` says whose each record is, so each user's records are sent together.
     */
    const start = async (
        ids: readonly string[],
        describe: (id: string) => string,
        ownerOf?: (id: string) => string | null,
    ) => {
        if (!ids.length || controllerRef.current) return;
        const controller = new AbortController();
        controllerRef.current = controller;
        setReport(null);
        setProgress({ label: 'Triaging with AI', done: 0, total: ids.length });
        try {
            const run = await runTriage({
                ids,
                signal: controller.signal,
                ownerOf,
                post: (chunk, signal) => postReviewAssist(section, 'triage', chunk, signal),
                onProgress: (step) => setProgress({
                    label: step.waitingSeconds ? 'Waiting for the assistant' : 'Triaging with AI',
                    done: step.done,
                    total: step.total,
                    detail: step.waitingSeconds ? `Resuming in ${step.waitingSeconds} s.` : undefined,
                }),
            });
            const built = buildTriageReport(run, noun, describe);
            setReport({
                summary: built.summary,
                failures: built.failures,
                tone: built.tone,
                link: built.suggested ? { label: 'Open the AI suggestions queue', section, view: 'suggestions' } : undefined,
            });
            onFinished?.(run);
        } finally {
            controllerRef.current = null;
            setProgress(null);
        }
    };

    return {
        progress,
        report,
        setReport,
        start,
        cancel: () => controllerRef.current?.abort(),
        running: Boolean(progress),
    };
}
