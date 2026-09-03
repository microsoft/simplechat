// imageRevisions.ts
// Reads and writes the version history of one generated image.
//
// The image counterpart of `blockRevisions.ts`, and deliberately much smaller. A diagram is a
// fenced block inside a message and has no identity, so its history is addressed by position
// among blocks of the same kind plus a fingerprint of its original source, with every failure
// mode that implies. **An image is its own message**, so it is addressed by message id and none
// of that machinery is needed.
//
// The other difference worth knowing: a diagram revision is substituted at render time, leaving
// the message's stored content alone. An image revision changes the content, because that
// content *is* a URL and an edited image is served from a different one. The server returns the
// new URL with the revision id in it, which is what stops the browser showing the copy it
// already has.

import { useCallback, useMemo, useState } from 'react';
import { useChatStore } from '../stores/chatStore';
import type { ConversationKind } from '../stores/chatStore';
import { useBootstrapStore } from '../stores/bootstrapStore';
import type {
    ImageRevision,
    ImageRevisionChatTurn,
    ImageRevisionEntry,
    ImageRevisionOrigin,
} from './endpoints';

export type { ImageRevision, ImageRevisionChatTurn, ImageRevisionOrigin } from './endpoints';

/** Longest instruction the server accepts. Matches MAX_INSTRUCTION_LENGTH. */
export const MAX_IMAGE_INSTRUCTION_LENGTH = 2000;

/** Longest prompt the server stores. Matches MAX_PROMPT_LENGTH. */
export const MAX_IMAGE_PROMPT_LENGTH = 4000;

/** Sizes the GPT image models emit. Anything else is rejected by the API. */
export const IMAGE_SIZES = ['1024x1024', '1536x1024', '1024x1536'] as const;
export const IMAGE_SIZE_LABELS: Record<string, string> = {
    '1024x1024': 'Square',
    '1536x1024': 'Landscape',
    '1024x1536': 'Portrait',
};

export const IMAGE_QUALITIES = ['low', 'medium', 'high'] as const;
export const IMAGE_BACKGROUNDS = ['opaque', 'transparent'] as const;

/** How a version came about, in words a reader recognises. */
export const IMAGE_ORIGIN_LABELS: Record<string, string> = {
    original: 'As generated',
    ai: 'AI edit',
    prompt: 'Prompt rewritten',
    control: 'Rendering change',
};

/** What the deployment can do to an existing image. */
export interface ImageEditCapability {
    /** `masked` supports changing a region; `regenerate` can only replace the whole image. */
    mode: 'masked' | 'regenerate';
    model_name: string;
    /** Why region editing is unavailable, worth showing rather than hiding. */
    reason: string;
}

const DEFAULT_CAPABILITY: ImageEditCapability = {
    mode: 'regenerate',
    model_name: '',
    reason: '',
};

/**
 * What the configured image deployment can do.
 *
 * Resolved server-side, because the answer depends on which model the selected deployment runs
 * and which API version is set, and neither is something the browser can see. Defaulting to
 * `regenerate` matters: it is the conservative answer, so a bootstrap that has not resolved
 * offers the operation that always works rather than one that might not.
 */
export function useImageEditCapability(): ImageEditCapability {
    return useBootstrapStore(
        (state) => state.data?.capabilities?.image_edit ?? DEFAULT_CAPABILITY,
    );
}

/** The revisions in a stored entry, ignoring anything that is not one. */
function readRevisions(entry: ImageRevisionEntry | undefined): ImageRevision[] {
    if (!entry || !Array.isArray(entry.revisions)) {
        return [];
    }
    return entry.revisions.filter(
        (revision): revision is ImageRevision => Boolean(revision) && typeof revision?.id === 'string',
    );
}

/** Where `current` points, clamped into the revisions that actually exist. */
function readCurrentIndex(entry: ImageRevisionEntry | undefined, total: number): number {
    const current = entry?.current;
    if (typeof current !== 'number' || !Number.isInteger(current) || total === 0) {
        return 0;
    }
    return Math.min(Math.max(current, 0), total - 1);
}

/** Whether an instruction is something the server will accept, and why not when it is not. */
export function describeInstructionProblem(instruction: string): string | null {
    const candidate = String(instruction ?? '').trim();
    if (!candidate) {
        return 'Describe the change you want.';
    }
    if (candidate.length > MAX_IMAGE_INSTRUCTION_LENGTH) {
        return `That is too long by ${
            candidate.length - MAX_IMAGE_INSTRUCTION_LENGTH
        } characters. Try describing one change at a time.`;
    }
    return null;
}

/** Whether a prompt is something the server will accept, and why not when it is not. */
export function describePromptProblem(prompt: string): string | null {
    const candidate = String(prompt ?? '').trim();
    if (!candidate) {
        return 'The prompt cannot be empty.';
    }
    if (candidate.length > MAX_IMAGE_PROMPT_LENGTH) {
        return `The prompt is too long by ${candidate.length - MAX_IMAGE_PROMPT_LENGTH} characters.`;
    }
    return null;
}

