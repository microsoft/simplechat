// masking.ts
// Message masking: hiding part or all of a message from the model and from other readers.
//
// Masks are stored on the message, not applied only at display time
// (functions_message_masking.py). The server strips masked content from the history it sends
// to the model, so the client's job here is to show what is masked and to make the correct
// calls -- never to enforce anything.
//
// A masked range records who applied it and when, so a reader can tell whose redaction they
// are looking at.

import type { ChatMessage } from './types';

/** Actions the mask endpoint accepts (SUPPORTED_MESSAGE_MASK_ACTIONS). */
export type MaskAction =
    | 'mask_all'
    | 'mask_selection'
    | 'unmask_message'
    | 'clear_all_masks';

/** A masked span, as normalised and returned by the server. */
export interface MaskedRange {
    id?: string;
    user_id?: string;
    display_name?: string;
    /** Canonical offsets into the message's raw `content`. */
    start: number;
    end: number;
    text?: string;
    timestamp?: string;
    display_start?: number;
    display_end?: number;
    display_text?: string;
}

export interface MaskState {
    /** The whole message is masked. */
    fullyMasked: boolean;
    ranges: MaskedRange[];
    hasAnyMask: boolean;
    /** Who applied the whole-message mask, when there is one. */
    maskedBy?: string;
    maskedAt?: string;
}

type Bag = Record<string, unknown>;

function bag(value: unknown): Bag {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Bag) : {};
}

/** Read the mask state out of a message's metadata. */
export function readMaskState(message: ChatMessage | undefined): MaskState {
    const metadata = bag(message?.metadata);
    const ranges = Array.isArray(metadata.masked_ranges)
        ? (metadata.masked_ranges as MaskedRange[]).filter(
              (range) =>
                  range &&
                  typeof range.start === 'number' &&
                  typeof range.end === 'number' &&
                  range.end > range.start,
          )
        : [];
    const fullyMasked = metadata.masked === true;

    return {
        fullyMasked,
        ranges,
        hasAnyMask: fullyMasked || ranges.length > 0,
        maskedBy:
            typeof metadata.masked_by_display_name === 'string'
                ? metadata.masked_by_display_name
                : undefined,
        maskedAt:
            typeof metadata.masked_timestamp === 'string'
                ? metadata.masked_timestamp
                : undefined,
    };
}

/**
 * Placeholder substituted for a masked span.
 *
 * Mirrors the citation placeholder: characters that will not appear in prose and survive the
 * markdown pipeline unchanged, so the redaction can be swapped back in as a component after
 * rendering rather than by injecting HTML into model output.
 */
export const MASK_PLACEHOLDER = (index: number) => `\u27E6mask:${index}\u27E7`;

export const MASK_PLACEHOLDER_PATTERN = /\u27E6mask:(\d+)\u27E7/g;

export interface MaskedContent {
    /** Content with each masked span replaced by its placeholder. */
    text: string;
    /** Ranges in the order their placeholders are numbered. */
    ranges: MaskedRange[];
}

/**
 * Replace each masked span in the raw content with a placeholder.
 *
 * `start` and `end` are canonical offsets into `content`, so the spans can be cut directly
 * rather than matched by text. This must run BEFORE citation parsing, which rewrites the
 * string and would invalidate the offsets.
 *
 * Ranges the server could not place are skipped rather than applied at a guessed position:
 * redacting the wrong text is worse than redacting none.
 */
export function applyMasks(content: string, ranges: MaskedRange[]): MaskedContent {
    if (ranges.length === 0) {
        return { text: content, ranges: [] };
    }

    const ordered = [...ranges]
        .filter((range) => range.start >= 0 && range.end <= content.length)
        .sort((left, right) => left.start - right.start);

    if (ordered.length === 0) {
        return { text: content, ranges: [] };
    }

    const parts: string[] = [];
    const applied: MaskedRange[] = [];
    let cursor = 0;

    for (const range of ordered) {
        // The server merges overlapping ranges, but a stale client copy could still hold
        // two that overlap; skipping keeps the output coherent.
        if (range.start < cursor) {
            continue;
        }
        parts.push(content.slice(cursor, range.start));
        parts.push(MASK_PLACEHOLDER(applied.length));
        applied.push(range);
        cursor = range.end;
    }

    parts.push(content.slice(cursor));

    return { text: parts.join(''), ranges: applied };
}

/** Describe who masked a span, for the tooltip on a redaction. */
export function describeMask(range: MaskedRange | undefined): string {
    if (!range) {
        return 'Masked content';
    }
    const who = String(range.display_name ?? '').trim() || 'Unknown User';
    const when = String(range.timestamp ?? '').trim();
    if (!when) {
        return `Masked by ${who}`;
    }
    const parsed = new Date(when);
    const rendered = Number.isNaN(parsed.getTime()) ? when : parsed.toLocaleString();
    return `Masked by ${who} on ${rendered}`;
}

/**
 * Whether the current user may change this message's masks.
 *
 * The server is the authority. It allows the message's author, falling back to the owner of
 * the conversation when a message records no author -- which is the case for assistant
 * messages, so a conversation owner can mask a response in their own conversation
 * (route_backend_chats.py). There is no `can_*` field on any payload, so the client mirrors
 * the rule to decide what to offer and still handles a 403.
 */
export function canMask(message: ChatMessage | undefined, currentUserId: string | undefined): boolean {
    if (!message || !currentUserId) {
        return false;
    }

    const metadata = bag(message.metadata);
    const author = String(bag(metadata.user_info).user_id ?? '').trim();
    if (author) {
        return author === currentUserId;
    }

    // No recorded author: the server falls back to conversation ownership, and the user is
    // only ever shown their own conversations.
    return true;
}

/** A text selection inside a message, in the form the mask endpoint expects. */
export interface MaskSelection {
    start: number;
    end: number;
    text: string;
    display_start: number;
    display_end: number;
    display_text: string;
}

/**
 * Build the selection payload from a DOM selection within a message body.
 *
 * Offsets are counted over the *rendered* text, which is what the user actually selected.
 * They will not line up with the raw markdown when the message contains formatting, and the
 * server expects that: it first tries the offsets, then falls back to locating the selected
 * text in the stored content, and finally to a markdown-stripped projection of it
 * (`_resolve_selection_offsets`). The text therefore matters more than the numbers.
 */
export function buildSelection(root: HTMLElement | null): MaskSelection | null {
    const selection = window.getSelection();
    if (!root || !selection || selection.rangeCount === 0) {
        return null;
    }

    const text = selection.toString();
    if (!text.trim()) {
        return null;
    }

    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
        return null;
    }

    const preceding = range.cloneRange();
    preceding.selectNodeContents(root);
    preceding.setEnd(range.startContainer, range.startOffset);
    const start = preceding.toString().length;
    const end = start + text.length;

    return {
        start,
        end,
        text,
        display_start: start,
        display_end: end,
        display_text: text,
    };
}
