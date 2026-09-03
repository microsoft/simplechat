// DiagramEditor.tsx
// Edit mode for a rendered diagram: source, layout, a scoped AI conversation, and history.
//
// This is what makes a generated diagram something you can live with. Before it, the only way
// to change one was to ask again in the thread, which produced another message with another
// diagram and left the conversation full of near-duplicates.
//
// The panel deliberately contains no HTML sink. Diagram markup is written to the DOM in exactly
// one reviewed file — MermaidDiagram.tsx — and test_v2_rich_rendering.py enforces that by
// failing when any other component sets inner HTML directly. The preview is therefore passed in
// as `renderPreview`, already rendered, rather than drawn here.

import { useEffect, useMemo, useRef, useState } from 'react';
import { History, PenLine, RotateCcw, Send, Sparkles, Wand2, X } from 'lucide-react';
import { GlassPanel } from '../ui/primitives';
import { describeSourceProblem, MAX_INSTRUCTION_LENGTH } from '../../lib/blockRevisions';
import type { BlockRevision, BlockRevisionChatTurn } from '../../lib/blockRevisions';
import {
    FLOW_DIRECTION_LABELS,
    FLOW_DIRECTIONS,
    readFlowDirection,
    readSpacingPreset,
    setFlowDirection,
    setSpacingPreset,
    SPACING_LABELS,
    SPACING_PRESETS,
    type FlowDirection,
    type SpacingPreset,
} from '../../lib/mermaidLayout';

type EditorTab = 'source' | 'layout' | 'ask' | 'history';

const TABS: { id: EditorTab; label: string; icon: typeof PenLine }[] = [
    { id: 'source', label: 'Source', icon: PenLine },
    { id: 'layout', label: 'Layout', icon: Wand2 },
    { id: 'ask', label: 'Ask AI', icon: Sparkles },
    { id: 'history', label: 'History', icon: History },
];

/** How a revision came about, in words a reader recognises. */
const ORIGIN_LABELS: Record<string, string> = {
    original: 'As generated',
    manual: 'Edited',
    control: 'Layout change',
    ai: 'AI edit',
};

function formatTimestamp(value: string | undefined): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString();
}

/** A small pill button, used for the direction and spacing choices. */
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

export interface DiagramEditorProps {
    title: string;
    /** What the diagram currently renders as, and the starting point for an edit. */
    currentSource: string;
    revisions: BlockRevision[];
    currentIndex: number;
    chat: BlockRevisionChatTurn[];
    canPersist: boolean;
    busy: boolean;
    error: string | null;
    onClearError: () => void;
    onSave: (source: string, origin?: 'manual' | 'control', note?: string) => Promise<boolean>;
    onRestore: (revisionId: string) => Promise<boolean>;
    onAsk: (instruction: string) => Promise<boolean>;
    /** Renders a diagram. Passed in so the only markup sink stays in MermaidDiagram.tsx. */
    renderPreview: (source: string) => React.ReactNode;    onClose: () => void;
}