export interface ImageRevisionState {
    /** Every stored version, oldest first, with the original at index zero. */
    revisions: ImageRevision[];
    /** Which of them is showing. */
    currentIndex: number;
    /** The version currently showing, or null when the image has never been changed. */
    current: ImageRevision | null;
    /** The version before the one showing, which is what a compare control reveals. */
    previous: ImageRevision | null;
    /** The image's own sub-conversation. */
    chat: ImageRevisionChatTurn[];
    /** Whether anything other than the original is showing. */
    isEdited: boolean;
    /** Whether this image has any stored history at all. */
    hasHistory: boolean;
    /** Whether a change can be kept. False while a reply is still streaming. */
    canPersist: boolean;
    /** True while a request is in flight, so the editor can disable itself. */
    busy: boolean;
    error: string | null;
    clearError: () => void;
    /** The prompt describing the version showing, which the Prompt tab edits. */
    prompt: string;
    /** Ask the model to change the image. */
    revise: (request: {
        origin?: ImageRevisionOrigin;
        instruction?: string;
        prompt?: string;
        mask?: string;
        maskRegions?: number;
        size?: string;
        quality?: string;
        background?: string;
    }) => Promise<boolean>;
    /** Show one of the stored versions. Nothing is discarded. */
    restore: (revisionId: string) => Promise<boolean>;
    /** The URL of one stored version, for the history thumbnails. */
    revisionUrl: (revisionId: string) => string;
}

/**
 * The version history of one image message, and the operations on it.
 *
 * `fallbackPrompt` is the prompt stored on the message itself, used before any version has been
 * recorded — an image nobody has edited has no revision to read a prompt from, but the Prompt
 * tab should still show what produced it.
 */
export function useImageRevisions(
    messageId: string | undefined,
    fallbackPrompt = '',
    imageEndpoint = '',
): ImageRevisionState {
    const canPersist = Boolean(messageId);

    // Selecting the raw metadata rather than a derived object keeps the subscription stable:
    // zustand compares by reference, and building a new object inside the selector would
    // re-render on any store change.
    const storedMetadata = useChatStore((state) =>
        messageId
            ? state.messages.find((message) => message.id === messageId)?.metadata
            : undefined,
    );

    const entry = useMemo<ImageRevisionEntry | undefined>(() => {
        if (!storedMetadata || typeof storedMetadata !== 'object') {
            return undefined;
        }
        const stored = (storedMetadata as Record<string, unknown>).image_revisions;
        return stored && typeof stored === 'object' ? (stored as ImageRevisionEntry) : undefined;
    }, [storedMetadata]);

    const revisions = useMemo(() => readRevisions(entry), [entry]);
    const currentIndex = readCurrentIndex(entry, revisions.length);
    const chat = useMemo(() => (Array.isArray(entry?.chat) ? entry.chat : []), [entry]);

    const current = revisions.length > 0 ? revisions[currentIndex] ?? null : null;
    const previous = currentIndex > 0 ? revisions[currentIndex - 1] ?? null : null;

    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const reviseImage = useChatStore((state) => state.reviseImage);
    const restoreImageRevision = useChatStore((state) => state.restoreImageRevision);

    /**
     * Run one operation, holding the busy flag and surfacing whatever went wrong.
     *
     * The conversation and its *kind* are captured when the call is made rather than read
     * inside it. A reader can switch threads while a generation is in flight -- these take
     * seconds, not milliseconds -- and the edit belongs to the conversation it was started in.
     * The kind decides which endpoint is used, so reading it later could send a shared
     * conversation's edit to the personal route.
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

    const revise = useCallback(
        (request: {
            origin?: ImageRevisionOrigin;
            instruction?: string;
            prompt?: string;
            mask?: string;
            maskRegions?: number;
            size?: string;
            quality?: string;
            background?: string;
        }) => {
            const origin = request.origin ?? 'ai';
            const problem =
                origin === 'ai'
                    ? describeInstructionProblem(request.instruction ?? '')
                    : origin === 'prompt'
                      ? describePromptProblem(request.prompt ?? '')
                      : null;
            if (problem) {
                setError(problem);
                return Promise.resolve(false);
            }

            return run((conversationId, conversationKind) =>
                reviseImage({
                    messageId: messageId as string,
                    conversationId,
                    conversationKind,
                    origin,
                    instruction: (request.instruction ?? '')
                        .trim()
                        .slice(0, MAX_IMAGE_INSTRUCTION_LENGTH),
                    prompt: (request.prompt ?? '').trim().slice(0, MAX_IMAGE_PROMPT_LENGTH),
                    mask: request.mask,
                    maskRegions: request.maskRegions,
                    size: request.size,
                    quality: request.quality,
                    background: request.background,
                    expectedRevisionCount: revisions.length || undefined,
                    expectedCurrentRevisionId: current?.id,
                }),
            );
        },
        [current?.id, messageId, revisions.length, reviseImage, run],
    );

    const restore = useCallback(
        (revisionId: string) =>
            run((conversationId, conversationKind) =>
                restoreImageRevision({
                    messageId: messageId as string,
                    conversationId,
                    conversationKind,
                    revisionId,
                }),
            ),
        [messageId, restoreImageRevision, run],
    );

    // Each version is addressed by its own id, which is what lets the history show several of
    // them at once: they would otherwise all resolve to the same URL and therefore to the same
    // cached image.
    const revisionUrl = useCallback(
        (revisionId: string) => {
            if (!imageEndpoint || !revisionId) {
                return imageEndpoint;
            }
            const separator = imageEndpoint.includes('?') ? '&' : '?';
            return `${imageEndpoint}${separator}rev=${encodeURIComponent(revisionId)}`;
        },
        [imageEndpoint],
    );

    return {
        revisions,
        currentIndex,
        current,
        previous,
        chat,
        isEdited: revisions.length > 0 && currentIndex > 0,
        hasHistory: revisions.length > 1,
        canPersist,
        busy,
        error,
        clearError: useCallback(() => setError(null), []),
        prompt: current?.prompt || fallbackPrompt,
        revise,
        restore,
        revisionUrl,
    };
}
