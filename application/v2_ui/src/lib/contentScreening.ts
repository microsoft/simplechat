// contentScreening.ts
// Screening markers remain authoritative even when enrollment is switched off.

export type ScreeningState =
    | 'pending_scan'
    | 'scanning'
    | 'scan_error'
    | 'incomplete'
    | 'pending_review'
    | 'remediating'
    | 'publishing'
    | 'cleared'
    | 'approved_with_flags'
    | 'rejected'
    | 'deleting'
    | 'deleted';

export interface ContentScreeningSummary {
    state: ScreeningState;
    available: boolean;
    finding_count: number;
    scan_id?: string | null;
    review_id?: string | null;
    updated_at?: string | null;
}

export interface ScreeningDocument {
    content_screening?: ContentScreeningSummary | null;
}

export interface ScreeningStatePresentation {
    label: string;
    description: string;
    tone: 'muted' | 'warning' | 'danger' | 'success';
    busy: boolean;
}

export const SCREENING_STATES: Record<ScreeningState, ScreeningStatePresentation> = {
    pending_scan: {
        label: 'Awaiting scan',
        description: 'Held until all required screening checks finish.',
        tone: 'warning',
        busy: true,
    },
    scanning: {
        label: 'Scanning',
        description: 'Held while the complete extracted content is screened.',
        tone: 'warning',
        busy: true,
    },
    scan_error: {
        label: 'Scan failed',
        description: 'Held because a required check failed. An authorized reviewer can retry.',
        tone: 'danger',
        busy: false,
    },
    incomplete: {
        label: 'Incomplete coverage',
        description: 'Held because not every required source unit and detector completed.',
        tone: 'danger',
        busy: false,
    },
    pending_review: {
        label: 'Review needed',
        description: 'Held until an authorized reviewer makes an explicit decision.',
        tone: 'warning',
        busy: false,
    },
    remediating: {
        label: 'Remediating',
        description: 'Held while a candidate is edited and rescanned.',
        tone: 'warning',
        busy: true,
    },
    publishing: {
        label: 'Publishing',
        description: 'Held until the approved content has been completely published.',
        tone: 'warning',
        busy: true,
    },
    cleared: {
        label: 'Screened',
        description: 'Every required screening check completed cleanly.',
        tone: 'success',
        busy: false,
    },
    approved_with_flags: {
        label: 'Approved with flags',
        description: 'An authorized reviewer accepted the recorded findings. Use with care.',
        tone: 'warning',
        busy: false,
    },
    rejected: {
        label: 'Rejected · held',
        description: 'Rejected content remains unavailable for ordinary use.',
        tone: 'danger',
        busy: false,
    },
    deleting: {
        label: 'Deleting · held',
        description: 'Unavailable while deletion completes.',
        tone: 'muted',
        busy: true,
    },
    deleted: {
        label: 'Deleted',
        description: 'This content is no longer available.',
        tone: 'muted',
        busy: false,
    },
};

export function screeningPresentation(
    summary: ContentScreeningSummary | null,
): ScreeningStatePresentation {
    return (summary && Object.hasOwn(SCREENING_STATES, summary.state) && SCREENING_STATES[summary.state]) || {
        label: 'Screening unavailable',
        description: 'The screening status could not be verified. Refresh before using this source.',
        tone: 'danger',
        busy: false,
    };
}

export function isScreeningAvailable(document: ScreeningDocument): boolean {
    if (!Object.prototype.hasOwnProperty.call(document, 'content_screening')) {
        return true;
    }
    const summary = document.content_screening;
    return summary?.available === true &&
        (summary.state === 'cleared' || summary.state === 'approved_with_flags');
}

export function isScreeningBusy(document: ScreeningDocument): boolean {
    return Boolean(document.content_screening && screeningPresentation(document.content_screening).busy);
}

/** Reject a selection that splits a surrogate pair instead of moving the requested edit. */
export function utf16ToCodePointOffset(text: string, offset: number): number {
    if (!Number.isInteger(offset) || offset < 0 || offset > text.length) {
        throw new RangeError('The selection is outside the source unit.');
    }
    if (offset > 0 && offset < text.length) {
        const previous = text.charCodeAt(offset - 1);
        const next = text.charCodeAt(offset);
        if (previous >= 0xd800 && previous <= 0xdbff && next >= 0xdc00 && next <= 0xdfff) {
            throw new RangeError('Select a complete Unicode character.');
        }
    }
    return Array.from(text.slice(0, offset)).length;
}

export function codePointSelection(text: string, start: number, end: number) {
    if (end <= start) {
        throw new RangeError('Select the exact text to remove.');
    }
    return {
        start: utf16ToCodePointOffset(text, start),
        end: utf16ToCodePointOffset(text, end),
        selected_text: text.slice(start, end),
    };
}

export function removeCodePointSpan(text: string, start: number, end: number): string {
    const characters = Array.from(text);
    if (!Number.isInteger(start) || !Number.isInteger(end) ||
        start < 0 || end <= start || end > characters.length) {
        throw new RangeError('The span is outside the source unit.');
    }
    return characters.slice(0, start).join('') + characters.slice(end).join('');
}
