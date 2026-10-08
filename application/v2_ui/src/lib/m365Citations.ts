// m365Citations.ts
// Reading and presenting the Microsoft 365 items an answer cites.
//
// An answer that uses SharePoint or OneDrive files, emails or calendar events carries them as
// `m365_citations` on the message, and the conversation lists them under `used_m365_items`. The
// server builds both (functions_m365_citations.py); everything here re-checks what it reads,
// because the records are rendered as links and labels in the reader's own session.

import type {
    ConversationMetadata,
    M365Citation,
    M365CitationKind,
    M365CitationSource,
    UsedM365Item,
} from './types';

/** `m365-` and 16 lowercase hex characters, the id shape the server mints. */
export const M365_CITATION_ID_PATTERN = /^m365-[0-9a-f]{16}$/;

const KIND_SOURCES: Record<M365CitationKind, readonly M365CitationSource[]> = {
    file: ['spo', 'onedrive'],
    email: ['email'],
    event: ['calendar'],
};

const LOCATION_LABELS: Record<M365CitationSource, string> = {
    spo: 'SharePoint',
    onedrive: 'OneDrive',
    email: 'Email',
    calendar: 'Calendar',
};

const MAX_RECORDS = 200;

export function isM365CitationId(value: unknown): value is string {
    return typeof value === 'string' && M365_CITATION_ID_PATTERN.test(value);
}

/**
 * The URL when it is an absolute https link without credentials, otherwise undefined.
 *
 * Only Microsoft Graph supplies these, but they are still checked here before they can become
 * an `href`: a link the reader opens must never run script or point at another scheme.
 */
export function safeM365Url(value: unknown): string | undefined {
    if (typeof value !== 'string') {
        return undefined;
    }
    const trimmed = value.trim();
    if (!trimmed || trimmed.length > 2048 || /\s/.test(trimmed)) {
        return undefined;
    }
    try {
        const parsed = new URL(trimmed);
        if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) {
            return undefined;
        }
        return parsed.toString();
    } catch {
        return undefined;
    }
}

function text(value: unknown, limit = 400): string | undefined {
    if (typeof value !== 'string') {
        return undefined;
    }
    const trimmed = value.replace(/\s+/g, ' ').trim();
    if (!trimmed) {
        return undefined;
    }
    return trimmed.length > limit ? `${trimmed.slice(0, limit - 1)}\u2026` : trimmed;
}

function flag(value: unknown): boolean | undefined {
    return typeof value === 'boolean' ? value : undefined;
}

/** One record, re-validated, or null when it is not a Microsoft 365 citation. */
export function readM365Citation(value: unknown): M365Citation | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null;
    }
    const raw = value as Record<string, unknown>;
    const kind = raw.kind as M365CitationKind;
    const source = raw.source as M365CitationSource;
    if (
        !isM365CitationId(raw.citation_id)
        || typeof kind !== 'string'
        || !Object.prototype.hasOwnProperty.call(KIND_SOURCES, kind)
        || !KIND_SOURCES[kind].includes(source)
    ) {
        return null;
    }
    const size = raw.size_bytes;
    const record: M365Citation = {
        citation_id: raw.citation_id,
        kind,
        source,
        title: text(raw.title, 300) ?? text(raw.file_name, 255) ?? 'Microsoft 365 item',
        location_label: LOCATION_LABELS[source],
        web_url: safeM365Url(raw.web_url),
        cited: flag(raw.cited),
        content_read: flag(raw.content_read),
        file_name: text(raw.file_name, 255),
        mime_type: text(raw.mime_type, 128),
        size_bytes: typeof size === 'number' && Number.isFinite(size) && size >= 0 ? size : undefined,
        modified_at: text(raw.modified_at, 40),
        modified_display: text(raw.modified_display, 40),
        from_name: text(raw.from_name, 200),
        from_address: text(raw.from_address, 320),
        received_at: text(raw.received_at, 40),
        received_display: text(raw.received_display, 80),
        is_read: flag(raw.is_read),
        importance: text(raw.importance, 16)?.toLowerCase(),
        preview: text(raw.preview, 280),
        start: text(raw.start, 40),
        end: text(raw.end, 40),
        time_zone: text(raw.time_zone, 64),
        is_all_day: flag(raw.is_all_day),
        when_display: text(raw.when_display, 120),
        location: text(raw.location, 200),
        organizer_name: text(raw.organizer_name, 200),
    };
    return record;
}

