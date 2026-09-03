// blockRevisions.ts
// Reads and writes the edit history of one diagram inside a message.
//
// A rendered diagram has no identity of its own, so its history is addressed exactly the way
// its colours are — by the block's position among blocks of the same kind, plus a fingerprint
// of the block's *original* source. See blockVisualStyle.ts, which does the same thing for the
// same reasons; the two deliberately share the addressing so they agree about what a block is.
//
// The fingerprint is always taken over the original source, never the current one. That is what
// lets colours survive an edit: recolouring a diagram and then rewriting it should not lose the
// colour, and it would if the key moved every time the source changed.
//
// Nothing here rewrites the message. The stored `content` keeps the diagram the model produced,
// and the current revision is substituted over it at render time. The server does the same
// substitution when it builds the model's history, so the conversation and the screen agree on
// which version is real without the message itself ever being edited.

import { useCallback, useMemo, useState } from 'react';
import { useChatStore } from '../stores/chatStore';
import type { ConversationKind } from '../stores/chatStore';
import { fingerprintSource } from './visualPalettes';
import type {
    BlockRevision,
    BlockRevisionChatTurn,
    BlockRevisionEntry,
} from './endpoints';

export type { BlockRevision, BlockRevisionChatTurn } from './endpoints';

/** Fence languages that can be edited. Matches BLOCK_REVISION_KINDS on the server. */
export const EDITABLE_BLOCK_KINDS = ['mermaid'] as const;
export type EditableBlockKind = (typeof EDITABLE_BLOCK_KINDS)[number];

/** Longest source the server will store. Matches MAX_SOURCE_LENGTH. */
export const MAX_BLOCK_SOURCE_LENGTH = 20000;

/** Longest instruction the assist endpoint accepts. Matches MAX_INSTRUCTION_LENGTH. */
export const MAX_INSTRUCTION_LENGTH = 2000;

/**
 * A line that would close the fence the diagram lives in.
 *
 * The server refuses these outright, because a source containing one would let an edit break
 * out of its own code block and inject markdown into the message. Checked here too so the
 * editor can say so while it is being typed rather than only on save.
 */
