// PromptEditorDialog.tsx
// Writing a prompt: a modal with the source and its rendering side by side.
//
// The section used to edit in place, above the list. Clicking Edit on a row far down the page
// moved the form to the top, out of view, with nothing tying it to the row that was clicked --
// so the first thing you did after pressing Edit was scroll to find the editor. A modal has no
// position to lose.
//
// Source and preview sit side by side from `lg` and become tabs below it, rather than the
// preview being dropped on a narrow screen: a prompt is markdown, and the whole reason to show
// a preview is that a list of five bullets and a paragraph containing hyphens look identical in
// a textarea.
//
// The toolbar deliberately stops at the marks that change meaning rather than appearance.
// A prompt is read by a model, and the things worth being able to insert quickly are the ones
// that structure the instruction -- headings, lists, code -- plus a variable, which is the one
// piece of syntax specific to this application and therefore the one nobody will guess.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Braces, Code, Eye, Heading, List, ListOrdered, PenLine, Quote } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { PlainMarkdown } from '../ui/PlainMarkdown';
import { parsePromptVariables } from '../../lib/promptVariables';
import { VariableChip } from './promptPresentation';

export interface PromptDraft {
    id: string | null;
    name: string;
    description: string;
    content: string;
}

export const EMPTY_PROMPT_DRAFT: PromptDraft = {
    id: null,
    name: '',
    description: '',
    content: '',
};

type EditorTab = 'write' | 'preview';

/**
 * Wrap or insert around the current selection.
 *
 * Returns the new value and where the selection should end up, so inserting a heading on an
 * empty line leaves the caret after the marker and wrapping a word keeps that word selected.
 */
function applyMarkdown(
    value: string,
    start: number,
    end: number,
    action: { prefix: string; suffix?: string; block?: boolean; placeholder?: string },
): { text: string; start: number; end: number } {
    const suffix = action.suffix ?? '';
    const selected = value.slice(start, end) || action.placeholder || '';

    if (action.block) {
        // Block marks apply from the start of the line, otherwise a heading inserted mid-line
        // produces `some text ## ` which is not a heading at all.
        const lineStart = value.lastIndexOf('\n', start - 1) + 1;
        const before = value.slice(0, lineStart);
        const after = value.slice(lineStart);
        const needsBlankLine = before && !before.endsWith('\n\n') && before.endsWith('\n');
        const lead = needsBlankLine ? '' : before && !before.endsWith('\n') ? '\n' : '';
        const text = `${before}${lead}${action.prefix}${after}`;
        const caret = lineStart + lead.length + action.prefix.length + (start - lineStart);
        return { text, start: caret, end: caret };
    }

    const text = `${value.slice(0, start)}${action.prefix}${selected}${suffix}${value.slice(end)}`;
    return {
        text,
        start: start + action.prefix.length,
        end: start + action.prefix.length + selected.length,
    };
}

const TOOLBAR: {
    label: string;
    icon: typeof Heading;
    prefix: string;
    suffix?: string;
    block?: boolean;
    placeholder?: string;
}[] = [
    { label: 'Heading', icon: Heading, prefix: '## ', block: true },
    { label: 'Bulleted list', icon: List, prefix: '- ', block: true },
    { label: 'Numbered list', icon: ListOrdered, prefix: '1. ', block: true },
    { label: 'Quote', icon: Quote, prefix: '> ', block: true },
    { label: 'Code', icon: Code, prefix: '`', suffix: '`', placeholder: 'code' },
    { label: 'Variable', icon: Braces, prefix: '{{', suffix: '}}', placeholder: 'name' },
];