export function DiagramEditor({
    title,
    currentSource,
    revisions,
    currentIndex,
    chat,
    canPersist,
    busy,
    error,
    onClearError,
    onSave,
    onRestore,
    onAsk,
    renderPreview,
    onClose,
}: DiagramEditorProps) {
    const [tab, setTab] = useState<EditorTab>('source');
    const [draft, setDraft] = useState(currentSource);
    const [instruction, setInstruction] = useState('');
    const closeRef = useRef<HTMLButtonElement>(null);

    // The stored source is the source of truth. When it changes underneath — an AI edit landed,
    // a revision was restored — the draft follows it, because the reader is now looking at
    // something else and an unsynced editor would silently overwrite it on the next save.
    useEffect(() => {
        setDraft(currentSource);
    }, [currentSource]);

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

    const dirty = draft.trim() !== currentSource.trim();
    const problem = useMemo(() => (dirty ? describeSourceProblem(draft) : null), [dirty, draft]);
    const direction = readFlowDirection(draft);
    const spacing = readSpacingPreset(draft);

    // The preview follows the draft, so a change is visible before it is saved. An invalid draft
    // keeps showing the last good source rather than flashing an error on every keystroke.
    const previewSource = problem ? currentSource : draft;

    const applyLayout = async (next: string, note: string) => {
        setDraft(next);
        await onSave(next, 'control', note);
    };

    const submitInstruction = async () => {
        const asked = instruction.trim();
        if (!asked) {
            return;
        }
        const ok = await onAsk(asked);
        if (ok) {
            setInstruction('');
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label={`Editing ${title}`}
        >
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-[90vh] w-full max-w-7xl flex-col overflow-hidden"
            >
                <div className="flex shrink-0 items-center gap-2 border-b border-edge px-5 py-3">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-1">
                        {title}
                    </h2>
                    {busy && <span className="text-xs text-text-3">Working…</span>}
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

                {!canPersist && (
                    <p className="shrink-0 border-b border-edge bg-surface-sunken px-5 py-2 text-xs text-text-3">
                        This diagram cannot be edited until the reply has finished.
                    </p>
                )}

                {error && (
                    <div className="flex shrink-0 items-start gap-2 border-b border-edge bg-danger/10 px-5 py-2">
                        <p className="flex-1 text-xs text-danger">{error}</p>
                        <button
                            type="button"
                            onClick={onClearError}
                            className="text-xs text-danger underline"
                        >
                            Dismiss
                        </button>
                    </div>
                )}

                <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                    <div className="min-h-0 flex-1 overflow-auto border-b border-edge p-4 lg:border-b-0 lg:border-r">
                        {renderPreview(previewSource)}
                    </div>

                    <div className="flex min-h-0 w-full flex-col lg:w-[26rem]">
                        <div
                            role="tablist"
                            aria-label="Diagram editing tools"
                            className="flex shrink-0 gap-1 border-b border-edge px-3 py-2"
                        >
                            {TABS.map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    type="button"
                                    role="tab"
                                    aria-selected={tab === id}
                                    onClick={() => setTab(id)}
                                    className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors ${
                                        tab === id
                                            ? 'bg-surface-2 text-text-1'
                                            : 'text-text-3 hover:bg-surface-2 hover:text-text-1'
                                    }`}
                                >
                                    <Icon size={13} />
                                    {label}
                                </button>
                            ))}
                        </div>

                        <div className="min-h-0 flex-1 overflow-auto p-3">
                            {tab === 'source' && (
                                <div className="flex h-full flex-col gap-2">
                                    <label
                                        htmlFor="diagram-source"
                                        className="text-xs font-medium text-text-2"
                                    >
                                        Mermaid source
                                    </label>
                                    <textarea
                                        id="diagram-source"
                                        value={draft}
                                        spellCheck={false}
                                        onChange={(event) => setDraft(event.target.value)}
                                        className="min-h-0 flex-1 resize-none rounded-lg border border-edge-strong bg-surface-sunken p-2 font-mono text-xs text-text-1 outline-none focus:border-accent"
                                    />
                                    {problem && <p className="text-xs text-danger">{problem}</p>}
                                    <div className="flex items-center gap-2">
                                        <button
                                            type="button"
                                            disabled={!dirty || Boolean(problem) || busy || !canPersist}
                                            onClick={() => void onSave(draft)}
                                            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            Save version
                                        </button>
                                        <button
                                            type="button"
                                            disabled={!dirty || busy}
                                            onClick={() => setDraft(currentSource)}
                                            className="rounded-lg px-3 py-1.5 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            Discard changes
                                        </button>
                                    </div>
                                </div>
                            )}

                            {tab === 'layout' && (
                                <div className="flex flex-col gap-4">
                                    <div className="flex flex-col gap-2">
                                        <p className="text-xs font-medium text-text-2">Direction</p>
                                        {direction ? (
                                            <div className="flex flex-wrap gap-1.5">
                                                {FLOW_DIRECTIONS.map((option: FlowDirection) => (
                                                    <ChoiceButton
                                                        key={option}
                                                        active={direction === option}
                                                        disabled={busy || !canPersist}
                                                        onClick={() =>
                                                            void applyLayout(
                                                                setFlowDirection(draft, option),
                                                                `Direction: ${FLOW_DIRECTION_LABELS[option]}`,
                                                            )
                                                        }
                                                    >
                                                        {FLOW_DIRECTION_LABELS[option]}
                                                    </ChoiceButton>
                                                ))}
                                            </div>
                                        ) : (
                                            <p className="text-xs text-text-3">
                                                This kind of diagram does not have a flow direction.
                                            </p>
                                        )}
                                    </div>

                                    <div className="flex flex-col gap-2">
                                        <p className="text-xs font-medium text-text-2">Spacing</p>
                                        <div className="flex flex-wrap gap-1.5">
                                            {SPACING_PRESETS.map((option: SpacingPreset) => (
                                                <ChoiceButton
                                                    key={option}
                                                    active={spacing === option}
                                                    disabled={busy || !canPersist}
                                                    onClick={() =>
                                                        void applyLayout(
                                                            setSpacingPreset(draft, option),
                                                            `Spacing: ${SPACING_LABELS[option]}`,
                                                        )
                                                    }
                                                >
                                                    {SPACING_LABELS[option]}
                                                </ChoiceButton>
                                            ))}
                                        </div>
                                    </div>

                                    <p className="text-xs leading-relaxed text-text-3">
                                        Mermaid works out where the boxes go, so they cannot be
                                        dragged to a position. Changing the direction or the
                                        spacing, or reordering the statements in the source, is
                                        how a diagram gets rearranged.
                                    </p>
                                </div>
                            )}

                            {tab === 'ask' && (
                                <div className="flex h-full flex-col gap-2">
                                    {chat.length === 0 ? (
                                        <p className="text-xs leading-relaxed text-text-3">
                                            Describe a change and it is applied to this diagram
                                            alone. Nothing here is added to the conversation, and
                                            only the version you keep is used as context later.
                                        </p>
                                    ) : (
                                        <ul className="flex min-h-0 flex-1 list-none flex-col gap-2 overflow-auto">
                                            {chat.map((turn, index) => (
                                                <li
                                                    key={`${turn.timestamp ?? ''}-${index}`}
                                                    className={
                                                        turn.role === 'user'
                                                            ? 'self-end rounded-lg bg-accent/10 px-2.5 py-1.5 text-xs text-text-1'
                                                            : 'self-start rounded-lg bg-surface-sunken px-2.5 py-1.5 font-mono text-[11px] text-text-2'
                                                    }
                                                >
                                                    {turn.role === 'assistant'
                                                        ? 'Updated the diagram.'
                                                        : turn.content}
                                                </li>
                                            ))}
                                        </ul>
                                    )}

                                    <div className="mt-auto flex flex-col gap-2">
                                        <label htmlFor="diagram-instruction" className="sr-only">
                                            Describe the change you want
                                        </label>
                                        <textarea
                                            id="diagram-instruction"
                                            value={instruction}
                                            rows={3}
                                            maxLength={MAX_INSTRUCTION_LENGTH}
                                            placeholder="Make it left to right and add a review step after approval"
                                            onChange={(event) => setInstruction(event.target.value)}
                                            onKeyDown={(event) => {
                                                if (event.key === 'Enter' && !event.shiftKey) {
                                                    event.preventDefault();
                                                    void submitInstruction();
                                                }
                                            }}
                                            className="resize-none rounded-lg border border-edge-strong bg-surface-sunken p-2 text-xs text-text-1 outline-none focus:border-accent"
                                        />
                                        <button
                                            type="button"
                                            disabled={!instruction.trim() || busy || !canPersist}
                                            onClick={() => void submitInstruction()}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            <Send size={13} />
                                            {busy ? 'Updating…' : 'Update diagram'}
                                        </button>
                                    </div>
                                </div>
                            )}

                            {tab === 'history' && (
                                <ul className="flex list-none flex-col gap-1.5">
                                    {revisions.length === 0 && (
                                        <li className="text-xs text-text-3">
                                            This diagram has not been edited yet.
                                        </li>
                                    )}
                                    {revisions
                                        .map((revision, index) => ({ revision, index }))
                                        .reverse()
                                        .map(({ revision, index }) => (
                                            <li
                                                key={revision.id}
                                                className={`rounded-lg border p-2 ${
                                                    index === currentIndex
                                                        ? 'border-accent bg-accent/5'
                                                        : 'border-edge-strong'
                                                }`}
                                            >
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-medium text-text-1">
                                                        {ORIGIN_LABELS[revision.origin] ?? 'Edited'}
                                                    </span>
                                                    {index === currentIndex && (
                                                        <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                                                            Showing
                                                        </span>
                                                    )}
                                                    {index !== currentIndex && (
                                                        <button
                                                            type="button"
                                                            disabled={busy || !canPersist}
                                                            onClick={() => void onRestore(revision.id)}
                                                            className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                                                        >
                                                            <RotateCcw size={11} />
                                                            Restore
                                                        </button>
                                                    )}
                                                </div>
                                                {revision.note && (
                                                    <p className="mt-1 text-[11px] text-text-2">
                                                        {revision.note}
                                                    </p>
                                                )}
                                                <p className="mt-1 text-[11px] text-text-3">
                                                    {[revision.author_name, formatTimestamp(revision.timestamp)]
                                                        .filter(Boolean)
                                                        .join(' · ')}
                                                </p>
                                            </li>
                                        ))}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </GlassPanel>
        </div>
    );
}