const FENCE_BREAKOUT_PATTERN = /^ {0,3}(?:`{3,}|~{3,})/m;

/** Whether a source is something the server will accept, and why not when it is not. */
export function describeSourceProblem(source: string): string | null {
    const candidate = String(source ?? '').trim();
    if (!candidate) {
        return 'The diagram cannot be empty.';
    }
    if (candidate.length > MAX_BLOCK_SOURCE_LENGTH) {
        return `The diagram is too long by ${
            candidate.length - MAX_BLOCK_SOURCE_LENGTH
        } characters.`;
    }
    if (FENCE_BREAKOUT_PATTERN.test(candidate)) {
        return 'The diagram cannot contain a line of backticks or tildes.';
    }
    return null;
}

/**
 * The stored entry for one block, or null when none of it still applies.
 *
 * An entry whose fingerprint no longer matches describes different content — the message was
 * edited, or a mask removed a block and shifted the positions — so it is reported as absent
 * rather than applied to whatever now sits at that position.
 */
function readStoredEntry(
    metadata: unknown,
    kind: string,
    blockIndex: number,
    sourceHash: string,
): BlockRevisionEntry | null {
    if (!metadata || typeof metadata !== 'object') {
        return null;
    }

    const stored = (metadata as Record<string, unknown>).block_revisions;
    if (!stored || typeof stored !== 'object') {
        return null;
    }

    const forKind = (stored as Record<string, unknown>)[kind];
    if (!forKind || typeof forKind !== 'object') {
        return null;
    }

    const entry = (forKind as Record<string, unknown>)[String(blockIndex)];
    if (!entry || typeof entry !== 'object') {
        return null;
    }

    const storedHash = (entry as BlockRevisionEntry).source_hash;
    if (typeof storedHash === 'string' && storedHash && storedHash !== sourceHash) {
        return null;
    }

    return entry as BlockRevisionEntry;
}

/** The revisions in a stored entry, ignoring anything that is not one. */
function readRevisions(entry: BlockRevisionEntry | null): BlockRevision[] {
    if (!entry || !Array.isArray(entry.revisions)) {
        return [];
    }
    return entry.revisions.filter(
        (revision): revision is BlockRevision =>
            Boolean(revision) && typeof revision?.source === 'string',
    );
}

/** Where `current` points, clamped into the revisions that actually exist. */
function readCurrentIndex(entry: BlockRevisionEntry | null, total: number): number {
    const current = entry?.current;
    if (typeof current !== 'number' || !Number.isInteger(current) || total === 0) {
        return 0;
    }
    return Math.min(Math.max(current, 0), total - 1);
}

export interface BlockRevisionState {
    /** The source to render: the current revision, or the original when there is none. */
    source: string;
    /** Every stored version, oldest first, with the original at index zero. */
    revisions: BlockRevision[];
    /** Which of them is showing. */
    currentIndex: number;
    /** The diagram's own sub-conversation. */
    chat: BlockRevisionChatTurn[];
    /** Whether anything other than the original is showing. */
    isEdited: boolean;
    /** Whether this block has any stored history at all. */
    hasHistory: boolean;
    /**
     * Whether a change can be kept.
     *
     * False while a reply is still streaming, because there is no message yet, and false for a
     * block the renderer could not number, because writing it would land in another block's slot.
     */
    canPersist: boolean;
    /** True while a request is in flight, so the editor can disable itself. */
    busy: boolean;
    error: string | null;
    clearError: () => void;
    /** Store an edited source as a new revision and show it. */
    save: (source: string, origin?: 'manual' | 'control', note?: string) => Promise<boolean>;
    /** Show one of the stored revisions. Nothing is discarded. */
    restore: (revisionId: string) => Promise<boolean>;
    /** Ask the model to change the diagram, scoped to this block. */
    ask: (instruction: string) => Promise<boolean>;
}

/**
 * The edit history of one block, and the operations on it.
 *
 * `source` is the block's *original* source — the fence body as the model wrote it. Everything
 * is keyed off its fingerprint, and the hook returns the source that should actually be drawn.
 */
export function useBlockRevisions(
    kind: EditableBlockKind,
    source: string,
    messageId?: string,
    blockIndex?: number,
): BlockRevisionState {
    const sourceHash = useMemo(() => fingerprintSource(source), [source]);
    const canPersist =
        Boolean(messageId) && typeof blockIndex === 'number' && Number.isInteger(blockIndex);

    // Selecting the raw metadata rather than a derived object keeps the subscription stable:
    // zustand compares by reference, and building a new object inside the selector would
    // re-render every diagram in the thread on any store change.
    const storedMetadata = useChatStore((state) =>
        messageId
            ? state.messages.find((message) => message.id === messageId)?.metadata
            : undefined,
    );

    const entry = useMemo(
        () =>
            canPersist
                ? readStoredEntry(storedMetadata, kind, blockIndex as number, sourceHash)
                : null,
        [canPersist, storedMetadata, kind, blockIndex, sourceHash],
    );

    const revisions = useMemo(() => readRevisions(entry), [entry]);
    const currentIndex = readCurrentIndex(entry, revisions.length);
    const chat = useMemo(
        () => (Array.isArray(entry?.chat) ? entry.chat : []),
        [entry],
    );

    const resolved = revisions.length > 0 ? revisions[currentIndex]?.source : '';
    const effectiveSource = resolved || source;

    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const saveBlockRevision = useChatStore((state) => state.saveBlockRevision);
    const restoreBlockRevision = useChatStore((state) => state.restoreBlockRevision);
    const askBlockRevision = useChatStore((state) => state.askBlockRevision);

    /**
     * Run one operation, holding the busy flag and surfacing whatever went wrong.
     *
     * The conversation is captured when the call is made rather than read inside it: a reader
     * can switch threads while a model edit is in flight, and the edit belongs to the
     * conversation it was started in.
     *
     * Its *kind* is captured at the same moment and for the same reason. A shared conversation
     * is written through a different endpoint, and deciding which one later would consult a
     * rail row that may no longer describe the conversation this edit belongs to. Matches how
     * `blockVisualStyle.ts` carries the kind alongside the id.
     */
    const run = useCallback(
        async (
            operation: (
                conversationId: string,
                conversationKind: ConversationKind | null,
            ) => Promise<string | null>,
        ) => {
            if (!canPersist) {
                return false;
            }
            const { activeConversationId, activeConversationKind } = useChatStore.getState();
            const conversationId = activeConversationId ?? '';
            if (!conversationId) {
                return false;
            }

            setBusy(true);
            setError(null);
            try {
                const failure = await operation(conversationId, activeConversationKind);
                if (failure) {
                    setError(failure);
                    return false;
                }
                return true;
            } finally {
                setBusy(false);
            }
        },
        [canPersist],
    );

    const save = useCallback(
        (next: string, origin: 'manual' | 'control' = 'manual', note = '') => {
            const problem = describeSourceProblem(next);
            if (problem) {
                setError(problem);
                return Promise.resolve(false);
            }
            return run((conversationId, conversationKind) =>
                saveBlockRevision({
                    messageId: messageId as string,
                    conversationId,
                    conversationKind,
                    blockKind: kind,
                    blockIndex: blockIndex as number,
                    sourceHash,
                    source: next,
                    originalSource: source,
                    origin,
                    note,
                    expectedRevisionCount: revisions.length || undefined,
                }),
            );
        },
        [blockIndex, kind, messageId, revisions.length, run, saveBlockRevision, source, sourceHash],
    );

    const restore = useCallback(
        (revisionId: string) =>
            run((conversationId, conversationKind) =>
                restoreBlockRevision({
                    messageId: messageId as string,
                    conversationId,
                    conversationKind,
                    blockKind: kind,
                    blockIndex: blockIndex as number,
                    sourceHash,
                    revisionId,
                }),
            ),
        [blockIndex, kind, messageId, restoreBlockRevision, run, sourceHash],
    );

    const ask = useCallback(
        (instruction: string) => {
            const trimmed = instruction.trim();
            if (!trimmed) {
                setError('Describe the change you want.');
                return Promise.resolve(false);
            }
            return run((conversationId, conversationKind) =>
                askBlockRevision({
                    messageId: messageId as string,
                    conversationId,
                    conversationKind,
                    blockKind: kind,
                    blockIndex: blockIndex as number,
                    sourceHash,
                    instruction: trimmed.slice(0, MAX_INSTRUCTION_LENGTH),
                    originalSource: source,
                    expectedRevisionCount: revisions.length || undefined,
                }),
            );
        },
        [askBlockRevision, blockIndex, kind, messageId, revisions.length, run, source, sourceHash],
    );

    return {
        source: effectiveSource,
        revisions,
        currentIndex,
        chat,
        isEdited: revisions.length > 0 && currentIndex > 0,
        hasHistory: revisions.length > 1,
        canPersist,
        busy,
        error,
        clearError: useCallback(() => setError(null), []),
        save,
        restore,
        ask,
    };
}
