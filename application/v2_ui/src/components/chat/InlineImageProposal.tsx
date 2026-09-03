// InlineImageProposal.tsx
// Renders a ```simpleimage fence as an approval card.
//
// Models are told not to generate images on their own; instead they propose one, and the user
// decides. That is what this card is: a description of an image that does not exist yet, with
// the controls to create it, change the prompt first, or dismiss it. Generation costs money
// and time, so nothing here starts until the user asks for it.
//
// The generated image is not held in this component. Approval appends it to the message
// thread, and it comes back through the proposal scope, so a card shows its image for exactly
// the same reason after a page reload as it does the moment it is approved — there is only
// one path, and no local copy to fall out of step.
//
// Nor is the card's own approval state held here. React rebuilds the markdown subtree a card
// lives in whenever the message re-renders, so state kept in the card would be discarded by
// the very thing the user is waiting for: the arrival of the first approved image. It lives in
// `imageProposalStore`, which outlives the card, the message bubble and the conversation view
// alike — an approval keeps running after the user opens another conversation or reloads the
// page, so the only place its progress can honestly be kept is somewhere that also does.

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Image as ImageIcon, Loader2, Pencil, TriangleAlert, X } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import {
    findResultForSpec,
    normalizePrompt,
    parseImageProposal,
    proposalBadges,
    proposalCardKey,
    PROMPT_MAX_LENGTH,
} from '../../lib/imageProposalSpec';
import { describeQueuePosition, enqueueImageApproval } from '../../lib/imageProposalQueue';
import { approvalRecordId } from '../../lib/imageProposalTracking';
import { useImageProposalStore } from '../../stores/imageProposalStore';
import { resolveImageSource } from '../../lib/images';
import { GlassButton } from '../ui/primitives';
import { ImageLightbox } from './ImageLightbox';
import { IDLE_CARD_STATE } from '../../lib/imageProposalCardState';
import { useImageProposalScope } from './ImageProposalContext';
import type { ChatMessage } from '../../lib/types';

/** Card shell, so every state has the same footprint in the reply. */
function ProposalCard({
    tone = 'default',
    children,
}: {
    tone?: 'default' | 'muted';
    children: React.ReactNode;
}) {
    return (
        <div
            className={clsx(
                'my-3 rounded-2xl border border-edge-strong bg-surface-sunken p-3',
                tone === 'muted' && 'opacity-70',
            )}
        >
            {children}
        </div>
    );
}

/** A card that cannot offer any action: a malformed payload, or one still arriving. */
function ProposalStatusCard({ title, detail }: { title: string; detail: string }) {
    return (
        <ProposalCard tone="muted">
            <div className="flex items-start gap-2">
                <ImageIcon size={15} className="mt-0.5 shrink-0 text-text-3" />
                <div className="min-w-0">
                    <p className="text-sm font-medium text-text-1">{title}</p>
                    <p className="mt-0.5 text-xs text-text-3">{detail}</p>
                </div>
            </div>
        </ProposalCard>
    );
}

/** The approved image, with the same viewer an ordinary image message opens. */
function ApprovedImage({ result, alt }: { result: ChatMessage; alt: string }) {
    const [failed, setFailed] = useState(false);
    const [lightboxOpen, setLightboxOpen] = useState(false);
    const source = resolveImageSource(result.content);

    const naming = useMemo(
        () => ({ filename: result.filename, prompt: result.prompt, id: result.id }),
        [result.filename, result.prompt, result.id],
    );

    if (!source || failed) {
        return (
            <p className="mt-2 text-xs text-text-3">
                The image was generated but could not be displayed here.
            </p>
        );
    }

    return (
        <>
            <button
                type="button"
                onClick={() => setLightboxOpen(true)}
                title="View the full-size image"
                aria-label={`View the full-size image: ${alt}`}
                aria-haspopup="dialog"
                className="mt-2 block cursor-zoom-in overflow-hidden rounded-xl"
            >
                <img
                    src={source.src}
                    alt={alt}
                    loading="lazy"
                    onError={() => setFailed(true)}
                    className="max-h-96 w-full rounded-xl object-contain"
                />
            </button>

            {lightboxOpen && (
                <ImageLightbox
                    source={source}
                    title={alt}
                    naming={naming}
                    onClose={() => setLightboxOpen(false)}
                />
            )}
        </>
    );
}

