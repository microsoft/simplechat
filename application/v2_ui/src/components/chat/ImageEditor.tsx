// ImageEditor.tsx
// Edit mode for a generated image: an AI change with an optional region, the prompt, rendering
// controls, and the version history. The server decides which inference operations are available;
// restoring history never needs a model.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    History,
    RotateCcw,
    Send,
    Settings2,
    Sparkles,
    Type,
    X,
} from 'lucide-react';
import { GlassPanel } from '../ui/primitives';
import { ImageMaskCanvas, type MaskSelection } from './ImageMaskCanvas';
import {
    describePromptProblem,
    imageOptionsForCapability,
    IMAGE_ORIGIN_LABELS,
    IMAGE_SIZE_LABELS,
    MAX_IMAGE_INSTRUCTION_LENGTH,
    MAX_IMAGE_PROMPT_LENGTH,
    type ImageEditCapability,
    type ImageRenderingOptions,
    type ImageRevisionState,
} from '../../lib/imageRevisions';

type EditorTab = 'ask' | 'prompt' | 'controls' | 'history';

const TABS: { id: EditorTab; label: string; icon: typeof Sparkles }[] = [
    { id: 'ask', label: 'Ask AI', icon: Sparkles },
    { id: 'prompt', label: 'Prompt', icon: Type },
    { id: 'controls', label: 'Controls', icon: Settings2 },
    { id: 'history', label: 'History', icon: History },
];

const EMPTY_SELECTION: MaskSelection = { dataUrl: null, regions: 0, coverage: 0 };

function formatTimestamp(value: string | undefined): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString();
}

