// tabularRunEstimate.ts
// Spotting a request that is about to start a long, expensive row-level run.
//
// "Write a summary for every one of these 4,000 rows" is one model call per batch, checkpointed
// and resumed over minutes. It is a perfectly reasonable thing to ask for deliberately and an
// expensive thing to ask for by accident, and the two are indistinguishable at the point of
// sending. Confirming first is the only moment where narrowing the prompt is still cheap.
//
// The heuristic is deliberately narrow. It fires only when the prompt asks for row-level
// output *and* asks for a file *and* names a count large enough to matter, because a
// confirmation that appears on ordinary questions gets clicked through without being read,
// which is worse than not asking. Thresholds are administrator-configured and arrive in the
// bootstrap settings.

/** The settings this reads, all present on the sanitized bootstrap payload. */
export interface TabularRunSettings {
    enable_tabular_durable_run_confirmation?: boolean;
    tabular_generated_output_max_batch_rows?: number | string;
    tabular_durable_run_confirmation_threshold_rows?: number | string;
    tabular_durable_run_confirmation_threshold_batches?: number | string;
}

export interface TabularRunEstimate {
    shouldConfirm: boolean;
    estimatedRows: number;
    estimatedBatches: number;
    rowThreshold: number;
    batchThreshold: number;
    maxBatchRows: number;
}

/** Asks for output per row rather than a summary over them. */
const EXHAUSTIVE_PATTERN =
    /\b(all rows|every row|each row|for each row|for every row|one row per|one object per)\b/;

/** Asks for something to be produced, rather than just described. */
const EXPORT_PATTERN = /\b(csv|json|xml|export|download|generate|create|save)\b/;

/** A count of rows, records or entries, with or without thousands separators. */
const ROW_COUNT_PATTERN = /\b(\d{1,3}(?:,\d{3})+|\d+)\s*(?:rows?|records?|entries?)\b/;

function positiveInteger(value: unknown): number {
    const normalized = String(value ?? '').replace(/,/g, '').trim();
    const parsed = Number.parseInt(normalized, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

/**
 * Decide whether a prompt should be confirmed before it is sent.
 *
 * Defaults match the server's own (50 rows per batch, 500 rows, 75 batches) so an
 * installation that has never touched these settings behaves the same as one that has saved
 * them unchanged. The confirmation is opt-out: only an explicit `false` disables it, because
 * a missing key means the setting has never been written, not that it is off.
 */
export function estimateLargeTabularRun(
    messageText: string,
    settings: TabularRunSettings = {},
): TabularRunEstimate {
    const maxBatchRows = Math.max(
        positiveInteger(settings.tabular_generated_output_max_batch_rows) || 50,
        1,
    );
    const rowThreshold = Math.max(
        positiveInteger(settings.tabular_durable_run_confirmation_threshold_rows) || 500,
        1,
    );
    const batchThreshold = Math.max(
        positiveInteger(settings.tabular_durable_run_confirmation_threshold_batches) || 75,
        1,
    );

    const empty: TabularRunEstimate = {
        shouldConfirm: false,
        estimatedRows: 0,
        estimatedBatches: 0,
        rowThreshold,
        batchThreshold,
        maxBatchRows,
    };

    const normalized = String(messageText ?? '').toLowerCase();
    if (settings.enable_tabular_durable_run_confirmation === false || !normalized.trim()) {
        return empty;
    }

    const estimatedRows = positiveInteger(normalized.match(ROW_COUNT_PATTERN)?.[1]);
    const estimatedBatches = estimatedRows > 0 ? Math.ceil(estimatedRows / maxBatchRows) : 0;

    return {
        shouldConfirm: Boolean(
            EXHAUSTIVE_PATTERN.test(normalized) &&
                EXPORT_PATTERN.test(normalized) &&
                estimatedRows > 0 &&
                (estimatedRows > rowThreshold || estimatedBatches > batchThreshold),
        ),
        estimatedRows,
        estimatedBatches,
        rowThreshold,
        batchThreshold,
        maxBatchRows,
    };
}

export function describeLargeTabularRun(estimate: TabularRunEstimate): string {
    return `This request mentions ${estimate.estimatedRows.toLocaleString()} rows and is estimated at about ${estimate.estimatedBatches.toLocaleString()} batches.`;
}
