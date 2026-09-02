// blockVisualStyle.ts
// Resolves the colours and the size one diagram or chart should use, and saves a change to
// either.
//
// Three sources are consulted for colours, in increasing precedence: the built-in default, the
// reader's own default from their settings document, and an override saved against this
// specific block of this specific message. Because the override wins outright, recolouring one
// chart leaves every other chart in the conversation exactly as it was.
//
// The size is simpler: a block either has a height someone dragged it to or it does not, and
// the two are stored in the same entry but changed independently. Resetting colours must not
// resize a block, and resizing a block must not stop it following the reader's palette.
//
// A block has no identity of its own, so an override is addressed by the block's position among
// blocks of the same kind in the message, together with a fingerprint of its source. If the
// message is later edited or masked such that the block at that position is different content,
// the fingerprint no longer matches and the override is ignored rather than applied to the
// wrong diagram.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useChatStore } from '../stores/chatStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import {
    DEFAULT_VISUAL_STYLE,
    fingerprintSource,
    resolveVisualStyle,
    sanitizeVisualStyle,
    type VisualStyle,
    type VisualStyleKind,
} from './visualPalettes';

/** Settings keys holding the reader's default for each kind of block. */
export const VISUAL_STYLE_SETTING_KEYS: Record<VisualStyleKind, string> = {
    mermaid: 'v2MermaidStyle',
    simplechart: 'v2ChartStyle',
};

/**
 * How long to wait before writing.
 *
 * A colour input reports every step of a drag, so without this a single adjustment would post
 * dozens of times. Matches the debounce the settings store uses for the same reason.
 */
const SAVE_DEBOUNCE_MS = 400;

/** The stored entry for one block, or null when there is none that still applies. */
function readStoredEntry(
    metadata: unknown,
    kind: VisualStyleKind,
    blockIndex: number,
    sourceHash: string,
): Record<string, unknown> | null {
    if (!metadata || typeof metadata !== 'object') {
        return null;
    }

    const styles = (metadata as Record<string, unknown>).visual_styles;
    if (!styles || typeof styles !== 'object') {
        return null;
    }

    const forKind = (styles as Record<string, unknown>)[kind];
    if (!forKind || typeof forKind !== 'object') {
        return null;
    }

    const entry = (forKind as Record<string, unknown>)[String(blockIndex)];
    if (!entry || typeof entry !== 'object') {
        return null;
    }

    // An entry saved before fingerprints existed has none; it is trusted, because the only
    // alternative is silently discarding a choice the reader made.
    const stored = (entry as Record<string, unknown>).source_hash;
    if (typeof stored === 'string' && stored && stored !== sourceHash) {
        return null;
    }

    return entry as Record<string, unknown>;
}

/**
 * The stored colour override for one block, or null when there is none.
 *
 * An entry that carries only a height is not a colour override. Treating it as one would stop
 * a diagram someone merely resized from following the reader's default palette, which is a
 * change they never asked for. The presence of `palette` is what distinguishes the two,
 * because the server writes the colour fields together or not at all.
 */
function readStoredOverride(
    metadata: unknown,
    kind: VisualStyleKind,
    blockIndex: number,
    sourceHash: string,
): VisualStyle | null {
    const entry = readStoredEntry(metadata, kind, blockIndex, sourceHash);
    if (!entry || typeof entry.palette !== 'string') {
        return null;
    }
    return sanitizeVisualStyle(entry);
}

/** The stored stage height for one block, or null when it has none. */
function readStoredHeight(
    metadata: unknown,
    kind: VisualStyleKind,
    blockIndex: number,
    sourceHash: string,
): number | null {
    const entry = readStoredEntry(metadata, kind, blockIndex, sourceHash);
    const height = entry?.height;
    if (typeof height !== 'number' || !Number.isFinite(height) || height <= 0) {
        return null;
    }
    return Math.round(height);
}

export interface BlockVisualStyle {
    /** The colours to render with. */
    style: VisualStyle;
    /** Apply a change, immediately on screen and shortly afterwards on the server. */
    setStyle: (next: VisualStyle) => void;
    /** Drop the block's own colours so it follows the reader's default again. */
    reset: () => void;
    /** The height the block was left at, or null to size it automatically. */
    height: number | null;
    /** Resize the block, immediately on screen and shortly afterwards on the server. */
    setHeight: (next: number) => void;
    /** Drop the chosen height so the block is sized automatically again. */
    resetHeight: () => void;
    /**
     * True when the choice will be kept.
     *
     * False while a reply is still streaming, because there is no message yet, and false for a
     * block the renderer could not number, because saving it would write into another block's
     * slot.
     */
    canPersist: boolean;
    error: string | null;
}

/**
 * One queued change.
 *
 * `undefined` on either field means "this change says nothing about that", which is how a
 * resize leaves the colours alone and a recolour leaves the size alone. Queued changes merge
 * rather than replace, so a recolour immediately followed by a drag still writes both.
 */
interface PendingChange {
    style?: VisualStyle | null;
    height?: number | null;
    conversationId: string;
}

