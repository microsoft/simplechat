// ImageEditor.tsx
// Edit mode for a generated image: an AI change with an optional region, the prompt, rendering
// controls, and the version history.
//
// The image counterpart of `DiagramEditor.tsx`, with one structural difference. A diagram can be
// hand-edited, so that panel's first tab is a source editor and the AI is an alternative. An
// image cannot: it is pixels, and no amount of typing produces one. So every tab here ends in a
// model call, and the honest framing is that this panel *describes a change* rather than makes
// one.
//
// What replaces hand-editing is the mask. Saying "change this bit" is meaningless in words and
// obvious with a pointer, which is why the region selector sits in the primary tab rather than
// being tucked away as an option.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    History,
    Info,
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
    IMAGE_BACKGROUNDS,
    IMAGE_ORIGIN_LABELS,
    IMAGE_QUALITIES,
    IMAGE_SIZE_LABELS,
    IMAGE_SIZES,
    MAX_IMAGE_INSTRUCTION_LENGTH,
    type ImageEditCapability,
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
    const [selection, setSelection] = useState<MaskSelection>(EMPTY_SELECTION);
    const [promptDraft, setPromptDraft] = useState(revisions.prompt);
    const [comparing, setComparing] = useState(false);
    const closeRef = useRef<HTMLButtonElement>(null);

    const masked = capability.mode === 'masked';

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
        () =>
            promptDraft.trim() !== revisions.prompt.trim()
                ? describePromptProblem(promptDraft)
                : null,
        [promptDraft, revisions.prompt],
    );

    const previewSrc =
        comparing && revisions.previous
            ? revisions.revisionUrl(revisions.previous.id)
            : imageSrc;

    const submitInstruction = async () => {
        if (!instruction.trim()) {
            return;
        }
        const ok = await revisions.revise({
            origin: 'ai',
            instruction,
            mask: selection.dataUrl ?? undefined,
            maskRegions: selection.regions,
        });
        if (ok) {
            setInstruction('');
            setSelection(EMPTY_SELECTION);
        }
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

                <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_26rem]">
                    <div className="flex min-h-0 flex-col gap-2 overflow-auto border-b border-edge p-4 lg:border-b-0 lg:border-r">
                        {tab === 'ask' && masked ? (
                            <ImageMaskCanvas
                                src={imageSrc}
                                alt={title}
                                disabled={revisions.busy}
                                onChange={setSelection}
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

                    <div className="flex min-h-0 flex-col">
                        <div className="flex shrink-0 gap-1 border-b border-edge px-3 py-2">
                            {TABS.map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    type="button"
                                    onClick={() => setTab(id)}
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
                            {revisions.error && (
                                <div className="mb-3 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-text-1">
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

                            {!masked && capability.reason && (
                                <p className="mb-3 flex items-start gap-2 rounded-lg border border-edge bg-surface-2 px-3 py-2 text-xs text-text-2">
                                    <Info size={14} className="mt-0.5 shrink-0 text-text-3" />
                                    <span>
                                        {capability.reason} Selecting a region is not available,
                                        so each change produces a new version of the whole image.
                                    </span>
                                </p>
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
                                        disabled={revisions.busy || !revisions.canPersist}
                                        placeholder={
                                            masked
                                                ? 'Make the sky orange'
                                                : 'Make the sky orange and add a path in the foreground'
                                        }
                                        className="w-full rounded-lg border border-edge-strong bg-surface-1 px-3 py-2 text-sm text-text-1 outline-none focus:border-accent disabled:opacity-50"
                                    />

                                    {masked && (
                                        <p className="text-[11px] leading-relaxed text-text-3">
                                            {selection.dataUrl
                                                ? `About ${Math.round(
                                                      selection.coverage * 100,
                                                  )}% of the image is selected. The model is guided by the selection but is not strictly bound by it, so areas outside it can still shift.`
                                                : 'Select a region on the left to change only part of the image. With nothing selected the whole image is reworked.'}
                                        </p>
                                    )}

                                    <button
                                        type="button"
                                        onClick={() => void submitInstruction()}
                                        disabled={
                                            revisions.busy ||
                                            !revisions.canPersist ||
                                            !instruction.trim()
                                        }
                                        className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        <Send size={13} />
                                        {revisions.busy ? 'Generating…' : 'Generate a new version'}
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
                                        value={promptDraft}
                                        onChange={(event) => setPromptDraft(event.target.value)}
                                        rows={10}
                                        disabled={revisions.busy || !revisions.canPersist}
                                        className="w-full rounded-lg border border-edge-strong bg-surface-1 px-3 py-2 font-mono text-xs text-text-1 outline-none focus:border-accent disabled:opacity-50"
                                    />
                                    {promptProblem && (
                                        <p className="text-[11px] text-danger">{promptProblem}</p>
                                    )}
                                    <p className="text-[11px] leading-relaxed text-text-3">
                                        Rewriting the prompt rebuilds the image from scratch. Use
                                        Ask AI instead to adjust the image you already have.
                                    </p>
                                    <div className="flex gap-2">
                                        <button
                                            type="button"
                                            onClick={() =>
                                                void revisions.revise({
                                                    origin: 'prompt',
                                                    prompt: promptDraft,
                                                })
                                            }
                                            disabled={
                                                revisions.busy ||
                                                !revisions.canPersist ||
                                                Boolean(promptProblem) ||
                                                promptDraft.trim() === revisions.prompt.trim()
                                            }
                                            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            <Send size={13} />
                                            Rebuild from this prompt
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
                                    <ControlGroup label="Shape">
                                        {IMAGE_SIZES.map((size) => (
                                            <ChoiceButton
                                                key={size}
                                                active={revisions.current?.size === size}
                                                disabled={revisions.busy || !revisions.canPersist}
                                                onClick={() =>
                                                    void revisions.revise({
                                                        origin: 'control',
                                                        size,
                                                    })
                                                }
                                            >
                                                {IMAGE_SIZE_LABELS[size]}
                                            </ChoiceButton>
                                        ))}
                                    </ControlGroup>

                                    <ControlGroup label="Quality">
                                        {IMAGE_QUALITIES.map((quality) => (
                                            <ChoiceButton
                                                key={quality}
                                                active={revisions.current?.quality === quality}
                                                disabled={revisions.busy || !revisions.canPersist}
                                                onClick={() =>
                                                    void revisions.revise({
                                                        origin: 'control',
                                                        quality,
                                                    })
                                                }
                                            >
                                                {quality[0].toUpperCase() + quality.slice(1)}
                                            </ChoiceButton>
                                        ))}
                                    </ControlGroup>

                                    <ControlGroup label="Background">
                                        {IMAGE_BACKGROUNDS.map((background) => (
                                            <ChoiceButton
                                                key={background}
                                                active={
                                                    revisions.current?.background === background
                                                }
                                                disabled={revisions.busy || !revisions.canPersist}
                                                onClick={() =>
                                                    void revisions.revise({
                                                        origin: 'control',
                                                        background,
                                                    })
                                                }
                                            >
                                                {background === 'transparent'
                                                    ? 'Transparent'
                                                    : 'Opaque'}
                                            </ChoiceButton>
                                        ))}
                                    </ControlGroup>

                                    <p className="text-[11px] leading-relaxed text-text-3">
                                        Each of these regenerates the image, so the result will
                                        differ in detail from the version you have now. Every
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
                                                            {IMAGE_ORIGIN_LABELS[revision.origin] ??
                                                                'Change'}
                                                            {revision.method === 'regenerate' &&
                                                                revision.origin === 'ai' && (
                                                                    <span className="ml-1 font-normal text-text-3">
                                                                        (whole image)
                                                                    </span>
                                                                )}
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
                                                            disabled={revisions.busy}
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
        <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-text-2">{label}</p>
            <div className="flex flex-wrap gap-1.5">{children}</div>
        </div>
    );
}
