// contentScreeningReview.ts
// Pure reviewer view/edit models. Wire adapters bind these to the API's revision tokens.

import { removeCodePointSpan } from './contentScreening';
import type { ScreeningReviewAction, ScreeningReviewMetadata } from './contentScreeningApi';

export interface ScreeningUnit {
    unit_id: string;
    text: string;
    content_hash: string;
    locator: Record<string, unknown>;
    normalization_version: string | number;
    offset_encoding: 'unicode_codepoints';
    text_offset?: number;
    text_total?: number;
}

export interface ScreeningUnitLocation {
    label: string;
    removeUnitLabel?: string;
    /** Present only when the source map explicitly identifies a physical page. */
    physicalPage?: number;
    cell?: {
        sheet_index: number;
        sheet: string;
        row: number;
        column: string | number;
        value_type: string;
    };
}

export function screeningUnitKey(unit: ScreeningUnit): string {
    return `${unit.unit_id}:${unit.text_offset ?? 0}`;
}

export function screeningUnitView(unit: ScreeningUnit): ScreeningUnitView {
    if (!unit || typeof unit.unit_id !== 'string' || !unit.unit_id ||
        typeof unit.content_hash !== 'string' || !unit.content_hash || typeof unit.text !== 'string' ||
        unit.offset_encoding !== 'unicode_codepoints' ||
        !unit.locator || typeof unit.locator !== 'object' || Array.isArray(unit.locator) ||
        !Number.isInteger(unit.text_offset ?? 0) || (unit.text_offset ?? 0) < 0 ||
        (unit.text_total !== undefined && (
            !Number.isInteger(unit.text_total) ||
            unit.text_total < (unit.text_offset ?? 0) + Array.from(unit.text).length
        ))) {
        throw new Error('The canonical evidence or its offset convention could not be verified.');
    }
    const locator = unit.locator;
    const kind = typeof locator.kind === 'string' ? locator.kind : '';
    const labels: Record<string, string> = {
        page: 'Physical page',
        slide: 'Slide',
        segment: 'Extracted segment',
        legacy_segment: 'Legacy indexed segment',
        text: 'Text',
        figure: 'Figure text',
        vision: 'Vision-derived text',
        table_sheet: 'Table sheet',
        table_cell: 'Table cell',
        table_formula: 'Table formula',
        metadata: 'Extracted metadata',
    };
    const coordinates = Object.entries(locator).filter(([key, value]) =>
        key !== 'kind' && (typeof value === 'string' || typeof value === 'number'),
    ).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`);
    const location: ScreeningUnitLocation = {
        label: [Object.hasOwn(labels, kind) ? labels[kind] : 'Source unit', ...coordinates].join(' · '),
        removeUnitLabel: kind === 'page'
            ? 'Remove extracted page'
            : kind === 'slide' ? 'Remove slide unit' : 'Remove source unit',
    };
    if ((kind === 'table_cell' || kind === 'table_formula') &&
        typeof locator.sheet_index === 'number' && typeof locator.sheet === 'string' &&
        typeof locator.row === 'number' &&
        (typeof locator.column === 'string' || typeof locator.column === 'number') &&
        typeof locator.value_type === 'string') {
        location.cell = {
            sheet_index: locator.sheet_index,
            sheet: locator.sheet,
            row: locator.row,
            column: locator.column,
            value_type: locator.value_type,
        };
    }
    return { ...unit, location };
}

export function screeningReviewAllows(review: ScreeningReviewMetadata, action: ScreeningReviewAction): boolean {
    if (!review.etag || !review.allowed_actions?.includes(action)) {
        return false;
    }
    if (action === 'approve_clean' || action === 'approve_with_flags') {
        if (review.coverage?.complete !== true ||
            (review.outcome !== 'pass' && review.outcome !== 'findings') ||
            review.state !== 'pending_review') {
            return false;
        }
    }
    if (action === 'approve_clean') {
        return Boolean(review.candidate_of) && review.outcome === 'pass' && review.finding_count === 0;
    }
    if (action === 'retry_publication') {
        return review.state === 'publishing';
    }
    return true;
}

export interface ScreeningUnitView extends ScreeningUnit {
    location: ScreeningUnitLocation;
}

interface ScreeningEditTarget {
    unit_id: string;
    content_hash: string;
}

export type ScreeningEdit =
    | (ScreeningEditTarget & { type: 'remove_unit' })
    | (ScreeningEditTarget & { type: 'remove_page'; page: number })
    | (ScreeningEditTarget & { type: 'remove_span'; start: number; end: number; selected_text: string })
    | (ScreeningEditTarget & { type: 'replace_cell'; replacement: string })
    | (ScreeningEditTarget & { type: 'clear_cell' });

export type ScreeningEditType = ScreeningEdit['type'];

export interface ScreeningDiff {
    unit_id: string;
    text_offset: number;
    label: string;
    before: string;
    after: string;
    removed: boolean;
}

export function appendScreeningEdit(edits: ScreeningEdit[], edit: ScreeningEdit): ScreeningEdit[] {
    const existing = edits.filter((item) => item.unit_id === edit.unit_id);
    if (existing.some((item) => item.content_hash !== edit.content_hash)) {
        throw new Error('The source changed. Refresh the review and recreate the edit.');
    }
    if (edit.type !== 'remove_span') {
        return [...edits.filter((item) => item.unit_id !== edit.unit_id), edit];
    }
    if (existing.some((item) => item.type !== 'remove_span')) {
        throw new Error('Remove the existing unit or cell edit before selecting a span.');
    }
    if (existing.some((item) => item.type === 'remove_span' && edit.start < item.end && edit.end > item.start)) {
        throw new Error('This span overlaps an existing edit. Remove that edit before replacing it.');
    }
    return [...edits, edit];
}

export function previewScreeningEdits(units: ScreeningUnitView[], edits: ScreeningEdit[]): ScreeningDiff[] {
    for (const edit of edits) {
        const unit = units.find((item) => item.unit_id === edit.unit_id && (
            edit.type !== 'remove_span' || (
                edit.start >= (item.text_offset ?? 0) &&
                edit.end <= (item.text_offset ?? 0) + Array.from(item.text).length
            )
        ));
        if (!unit || unit.content_hash !== edit.content_hash || unit.offset_encoding !== 'unicode_codepoints') {
            throw new Error('The source or offset convention changed. Refresh before editing.');
        }
        if (edit.type === 'remove_page' && unit.location.physicalPage !== edit.page) {
            throw new Error('This unit does not identify the requested physical page.');
        }
        if ((edit.type === 'clear_cell' || edit.type === 'replace_cell') && !unit.location.cell) {
            throw new Error('Cell edits require a structured table-cell locator.');
        }
        if (edit.type === 'remove_span' &&
            Array.from(unit.text).slice(edit.start - (unit.text_offset ?? 0), edit.end - (unit.text_offset ?? 0)).join('') !== edit.selected_text) {
            throw new Error('The selected text no longer matches this source unit.');
        }
    }
    const removedPages = new Set(edits.flatMap((edit) => edit.type === 'remove_page' ? [edit.page] : []));
    const differences: ScreeningDiff[] = [];
    for (const unit of units) {
        const changes = edits.filter((edit) => edit.unit_id === unit.unit_id);
        const removed = changes.some((edit) => edit.type === 'remove_unit') ||
            (unit.location.physicalPage !== undefined && removedPages.has(unit.location.physicalPage));
        let after = unit.text;
        if (removed || changes.some((edit) => edit.type === 'clear_cell')) {
            after = '';
        } else {
            const cellEdit = changes.find((edit) => edit.type === 'replace_cell');
            if (cellEdit?.type === 'replace_cell') {
                after = cellEdit.replacement;
            } else {
                const offset = unit.text_offset ?? 0;
                const end = offset + Array.from(unit.text).length;
                const spans = changes.filter((edit) =>
                    edit.type === 'remove_span' && edit.start >= offset && edit.end <= end,
                ).filter((edit) => edit.type === 'remove_span')
                    .sort((left, right) => right.start - left.start);
                for (const span of spans) {
                    after = removeCodePointSpan(after, span.start - offset, span.end - offset);
                }
            }
        }
        if (removed || after !== unit.text) {
            differences.push({
                unit_id: unit.unit_id,
                text_offset: unit.text_offset ?? 0,
                label: unit.location.label,
                before: unit.text,
                after,
                removed,
            });
        }
    }
    return differences;
}
