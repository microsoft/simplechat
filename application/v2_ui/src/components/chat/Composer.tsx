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
    Search,
    Square,
    Telescope,
} from 'lucide-react';
import { useChatStore, type ComposerOptions } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { uploadDocument } from '../../lib/endpoints';
import { agentSelectionKey } from '../../lib/agents';
import { modelSelectionKey, findModel, type ModelCatalogEntry } from '../../lib/models';
import { resolveGating } from '../../lib/composerGating';
import { useUiStore } from '../../stores/uiStore';
import { chatWidthClass } from '../../lib/chatWidth';
import {
    getModelSupportedLevels,
    reasoningModelKey,
    resolveReasoningEffort,
    REASONING_LABELS,
    supportsReasoning,
    type ReasoningEffortSettings,
} from '../../lib/reasoning';
import { Dropdown, type DropdownOption } from '../ui/Dropdown';
import { toast } from '../../stores/toastStore';
import { AiNotice } from './AiNotice';
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
    // The level chosen per model, shared with the classic interface. Read from the store
    // rather than held here so a change made anywhere is reflected without a reload.
    const reasoningEffortSettings = useUserSettingsStore(
        (state) => state.settings.reasoningEffortSettings as ReasoningEffortSettings | undefined,
    );
    // Unlike every other preference V2 writes, this one is a map rather than a scalar, and
    // the route stores it whole. The app renders as soon as the bootstrap resolves, which is
    // not necessarily after the settings have arrived, so merging into a map that has not
    // been read would replace every other model's level with the single entry just chosen.
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const settingsFailed = useUserSettingsStore((state) => state.error !== null);
    const settingsLoaded = !settingsLoading && !settingsFailed;

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [text, setText] = useState('');
    const [uploading, setUploading] = useState(false);
    const [uploadNotice, setUploadNotice] = useState<string | null>(null);
    const chatWidth = useUiStore((state) => state.chatWidth);

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
    const selectedModel = findModel(
        bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
        options.modelDeployment,
    );

    // Both the offered levels and the key the chosen level is stored under come from this
    // one name, so the classic interface finds the same entry in the shared map.
    const reasoningKey = reasoningModelKey(
        selectedModel,
        modelOptions.find((option) => option.value === options.modelDeployment)?.label ||
            options.modelDeployment,
    );

    const reasoningLevels: DropdownOption[] = useMemo(() => {
        if (!supportsReasoning(reasoningKey)) {
            return [];
        }
        return getModelSupportedLevels(reasoningKey).map((level) => ({
            value: level,
            label: REASONING_LABELS[level],
        }));
    }, [reasoningKey]);

    // The level in effect is derived from the model and what has been stored for it, never
    // remembered on its own. A level chosen for one model must not follow the user to
    // another, and a model that offers no choice must not carry one into the request at all.
    //
    // Nothing is derived without a model to derive it from. A single-endpoint deployment has
    // no model catalog, so the offered levels are a guess and a default would attach a
    // parameter to every request that the user never asked for. There the control stays
    // opt-in for the session, as it was before.
    const derivedReasoning =
        reasoningKey && reasoningLevels.length > 0
            ? resolveReasoningEffort(reasoningKey, reasoningEffortSettings)
            : undefined;

    useEffect(() => {
        if (!reasoningKey) {
            return;
        }
        setOptions((current) =>
            current.reasoningEffort === derivedReasoning
                ? current
                : { ...current, reasoningEffort: derivedReasoning },
        );
    }, [reasoningKey, derivedReasoning]);

    /**
     * Levels chosen before the stored map arrived.
     *
     * Held rather than written, because the map is stored whole and merging into one that
     * has not been read would discard every other model's level. Held rather than dropped,
     * because a preference that quietly fails to save is the defect this change is fixing.
     * A map rather than a single entry, so choosing for two models in that window keeps both.
     */
    const pendingLevels = useRef<ReasoningEffortSettings>({});

    const storeReasoningLevels = (levels: ReasoningEffortSettings) => {
        // Read at write time rather than from the render's closure, so a map that arrived
        // between the choice and the write is merged into rather than replaced.
        const saved = useUserSettingsStore.getState().settings
            .reasoningEffortSettings as ReasoningEffortSettings | undefined;
        useUserSettingsStore.getState().update({
            reasoningEffortSettings: { ...saved, ...levels },
        });
    };

    useEffect(() => {
        if (!settingsLoaded || Object.keys(pendingLevels.current).length === 0) {
            return;
        }
        const held = pendingLevels.current;
        pendingLevels.current = {};
        storeReasoningLevels(held);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [settingsLoaded]);

    /** Store a chosen level against the current model, for both interfaces to read back. */
    const chooseReasoningLevel = (level: string | undefined) => {
        if (!level) {
            // Only reachable where the control is clearable, which is where no level is
            // stored, so there is nothing to clear but the session's own choice.
            setOptions((current) => ({ ...current, reasoningEffort: undefined }));
            return;
        }

        setOptions((current) => ({ ...current, reasoningEffort: level }));

        // A single-endpoint deployment has no model catalog, so there is no identity to
        // store the choice against. It still applies for the rest of the session.
        if (!reasoningKey) {
            return;
        }

        if (settingsLoaded) {
            storeReasoningLevels({ [reasoningKey]: level });
            return;
        }

        if (settingsFailed) {
            // The map was never read, so writing would replace it. Saying so is better than
            // a control that appears to save and does not.
            toast.error(
                'Your preferences could not be loaded, so this reasoning level applies to this conversation only.',
            );
            return;
        }

        pendingLevels.current = { ...pendingLevels.current, [reasoningKey]: level };
    };

    /**
     * Remember the chosen model.
     *
     * The bootstrap resolves `initial_model_selection` from these keys on the next visit;
     * without them the composer silently falls back to the first entry in the catalog.
     */
    const rememberModelSelection = (selection: string | undefined) => {
        const model = findModel(
            bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
            selection,
        );
        if (!model) {
            return;
        }

        const deployment =
            typeof model.deployment_name === 'string' ? model.deployment_name.trim() : '';
        useUserSettingsStore.getState().update({
            preferredModelId: modelSelectionKey(model),
            // The server falls back to the deployment name when the selection key no longer
            // resolves, which is what happens after an endpoint is replaced.
            ...(deployment ? { preferredModelDeployment: deployment } : {}),
        });
    };

    const submit = () => {
        if (!text.trim() || streaming) {
            return;
        }
        void sendMessage(text, options);
        setText('');
    };

    const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
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

                <div className="glass glass-edge rounded-2xl p-2">
                    <label htmlFor="composer-input" className="sr-only">
                        Message
                    </label>
                    <textarea
                        id="composer-input"
                        ref={textareaRef}
                        rows={1}
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                        onKeyDown={onKeyDown}
                        placeholder="Send a message…"
                        className={clsx(
                            'w-full resize-none bg-transparent px-3 py-2.5 text-[15px] leading-relaxed',
                            'text-text-1 placeholder:text-text-3 focus:outline-none',
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
                                onChange={(value) => {
                                    setOptions((current) => ({
                                        ...current,
                                        modelDeployment: value,
                                    }));
                                    rememberModelSelection(value);
                                }}
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
                            endpoint strips the parameter for models that reject it. The
                            level is stored per model, so it survives a reload and applies
                            to this model alone. It is clearable only where no level is in
                            effect — a deployment with no model catalog — because that is
                            the one case where "no level" is a state to get back to. */}
                        {reasoningLevels.length > 0 && (
                            <Dropdown
                                options={reasoningLevels}
                                value={options.reasoningEffort}
                                placeholder="Reasoning"
                                clearable={!reasoningKey}
                                icon={<Gauge size={15} />}
                                onChange={chooseReasoningLevel}
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
                                    disabled={!text.trim()}
                                    aria-label="Send message"
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
