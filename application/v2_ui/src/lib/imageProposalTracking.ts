// imageProposalTracking.ts
// What is known about an image approval that is still running, and how to recognise its image.
//
// An approval is a blocking POST that the server finishes whether or not the browser is still
// there to hear about it. That makes an approval two separate things: a request, which belongs
// to the page that made it, and a piece of work, which does not. This module describes the
// second one — enough about an approval to find its image afterwards, from a page that never
// made the request.
//
// It deliberately imports nothing. The store, the resume watcher and the Node test that
// exercises the matching rules all read it, and a dependency on React, zustand or the API
// client in any of those directions would make the rules untestable on their own.

/** An approval that has been started and whose image has not been seen yet. */
export interface TrackedApproval {
    conversationId: string;
    assistantMessageId: string;
    /** `proposalCardKey` for the card that started it, within that message. */
    cardKey: string;
    /**
     * The proposal fields the image will carry back in its `image_proposal` metadata.
     *
     * Stored as the approval was actually submitted, so an edited prompt still matches: the
     * card's own spec says what the model proposed, not what the user approved.
     */
    visualId: string;
    title: string;
    prompt: string;
    /** Epoch milliseconds. Bounds both the search window and the record's own lifetime. */
    startedAt: number;
    /**
     * True when the record was restored from storage rather than started by this page, so the
     * request behind it is gone and only polling can settle it.
     */
    resumed: boolean;
}

/**
 * Discard a restored record older than this.
 *
 * Long enough that a slow generation is still recovered, short enough that a tab reopened the
 * next morning does not claim to be waiting for something that finished hours ago.
 */
export const STALE_RECORD_MS = 15 * 60 * 1000;

/**
 * Stop polling for a record this long after it was started.
 *
 * Reached only when the image never arrives, which means the work really was lost — the worker
 * was restarted, or the request died with the page. The card says so instead of spinning
 * forever, because an unresolvable spinner is the failure this whole change exists to remove.
 */
export const GIVE_UP_AFTER_MS = 10 * 60 * 1000;

/** Identify one card's approval. Stable across a reload, unique within a conversation. */
export function approvalRecordId(
    conversationId: string,
    assistantMessageId: string,
    cardKey: string,
): string {
    return `${conversationId}\u0000${assistantMessageId}\u0000${cardKey}`;
}

/** Collapse whitespace and lowercase, so two spellings of one prompt still compare equal. */
function comparable(value: unknown): string {
    return String(value ?? '')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();
}

/** Reduce a visual id the way the server and `imageProposalSpec` both do. */
function comparableVisualId(value: unknown): string {
    return String(value ?? '')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/[^a-zA-Z0-9_.-]+/g, '_')
        .replace(/^[_\-.]+|[_\-.]+$/g, '')
        .toLowerCase();
}

/** The shape of one entry from `/api/chat/image-proposals/status`, structurally. */
export interface TrackedApprovalCandidate {
    message_id: string;
    created_at?: string;
    source_assistant_message_id: string;
    visual_id: string;
    title: string;
    prompt: string;
}

/** A generous margin on `created_at`, since the browser clock and the server clock differ. */
const CLOCK_SKEW_MS = 60 * 1000;

/**
 * Whether a stored image is the one this approval is waiting for.
 *
 * The field precedence is `findResultForSpec`'s, and for the same reasons: the visual id is
 * the only field the guidance asks the model to make unique, the prompt is the only field a
 * proposal cannot omit, and the title is the most likely to repeat so it comes last.
 *
 * Two conditions are checked before any of that. The image must have been proposed by the same
 * assistant message, which stops a proposal in one reply claiming the image of an identically
 * worded proposal in another. And it must not predate the approval, which stops a *second*
 * approval of an already-generated proposal resolving instantly against the first one's image.
 */
export function matchesTrackedApproval(
    record: TrackedApproval,
    candidate: TrackedApprovalCandidate,
): boolean {
    if (record.assistantMessageId !== String(candidate.source_assistant_message_id ?? '')) {
        return false;
    }

    if (candidate.created_at) {
        const createdAt = Date.parse(candidate.created_at);
        if (Number.isFinite(createdAt) && createdAt < record.startedAt - CLOCK_SKEW_MS) {
            return false;
        }
    }

    const visualId = comparableVisualId(record.visualId);
    if (visualId) {
        return visualId === comparableVisualId(candidate.visual_id);
    }

    const prompt = comparable(record.prompt);
    if (prompt) {
        return prompt === comparable(candidate.prompt);
    }

    const title = comparable(record.title);
    return Boolean(title) && title === comparable(candidate.title);
}

