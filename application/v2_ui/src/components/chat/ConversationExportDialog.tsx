// ConversationExportDialog.tsx
// The conversation export wizard: pick conversations, a format, packaging and an optional
// intro summary, then download.
//
// Stepped rather than a single form because the choices are not independent. Packaging only
// makes sense once the count is known, the intro summary needs a model chosen for it, and the
// last step has to state what is about to be produced — a PDF of eleven conversations is not
// something to discover after clicking. This matches the classic wizard step for step, so the
// two interfaces can be described by one set of instructions.
//
// Diagrams are rasterized here rather than on the server. Mermaid is a browser library, so the
// alternative is launching headless Chromium per export; see lib/exportVisuals.ts.

import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import {
    Check,
    ChevronLeft,
    ChevronRight,
    CircleAlert,
    Download,
    FileArchive,
    FileJson,
    FileText,
    FileType,
    Loader2,
    MessageSquare,
    Sparkles,
    X,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { buildConversationVisualAssets } from '../../lib/exportVisuals';
import {
    conversationExportExtension,
    downloadConversationExport,
    type ConversationExportFormat,
    type ConversationExportPackaging,
} from '../../lib/endpoints';
import {
    buildConversationExportRequest,
    defaultPackaging,
    exportSteps,
    needsVisualAssets,
    type ExportStepId,
} from '../../lib/conversationExport';
import { modelSelectionKey, type ModelCatalogEntry } from '../../lib/models';

interface FormatChoice {
    id: ConversationExportFormat;
    label: string;
    description: string;
    icon: React.ReactNode;
}

const FORMATS: FormatChoice[] = [
    {
        id: 'json',
        label: 'JSON',
        description: 'Structured data. Best for re-importing or analysing elsewhere.',
        icon: <FileJson size={22} />,
    },
    {
        id: 'markdown',
        label: 'Markdown',
        description: 'Readable text. Good for documentation and sharing.',
        icon: <FileText size={22} />,
    },
    {
        id: 'pdf',
        label: 'PDF',
        description: 'Print-ready transcript with chat bubbles. Best for archiving.',
        icon: <FileType size={22} />,
    },
];

const FORMAT_LABEL: Record<ConversationExportFormat, string> = {
    json: 'JSON',
    markdown: 'Markdown',
    pdf: 'PDF',
};

/** A selectable card, used for both the format and the packaging choice. */
function ChoiceCard({
    selected,
    label,
    description,
    icon,
    onSelect,
}: {
    selected: boolean;
    label: string;
    description: string;
    icon: React.ReactNode;
    onSelect: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onSelect}
            aria-pressed={selected}
            className={clsx(
                'flex h-full flex-col items-start gap-2 rounded-xl border p-4 text-left transition-colors',
                selected
                    ? 'border-accent bg-accent-soft text-accent'
                    : 'border-edge text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            <span className={clsx(selected ? 'text-accent' : 'text-text-3')}>{icon}</span>
            <span className="text-sm font-semibold text-text-1">{label}</span>
            <span className="text-xs leading-relaxed text-text-3">{description}</span>
        </button>
    );
}

function StepIndicator({
    steps,
    currentIndex,
}: {
    steps: { id: ExportStepId; label: string }[];
    currentIndex: number;
}) {
    return (
        <ol className="flex items-center gap-1.5 px-5 py-3">
            {steps.map((step, index) => {
                const done = index < currentIndex;
                const active = index === currentIndex;
                return (
                    <li key={step.id} className="flex min-w-0 items-center gap-1.5">
                        <span
                            aria-hidden="true"
                            className={clsx(
                                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                                done && 'bg-accent text-on-accent',
                                active && 'bg-accent-soft text-accent ring-1 ring-accent',
                                !done && !active && 'bg-surface-sunken text-text-3',
                            )}
                        >
                            {done ? <Check size={12} /> : index + 1}
                        </span>
                        <span
                            className={clsx(
                                'truncate text-xs',
                                active ? 'font-medium text-text-1' : 'text-text-3',
                            )}
                        >
                            {step.label}
                        </span>
                        {index < steps.length - 1 && (
                            <span aria-hidden="true" className="mx-1 h-px w-4 bg-edge" />
                        )}
                    </li>
                );
            })}
        </ol>
    );
}

export function ConversationExportDialog({
    conversationIds,
    skipSelection = false,
    onClose,
}: {
    conversationIds: string[];
    skipSelection?: boolean;
    onClose: () => void;
}) {
    const conversations = useChatStore((state) => state.conversations);
    const models = useBootstrapStore(
        (state) => state.data?.catalogs?.models as ModelCatalogEntry[] | undefined,
    );

    const [ids, setIds] = useState<string[]>(conversationIds);
    const [stepIndex, setStepIndex] = useState(0);
    const [format, setFormat] = useState<ConversationExportFormat>('json');
    const [packaging, setPackaging] = useState<ConversationExportPackaging>(() =>
        defaultPackaging(conversationIds.length),
    );
    const [includeSummary, setIncludeSummary] = useState(false);
    const [summaryModelKey, setSummaryModelKey] = useState('');
    const [packagingTouched, setPackagingTouched] = useState(false);
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState('');
    const [failure, setFailure] = useState('');
    const [finished, setFinished] = useState(false);

    const steps = useMemo(() => exportSteps(skipSelection), [skipSelection]);
    const step = steps[stepIndex]?.id ?? 'download';
    const isLastStep = stepIndex === steps.length - 1;

    /**
     * The model the summary will actually use.
     *
     * Derived rather than stored, because the catalog arrives with the bootstrap request and
     * may not be loaded when this dialog mounts. Defaulting in state would leave the picker
     * showing the first model while the request carried none.
     */
    const effectiveModelKey = summaryModelKey || modelSelectionKey(models?.[0]) || '';

    // Titles come from the feed the rail already loaded rather than a request of their own.
    // A conversation opened by link may not be in that list, hence the fallback.
    const titleOf = (id: string) =>
        conversations.find((conversation) => conversation.id === id)?.title ||
        'Untitled conversation';

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && !busy) {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose, busy]);

    const removeId = (id: string) => {
        const next = ids.filter((item) => item !== id);
        setIds(next);
        if (next.length === 0) {
            toast.info('Every conversation was removed, so there is nothing to export.');
            onClose();
            return;
        }
        // Only re-default packaging while it is still a default. Changing a choice the user
        // already made, as a side effect of removing an unrelated conversation, is worse than
        // leaving a single conversation in a ZIP because that is what they asked for.
        if (!packagingTouched) {
            setPackaging(defaultPackaging(next.length));
        }
    };

    const runExport = async () => {
        setBusy(true);
        setFailure('');
        setProgress(
            needsVisualAssets(format)
                ? 'Drawing diagrams…'
                : 'Building the export…',
        );

        try {
            const visualAssets = needsVisualAssets(format)
                ? await buildConversationVisualAssets(ids)
                : [];

            setProgress('Building the export…');
            await downloadConversationExport(
                buildConversationExportRequest({
                    conversationIds: ids,
                    format,
                    packaging,
                    includeSummaryIntro: includeSummary,
                    models,
                    summaryModelKey: effectiveModelKey,
                    visualAssets,
                }),
            );

            setFinished(true);
            setProgress('');
            toast.success(
                ids.length === 1
                    ? 'Conversation exported.'
                    : `${ids.length} conversations exported.`,
            );
            window.setTimeout(onClose, 1200);
        } catch (error) {
            const message =
                error instanceof Error ? error.message : 'The export could not be built.';
            setFailure(message);
            setProgress('');
            toast.error(`Export failed: ${message}`);
        } finally {
            setBusy(false);
        }
    };

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Export conversations"
        >
            <div
                className="absolute inset-0 bg-black/40"
                aria-hidden="true"
                onClick={() => {
                    if (!busy) {
                        onClose();
                    }
                }}
            />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[85vh] w-full max-w-2xl flex-col"
            >
                <div className="flex h-14 shrink-0 items-center border-b border-edge px-5">
                    <h2 className="text-[15px] font-semibold text-text-1">
                        {ids.length === 1
                            ? 'Export conversation'
                            : `Export ${ids.length} conversations`}
                    </h2>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={busy}
                        aria-label="Close export"
                        className="ml-auto rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:opacity-50"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="shrink-0 border-b border-edge">
                    <StepIndicator steps={steps} currentIndex={stepIndex} />
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    {step === 'select' && (
                        <section>
                            <h3 className="text-sm font-semibold text-text-1">
                                Review conversations
                            </h3>
                            <p className="mt-1 mb-3 text-xs text-text-3">
                                {ids.length} selected. Remove any you do not want included.
                            </p>
                            <ul className="divide-y divide-edge overflow-hidden rounded-xl border border-edge">
                                {ids.map((id) => (
                                    <li
                                        key={id}
                                        className="flex items-center gap-2 px-3 py-2 text-sm"
                                    >
                                        <MessageSquare
                                            size={14}
                                            className="shrink-0 text-text-3"
                                        />
                                        <span className="min-w-0 flex-1 truncate text-text-1">
                                            {titleOf(id)}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => removeId(id)}
                                            aria-label={`Remove ${titleOf(id)} from the export`}
                                            className="rounded-md p-1 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger"
                                        >
                                            <X size={14} />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </section>
                    )}

                    {step === 'format' && (
                        <section>
                            <h3 className="text-sm font-semibold text-text-1">Choose a format</h3>
                            <p className="mt-1 mb-3 text-xs text-text-3">
                                Markdown and PDF embed diagrams as pictures. JSON keeps the
                                original text.
                            </p>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                                {FORMATS.map((choice) => (
                                    <ChoiceCard
                                        key={choice.id}
                                        selected={format === choice.id}
                                        label={choice.label}
                                        description={choice.description}
                                        icon={choice.icon}
                                        onSelect={() => setFormat(choice.id)}
                                    />
                                ))}
                            </div>
                        </section>
                    )}

                    {step === 'packaging' && (
                        <section>
                            <h3 className="text-sm font-semibold text-text-1">
                                Choose packaging
                            </h3>
                            <p className="mt-1 mb-3 text-xs text-text-3">
                                How the download should be arranged.
                            </p>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                <ChoiceCard
                                    selected={packaging === 'single'}
                                    label="Single file"
                                    description={
                                        ids.length > 1
                                            ? 'Every conversation in one combined file.'
                                            : 'One file containing the conversation.'
                                    }
                                    icon={<FileText size={22} />}
                                    onSelect={() => {
                                        setPackaging('single');
                                        setPackagingTouched(true);
                                    }}
                                />
                                <ChoiceCard
                                    selected={packaging === 'zip'}
                                    label="ZIP archive"
                                    description={
                                        ids.length > 1
                                            ? 'One file per conversation, bundled together.'
                                            : 'The conversation wrapped in a ZIP.'
                                    }
                                    icon={<FileArchive size={22} />}
                                    onSelect={() => {
                                        setPackaging('zip');
                                        setPackagingTouched(true);
                                    }}
                                />
                            </div>
                        </section>
                    )}

                    {step === 'summary' && (
                        <section>
                            <h3 className="text-sm font-semibold text-text-1">
                                Intro summary
                            </h3>
                            <p className="mt-1 mb-3 text-xs text-text-3">
                                Adds a short written abstract above each transcript, generated
                                from the conversation itself.
                            </p>

                            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-edge p-3">
                                <input
                                    type="checkbox"
                                    checked={includeSummary}
                                    onChange={(event) => setIncludeSummary(event.target.checked)}
                                    className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]"
                                />
                                <span className="min-w-0">
                                    <span className="flex items-center gap-1.5 text-sm font-medium text-text-1">
                                        <Sparkles size={13} className="text-accent" />
                                        Include an AI-generated intro
                                    </span>
                                    <span className="mt-0.5 block text-xs text-text-3">
                                        {ids.length > 1
                                            ? 'One intro is written for each conversation, so this takes longer for a large export.'
                                            : 'Adds a little time to the export.'}
                                    </span>
                                </span>
                            </label>

                            {includeSummary && (
                                <div className="mt-3 rounded-xl border border-edge p-3">
                                    <label
                                        htmlFor="export-summary-model"
                                        className="block text-xs font-medium text-text-2"
                                    >
                                        Summary model
                                    </label>
                                    <select
                                        id="export-summary-model"
                                        value={effectiveModelKey}
                                        onChange={(event) =>
                                            setSummaryModelKey(event.target.value)
                                        }
                                        disabled={!models?.length}
                                        className="mt-1.5 w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1 outline-none focus:border-accent disabled:opacity-60"
                                    >
                                        {models?.length ? (
                                            models.map((model, index) => (
                                                <option
                                                    key={modelSelectionKey(model) || index}
                                                    value={modelSelectionKey(model) || ''}
                                                >
                                                    {(model.display_name as string) ||
                                                        (model.deployment_name as string) ||
                                                        'Model'}
                                                </option>
                                            ))
                                        ) : (
                                            <option value="">No chat models available</option>
                                        )}
                                    </select>
                                    <p className="mt-1.5 text-[11px] text-text-3">
                                        The same models the composer offers.
                                    </p>
                                </div>
                            )}
                        </section>
                    )}

                    {step === 'download' && (
                        <section>
                            <h3 className="text-sm font-semibold text-text-1">Ready to export</h3>
                            <p className="mt-1 mb-3 text-xs text-text-3">
                                Check the details, then download.
                            </p>

                            <dl className="overflow-hidden rounded-xl border border-edge text-sm">
                                {[
                                    [
                                        'Conversations',
                                        `${ids.length} conversation${ids.length === 1 ? '' : 's'}`,
                                    ],
                                    ['Format', FORMAT_LABEL[format]],
                                    [
                                        'Packaging',
                                        packaging === 'zip' ? 'ZIP archive' : 'Single file',
                                    ],
                                    ['Intro summary', includeSummary ? 'Included' : 'None'],
                                    ['File type', conversationExportExtension(format, packaging)],
                                ].map(([label, value]) => (
                                    <div
                                        key={label}
                                        className="flex gap-3 border-b border-edge px-3 py-2 last:border-b-0"
                                    >
                                        <dt className="w-32 shrink-0 text-xs text-text-3">
                                            {label}
                                        </dt>
                                        <dd className="min-w-0 flex-1 text-xs font-medium text-text-1">
                                            {value}
                                        </dd>
                                    </div>
                                ))}
                            </dl>

                            {failure && (
                                <p
                                    role="alert"
                                    className="mt-3 flex items-start gap-2 rounded-xl border border-danger bg-danger-soft px-3 py-2 text-xs text-danger"
                                >
                                    <CircleAlert size={14} className="mt-px shrink-0" />
                                    <span>{failure}</span>
                                </p>
                            )}

                            {progress && (
                                <p className="mt-3 flex items-center gap-2 text-xs text-text-3">
                                    <Loader2 size={13} className="animate-spin" />
                                    {progress}
                                </p>
                            )}
                        </section>
                    )}
                </div>

                <div className="flex h-16 shrink-0 items-center gap-2 border-t border-edge px-5">
                    <GlassButton
                        variant="ghost"
                        size="sm"
                        onClick={() => setStepIndex((index) => Math.max(0, index - 1))}
                        disabled={stepIndex === 0 || busy}
                    >
                        <ChevronLeft size={14} /> Back
                    </GlassButton>

                    <div className="ml-auto flex items-center gap-2">
                        {isLastStep ? (
                            <GlassButton
                                variant="primary"
                                size="sm"
                                onClick={runExport}
                                disabled={busy || finished || ids.length === 0}
                            >
                                {busy ? (
                                    <>
                                        <Loader2 size={14} className="animate-spin" /> Exporting…
                                    </>
                                ) : finished ? (
                                    <>
                                        <Check size={14} /> Downloaded
                                    </>
                                ) : (
                                    <>
                                        <Download size={14} />
                                        {failure ? 'Try again' : 'Download'}
                                    </>
                                )}
                            </GlassButton>
                        ) : (
                            <GlassButton
                                variant="primary"
                                size="sm"
                                onClick={() =>
                                    setStepIndex((index) =>
                                        Math.min(steps.length - 1, index + 1),
                                    )
                                }
                                disabled={ids.length === 0}
                            >
                                Next <ChevronRight size={14} />
                            </GlassButton>
                        )}
                    </div>
                </div>
            </GlassPanel>
        </div>,
        // Portalled to the body deliberately. The rail lives inside a `.glass` element, and a
        // non-`none` backdrop-filter makes an element a containing block for fixed-position
        // descendants — so rendered in place, `fixed inset-0` would resolve to the 280px
        // sidebar rather than the viewport, drawing the wizard as a narrow column with a
        // backdrop that dimmed only the rail.
        document.body,
    );
}