export function InlineImageProposal({
    source,
    blockIndex,
}: {
    source: string;
    /**
     * This proposal's position among the message's proposal fences, from
     * `rehypeRichBlockIndex`. It is what files the card's approval state under the right
     * entry, so two cards in one message cannot share one.
     */
    blockIndex?: number;
}) {
    const parsed = useMemo(() => parseImageProposal(source), [source]);
    const {
        conversationId,
        assistantMessageId,
        results,
        approveAllToken,
        setPending,
        cardStates,
        updateCardState,
    } = useImageProposalScope();
    const approveImageProposal = useChatStore((state) => state.approveImageProposal);
    const beginApproval = useImageProposalStore((state) => state.beginApproval);
    const endApproval = useImageProposalStore((state) => state.endApproval);

    const spec = parsed.ok ? parsed.spec : null;

    // Two identities, deliberately. `cardKey` names this card within its message and is what
    // the scope files its approval state under, so it has to survive the card being rebuilt.
    // The prompt field's `id` has to be unique across the whole document instead, and every
    // message's first proposal shares a card key, so that one comes from `useId`.
    const cardKey = useMemo(() => proposalCardKey(spec, blockIndex), [spec, blockIndex]);
    const cardId = useId();
    const promptFieldId = `${cardId}-prompt`;

    const cardState = cardStates[cardKey] ?? IDLE_CARD_STATE;
    const { status, queuePosition, failure, editing, resumed } = cardState;
    const prompt = cardState.prompt ?? (spec ? spec.prompt : '');

    const result = useMemo(
        () => (spec ? findResultForSpec(spec, results) : null),
        [spec, results],
    );

    const recordId = useMemo(
        () => approvalRecordId(conversationId, assistantMessageId, cardKey),
        [conversationId, assistantMessageId, cardKey],
    );

    // Only an untouched card is something "Approve all" should act on, and only such a card
    // makes the bulk control worth showing at all.
    const isPending = Boolean(spec) && !result && status === 'idle';

    useEffect(() => {
        setPending(cardKey, isPending);
    }, [cardKey, isPending, setPending]);

    useEffect(() => () => setPending(cardKey, false), [cardKey, setPending]);

    // The image arriving is what ends the wait, whichever route it came by: this approval's own
    // response, a poll that noticed it after a reload, or simply opening a conversation where it
    // had already been stored. Stopping the tracking here rather than in each of those places
    // means none of them can leave a record behind to be resumed forever.
    useEffect(() => {
        if (!result) {
            return;
        }
        endApproval(recordId, 'generated');
    }, [result, recordId, endApproval]);

    const approve = useCallback(async () => {
        if (!spec || !assistantMessageId) {
            return;
        }

        const finalPrompt = normalizePrompt(prompt);
        if (!finalPrompt) {
            updateCardState(cardKey, {
                status: 'error',
                failure: 'Add a prompt before generating the image.',
            });
            return;
        }

        // Read now, not when the queue gets to this approval. A bulk approval can still be
        // draining after the user has opened another conversation, and generating this image
        // into whichever thread is open by then would be both wrong and billable.
        const activeConversationId = useChatStore.getState().activeConversationId;
        if (!activeConversationId) {
            updateCardState(cardKey, {
                status: 'error',
                failure: 'Open a conversation before generating the image.',
            });
            return;
        }

        // Tracked before anything is sent, so the record exists for the whole life of the
        // request — including the part of it that happens after this page is gone. A refusal
        // means an approval for this card is already running and this one would be a second
        // request for an image that is already being paid for.
        const tracked = beginApproval({
            conversationId: activeConversationId,
            assistantMessageId,
            cardKey,
            visualId: spec.visualId,
            title: spec.title,
            prompt: finalPrompt,
            startedAt: Date.now(),
        });
        if (!tracked) {
            return;
        }
        const activeRecordId = approvalRecordId(activeConversationId, assistantMessageId, cardKey);

        updateCardState(cardKey, {
            editing: false,
            failure: '',
            queuePosition: 0,
            status: 'queued',
            resumed: false,
        });

        try {
            await enqueueImageApproval(
                async () => {
                    updateCardState(cardKey, { status: 'generating' });
                    await approveImageProposal(activeConversationId, assistantMessageId, {
                        ...spec,
                        prompt: finalPrompt,
                    });
                },
                (ahead) => updateCardState(cardKey, { queuePosition: ahead }),
            );

            // The image itself arrives through the scope. This only covers the case where it
            // cannot be matched back to this card, so the outcome is still reported.
            updateCardState(cardKey, { status: 'generated' });
            endApproval(activeRecordId, 'generated');
        } catch (error) {
            updateCardState(cardKey, {
                status: 'error',
                failure:
                    error instanceof Error
                        ? error.message
                        : 'The image could not be generated.',
            });
            endApproval(activeRecordId, 'failed');
        }
    }, [
        spec,
        assistantMessageId,
        prompt,
        approveImageProposal,
        cardKey,
        updateCardState,
        beginApproval,
        endApproval,
    ]);

    // "Approve all" is delivered as a token rather than a call, because the scope has no
    // handle on individual cards. Read through a ref so the effect can depend on the token
    // alone and cannot fire on an unrelated re-render.
    const approveIfPending = useRef<() => void>(() => {});
    approveIfPending.current = () => {
        if (isPending) {
            void approve();
        }
    };

    // Only a token that has gone up since this card appeared counts. The token belongs to the
    // message and outlives any one card, so testing it against zero would make a card that
    // remounts after the button was pressed generate an image nobody asked for.
    const seenApproveAllToken = useRef(approveAllToken);

    useEffect(() => {
        if (approveAllToken > seenApproveAllToken.current) {
            seenApproveAllToken.current = approveAllToken;
            approveIfPending.current();
        }
    }, [approveAllToken]);

    if (!parsed.ok) {
        return <ProposalStatusCard title="Image proposal unavailable" detail={parsed.reason} />;
    }

    const activeSpec = parsed.spec;
    const badges = proposalBadges(activeSpec);
    // The spec carries the title the model actually gave, so an untitled proposal cannot claim
    // another's image on a shared default. The heading is supplied here instead.
    const displayTitle = activeSpec.title || 'Generate image';
    const alt = activeSpec.title || 'Generated image';
    const busy = status === 'queued' || status === 'generating';

    if (result) {
        // The badges describe an image that does not exist yet: what kind of visual it would
        // be, which slide it would illustrate, what it would be drawn from. Once the image is
        // here they describe nothing the reader cannot see, so only the title stays.
        return (
            <ProposalCard>
                <div className="flex items-start gap-2">
                    <ImageIcon size={15} className="mt-0.5 shrink-0 text-accent" />
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-text-1">{displayTitle}</p>
                        <ApprovedImage result={result} alt={alt} />
                        {result.model_deployment_name ? (
                            <p className="mt-1.5 text-[11px] text-text-3">
                                {String(result.model_deployment_name)}
                            </p>
                        ) : null}
                    </div>
                </div>
            </ProposalCard>
        );
    }

    if (status === 'cancelled') {
        return (
            <ProposalStatusCard
                title={displayTitle}
                detail="Image proposal dismissed."
            />
        );
    }

    if (status === 'generated') {
        return (
            <ProposalStatusCard
                title={displayTitle}
                detail="Image generated. It has been saved to this conversation."
            />
        );
    }

    return (
        <ProposalCard>
            <div className="flex items-start gap-2">
                <ImageIcon size={15} className="mt-0.5 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-text-1">{displayTitle}</p>
                    {activeSpec.description && (
                        <p className="mt-0.5 text-xs text-text-2">{activeSpec.description}</p>
                    )}
                    {badges.length > 0 && <ProposalBadges badges={badges} />}

                    {editing && (
                        <div className="mt-2">
                            <label
                                htmlFor={promptFieldId}
                                className="mb-1 block text-xs font-medium text-text-2"
                            >
                                Image prompt
                            </label>
                            <textarea
                                id={promptFieldId}
                                autoFocus
                                rows={5}
                                maxLength={PROMPT_MAX_LENGTH}
                                value={prompt}
                                disabled={busy}
                                onChange={(event) =>
                                    updateCardState(cardKey, { prompt: event.target.value })
                                }
                                className="w-full resize-y rounded-xl border border-edge-strong bg-surface-solid px-3 py-2 text-sm text-text-1 outline-none focus:border-accent"
                            />
                        </div>
                    )}

                    {busy && (
                        <p className="mt-2 flex items-center gap-1.5 text-xs text-text-3">
                            <Loader2 size={12} className="animate-spin" />
                            {status === 'queued'
                                ? describeQueuePosition(queuePosition)
                                : resumed
                                  ? 'Still generating from before the page reloaded…'
                                  : 'Generating image…'}
                        </p>
                    )}

                    {status === 'error' && failure && (
                        <p className="mt-2 flex items-start gap-1.5 text-xs text-danger">
                            <TriangleAlert size={12} className="mt-0.5 shrink-0" />
                            {failure}
                        </p>
                    )}

                    {!assistantMessageId && (
                        <p className="mt-2 text-xs text-text-3">
                            Available once the response has finished.
                        </p>
                    )}

                    <div className="mt-2.5 flex flex-wrap gap-2">
                        <GlassButton
                            size="sm"
                            variant="primary"
                            onClick={() => void approve()}
                            disabled={busy || !assistantMessageId}
                            title="Generate this image"
                        >
                            {busy ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <ImageIcon size={14} />
                            )}
                            Approve
                        </GlassButton>
                        <GlassButton
                            size="sm"
                            variant="subtle"
                            onClick={() => updateCardState(cardKey, { editing: !editing })}
                            disabled={busy}
                            aria-expanded={editing}
                            title="Edit the image prompt before generating"
                        >
                            <Pencil size={14} />
                            {editing ? 'Done' : 'Edit'}
                        </GlassButton>
                        <GlassButton
                            size="sm"
                            variant="ghost"
                            onClick={() => updateCardState(cardKey, { status: 'cancelled' })}
                            disabled={busy}
                            title="Dismiss this image proposal"
                        >
                            <X size={14} />
                            Cancel
                        </GlassButton>
                    </div>
                </div>
            </div>
        </ProposalCard>
    );
}

function ProposalBadges({ badges }: { badges: string[] }) {
    return (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
            {badges.map((badge) => (
                <span
                    key={badge}
                    className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-text-2"
                >
                    {badge}
                </span>
            ))}
        </div>
    );
}