export function PromptEditorDialog({
    draft,
    saving,
    error,
    onChange,
    onSave,
    onCancel,
}: {
    draft: PromptDraft;
    saving: boolean;
    error: string | null;
    onChange: (next: PromptDraft) => void;
    onSave: () => void;
    onCancel: () => void;
}) {
    const [tab, setTab] = useState<EditorTab>('write');
    const [confirmingDiscard, setConfirmingDiscard] = useState(false);
    const contentRef = useRef<HTMLTextAreaElement>(null);
    const nameRef = useRef<HTMLInputElement>(null);

    // What the draft looked like when the dialog opened, so "has anything changed?" is a real
    // comparison rather than a flag every edit path has to remember to set.
    const [original] = useState(() => ({ ...draft }));
    const dirty =
        draft.name !== original.name ||
        draft.description !== original.description ||
        draft.content !== original.content;

    const variables = useMemo(() => parsePromptVariables(draft.content), [draft.content]);
    const canSave = draft.name.trim().length > 0 && draft.content.trim().length > 0;

    useEffect(() => {
        // Editing starts in the body far more often than in the name, but a new prompt needs a
        // name before anything else. An unfocused modal makes the first keystroke go nowhere.
        const target = draft.id ? contentRef.current : nameRef.current;
        target?.focus();
    }, [draft.id]);

    /** Escape and the backdrop route through here so unsaved work is not lost to a stray click. */
    const requestClose = () => {
        if (dirty && !confirmingDiscard) {
            setConfirmingDiscard(true);
            return;
        }
        onCancel();
    };

    const runToolbar = (action: (typeof TOOLBAR)[number]) => {
        const field = contentRef.current;
        if (!field) {
            return;
        }
        const result = applyMarkdown(draft.content, field.selectionStart, field.selectionEnd, action);
        onChange({ ...draft, content: result.text });
        // After React has written the new value back into the textarea.
        window.requestAnimationFrame(() => {
            field.focus();
            field.setSelectionRange(result.start, result.end);
        });
    };

    const sourcePane = (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-0.5 border-b border-edge px-2 py-1.5">
                {TOOLBAR.map((action) => {
                    const Icon = action.icon;
                    return (
                        <button
                            key={action.label}
                            type="button"
                            title={action.label}
                            aria-label={action.label}
                            onClick={() => runToolbar(action)}
                            className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <Icon size={14} />
                        </button>
                    );
                })}
            </div>
            <textarea
                id="prompt-content"
                ref={contentRef}
                value={draft.content}
                onChange={(event) => onChange({ ...draft, content: event.target.value })}
                placeholder={
                    'Summarise the attached documents for {{audience}} as five bullet points,\nthen list any open questions.'
                }
                spellCheck
                className="min-h-0 flex-1 resize-none bg-transparent px-3 py-2 font-mono text-sm text-text-1 placeholder:text-text-3 focus:outline-none"
            />
        </div>
    );

    const previewPane = (
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
            <PlainMarkdown
                content={draft.content}
                emptyLabel="Start writing and the rendered prompt appears here."
            />
        </div>
    );

    return (
        <Modal
            title={draft.id ? 'Edit prompt' : 'New prompt'}
            description="Prompts are markdown. Use {{name}} for anything you want to fill in each time."
            onClose={requestClose}
            size="xl"
            tall
            bodyClassName="min-h-0 flex-1 flex flex-col overflow-hidden"
            footer={
                confirmingDiscard ? (
                    <>
                        <span className="mr-auto text-xs text-text-3">
                            Discard your unsaved changes?
                        </span>
                        <GlassButton size="sm" onClick={() => setConfirmingDiscard(false)}>
                            Keep editing
                        </GlassButton>
                        <GlassButton variant="danger" size="sm" onClick={onCancel}>
                            Discard
                        </GlassButton>
                    </>
                ) : (
                    <>
                        {error ? (
                            <span className="mr-auto text-xs text-danger">{error}</span>
                        ) : variables.length > 0 ? (
                            <span className="mr-auto flex flex-wrap items-center gap-1.5 text-xs text-text-3">
                                Fills in:
                                {variables.map((variable) => (
                                    <VariableChip
                                        key={variable.key}
                                        name={variable.name}
                                        builtIn={variable.builtIn}
                                        hasDefault={Boolean(variable.defaultValue)}
                                    />
                                ))}
                            </span>
                        ) : null}
                        <GlassButton size="sm" onClick={requestClose} disabled={saving}>
                            Cancel
                        </GlassButton>
                        <GlassButton
                            variant="primary"
                            size="sm"
                            onClick={onSave}
                            disabled={!canSave || saving}
                        >
                            {saving ? 'Saving' : draft.id ? 'Save changes' : 'Create prompt'}
                        </GlassButton>
                    </>
                )
            }
        >
            <div className="grid shrink-0 gap-3 px-4 py-3 sm:grid-cols-2">
                <label className="block">
                    <span className="mb-1 block text-xs font-medium text-text-2">Name</span>
                    <input
                        id="prompt-name"
                        ref={nameRef}
                        type="text"
                        value={draft.name}
                        onChange={(event) => onChange({ ...draft, name: event.target.value })}
                        placeholder="Weekly status summary"
                        className="w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                </label>
                <label className="block">
                    <span className="mb-1 block text-xs font-medium text-text-2">
                        Description <span className="text-text-3">(optional)</span>
                    </span>
                    <input
                        id="prompt-description"
                        type="text"
                        maxLength={200}
                        value={draft.description}
                        onChange={(event) =>
                            onChange({ ...draft, description: event.target.value })
                        }
                        placeholder="What this is for, so future you can tell it apart"
                        className="w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                </label>
            </div>

            {/* Tabs below `lg`, where two panes would each be too narrow to read. */}
            <div className="flex shrink-0 gap-1 border-b border-edge px-4 lg:hidden">
                {(
                    [
                        ['write', 'Write', PenLine],
                        ['preview', 'Preview', Eye],
                    ] as const
                ).map(([value, label, Icon]) => (
                    <button
                        key={value}
                        type="button"
                        onClick={() => setTab(value)}
                        aria-pressed={tab === value}
                        className={clsx(
                            'flex items-center gap-1.5 border-b-2 px-2 py-1.5 text-xs font-medium transition-colors',
                            tab === value
                                ? 'border-accent text-accent'
                                : 'border-transparent text-text-3 hover:text-text-1',
                        )}
                    >
                        <Icon size={13} />
                        {label}
                    </button>
                ))}
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-2 lg:divide-x lg:divide-edge">
                <div
                    className={clsx(
                        'flex min-h-0 flex-col',
                        tab === 'write' ? 'flex' : 'hidden lg:flex',
                    )}
                >
                    {sourcePane}
                </div>
                <div
                    className={clsx(
                        'flex min-h-0 flex-col bg-surface-sunken/40',
                        tab === 'preview' ? 'flex' : 'hidden lg:flex',
                    )}
                >
                    {previewPane}
                </div>
            </div>
        </Modal>
    );
}
