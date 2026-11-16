// enhancedCitations.ts
// Types and helpers for enhanced citations.
//
// An enhanced citation opens the source itself — the PDF page, the image, the video seeked
// to the cited moment — rather than only the extracted text passage. Which viewer applies
// is decided purely from the file extension, mirroring getFileType in
// static/js/chat/chat-enhanced-citations.js; there is no content-type discriminator.

export type EnhancedCitationType =
    | 'image'
    | 'pdf'
    | 'video'
    | 'audio'
    | 'tabular'
    | 'visio';

/**
 * Extension sets, matching chat-enhanced-citations.js exactly.
 *
 * These are deliberately the client-side lists rather than the broader server constants:
 * the server accepts more image formats than a browser will reliably display, so widening
 * these would produce viewers that fail rather than falling back to readable text.
 */
const EXTENSION_TYPES: Record<EnhancedCitationType, readonly string[]> = {
    image: ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif'],
    pdf: ['pdf'],
    video: ['mp4', 'mov', 'avi', 'mkv', 'flv', 'webm', 'wmv', 'm4v', '3gp'],
    audio: ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a'],
    tabular: ['csv', 'xlsx', 'xls', 'xlsm'],
    visio: ['vsdx'],
};

/** Resolve a file name to a viewer type, or null when no viewer applies. */
export function getEnhancedCitationType(fileName?: string): EnhancedCitationType | null {
    if (!fileName || !fileName.includes('.')) {
        return null;
    }
    const extension = fileName.toLowerCase().split('.').pop() ?? '';
    for (const [type, extensions] of Object.entries(EXTENSION_TYPES)) {
        if (extensions.includes(extension)) {
            return type as EnhancedCitationType;
        }
    }
    return null;
}

/** Response of GET /api/enhanced_citations/document_metadata. */
export interface EnhancedCitationMetadata {
    id?: string;
    document_id?: string;
    file_name?: string;
    version?: number | string;
    is_current_version?: boolean;
    /** Per-document opt-out. Only an explicit false disables enhanced rendering. */
    enhanced_citations?: boolean;
}

/**
 * Convert a citation's location value into seconds.
 *
 * Audio and video citations carry a time offset where document citations carry a page
 * number. The value arrives as a plain seconds count, or as HH:MM:SS or MM:SS. Anything
 * unparseable becomes 0, which starts playback at the beginning rather than failing.
 *
 * Mirrors convertTimestampToSeconds in chat-enhanced-citations.js, with one deliberate
 * difference: the clock format is checked BEFORE a bare numeric parse. V1 tries
 * parseFloat first, which silently turns "0:02" into 0 because parseFloat stops at the
 * colon — so a citation two seconds into a recording seeks to the very start. Colons
 * never appear in a plain seconds value, so checking them first is unambiguous.
 */
export function convertTimestampToSeconds(timestamp: unknown): number {
    if (typeof timestamp === 'number' && Number.isFinite(timestamp)) {
        return timestamp;
    }

    if (typeof timestamp === 'string') {
        if (timestamp.includes(':')) {
            const parts = timestamp.split(':').map((part) => Number.parseFloat(part));
            if (parts.every((part) => !Number.isNaN(part))) {
                if (parts.length === 3) {
                    return parts[0] * 3600 + parts[1] * 60 + parts[2];
                }
                if (parts.length === 2) {
                    return parts[0] * 60 + parts[1];
                }
            }
        }

        const numeric = Number.parseFloat(timestamp);
        if (!Number.isNaN(numeric)) {
            return numeric;
        }
    }

    return 0;
}

/** Format a seconds offset for display next to a media citation. */
export function formatTimestamp(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) {
        return '0:00';
    }
    const whole = Math.floor(seconds);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const remainder = whole % 60;

    if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
    }
    return `${minutes}:${String(remainder).padStart(2, '0')}`;
}
