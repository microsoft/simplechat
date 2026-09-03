// Composer.tsx
// The message input surface: textarea, send/stop control, model / agent / prompt pickers
// and the capability toggles that map onto the /api/chat/stream request fields.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    ArrowUp,
    Bot,
    FileText,
    Gauge,
    Globe,
    Image as ImageIcon,
    Link2,
    Loader2,
    Paperclip,
    Reply,
    Search,
    Square,
    Telescope,
    X,
} from 'lucide-react';
import { useChatStore, type ComposerOptions } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import { uploadDocument } from '../../lib/endpoints';
import { sendCollaborationTyping } from '../../lib/collaboration';
import { agentSelectionKey } from '../../lib/agents';
import { modelSelectionKey, findModel, type ModelCatalogEntry } from '../../lib/models';
import { resolveGating } from '../../lib/composerGating';
import {
    findMentionAtCaret,
    replaceMention,
    type MentionMatch,
    type MentionSuggestion,
} from '../../lib/mentions';
import { useUiStore } from '../../stores/uiStore';
import { toast } from '../../stores/toastStore';
import { chatWidthClass } from '../../lib/chatWidth';
import {
    getModelSupportedLevels,
    REASONING_LABELS,
    supportsReasoning,
} from '../../lib/reasoning';
import { Dropdown, type DropdownOption } from '../ui/Dropdown';
import { AiNotice } from './AiNotice';
import { MentionMenu, useMentionSuggestions } from './MentionMenu';
import { VoiceInput } from './VoiceInput';
import { WebSearchNotice } from './WebSearchNotice';

