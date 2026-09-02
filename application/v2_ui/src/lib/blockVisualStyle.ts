// blockVisualStyle.ts
// Resolves the colours one diagram or chart should use, and saves a change to them.
//
// Three sources are consulted, in increasing precedence: the built-in default, the reader's own
// default from their settings document, and an override saved against this specific block of
// this specific message. Because the override wins outright, recolouring one chart leaves every
// other chart in the conversation exactly as it was.
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

/** The stored override for one block, or null when there is none that still applies. */
function readStoredOverride(
    metadata: unknown,
    kind: VisualStyleKind,
    blockIndex: number,
    sourceHash: string,
): VisualStyle | null {
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

    return sanitizeVisualStyle(entry);
}

export interface BlockVisualStyle {
    /** The colours to render with. */
    style: VisualStyle;
    /** Apply a change, immediately on screen and shortly afterwards on the server. */
    setStyle: (next: VisualStyle) => void;
    /** Drop the block's own colours so it follows the reader's default again. */
    reset: () => void;
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

    /** The reader's unsaved change, which takes precedence until the write settles. */
    const [draft, setDraft] = useState<{ value: VisualStyle | null } | null>(null);
    const [error, setError] = useState<string | null>(null);

    const applyVisualStyle = useChatStore((state) => state.applyVisualStyle);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    /** The change waiting to be written, with the conversation it was made in. */
    const pendingRef = useRef<{ value: VisualStyle | null; conversationId: string } | null>(
        null,
    );

    /** Write a value now, without waiting for the debounce. */
    const write = useCallback(
        (value: VisualStyle | null, conversationId: string) => {
            if (!messageId || typeof blockIndex !== 'number') {
                return;
            }
            void applyVisualStyle(
                messageId,
                conversationId,
                kind,
                blockIndex,
                sourceHash,
                value,
            ).then((saved) => {
                // Either way the draft is dropped: on success the store now holds the stored
                // value, and on failure the block should show what is actually saved rather
                // than a change that never landed.
                setDraft(null);
                setError(saved ? null : 'Those colours could not be saved.');
            });
        },
        [applyVisualStyle, blockIndex, kind, messageId, sourceHash],
    );

    const schedule = useCallback(
        (value: VisualStyle | null) => {
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

            pendingRef.current = { value, conversationId };
            timerRef.current = setTimeout(() => {
                timerRef.current = null;
                pendingRef.current = null;
                write(value, conversationId);
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
                const { value, conversationId } = pendingRef.current;
                pendingRef.current = null;
                writeRef.current(value, conversationId);
            }
        },
        [],
    );

    const setStyle = useCallback(
        (next: VisualStyle) => {
            setError(null);
            setDraft({ value: next });
            schedule(next);
        },
        [schedule],
    );

    const reset = useCallback(() => {
        setError(null);
        setDraft({ value: null });
        schedule(null);
    }, [schedule]);

    const style = useMemo(() => {
        const override = draft ? draft.value : storedOverride;
        return resolveVisualStyle(userDefault, override) ?? DEFAULT_VISUAL_STYLE;
    }, [draft, storedOverride, userDefault]);

    return { style, setStyle, reset, canPersist: addressable, error };
}