/**
 * The earliest moment any of these approvals could have produced an image.
 *
 * Sent to the status route as `since`, so a poll reads only what was written while the caller
 * was waiting rather than every proposal image the conversation has ever contained.
 */
export function earliestStart(records: TrackedApproval[]): string | undefined {
    let earliest = Number.POSITIVE_INFINITY;
    for (const record of records) {
        if (record.startedAt < earliest) {
            earliest = record.startedAt;
        }
    }
    if (!Number.isFinite(earliest)) {
        return undefined;
    }
    return new Date(earliest - CLOCK_SKEW_MS).toISOString();
}

/** Whether polling for this record should stop and report that it was lost. */
export function hasExpired(record: TrackedApproval, now = Date.now()): boolean {
    return now - record.startedAt > GIVE_UP_AFTER_MS;
}

/* -------------------------------------------------------------------------- */
/* Storage                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Where restored records are kept.
 *
 * Versioned in the key rather than inside the payload, so a change to the record shape simply
 * leaves the old entry unread instead of requiring it to be migrated or defended against.
 */
export const APPROVAL_STORAGE_KEY = 'simplechat.v2.imageApprovals.v1';

/** Anything that behaves like `sessionStorage`, so this can be exercised without a browser. */
export interface ApprovalStorage {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
    removeItem: (key: string) => void;
}

/**
 * The tab's own `sessionStorage`, or null where there is none.
 *
 * `sessionStorage` and not `localStorage`: it survives the reload this is recovering from, and
 * it does not reach a second tab, which would otherwise show progress for an approval that tab
 * never started and cannot settle.
 *
 * Access is guarded because a browser with storage disabled throws on the property itself, not
 * merely on the read.
 */
export function defaultApprovalStorage(): ApprovalStorage | null {
    try {
        return typeof window === 'undefined' ? null : window.sessionStorage;
    } catch {
        return null;
    }
}

/** Read a record as untrusted input: storage is shared with whatever else wrote to it. */
function readRecord(raw: unknown): TrackedApproval | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return null;
    }

    const source = raw as Record<string, unknown>;
    const conversationId = String(source.conversationId ?? '');
    const assistantMessageId = String(source.assistantMessageId ?? '');
    const cardKey = String(source.cardKey ?? '');
    const startedAt = Number(source.startedAt);

    if (!conversationId || !assistantMessageId || !cardKey || !Number.isFinite(startedAt)) {
        return null;
    }

    return {
        conversationId,
        assistantMessageId,
        cardKey,
        visualId: String(source.visualId ?? ''),
        title: String(source.title ?? ''),
        prompt: String(source.prompt ?? ''),
        startedAt,
        // Anything read back from storage was, by definition, not started by this page.
        resumed: true,
    };
}

/** Load the records worth resuming, dropping malformed and stale ones. */
export function loadApprovals(
    storage: ApprovalStorage | null = defaultApprovalStorage(),
    now = Date.now(),
): TrackedApproval[] {
    if (!storage) {
        return [];
    }

    let parsed: unknown;
    try {
        const raw = storage.getItem(APPROVAL_STORAGE_KEY);
        if (!raw) {
            return [];
        }
        parsed = JSON.parse(raw);
    } catch {
        return [];
    }

    if (!Array.isArray(parsed)) {
        return [];
    }

    const records: TrackedApproval[] = [];
    for (const entry of parsed) {
        const record = readRecord(entry);
        if (record && now - record.startedAt <= STALE_RECORD_MS) {
            records.push(record);
        }
    }
    return records;
}

/** Write the current records, removing the entry entirely once none are left. */
export function saveApprovals(
    records: TrackedApproval[],
    storage: ApprovalStorage | null = defaultApprovalStorage(),
): void {
    if (!storage) {
        return;
    }

    try {
        if (records.length === 0) {
            storage.removeItem(APPROVAL_STORAGE_KEY);
            return;
        }
        storage.setItem(APPROVAL_STORAGE_KEY, JSON.stringify(records));
    } catch {
        // A full or disabled storage costs the reload recovery, not the approval itself.
    }
}