/** A capability toggle in the composer toolbar. */
function ToolToggle({
    active,
    onClick,
    icon,
    label,
    disabled = false,
}: {
    active: boolean;
    onClick: () => void;
    icon: React.ReactNode;
    label: string;
    disabled?: boolean;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-pressed={active}
            title={label}
            className={clsx(
                'inline-flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-sm transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-40',
                active
                    ? 'border-transparent bg-accent-soft text-accent'
                    : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {icon}
            <span className="hidden lg:inline">{label}</span>
        </button>
    );
}

export function Composer() {
    const { streaming, sendMessage, stopStreaming, activeConversationId } = useChatStore();
    const bootstrap = useBootstrapStore((state) => state.data);
    const features = bootstrap?.features ?? {};

    /**
     * Whether this is a shared conversation, and whether the reader may write in it.
     *
     * `can_post_messages` is the server's decision. A pending invitee can read a shared
     * conversation but not write in it, and a group-visibility conversation grants posting
     * with no membership record at all, so this cannot be worked out from the participant
     * list in the browser.
     */
    const shared = useChatStore((state) => state.activeConversationKind === 'collaborative');
    const loadedCollaboration = useCollaborationStore((state) => state.conversation);
    // Only trusted when it is this conversation's membership. The participants panel used to
    // share this slot, and an unrelated conversation's flags gating the thread on screen was
    // exactly the failure that split them apart.
    const collaboration =
        loadedCollaboration?.id === activeConversationId ? loadedCollaboration : null;
    /**
     * Whether the reader may write here.
     *
     * Deny-by-default in a shared conversation: `can_post_messages` must be explicitly true,
     * so a membership that has not loaded yet — or failed to — leaves the composer disabled
     * rather than offering a Send button to somebody who has not joined. A personal
     * conversation is unaffected.
     */
    const canPost = !shared || collaboration?.can_post_messages === true;
    const awaitingInvite = Boolean(shared && collaboration?.can_accept_invite);
    const checkingAccess = shared && !collaboration;
    const replyTo = useCollaborationStore((state) => state.replyTo);
    const setReplyTo = useCollaborationStore((state) => state.setReplyTo);

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [text, setText] = useState('');
    const [uploading, setUploading] = useState(false);
    const [uploadNotice, setUploadNotice] = useState<string | null>(null);
    const chatWidth = useUiStore((state) => state.chatWidth);

    /** The `@` token under the caret, when the menu should be offering completions for it. */
    const [mention, setMention] = useState<MentionMatch | null>(null);
    const [mentionIndex, setMentionIndex] = useState(0);
    const suggestions = useMentionSuggestions(shared && canPost ? (mention?.query ?? null) : null);

    const [options, setOptions] = useState<ComposerOptions>({
        documentSearch: false,
        webSearch: false,
        imageGeneration: false,
        deepResearch: false,
        urlAccess: false,
        selectedDocumentIds: [],
    });

    // Which controls are relevant right now. Deep research and Read URLs depend on what is
    // currently typed, not only on what is enabled.
    const gating = useMemo(
        () =>
            resolveGating({
                prompt: text,
                features: features as Record<string, unknown>,
                webSearchActive: options.webSearch,
                urlAccessActive: options.urlAccess,
                imageGenerationActive: options.imageGeneration,
            }),
        [text, features, options.webSearch, options.urlAccess, options.imageGeneration],
    );

    // A control that stops being relevant must not leave its option set behind it, or the
    // request would carry a capability the user can no longer see they enabled.
    useEffect(() => {
        setOptions((current) => {
            const next = { ...current };
            let changed = false;
            if (!gating.showUrlAccess && next.urlAccess) {
                next.urlAccess = false;
                changed = true;
            }
            if (!gating.showDeepResearch && next.deepResearch) {
                next.deepResearch = false;
                changed = true;
            }
            return changed ? next : current;
        });
    }, [gating.showUrlAccess, gating.showDeepResearch]);

    // Apply the server's preferred model once bootstrap resolves. Stored as the same
    // selection key the picker uses, so the full identity can be resolved from it.
    useEffect(() => {
        const initial = bootstrap?.catalogs?.initial_model_selection;
        if (!initial) {
            return;
        }
        const key = modelSelectionKey(initial as ModelCatalogEntry);
        if (!key) {
            return;
        }
        setOptions((current) =>
            current.modelDeployment ? current : { ...current, modelDeployment: key },
        );
    }, [bootstrap]);

    const autoGrow = () => {
        const element = textareaRef.current;
        if (!element) {
            return;
        }
        element.style.height = 'auto';
        element.style.height = `${Math.min(element.scrollHeight, 224)}px`;
    };

    useEffect(autoGrow, [text]);

    /**
     * Tell the other participants that this person is writing.
     *
     * Sent as a state change rather than per keystroke — one ping when typing starts and
     * one when it stops — because the server broadcasts every one of these to every other
     * participant's event stream. The stop is also sent on a short idle timer, so walking
     * away mid-sentence clears the indicator instead of leaving it up until the server's own
     * eight-second expiry.
     */
    const typingRef = useRef(false);
    const typingIdleTimer = useRef<number | null>(null);

    const setTyping = (isTyping: boolean) => {
        if (!shared || !activeConversationId || !canPost || typingRef.current === isTyping) {
            return;
        }
        typingRef.current = isTyping;
        void sendCollaborationTyping(activeConversationId, isTyping).catch(() => {
            /* Presence is advisory; a lost ping expires on its own. */
        });
    };

    const stopTyping = () => {
        if (typingIdleTimer.current !== null) {
            window.clearTimeout(typingIdleTimer.current);
            typingIdleTimer.current = null;
        }
        setTyping(false);
    };

    const noteTyping = (value: string) => {
        if (!shared) {
            return;
        }
        setTyping(Boolean(value.trim()));
        if (typingIdleTimer.current !== null) {
            window.clearTimeout(typingIdleTimer.current);
        }
        typingIdleTimer.current = window.setTimeout(() => {
            typingIdleTimer.current = null;
            setTyping(false);
        }, 3000);
    };

    // Leaving the conversation, or the page, must not leave a stale "is typing" behind for
    // everybody else.
    useEffect(
        () => () => {
            if (typingIdleTimer.current !== null) {
                window.clearTimeout(typingIdleTimer.current);
            }
            typingRef.current = false;
        },
        [],
    );

    useEffect(() => {
        // A conversation change invalidates both the draft's mention state and any typing
        // claim made in the conversation being left.
        setMention(null);
        typingRef.current = false;
    }, [activeConversationId]);

    // A model is identified by endpoint + id + provider + deployment together, so the
    // option is keyed on `selection_key` (unique per endpoint) rather than the deployment
    // name, which can repeat across endpoints.
    const modelOptions: DropdownOption[] = (bootstrap?.catalogs?.models ?? []).map(
        (model, index) => ({
            value: modelSelectionKey(model as ModelCatalogEntry) || String(index),
            label:
                (model.display_name as string) ||
                (model.deployment_name as string) ||
                'Model',
        }),
    );

    // The catalog record has no `selection_key` (that is a model concept), so the agent is
    // identified by id, falling back to name for a record that somehow lacks one.
    const agentOptions: DropdownOption[] = (bootstrap?.catalogs?.agents ?? []).map(
        (agent, index) => ({
            value: agentSelectionKey(agent) || String(index),
            label: (agent.display_name as string) || (agent.name as string) || 'Agent',
            description: agent.description as string | undefined,
            group: agent.scope_type ? String(agent.scope_type) : undefined,
        }),
    );

    const promptOptions: DropdownOption[] = (bootstrap?.catalogs?.prompts ?? []).map(
        (prompt, index) => ({
            value: (prompt.id as string) ?? String(index),
            label: (prompt.name as string) || 'Prompt',
            group: prompt.scope_type ? String(prompt.scope_type) : undefined,
        }),
    );

    // Reasoning support is per-model, so the control appears only when the current model
    // actually offers a choice. Resolved from the catalog record rather than the label,
    // since the display name can be anything an administrator typed.
    const reasoningLevels: DropdownOption[] = useMemo(() => {
        const selected = findModel(
            bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
            options.modelDeployment,
        );
        const modelName =
            (selected?.deployment_name as string) ||
            (selected?.model_id as string) ||
            modelOptions.find((option) => option.value === options.modelDeployment)?.label ||
            options.modelDeployment;
        if (!supportsReasoning(modelName)) {
            return [];
        }
        return getModelSupportedLevels(modelName).map((level) => ({
            value: level,
            label: REASONING_LABELS[level],
        }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [options.modelDeployment, bootstrap]);

    const submit = () => {
        if (!text.trim() || streaming || !canPost) {
            return;
        }
        void sendMessage(text, options);
        setText('');
        setMention(null);
        // Sent, so the indicator other people can see must stop now rather than when the
        // idle timer happens to fire.
        stopTyping();
    };

    /**
     * Track the `@` token under the caret.
     *
     * Recomputed from the value and the caret on every change, rather than tracked
     * incrementally, so editing in the middle of a line, pasting and undo all behave the
     * same as typing.
     */
    const syncMention = (element: HTMLTextAreaElement) => {
        if (!shared || !canPost) {
            return;
        }
        const found = findMentionAtCaret(element.value, element.selectionStart ?? 0);
        setMention(found);
        setMentionIndex(0);
    };

    const applySuggestion = (suggestion: MentionSuggestion) => {
        const element = textareaRef.current;
        if (!element || !mention) {
            return;
        }
        const { value, caretIndex } = replaceMention(text, mention, suggestion.mention_text);
        setText(value);
        setMention(null);

        // An "Add to this conversation" row is an action, not just a completion. Inserting
        // the name without performing it left the row dead: the person was neither added nor
        // mentioned, because the mention list is resolved against existing participants only
        // and the server filters it again.
        if (suggestion.kind === 'invite' && activeConversationId) {
            void useCollaborationStore
                .getState()
                .inviteParticipants([
                    {
                        user_id: suggestion.user_id,
                        display_name: suggestion.display_name,
                        email: suggestion.email,
                    },
                ])
                .then(() => {
                    toast.success(`${suggestion.display_name} was added to this conversation.`);
                })
                .catch((error: unknown) => {
                    toast.error(
                        error instanceof Error
                            ? error.message
                            : `${suggestion.display_name} could not be added.`,
                    );
                });
        }

        // Applied after the value change has been rendered, or the browser would put the
        // caret back at the end of the new value.
        window.requestAnimationFrame(() => {
            element.focus();
            element.setSelectionRange(caretIndex, caretIndex);
        });
    };

    const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
        // The mention menu owns these keys while it is open, which is why it is handled
        // before the send: Enter should complete the highlighted name, not send a message
        // containing a half-typed one.
        if (mention && suggestions.length > 0) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                setMentionIndex((index) => (index + 1) % suggestions.length);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                setMentionIndex(
                    (index) => (index - 1 + suggestions.length) % suggestions.length,
                );
                return;
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                applySuggestion(suggestions[mentionIndex]);
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                setMention(null);
                return;
            }
        }

        // Escape also cancels a reply, which is otherwise easy to forget is armed.
        if (event.key === 'Escape' && replyTo) {
            event.preventDefault();
            setReplyTo(null);
            return;
        }

        // Enter sends; Shift+Enter inserts a newline. Matches the classic UI.
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
        }
    };

    const onPickPrompt = (promptId: string | undefined) => {
        setOptions((current) => ({ ...current, promptId }));
        const prompt = bootstrap?.catalogs?.prompts?.find((item) => item.id === promptId);
        if (prompt?.content) {
            setText(String(prompt.content));
            textareaRef.current?.focus();
        }
    };

    const onSelectFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) {
            return;
        }

        setUploading(true);
        setUploadNotice(null);
        try {
            const result = await uploadDocument(file, activeConversationId);
            setUploadNotice(
                result.error ? result.error : `Attached ${file.name}. Processing has started.`,
            );
        } catch (error) {
            setUploadNotice(
                error instanceof Error ? error.message : `Could not upload ${file.name}.`,
            );
        } finally {
            setUploading(false);
            // Reset so re-selecting the same file fires a change event.
            event.target.value = '';
        }
    };

    return (
        <div className="shrink-0 px-4 pb-4">
            <div className={clsx('mx-auto w-full', chatWidthClass(chatWidth))}>
                {uploadNotice && (
                    <p className="mb-2 rounded-xl border border-edge bg-surface-1 px-3 py-2 text-xs text-text-2">
                        {uploadNotice}
                    </p>
                )}

                {/* Above the input, matching the classic interface: the warning belongs
                    next to the message it is about, not below the send button. */}
                <WebSearchNotice active={options.webSearch} />

                <div className="glass glass-edge relative rounded-2xl p-2">
                    {mention && (
                        <MentionMenu
                            suggestions={suggestions}
                            activeIndex={mentionIndex}
                            onSelect={applySuggestion}
                        />
                    )}

                    {replyTo && (
                        <div className="mb-1 flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2">
                            <Reply size={13} className="mt-0.5 shrink-0 text-text-3" />
                            <span className="min-w-0 flex-1 text-xs text-text-2">
                                {replyTo.display_name && (
                                    <span className="font-medium">Replying to {replyTo.display_name}: </span>
                                )}
                                <span className="line-clamp-2">{replyTo.preview}</span>
                            </span>
                            <button
                                type="button"
                                onClick={() => setReplyTo(null)}
                                aria-label="Cancel reply"
                                className="shrink-0 rounded-md p-0.5 text-text-3 hover:bg-surface-3 hover:text-text-1"
                            >
                                <X size={13} />
                            </button>
                        </div>
                    )}

                    <label htmlFor="composer-input" className="sr-only">
                        Message
                    </label>
                    <textarea
                        id="composer-input"
                        ref={textareaRef}
                        rows={1}
                        value={text}
                        disabled={!canPost}
                        onChange={(event) => {
                            setText(event.target.value);
                            syncMention(event.target);
                            noteTyping(event.target.value);
                        }}
                        // The caret can move without the value changing — clicking, or an
                        // arrow key — and the mention under it changes with it.
                        onSelect={(event) => syncMention(event.currentTarget)}
                        onBlur={stopTyping}
                        onKeyDown={onKeyDown}
                        placeholder={
                            checkingAccess
                                ? 'Checking your access to this conversation…'
                                : awaitingInvite
                                  ? 'Join this conversation to reply'
                                  : !canPost
                                    ? 'You do not have permission to write in this conversation'
                                    : shared
                                      ? 'Message the group, or @mention a model or agent to ask the assistant…'
                                      : 'Send a message…'
                        }
                        className={clsx(
                            'w-full resize-none bg-transparent px-3 py-2.5 text-[15px] leading-relaxed',
                            'text-text-1 placeholder:text-text-3 focus:outline-none',
                            'disabled:cursor-not-allowed',
                        )}
                    />

                    <div className="flex flex-wrap items-center gap-1.5 px-1 pt-1">
                        {/* Hidden while generating an image: the request goes to an image
                            endpoint that does not take a chat model. */}
                        {gating.showModelPicker && (
                            <Dropdown
                                options={modelOptions}
                                value={options.modelDeployment}
                                placeholder="Model"
                                onChange={(value) =>
                                    setOptions((current) => ({
                                        ...current,
                                        modelDeployment: value,
                                    }))
                                }
                            />
                        )}

                        {agentOptions.length > 0 && (
                            <Dropdown
                                options={agentOptions}
                                value={options.agentSelection}
                                placeholder="Agent"
                                clearable
                                icon={<Bot size={15} />}
                                onChange={(value) =>
                                    setOptions((current) => ({
                                        ...current,
                                        agentSelection: value,
                                    }))
                                }
                            />
                        )}

                        {promptOptions.length > 0 && (
                            <Dropdown
                                options={promptOptions}
                                value={options.promptId}
                                placeholder="Prompt"
                                clearable
                                icon={<FileText size={15} />}
                                onChange={onPickPrompt}
                            />
                        )}

                        <span className="mx-0.5 h-6 w-px bg-edge-strong" aria-hidden="true" />

                        <ToolToggle
                            active={options.documentSearch}
                            disabled={gating.disabledByImageGeneration}
                            onClick={() =>
                                setOptions((current) => ({
                                    ...current,
                                    documentSearch: !current.documentSearch,
                                }))
                            }
                            icon={<Search size={15} />}
                            label="Documents"
                        />

                        {gating.showWeb && (
                            <ToolToggle
                                active={options.webSearch}
                                disabled={gating.disabledByImageGeneration}
                                onClick={() =>
                                    setOptions((current) => ({
                                        ...current,
                                        webSearch: !current.webSearch,
                                    }))
                                }
                                icon={<Globe size={15} />}
                                label="Web"
                            />
                        )}

                        {gating.showImage && (
                            <ToolToggle
                                active={options.imageGeneration}
                                onClick={() =>
                                    setOptions((current) => ({
                                        ...current,
                                        imageGeneration: !current.imageGeneration,
                                    }))
                                }
                                icon={<ImageIcon size={15} />}
                                label="Image"
                            />
                        )}

                        {/* Deep research sets both source_review_enabled and
                            deep_research_enabled, matching the existing client. It appears
                            only once there is something to research: web search, or URLs
                            in the prompt. */}
                        {gating.showDeepResearch && (
                            <ToolToggle
                                active={options.deepResearch}
                                disabled={gating.disabledByImageGeneration}
                                onClick={() =>
                                    setOptions((current) => ({
                                        ...current,
                                        deepResearch: !current.deepResearch,
                                    }))
                                }
                                icon={<Telescope size={15} />}
                                label="Deep research"
                            />
                        )}

                        {/* Only offered when the prompt actually contains a URL. */}
                        {gating.showUrlAccess && (
                            <ToolToggle
                                active={options.urlAccess}
                                disabled={gating.disabledByImageGeneration}
                                onClick={() =>
                                    setOptions((current) => ({
                                        ...current,
                                        urlAccess: !current.urlAccess,
                                    }))
                                }
                                icon={<Link2 size={15} />}
                                label="Read URLs"
                            />
                        )}

                        {/* Only shown when the selected model offers a real choice; the
                            endpoint strips the parameter for models that reject it. */}
                        {reasoningLevels.length > 0 && (
                            <Dropdown
                                options={reasoningLevels}
                                value={options.reasoningEffort}
                                placeholder="Reasoning"
                                clearable
                                icon={<Gauge size={15} />}
                                onChange={(value) =>
                                    setOptions((current) => ({
                                        ...current,
                                        reasoningEffort: value,
                                    }))
                                }
                            />
                        )}

                        <div className="ml-auto flex items-center gap-1.5">
                            <input
                                ref={fileInputRef}
                                type="file"
                                className="hidden"
                                onChange={onSelectFile}
                            />

                            {features.enable_speech_to_text_input && (
                                <VoiceInput
                                    onTranscribed={(transcript) =>
                                        setText((current) =>
                                            current ? `${current} ${transcript}` : transcript,
                                        )
                                    }
                                />
                            )}

                            <button
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={
                                    uploading ||
                                    !gating.showFileUpload ||
                                    gating.disabledByImageGeneration
                                }
                                title="Attach a file"
                                aria-label="Attach a file"
                                className={clsx(
                                    'inline-flex h-9 w-9 items-center justify-center rounded-xl border border-edge',
                                    'bg-surface-1 text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1',
                                    'disabled:cursor-not-allowed disabled:opacity-40',
                                )}
                            >
                                {uploading ? (
                                    <Loader2 size={16} className="animate-spin" />
                                ) : (
                                    <Paperclip size={16} />
                                )}
                            </button>

                            {streaming ? (
                                <button
                                    type="button"
                                    onClick={stopStreaming}
                                    aria-label="Stop generating"
                                    className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-danger-soft text-danger transition-colors hover:bg-danger hover:text-white"
                                >
                                    <Square size={15} className="fill-current" />
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    onClick={submit}
                                    disabled={!text.trim() || !canPost}
                                    aria-label={
                                        shared && !streaming
                                            ? 'Send to this conversation'
                                            : 'Send message'
                                    }
                                    className={clsx(
                                        'inline-flex h-9 w-9 items-center justify-center rounded-xl',
                                        'bg-accent text-on-accent transition-colors hover:bg-accent-hover',
                                        'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent',
                                    )}
                                >
                                    <ArrowUp size={17} />
                                </button>
                            )}
                        </div>
                    </div>
                </div>

                <AiNotice />
            </div>
        </div>
    );
}
