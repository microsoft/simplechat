// Composer.tsx
// The message input surface: textarea, send/stop control, model / agent / prompt pickers
// and the capability toggles that map onto the /api/chat/stream request fields.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    ArrowUp,
    Bot,
    FileText,
    Globe,
    Image as ImageIcon,
    Loader2,
    Mic,
    Paperclip,
    Search,
    Square,
    Telescope,
    Volume2,
} from 'lucide-react';
import { useChatStore, type ComposerOptions } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { uploadDocument } from '../../lib/endpoints';
import { Dropdown, type DropdownOption } from '../ui/Dropdown';
import { NotWiredBadge } from '../ui/primitives';

/** A capability toggle in the composer toolbar. */
function ToolToggle({
    active,
    onClick,
    icon,
    label,
    disabled = false,
    preview = false,
}: {
    active: boolean;
    onClick: () => void;
    icon: React.ReactNode;
    label: string;
    disabled?: boolean;
    preview?: boolean;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-pressed={active}
            title={preview ? `${label} (not wired up yet)` : label}
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
            {preview && <NotWiredBadge className="hidden lg:inline" />}
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

    const [options, setOptions] = useState<ComposerOptions>({
        documentSearch: false,
        webSearch: false,
        imageGeneration: false,
        selectedDocumentIds: [],
        docScope: 'all',
    });

    // Apply the server's preferred model once bootstrap resolves.
    useEffect(() => {
        const initial = bootstrap?.catalogs?.initial_model_selection;
        if (!initial) {
            return;
        }
        setOptions((current) =>
            current.modelDeployment
                ? current
                : {
                      ...current,
                      modelDeployment:
                          (initial.option_value as string) ??
                          (initial.deployment_name as string) ??
                          undefined,
                      modelEndpointId: initial.model_endpoint_id as string | undefined,
                  },
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

    const modelOptions: DropdownOption[] = (bootstrap?.catalogs?.models ?? []).map(
        (model, index) => ({
            value:
                (model.option_value as string) ??
                (model.selection_key as string) ??
                (model.deployment_name as string) ??
                String(index),
            label:
                (model.display_name as string) ||
                (model.deployment_name as string) ||
                'Model',
        }),
    );

    const agentOptions: DropdownOption[] = (bootstrap?.catalogs?.agents ?? []).map(
        (agent, index) => ({
            value:
                (agent.selection_key as string) ??
                (agent.name as string) ??
                String(index),
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
            <div className="mx-auto w-full max-w-4xl">
                {uploadNotice && (
                    <p className="mb-2 rounded-xl border border-edge bg-surface-1 px-3 py-2 text-xs text-text-2">
                        {uploadNotice}
                    </p>
                )}

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
                        <Dropdown
                            options={modelOptions}
                            value={options.modelDeployment}
                            placeholder="Model"
                            onChange={(value) =>
                                setOptions((current) => ({ ...current, modelDeployment: value }))
                            }
                        />

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
                            onClick={() =>
                                setOptions((current) => ({
                                    ...current,
                                    documentSearch: !current.documentSearch,
                                }))
                            }
                            icon={<Search size={15} />}
                            label="Documents"
                        />

                        {features.enable_web_search && (
                            <ToolToggle
                                active={options.webSearch}
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

                        {features.enable_image_generation && (
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

                        {/* Long-tail controls are shown so the V2 layout can be judged in
                            full, but are explicitly marked rather than silently inert. */}
                        {features.enable_source_review && (
                            <ToolToggle
                                active={false}
                                onClick={() => undefined}
                                icon={<Telescope size={15} />}
                                label="Deep research"
                                disabled
                                preview
                            />
                        )}

                        <ToolToggle
                            active={false}
                            onClick={() => undefined}
                            icon={<Volume2 size={15} />}
                            label="Voice reply"
                            disabled
                            preview
                        />

                        <div className="ml-auto flex items-center gap-1.5">
                            <input
                                ref={fileInputRef}
                                type="file"
                                className="hidden"
                                onChange={onSelectFile}
                            />

                            <button
                                type="button"
                                onClick={() => undefined}
                                disabled
                                title="Voice input (not wired up yet)"
                                aria-label="Voice input"
                                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-edge bg-surface-1 text-text-3 disabled:opacity-40"
                            >
                                <Mic size={16} />
                            </button>

                            <button
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={uploading || features.enable_chat_file_uploads === false}
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

                <p className="mt-2 text-center text-[11px] text-text-3">
                    AI responses can be inaccurate. Verify important information.
                </p>
            </div>
        </div>
    );
}