function ChoiceButton({
    active,
    disabled,
    onClick,
    children,
}: {
    active: boolean;
    disabled?: boolean;
    onClick: () => void;
    children: React.ReactNode;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-pressed={active}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                active
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-edge-strong text-text-2 hover:bg-surface-2 hover:text-text-1'
            }`}
        >
            {children}
        </button>
    );
}

export function ImageEditor({
    title,
    imageSrc,
    revisions,
    capability,
    onClose,
}: {
    title: string;
    /** The image currently showing, already carrying its revision. */
    imageSrc: string;
    revisions: ImageRevisionState;
    capability: ImageEditCapability;
    onClose: () => void;
}) {
    const [tab, setTab] = useState<EditorTab>('ask');
    const [instruction, setInstruction] = useState('');
    const [promptDraft, setPromptDraft] = useState(revisions.prompt);
    const [comparing, setComparing] = useState(false);
    const closeRef = useRef<HTMLButtonElement>(null);

    const inferenceEnabled = capability.enabled && capability.mode !== 'unavailable'
        && capability.availability !== 'unavailable';
    const inferenceDisabled = revisions.busy || !revisions.canPersist || !inferenceEnabled;
    const masked = inferenceEnabled && capability.mode === 'masked' && capability.masking;
    const editing = inferenceEnabled && capability.editing
        && (capability.mode === 'masked' || capability.mode === 'edit');
    const contextKey = JSON.stringify([imageSrc, capability]);
    const [selectionState, setSelectionState] = useState({ key: contextKey, value: EMPTY_SELECTION });
    const [optionState, setOptionState] = useState<{ key: string; value: ImageRenderingOptions }>({
        key: contextKey,
        value: {},
    });
    const [maskReset, setMaskReset] = useState(0);
    const selection = selectionState.key === contextKey ? selectionState.value : EMPTY_SELECTION;
    const selectedOptions = imageOptionsForCapability(
        capability,
        optionState.key === contextKey ? optionState.value : {},
    );
    const onSelectionChange = useCallback((value: MaskSelection) => {
        setSelectionState({ key: contextKey, value });
    }, [contextKey]);

    // Key the canvas as well as the payload: clearing the parent alone leaves drawn regions behind.
    // The keyed reads also prevent an event before this effect from submitting an old selection.
    useEffect(() => {
        setSelectionState({ key: contextKey, value: EMPTY_SELECTION });
        setOptionState({ key: contextKey, value: {} });
    }, [contextKey]);

    // The stored prompt is the source of truth. When it changes underneath -- a version landed,
    // an older one was restored -- the draft follows it, because the reader is now looking at
    // something else and an unsynced editor would overwrite it on the next run.
    useEffect(() => {
        setPromptDraft(revisions.prompt);
    }, [revisions.prompt]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    // Opening a dialog moves focus into it; closing hands it back to whatever opened it.
    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        return () => previous?.focus?.();
    }, []);

    const promptProblem = useMemo(
        () => describePromptProblem(promptDraft),
        [promptDraft],
    );

    const previewSrc =
        comparing && revisions.previous
            ? revisions.revisionUrl(revisions.previous.id)
            : imageSrc;

    const submitInstruction = async () => {
        if (inferenceDisabled || !instruction.trim()) {
            return;
        }
        const ok = await revisions.revise({
            origin: 'ai',
            operation: editing ? 'edit' : 'regenerate',
            instruction,
            ...(masked && selection.dataUrl ? {
                mask: selection.dataUrl,
                maskRegions: selection.regions,
            } : {}),
        });
        if (ok) {
            setInstruction('');
            onSelectionChange(EMPTY_SELECTION);
            setMaskReset((value) => value + 1);
        }
    };

    const regenerate = (origin: 'prompt' | 'control') => {
        if (inferenceDisabled || (origin === 'prompt' && promptProblem)) {
            return;
        }
        void revisions.revise({
            origin,
            operation: 'regenerate',
            ...(origin === 'prompt' ? { prompt: promptDraft } : selectedOptions),
        });
    };

    const selectOption = (key: keyof ImageRenderingOptions, value: string) => {
        setOptionState({
            key: contextKey,
            value: {
                ...selectedOptions,
                [key]: selectedOptions[key] === value ? undefined : value,
            },
        });
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Edit image"
        >
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-[88vh] w-full max-w-6xl flex-col overflow-hidden"
            >
                <div className="flex shrink-0 items-center gap-3 border-b border-edge px-5 py-3">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-1">
                        {title}
                    </h2>
                    {revisions.busy && (
                        <span className="shrink-0 text-xs text-text-3">Generating…</span>
                    )}
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        title="Close"
                        aria-label="Close the editor"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] lg:grid-cols-[minmax(0,1fr)_26rem] lg:grid-rows-1">
                    <div className="flex min-h-0 min-w-0 flex-col gap-2 overflow-auto border-b border-edge p-4 lg:border-b-0 lg:border-r">
                        {tab === 'ask' && masked ? (
                            <ImageMaskCanvas
                                key={`${contextKey}:${maskReset}`}
                                src={imageSrc}
                                alt={title}
                                disabled={inferenceDisabled}
                                onChange={onSelectionChange}
                            />
                        ) : (
                            <div className="flex min-h-0 flex-1 items-center justify-center">
                                <img
                                    src={previewSrc}
                                    alt={title}
                                    className="max-h-full max-w-full rounded-xl object-contain"
                                />
                            </div>
                        )}

                        {revisions.previous && tab !== 'ask' && (
                            <button
                                type="button"
                                onMouseDown={() => setComparing(true)}
                                onMouseUp={() => setComparing(false)}
                                onMouseLeave={() => setComparing(false)}
                                onFocus={() => setComparing(true)}
                                onBlur={() => setComparing(false)}
                                className="self-center rounded-lg border border-edge-strong px-3 py-1 text-xs font-medium text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                            >
                                {comparing ? 'Showing the previous version' : 'Hold to compare'}
                            </button>
                        )}
                    </div>

                    <div className="flex min-h-0 min-w-0 flex-col">
                        <div className="flex shrink-0 flex-wrap gap-1 border-b border-edge px-3 py-2">
                            {TABS.map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    type="button"
                                    onClick={() => {
                                        if (tab === 'ask' && id !== 'ask') {
                                            onSelectionChange(EMPTY_SELECTION);
                                        }
                                        setTab(id);
                                    }}
                                    aria-pressed={tab === id}
                                    className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                                        tab === id
                                            ? 'bg-accent/10 text-accent'
                                            : 'text-text-3 hover:bg-surface-2 hover:text-text-1'
                                    }`}
                                >
                                    <Icon size={13} />
                                    {label}
                                </button>
                            ))}
                        </div>

                        <div className="min-h-0 flex-1 overflow-auto p-4">
                            <div className="mb-3 rounded-lg border border-edge bg-surface-2 px-3 py-2 text-xs text-text-2" data-testid="image-edit-profile">
                                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 break-words">
                                    <dt className="text-text-3">Model</dt>
                                    <dd>{capability.model_name || 'No resolved image model'}</dd>
                                    <dt className="text-text-3">Provider</dt>
                                    <dd>{capability.provider_label || 'Not specified'}</dd>
                                    <dt className="text-text-3">Endpoint cloud</dt>
                                    <dd>{capability.cloud_label || 'Unknown'}</dd>
                                </dl>
                                {capability.reason && <p className="mt-2">{capability.reason}</p>}
                            </div>
                            {capability.availability === 'unknown' && (
                                <p role="status" className="mb-3 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
                                    Availability for this configured endpoint is not documented or is unknown.
                                    This is not a confirmation of provider support.
                                    {capability.availability_reason ? ` ${capability.availability_reason}` : ''}
                                </p>
                            )}
                            {capability.availability === 'unavailable' && capability.availability_reason && (
                                <p role="status" className="mb-3 text-xs text-warn">{capability.availability_reason}</p>
                            )}
                            {!inferenceEnabled && (
                                <p role="status" className="mb-3 text-xs text-text-2">
                                    Generation and editing are unavailable. You can still restore saved versions in History.
                                </p>
                            )}
                            {revisions.error && (
                                <div role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-text-1">
                                    <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                                    <span className="flex-1">{revisions.error}</span>
                                    <button
                                        type="button"
                                        onClick={revisions.clearError}
                                        aria-label="Dismiss the error"
                                        className="shrink-0 text-text-3 hover:text-text-1"
                                    >
                                        <X size={13} />
                                    </button>
                                </div>
                            )}

                            {tab === 'ask' && (
                                <div className="flex flex-col gap-3">
                                    <label
                                        htmlFor="image-edit-instruction"
                                        className="text-xs font-medium text-text-2"
                                    >
                                        Describe the change
                                    </label>
                                    <textarea
                                        id="image-edit-instruction"
                                        aria-describedby="image-edit-guidance"
                                        value={instruction}
                                        onChange={(event) => setInstruction(event.target.value)}
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter' && !event.shiftKey) {
                                                event.preventDefault();
                                                void submitInstruction();
                                            }
                                        }}
                                        maxLength={MAX_IMAGE_INSTRUCTION_LENGTH}
                                        rows={4}
                                        disabled={inferenceDisabled}
                                        placeholder={
                                            masked
                                                ? 'Make the sky orange'
                                                : 'Make the sky orange and add a path in the foreground'
                                        }
                                        className="w-full rounded-lg border border-edge-strong bg-surface-1 px-3 py-2 text-sm text-text-1 outline-none focus:border-accent disabled:opacity-50"
                                    />

                                    <p id="image-edit-guidance" className="text-[11px] leading-relaxed text-text-3">
                                        {masked
                                            ? `${selection.dataUrl
                                                ? `About ${Math.round(selection.coverage * 100)}% of the image is selected.`
                                                : 'The current image guides the edit. Optionally select a region to guide where it changes.'} The model is not strictly bound by a mask; areas outside it can still shift. Pixel-exact preservation is not guaranteed.`
                                            : editing
                                              ? 'The current image is used as a reference for this edit. Region selection is not supported; changes may affect the whole image.'
                                              : inferenceEnabled
                                                ? 'This model only supports whole-image regeneration. Ask AI creates a replacement from the prompt and your instruction, without using the current image as a reference.'
                                                : 'Ask an administrator to configure an available image model before requesting a new version.'}
                                    </p>

                                    <button
                                        type="button"
                                        onClick={() => void submitInstruction()}
                                        disabled={
                                            inferenceDisabled ||
                                            !instruction.trim()
                                        }
                                        className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        <Send size={13} />
                                        {revisions.busy
                                            ? 'Generating…'
                                            : masked
                                              ? selection.dataUrl ? 'Edit selected region' : 'Edit image'
                                              : editing ? 'Edit using source image' : 'Regenerate whole image'}
                                    </button>

                                    {revisions.chat.length > 0 && (
                                        <div className="mt-2 flex flex-col gap-2 border-t border-edge pt-3">
                                            <p className="text-[11px] font-medium text-text-3">
                                                Earlier changes to this image
                                            </p>
                                            {revisions.chat
                                                .filter((turn) => turn.role === 'user')
                                                .slice(-6)
                                                .map((turn, index) => (
                                                    <p
                                                        key={`${turn.timestamp}-${index}`}
                                                        className="rounded-lg bg-surface-2 px-2.5 py-1.5 text-[11px] text-text-2"
                                                    >
                                                        {turn.content}
                                                    </p>
                                                ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {tab === 'prompt' && (
                                <div className="flex flex-col gap-3">
                                    <label
                                        htmlFor="image-edit-prompt"
                                        className="text-xs font-medium text-text-2"
                                    >
                                        The prompt behind this version
                                    </label>
                                    <textarea
                                        id="image-edit-prompt"
                                        aria-describedby="image-regenerate-guidance"
                                        value={promptDraft}
                                        onChange={(event) => setPromptDraft(event.target.value)}
                                        rows={10}
                                        maxLength={MAX_IMAGE_PROMPT_LENGTH}
                                        disabled={inferenceDisabled}
                                        className="w-full rounded-lg border border-edge-strong bg-surface-1 px-3 py-2 font-mono text-xs text-text-1 outline-none focus:border-accent disabled:opacity-50"
                                    />
                                    {promptProblem && (
                                        <p className="text-[11px] text-danger">{promptProblem}</p>
                                    )}
                                    <p id="image-regenerate-guidance" className="text-[11px] leading-relaxed text-text-3">
                                        Whole-image regeneration creates a replacement from this prompt,
                                        without the current image or any selected region.
                                        {editing ? ' Use Ask AI for a source-image edit instead.' : ''}
                                    </p>
                                    <div className="flex flex-wrap gap-2">
                                        <button
                                            type="button"
                                            onClick={() => regenerate('prompt')}
                                            disabled={
                                                inferenceDisabled ||
                                                Boolean(promptProblem)
                                            }
                                            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            <Send size={13} />
                                            Regenerate whole image
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setPromptDraft(revisions.prompt)}
                                            disabled={
                                                revisions.busy ||
                                                promptDraft.trim() === revisions.prompt.trim()
                                            }
                                            className="rounded-lg border border-edge-strong px-3 py-2 text-xs font-medium text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            Discard changes
                                        </button>
                                    </div>
                                </div>
                            )}

                            {tab === 'controls' && (
                                <div className="flex flex-col gap-4">
                                    <p className="text-[11px] leading-relaxed text-text-3">
                                        These settings apply to whole-image regeneration from this version&apos;s
                                        prompt. The source image and any selected region are not used.
                                        Unselected options use the selected model&apos;s defaults.
                                    </p>
                                    {capability.sizes.length > 0 && <ControlGroup label="Shape">
                                        {capability.sizes.map((size) => (
                                            <ChoiceButton
                                                key={size}
                                                active={selectedOptions.size === size}
                                                disabled={inferenceDisabled}
                                                onClick={() => selectOption('size', size)}
                                            >
                                                {IMAGE_SIZE_LABELS[size] ? `${IMAGE_SIZE_LABELS[size]} · ${size}` : size}
                                            </ChoiceButton>
                                        ))}
                                    </ControlGroup>}

                                    {capability.qualities.length > 0 && <ControlGroup label="Quality">
                                        {capability.qualities.map((quality) => (
                                            <ChoiceButton
                                                key={quality}
                                                active={selectedOptions.quality === quality}
                                                disabled={inferenceDisabled}
                                                onClick={() => selectOption('quality', quality)}
                                            >
                                                {quality[0].toUpperCase() + quality.slice(1)}
                                            </ChoiceButton>
                                        ))}
                                    </ControlGroup>}

                                    {capability.backgrounds.length > 0 && <ControlGroup label="Background">
                                        {capability.backgrounds.map((background) => (
                                            <ChoiceButton
                                                key={background}
                                                active={
                                                    selectedOptions.background === background
                                                }
                                                disabled={inferenceDisabled}
                                                onClick={() => selectOption('background', background)}
                                            >
                                                {background[0].toUpperCase() + background.slice(1)}
                                            </ChoiceButton>
                                        ))}
                                    </ControlGroup>}

                                    {!capability.sizes.length && !capability.qualities.length && !capability.backgrounds.length && (
                                        <p className="text-xs text-text-3">No additional rendering controls are supported by this model.</p>
                                    )}
                                    <button
                                        type="button"
                                        onClick={() => regenerate('control')}
                                        disabled={inferenceDisabled}
                                        className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        <Send size={13} />
                                        Regenerate whole image
                                    </button>

                                    <p className="text-[11px] leading-relaxed text-text-3">
                                        A regenerated image will differ from the version you have now. Every
                                        change is recorded, so you can restore this one from the
                                        History tab.
                                    </p>
                                </div>
                            )}

                            {tab === 'history' && (
                                <div className="flex flex-col gap-2">
                                    {revisions.revisions.length === 0 && (
                                        <p className="text-xs text-text-3">
                                            This image has not been changed yet.
                                        </p>
                                    )}

                                    {revisions.revisions
                                        .map((revision, index) => ({ revision, index }))
                                        .reverse()
                                        .map(({ revision, index }) => {
                                            const isCurrent = index === revisions.currentIndex;
                                            return (
                                                <div
                                                    key={revision.id}
                                                    className={`flex gap-3 rounded-xl border p-2 ${
                                                        isCurrent
                                                            ? 'border-accent bg-accent/5'
                                                            : 'border-edge'
                                                    }`}
                                                >
                                                    <img
                                                        src={revisions.revisionUrl(revision.id)}
                                                        alt={`Version ${index + 1}`}
                                                        loading="lazy"
                                                        className="size-16 shrink-0 rounded-lg object-cover"
                                                    />
                                                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                                                        <p className="text-xs font-medium text-text-1">
                                                            {revision.method === 'regenerate' && revision.origin === 'ai'
                                                                ? 'AI regeneration (whole image)'
                                                                : IMAGE_ORIGIN_LABELS[revision.origin] ?? 'Change'}
                                                        </p>
                                                        {revision.instruction && (
                                                            <p className="truncate text-[11px] text-text-2">
                                                                {revision.instruction}
                                                            </p>
                                                        )}
                                                        <p className="text-[11px] text-text-3">
                                                            {[
                                                                revision.author_name,
                                                                formatTimestamp(revision.timestamp),
                                                                revision.has_mask
                                                                    ? `${Math.round(
                                                                          (revision.mask_coverage ??
                                                                              0) * 100,
                                                                      )}% selected`
                                                                    : '',
                                                            ]
                                                                .filter(Boolean)
                                                                .join(' · ')}
                                                        </p>
                                                    </div>
                                                    {!isCurrent && (
                                                        <button
                                                            type="button"
                                                            onClick={() =>
                                                                void revisions.restore(revision.id)
                                                            }
                                                            disabled={revisions.busy || !revisions.canPersist}
                                                            className="inline-flex h-fit shrink-0 items-center gap-1 self-center rounded-lg border border-edge-strong px-2 py-1 text-[11px] font-medium text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                                                        >
                                                            <RotateCcw size={12} />
                                                            Restore
                                                        </button>
                                                    )}
                                                </div>
                                            );
                                        })}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </GlassPanel>
        </div>
    );
}

function ControlGroup({
    label,
    children,
}: {
    label: string;
    children: React.ReactNode;
}) {
    return (
        <fieldset className="min-w-0">
            <legend className="mb-1.5 text-xs font-medium text-text-2">{label}</legend>
            <div className="flex flex-wrap gap-1.5">{children}</div>
        </fieldset>
    );
}
