// ConversationHandoffDialog.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { ArrowRight, ExternalLink, Loader2, MessageSquare, Send, TriangleAlert, X } from 'lucide-react';
import { chatHrefForConversation } from '../../lib/conversationUrl';
import {
    cancelConversationHandoff,
    createConversationHandoff,
    HANDOFF_STATUS_LABELS,
    previewConversationHandoffDestination,
    resolveConversationReferences,
    type ConversationHandoff,
    type ConversationHandoffDestinationConfig,
    type ConversationSource,
} from '../../lib/conversationReferences';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { ConversationSourcePicker } from './ConversationReferences';

export function ConversationHandoffDialog({
    source,
    onClose,
    onCreated,
}: {
    source: ConversationSource;
    onClose: () => void;
    onCreated?: (handoff: ConversationHandoff) => void;
}) {
    const id = useId();
    const bootstrap = useBootstrapStore((state) => state.data);
    const upsertConversationHandoff = useChatStore((state) => state.upsertConversationHandoff);
    const [destination, setDestination] = useState<ConversationSource | null>(null);
    const [instruction, setInstruction] = useState('');
    const [excerpt, setExcerpt] = useState('');
    const [partial, setPartial] = useState(false);
    const [destinationConfig, setDestinationConfig] = useState<ConversationHandoffDestinationConfig | null>(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewError, setPreviewError] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState('');
    const previewSeq = useRef(0);

    const fallbackModel = String(
        bootstrap?.catalogs?.initial_model_selection?.display_name
        || bootstrap?.catalogs?.initial_model_selection?.deployment_name
        || bootstrap?.catalogs?.models?.[0]?.display_name
        || bootstrap?.catalogs?.models?.[0]?.deployment_name
        || 'Configured destination model',
    );
    const destinationModelLabel = destinationConfig?.model_name
        || destinationConfig?.model_deployment
        || fallbackModel;

    useEffect(() => {
        const seq = ++previewSeq.current;
        setPreviewLoading(true);
        setPreviewError('');
        const timer = window.setTimeout(() => {
            const resolvePromise = resolveConversationReferences(
                [{ kind: 'conversation', id: source.id }],
                destination?.id ?? null,
                instruction.trim(),
            );
            const destPromise = destination?.id
                ? previewConversationHandoffDestination(destination.id).catch(() => undefined)
                : Promise.resolve(undefined);
            Promise.all([resolvePromise, destPromise])
                .then(([resolved, destConfig]) => {
                    if (seq !== previewSeq.current) return;
                    setExcerpt(
                        resolved.excerpts.map((item) => `${item.role}: ${item.content}`).join('\n\n')
                        || 'No visible source messages are available.',
                    );
                    setPartial(Boolean(resolved.partial));
                    setDestinationConfig(destConfig ?? resolved.destination_config ?? null);
                })
                .catch((error: unknown) => {
                    if (seq !== previewSeq.current) return;
                    setPreviewError(error instanceof Error ? error.message : 'Could not preview source evidence.');
                })
                .finally(() => {
                    if (seq === previewSeq.current) {
                        setPreviewLoading(false);
                    }
                });
        }, 120);
        return () => window.clearTimeout(timer);
    }, [source.id, destination?.id, instruction]);

    const submit = async () => {
        if (!destination || !instruction.trim() || submitting) {
            return;
        }
        setSubmitting(true);
        setSubmitError('');
        try {
            const created = await createConversationHandoff({
                source_conversation_id: source.id,
                destination_conversation_id: destination.id,
                instruction: instruction.trim(),
                conversation_references: [{ kind: 'conversation', id: source.id }],
                ...(destinationConfig?.revision ? { destination_config_revision: destinationConfig.revision } : {}),
            });
            const enriched: ConversationHandoff = {
                ...created,
                source_conversation_title: created.source_conversation_title || source.title,
                destination_conversation_title: created.destination_conversation_title || destination.title,
            };
            upsertConversationHandoff(enriched);
            onCreated?.(enriched);
            onClose();
        } catch (error) {
            setSubmitError(error instanceof Error ? error.message : 'Could not send task to conversation.');
        } finally {
            setSubmitting(false);
        }
    };

    return createPortal(
        <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`${id}-title`}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={(event) => {
                if (event.target === event.currentTarget && !submitting) {
                    onClose();
                }
            }}
        >
            <GlassPanel
                elevation="modal"
                edge
                className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl"
                data-conversation-handoff-dialog
            >
                <header className="flex items-center justify-between gap-2 border-b border-edge px-4 py-3">
                    <div>
                        <h2 id={`${id}-title`} className="text-base font-semibold text-text-1">
                            Send To Conversation
                        </h2>
                        <p className="text-xs text-text-3">
                            Source: {source.title || 'Untitled conversation'}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={submitting}
                        aria-label="Close Send To Conversation"
                        className="rounded-lg p-1.5 text-text-3 hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={16} />
                    </button>
                </header>

                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                    <p className="rounded-xl border border-edge bg-surface-2 px-3 py-2 text-xs text-text-2">
                        AI work will start in the destination conversation and queues in FIFO order if that conversation is busy.
                    </p>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-text-2">Destination conversation</span>
                            {destination && (
                                <span className="inline-flex items-center gap-1 rounded-lg bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
                                    <MessageSquare size={12} />
                                    {destination.title || 'Untitled conversation'}
                                </span>
                            )}
                        </div>
                        <ConversationSourcePicker
                            excludeId={source.id}
                            disabled={submitting}
                            onSelect={(selected) => setDestination(selected)}
                        />
                    </div>

                    <div>
                        <label htmlFor={`${id}-instruction`} className="block text-xs font-medium text-text-2">
                            Task instruction
                        </label>
                        <textarea
                            id={`${id}-instruction`}
                            aria-label="Task instruction"
                            rows={3}
                            maxLength={12000}
                            disabled={submitting}
                            value={instruction}
                            onChange={(event) => setInstruction(event.target.value)}
                            placeholder="Write the task instruction to run in the destination conversation…"
                            className="mt-1 w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                        />
                    </div>

                    <div className="space-y-2 rounded-xl border border-edge bg-surface-1 p-3 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-medium text-text-2">Destination model</span>
                            <span className="text-text-1" data-destination-model>
                                {destination ? destinationModelLabel : 'Select a destination conversation'}
                            </span>
                        </div>
                        <div className="border-t border-edge pt-2">
                            <div className="flex items-center justify-between gap-2">
                                <span className="font-medium text-text-2">Bounded source preview</span>
                                {partial && (
                                    <span className="text-[11px] text-text-3">Partial coverage</span>
                                )}
                            </div>
                            {previewLoading ? (
                                <p role="status" className="mt-1 flex items-center gap-1.5 text-text-3">
                                    <Loader2 size={12} className="animate-spin" /> Loading source preview…
                                </p>
                            ) : previewError ? (
                                <p role="alert" className="mt-1 text-danger">{previewError}</p>
                            ) : (
                                <p className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-text-2" data-handoff-source-preview>
                                    {excerpt}
                                </p>
                            )}
                        </div>
                    </div>

                    {submitError && (
                        <p role="alert" className="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2 text-xs text-danger">
                            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                            <span>{submitError}</span>
                        </p>
                    )}
                </div>

                <footer className="flex items-center justify-end gap-2 border-t border-edge px-4 py-3">
                    <GlassButton type="button" size="sm" onClick={onClose} disabled={submitting}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        type="button"
                        size="sm"
                        variant="primary"
                        disabled={!destination || !instruction.trim() || submitting || Boolean(previewError)}
                        onClick={() => void submit()}
                    >
                        {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        Send and start AI
                    </GlassButton>
                </footer>
            </GlassPanel>
        </div>,
        document.body,
    );
}