export function useBlockVisualStyle(
    kind: VisualStyleKind,
    source: string,
    messageId?: string,
    blockIndex?: number,
): BlockVisualStyle {
    const sourceHash = useMemo(() => fingerprintSource(source), [source]);
    const addressable =
        Boolean(messageId) && typeof blockIndex === 'number' && Number.isInteger(blockIndex);

    const rawUserDefault = useUserSettingsStore(
        (state) => state.settings[VISUAL_STYLE_SETTING_KEYS[kind]],
    );
    const userDefault = useMemo(
        () => sanitizeVisualStyle(rawUserDefault),
        [rawUserDefault],
    );

    // Selecting the raw entry rather than a derived object keeps the subscription stable:
    // zustand compares by reference, and sanitising inside the selector would allocate a new
    // object on every store change and re-render every block in the thread.
    const storedMetadata = useChatStore((state) =>
        messageId
            ? state.messages.find((message) => message.id === messageId)?.metadata
            : undefined,
    );
    const storedOverride = useMemo(
        () =>
            addressable
                ? readStoredOverride(storedMetadata, kind, blockIndex as number, sourceHash)
                : null,
        [addressable, storedMetadata, kind, blockIndex, sourceHash],
    );
    const storedHeight = useMemo(
        () =>
            addressable
                ? readStoredHeight(storedMetadata, kind, blockIndex as number, sourceHash)
                : null,
        [addressable, storedMetadata, kind, blockIndex, sourceHash],
    );

    /** The reader's unsaved change, which takes precedence until the write settles. */
    const [draft, setDraft] = useState<{ value: VisualStyle | null } | null>(null);
    const [heightDraft, setHeightDraft] = useState<{ value: number | null } | null>(null);
    const [error, setError] = useState<string | null>(null);

    const applyVisualStyle = useChatStore((state) => state.applyVisualStyle);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    /** The change waiting to be written, with the conversation it was made in. */
    const pendingRef = useRef<PendingChange | null>(null);

    const style = useMemo(() => {
        const override = draft ? draft.value : storedOverride;
        return resolveVisualStyle(userDefault, override) ?? DEFAULT_VISUAL_STYLE;
    }, [draft, storedOverride, userDefault]);

    const height = heightDraft ? heightDraft.value : storedHeight;

    // Read when a resize is scheduled, so the write carries the colours the block actually has
    // rather than re-deriving them: sending the resolved style would pin a block that is only
    // following the reader's default.
    const effectiveOverrideRef = useRef<VisualStyle | null>(null);
    effectiveOverrideRef.current = draft ? draft.value : storedOverride;

    /** Write a change now, without waiting for the debounce. */
    const write = useCallback(
        (change: PendingChange) => {
            if (!messageId || typeof blockIndex !== 'number') {
                return;
            }
            const styleForWrite =
                change.style === undefined ? effectiveOverrideRef.current : change.style;

            void applyVisualStyle(
                messageId,
                change.conversationId,
                kind,
                blockIndex,
                sourceHash,
                styleForWrite,
                change.height,
            ).then((saved) => {
                // Either way the drafts are dropped: on success the store now holds the stored
                // values, and on failure the block should show what is actually saved rather
                // than a change that never landed.
                setDraft(null);
                setHeightDraft(null);
                setError(saved ? null : 'That change could not be saved.');
            });
        },
        [applyVisualStyle, blockIndex, kind, messageId, sourceHash],
    );

    const schedule = useCallback(
        (change: Omit<PendingChange, 'conversationId'>) => {
            if (timerRef.current !== null) {
                clearTimeout(timerRef.current);
                timerRef.current = null;
            }
            if (!addressable) {
                return;
            }

            // Captured now rather than read when the write fires: the conversation can change
            // between the two, and this change belongs to the one it was made in.
            const conversationId = useChatStore.getState().activeConversationId ?? '';
            if (!conversationId) {
                return;
            }

            const merged: PendingChange = {
                ...(pendingRef.current ?? {}),
                ...(change.style === undefined ? {} : { style: change.style }),
                ...(change.height === undefined ? {} : { height: change.height }),
                conversationId,
            };

            pendingRef.current = merged;
            timerRef.current = setTimeout(() => {
                timerRef.current = null;
                pendingRef.current = null;
                write(merged);
            }, SAVE_DEBOUNCE_MS);
        },
        [addressable, write],
    );

    // A change made moments before the thread is closed or scrolled away is still a change the
    // reader made, so a pending write is issued on unmount rather than discarded.
    const writeRef = useRef(write);
    writeRef.current = write;
    useEffect(
        () => () => {
            if (timerRef.current !== null) {
                clearTimeout(timerRef.current);
                timerRef.current = null;
            }
            if (pendingRef.current) {
                const change = pendingRef.current;
                pendingRef.current = null;
                writeRef.current(change);
            }
        },
        [],
    );

    const setStyle = useCallback(
        (next: VisualStyle) => {
            setError(null);
            setDraft({ value: next });
            schedule({ style: next });
        },
        [schedule],
    );

    const reset = useCallback(() => {
        setError(null);
        setDraft({ value: null });
        schedule({ style: null });
    }, [schedule]);

    const setHeight = useCallback(
        (next: number) => {
            setError(null);
            setHeightDraft({ value: Math.round(next) });
            schedule({ height: Math.round(next) });
        },
        [schedule],
    );

    const resetHeight = useCallback(() => {
        setError(null);
        setHeightDraft({ value: null });
        schedule({ height: null });
    }, [schedule]);

    return {
        style,
        setStyle,
        reset,
        height,
        setHeight,
        resetHeight,
        canPersist: addressable,
        error,
    };
}
