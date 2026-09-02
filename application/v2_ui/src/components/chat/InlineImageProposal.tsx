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

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Image as ImageIcon, Loader2, Pencil, TriangleAlert, X } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import {
    findResultForSpec,
    normalizePrompt,
    parseImageProposal,
    proposalBadges,
    PROMPT_MAX_LENGTH,
} from '../../lib/imageProposalSpec';
import { describeQueuePosition, enqueueImageApproval } from '../../lib/imageProposalQueue';
import { resolveImageSource } from '../../lib/images';
import { GlassButton } from '../ui/primitives';
import { ImageLightbox } from './ImageLightbox';
import { useImageProposalScope } from './ImageProposalContext';
import type { ChatMessage } from '../../lib/types';

/**
 * Where an approval has got to.
 *
 * `generated` means the server reported success but the stored image could not be matched
 * back to this card. The image exists either way, so the card says so rather than sitting on
 * a spinner that will never resolve.
 */
type ApprovalStatus = 'idle' | 'queued' | 'generating' | 'generated' | 'error' | 'cancelled';

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

export function InlineImageProposal({ source }: { source: string }) {
    const parsed = useMemo(() => parseImageProposal(source), [source]);
    const { assistantMessageId, results, approveAllToken, setPending } = useImageProposalScope();
    const approveImageProposal = useChatStore((state) => state.approveImageProposal);

    const cardId = useId();
    const promptFieldId = `${cardId}-prompt`;

    const [status, setStatus] = useState<ApprovalStatus>('idle');
    const [queuePosition, setQueuePosition] = useState(0);
    const [failure, setFailure] = useState('');
    const [editing, setEditing] = useState(false);
    const [prompt, setPrompt] = useState(parsed.ok ? parsed.spec.prompt : '');

    const spec = parsed.ok ? parsed.spec : null;
    const result = useMemo(
        () => (spec ? findResultForSpec(spec, results) : null),
        [spec, results],
    );

    // Only an untouched card is something "Approve all" should act on, and only such a card
    // makes the bulk control worth showing at all.
    const isPending = Boolean(spec) && !result && status === 'idle';

    useEffect(() => {
        setPending(cardId, isPending);
    }, [cardId, isPending, setPending]);

    useEffect(() => () => setPending(cardId, false), [cardId, setPending]);

    const approve = useCallback(async () => {
        if (!spec || !assistantMessageId) {
            return;
        }

        const finalPrompt = normalizePrompt(prompt);
        if (!finalPrompt) {
            setStatus('error');
            setFailure('Add a prompt before generating the image.');
            return;
        }

        // Read now, not when the queue gets to this approval. A bulk approval can still be
        // draining after the user has opened another conversation, and generating this image
        // into whichever thread is open by then would be both wrong and billable.
        const conversationId = useChatStore.getState().activeConversationId;
        if (!conversationId) {
            setStatus('error');
            setFailure('Open a conversation before generating the image.');
            return;
        }

        setEditing(false);
        setFailure('');
        setQueuePosition(0);
        setStatus('queued');

        try {
            await enqueueImageApproval(async () => {
                setStatus('generating');
                await approveImageProposal(conversationId, assistantMessageId, {
                    ...spec,
                    prompt: finalPrompt,
                });
            }, setQueuePosition);

            // The image itself arrives through the scope. This only covers the case where it
            // cannot be matched back to this card, so the outcome is still reported.
            setStatus('generated');
        } catch (error) {
            setStatus('error');
            setFailure(
                error instanceof Error ? error.message : 'The image could not be generated.',
            );
        }
    }, [spec, assistantMessageId, prompt, approveImageProposal]);

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
        return (
            <ProposalCard>
                <div className="flex items-start gap-2">
                    <ImageIcon size={15} className="mt-0.5 shrink-0 text-accent" />
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-text-1">{displayTitle}</p>
                        {badges.length > 0 && <ProposalBadges badges={badges} />}
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
                                onChange={(event) => setPrompt(event.target.value)}
                                className="w-full resize-y rounded-xl border border-edge-strong bg-surface-solid px-3 py-2 text-sm text-text-1 outline-none focus:border-accent"
                            />
                        </div>
                    )}

                    {busy && (
                        <p className="mt-2 flex items-center gap-1.5 text-xs text-text-3">
                            <Loader2 size={12} className="animate-spin" />
                            {status === 'queued'
                                ? describeQueuePosition(queuePosition)
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
                            onClick={() => setEditing((open) => !open)}
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
                            onClick={() => setStatus('cancelled')}
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
