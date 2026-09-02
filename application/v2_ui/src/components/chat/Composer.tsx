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
import { uploadDocument } from '../../lib/endpoints';
import { agentSelectionKey } from '../../lib/agents';
import { hasResolvableAgent } from '../../lib/chatRequestSelection';
import { modelSelectionKey, findModel, type ModelCatalogEntry } from '../../lib/models';
import { resolveGating } from '../../lib/composerGating';
import { useUiStore } from '../../stores/uiStore';
import { chatWidthClass } from '../../lib/chatWidth';
import {
    getModelSupportedLevels,
    REASONING_LABELS,
    supportsReasoning,
} from '../../lib/reasoning';
import { Dropdown, type DropdownOption } from '../ui/Dropdown';
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

    // An agent supplies its own deployment and never receives a reasoning level, so a
    // selection the server can actually resolve is what puts the model picker into its
    // overridden state. Resolved against the catalog, not the raw key, so a stale selection
    // does not silently deactivate a control that is still in force.
    const agentActive = useMemo(
        () =>
            hasResolvableAgent(
                bootstrap?.catalogs?.agents as Record<string, unknown>[] | undefined,
                options.agentSelection,
            ),
        [bootstrap, options.agentSelection],
    );

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
                agentActive,
            }),
        [
            text,
            features,
            options.webSearch,
            options.urlAccess,
            options.imageGeneration,
            agentActive,
        ],
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

    // Names the agent in the model picker's tooltip. Saying which one is holding the model
    // back is the difference between an explanation and a control that has simply gone dim.
    const activeAgentLabel = agentActive
        ? (agentOptions.find((option) => option.value === options.agentSelection)?.label ??
          'the selected agent')
        : null;

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
                            endpoint that does not take a chat model. Shown but overridden
                            while an agent is selected, since the agent brings its own
                            deployment — picking a model here is how the user gets back to
                            using one, so it stays usable rather than disabled. */}
                        {gating.showModelPicker && (
                            <Dropdown
                                options={modelOptions}
                                value={options.modelDeployment}
                                placeholder="Model"
                                inactive={gating.modelPickerInactive}
                                title={
                                    activeAgentLabel
                                        ? `${activeAgentLabel} supplies its own model. Pick a model to use one instead.`
                                        : undefined
                                }
                                onChange={(value) =>
                                    setOptions((current) => ({
                                        ...current,
                                        modelDeployment: value,
                                        // Choosing a model is the way out of agent mode. The
                                        // two cannot both apply, and the server reads a model
                                        // sent alongside an agent as an override of it.
                                        agentSelection: undefined,
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
                                        // The model selection is kept, not cleared: it is
                                        // simply not in force, and it comes back the moment
                                        // the agent is cleared.
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

                        {/* Only shown when a reasoning level is a real choice: the selected
                            model has to offer one, and neither an agent nor image generation
                            can be in play, because neither carries the parameter. */}
                        {gating.showReasoning && reasoningLevels.length > 0 && (
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
