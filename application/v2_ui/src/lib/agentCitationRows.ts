// agentCitationRows.ts
// Reading a tool result that turned out to be a table.
//
// A tabular tool answers with rows, and a query that matched four thousand of them returns
// four thousand. Dumped whole into the inspector that is a page of JSON nobody scrolls, and
// truncated silently it is a lie about what the tool found. Neither tells you the one thing
// worth knowing: how many matched, versus how many you are looking at.
//
// So the count is stated and the rows are banded — a few by default, twenty-five on request,
// all of them if you insist. The bands exist because the middle case is the common one:
// enough rows to judge whether the answer used the right data, without rendering the lot.

/** Row counts for the three view modes. */
export const PREVIEW_ROWS = 3;
export const EXPANDED_ROWS = 25;

export type RowMode = 'preview' | 'expanded25' | 'all';

/**
 * A tool result that is a table.
 *
 * Recognised structurally rather than by tool name, because several tabular operations
 * return this shape and naming them all here would mean editing this file every time one is
 * added. `data` alone is not enough — plenty of results carry an unrelated `data` array — so
 * one of the tabular report fields must be present too.
 */
export interface TabularToolResult {
    [key: string]: unknown;
    data: unknown[];
    returned_rows?: number;
    total_matches?: number;
    filename?: string;
    selected_sheet?: string;
}

export function isTabularToolResult(payload: unknown): payload is TabularToolResult {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        return false;
    }
    const record = payload as Record<string, unknown>;
    if (!Array.isArray(record.data)) {
        return false;
    }
    return (
        'returned_rows' in record ||
        'total_matches' in record ||
        'filename' in record ||
        'selected_sheet' in record
    );
}

export function rowLimitFor(mode: RowMode, totalRows: number): number {
    if (mode === 'all') {
        return totalRows;
    }
    if (mode === 'expanded25') {
        return Math.min(totalRows, EXPANDED_ROWS);
    }
    return Math.min(totalRows, PREVIEW_ROWS);
}

export interface RowModeControl {
    mode: RowMode;
    label: string;
}

export interface TabularToolResultView {
    /** The result as JSON, with `data` cut to the current mode. */
    resultText: string;
    /** "total_matches: 4000 • returned_rows: 4000 • showing 3 rows". */
    summaryText: string;
    controls: RowModeControl[];
}

/**
 * Render a tool result for the inspector.
 *
 * A non-tabular result is simply serialised; the row machinery would have nothing to act on.
 * The offered controls exclude the current mode and any mode that would not change what is
 * shown, so a result with two rows offers nothing to expand.
 */
export function buildToolResultView(payload: unknown, mode: RowMode): TabularToolResultView {
    if (!isTabularToolResult(payload)) {
        return { resultText: serialize(payload), summaryText: '', controls: [] };
    }

    const allRows = payload.data;
    const totalRows = allRows.length;
    const shown = rowLimitFor(mode, totalRows);

    const displayed: Record<string, unknown> = {
        ...(payload as Record<string, unknown>),
        data: allRows.slice(0, shown),
        displayed_rows: shown,
        data_rows_limited: shown < totalRows,
    };

    const summaryParts: string[] = [];
    if ('total_matches' in payload) {
        summaryParts.push(`total_matches: ${String(payload.total_matches)}`);
    }
    if ('returned_rows' in payload) {
        summaryParts.push(`returned_rows: ${String(payload.returned_rows)}`);
    }
    summaryParts.push(`showing ${shown} row${shown === 1 ? '' : 's'}`);

    const controls: RowModeControl[] = [];
    if (totalRows > PREVIEW_ROWS && mode !== 'preview') {
        controls.push({ mode: 'preview', label: 'Show preview' });
    }
    if (totalRows > EXPANDED_ROWS && mode !== 'expanded25') {
        controls.push({ mode: 'expanded25', label: 'Show 25 rows' });
    }
    if (totalRows > PREVIEW_ROWS && mode !== 'all') {
        controls.push({ mode: 'all', label: 'Show all rows' });
    }

    return {
        resultText: serialize(displayed),
        summaryText: summaryParts.join(' • '),
        controls,
    };
}

function serialize(value: unknown): string {
    if (value === null || typeof value === 'undefined') {
        return '';
    }
    if (typeof value === 'string') {
        return value;
    }
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}