const CANCELLABLE_STATUSES = new Set(['queued', 'starting', 'running']);

export function ConversationHandoffCards({
    conversationId,
}: {
    conversationId: string | null;
}) {
    const handoffs = useChatStore((state) => state.conversationHandoffs);
    const conversations = useChatStore((state) => state.conversations);
    const metadata = useChatStore((state) => state.metadata);
    const upsertConversationHandoff = useChatStore((state) => state.upsertConversationHandoff);
    const loadConversationHandoffs = useChatStore((state) => state.loadConversationHandoffs);
    const [cancellingId, setCancellingId] = useState<string | null>(null);
    const [errorById, setErrorById] = useState<Record<string, string>>({});

    useEffect(() => {
        if (!conversationId) return;
        const rawList = metadata?.conversation_handoffs;
        if (Array.isArray(rawList)) {
            for (const entry of rawList) {
                if (entry && typeof entry === 'object' && typeof (entry as { id?: unknown }).id === 'string') {
                    upsertConversationHandoff(entry as ConversationHandoff);
                }
            }
            return;
        }
        if (metadata?.has_conversation_handoffs === true) {
            void loadConversationHandoffs(conversationId);
        }
    }, [conversationId, metadata, upsertConversationHandoff, loadConversationHandoffs]);

    const visible = handoffs.filter((handoff) =>
        !conversationId
        || handoff.source_conversation_id === conversationId
        || handoff.destination_conversation_id === conversationId,
    );

    if (visible.length === 0) {
        return null;
    }

    const titleFor = (targetId: string, fallback?: string) =>
        fallback
        || conversations.find((item) => item.id === targetId)?.title
        || 'Private conversation';

    const onCancel = async (handoff: ConversationHandoff) => {
        setCancellingId(handoff.id);
        setErrorById((current) => ({ ...current, [handoff.id]: '' }));
        try {
            const updated = await cancelConversationHandoff(handoff.id, handoff.destination_conversation_id);
            upsertConversationHandoff(updated);
        } catch (error) {
            setErrorById((current) => ({
                ...current,
                [handoff.id]: error instanceof Error ? error.message : 'Could not cancel handoff.',
            }));
        } finally {
            setCancellingId(null);
        }
    };

    return (
        <section aria-label="Conversation handoffs" className="space-y-2" data-conversation-handoffs>
            {visible.map((handoff) => {
                const outgoing = !conversationId || handoff.source_conversation_id === conversationId;
                const linkedId = outgoing ? handoff.destination_conversation_id : handoff.source_conversation_id;
                const linkedTitle = outgoing
                    ? titleFor(handoff.destination_conversation_id, handoff.destination_conversation_title)
                    : titleFor(handoff.source_conversation_id, handoff.source_conversation_title);
                const statusLabel = HANDOFF_STATUS_LABELS[handoff.status] ?? handoff.status;
                const canCancel = CANCELLABLE_STATUSES.has(handoff.status) && !handoff.cancel_requested;
                const cardError = errorById[handoff.id] || handoff.error;

                return (
                    <div
                        key={handoff.id}
                        data-handoff-card={handoff.id}
                        data-handoff-status={handoff.status}
                        className="rounded-xl border border-edge bg-surface-1 px-3 py-2 text-xs text-text-2"
                    >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="inline-flex min-w-0 items-center gap-1.5 font-medium text-text-1">
                                <ArrowRight size={13} className="shrink-0 text-accent" />
                                <span className="truncate">
                                    {outgoing ? `Sent to ${linkedTitle}` : `From ${linkedTitle}`}
                                </span>
                            </span>
                            <div className="flex items-center gap-2">
                                <span
                                    data-handoff-status-label
                                    className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-text-1"
                                >
                                    {statusLabel}
                                </span>
                                <Link
                                    to={chatHrefForConversation(linkedId)}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title="Open conversation in a new tab; your draft stays here"
                                    className="inline-flex items-center gap-1 text-accent underline decoration-edge underline-offset-2"
                                >
                                    {outgoing ? 'Open destination' : 'Open source'}
                                    <ExternalLink size={11} />
                                </Link>
                                {canCancel && (
                                    <button
                                        type="button"
                                        disabled={cancellingId === handoff.id}
                                        onClick={() => void onCancel(handoff)}
                                        aria-label={`Cancel handoff to ${linkedTitle}`}
                                        className="rounded-lg border border-edge px-2 py-0.5 text-text-2 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40"
                                    >
                                        Cancel
                                    </button>
                                )}
                            </div>
                        </div>
                        {handoff.instruction && (
                            <p className="mt-1 line-clamp-2 break-words text-text-3">{handoff.instruction}</p>
                        )}
                        {cardError && (
                            <p role="alert" className="mt-1 text-danger">{cardError}</p>
                        )}
                    </div>
                );
            })}
        </section>
    );
}