/** Every valid record in a message's `m365_citations`, de-duplicated by id. */
export function readM365Citations(value: unknown): M365Citation[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const byId = new Map<string, M365Citation>();
    for (const entry of value.slice(0, MAX_RECORDS)) {
        const record = readM365Citation(entry);
        if (record && !byId.has(record.citation_id)) {
            byId.set(record.citation_id, record);
        }
    }
    return [...byId.values()];
}

export interface UsedM365Groups {
    files: UsedM365Item[];
    emails: UsedM365Item[];
    events: UsedM365Item[];
    total: number;
}

/** The conversation's Microsoft 365 items for the Documents pane, grouped by kind, newest first. */
export function readUsedM365Items(metadata: ConversationMetadata | null | undefined): UsedM365Groups {
    const raw = Array.isArray(metadata?.used_m365_items) ? metadata.used_m365_items : [];
    const groups: UsedM365Groups = { files: [], emails: [], events: [], total: 0 };
    const seen = new Set<string>();
    for (const entry of raw.slice(0, MAX_RECORDS)) {
        const record = readM365Citation(entry);
        if (!record || seen.has(record.citation_id)) {
            continue;
        }
        seen.add(record.citation_id);
        const source = entry as unknown as Record<string, unknown>;
        const item: UsedM365Item = {
            ...record,
            last_used_at: text(source.last_used_at, 64),
            message_ids: Array.isArray(source.message_ids)
                ? source.message_ids.filter((id): id is string => typeof id === 'string').slice(-20)
                : [],
        };
        if (record.kind === 'file') {
            groups.files.push(item);
        } else if (record.kind === 'email') {
            groups.emails.push(item);
        } else {
            groups.events.push(item);
        }
        groups.total += 1;
    }
    return groups;
}

/** The button text that says where an item opens. */
export function m365OpenLabel(record: Pick<M365Citation, 'source'>): string {
    if (record.source === 'spo') {
        return 'Open in SharePoint';
    }
    if (record.source === 'onedrive') {
        return 'Open in OneDrive';
    }
    return 'Open in Outlook';
}

/** The short text an inline chip shows: a file's name, an email's subject, an event's title. */
export function m365ChipLabel(record: M365Citation): string {
    if (record.kind === 'file') {
        return record.file_name || record.title;
    }
    return record.title;
}

/** A readable file size, such as `1.2 MB`. */
export function formatM365FileSize(bytes: number | undefined): string {
    if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) {
        return '';
    }
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    const units = ['KB', 'MB', 'GB', 'TB'];
    let value = bytes / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** The line under an item's title: where and when for a file, from whom and when for an email, when and where for an event. */
export function m365SecondaryLine(record: M365Citation): string {
    if (record.kind === 'file') {
        return [record.location_label, record.modified_display ? `modified ${record.modified_display}` : '']
            .filter(Boolean)
            .join(' \u00b7 ');
    }
    if (record.kind === 'email') {
        return [record.from_name || record.from_address, record.received_display]
            .filter(Boolean)
            .join(' \u00b7 ');
    }
    return [record.when_display, record.location].filter(Boolean).join(' \u00b7 ');
}

/** One labelled row of a source card. */
export interface M365DetailRow {
    label: string;
    value: string;
}

/** The facts a source card lists for one item, in reading order. */
export function m365DetailRows(record: M365Citation): M365DetailRow[] {
    const rows: M365DetailRow[] = [];
    const push = (label: string, value: string | undefined) => {
        if (value) {
            rows.push({ label, value });
        }
    };
    if (record.kind === 'file') {
        push('Location', record.location_label);
        push('Modified', record.modified_display);
        push('Size', formatM365FileSize(record.size_bytes));
    } else if (record.kind === 'email') {
        const sender = record.from_name && record.from_address
            ? `${record.from_name} <${record.from_address}>`
            : record.from_name || record.from_address;
        push('From', sender);
        push('Received', record.received_display);
        if (typeof record.is_read === 'boolean') {
            push('Status', record.is_read ? 'Read' : 'Unread');
        }
        if (record.importance && record.importance !== 'normal') {
            push('Importance', record.importance === 'high' ? 'High' : record.importance === 'low' ? 'Low' : record.importance);
        }
        push('Preview', record.preview);
    } else {
        push('When', record.when_display);
        push('Where', record.location);
        push('Organizer', record.organizer_name);
    }
    return rows;
}
