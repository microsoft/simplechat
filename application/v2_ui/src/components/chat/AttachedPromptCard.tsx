// AttachedPromptCard.tsx
// A saved prompt attached to the turn being written, shown above the message box.
//
// Picking a prompt used to paste its text into the composer. That answered the question "what
// does this prompt say" and lost every other one: which part of the box is the template and
// which part is yours, how to take it back off, how to change a variable you got wrong. The
// text was just text, and the prompt stopped existing the moment it was inserted.
//
// So the prompt stays a prompt until send. It sits here as a card, the box below stays yours
// to type in, and the two are combined only when the message is actually sent.
//
// Collapsed by default, because the common case is a prompt you already know the contents of
// and a message you want room to write. It expands to fill in variables, read the resolved
// text, or edit the wording for this one turn -- an edit that never touches the saved prompt,
// which is why it is badged and reversible rather than silent.

import { useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, Lightbulb, Pencil, RotateCcw, X } from 'lucide-react';
import type { BuiltInPromptVariable } from '../../lib/promptVariables';
import type { PromptVariableValues } from '../../lib/usePromptVariableValues';
import {
    PromptVariableField,
    type PromptFillSource,
} from '../prompts/PromptVariableField';

export type { PromptFillSource };

export function AttachedPromptCard({
    name,
    scopeLabel,
    content,
    edited,
    variableState,
    sources = [],
    disabled = false,
    onContentChange,
    onResetContent,
    onRemove,
}: {
    name: string;
    scopeLabel?: string;
    /** The wording this turn will use: the edited text when there is one, else the saved text. */
    content: string;
    edited: boolean;
    variableState: PromptVariableValues;
    sources?: PromptFillSource[];
    disabled?: boolean;
    onContentChange: (value: string) => void;
    onResetContent: () => void;
    onRemove: () => void;
}) {
    const [open, setOpen] = useState(false);
    const [editing, setEditing] = useState(false);

    const { variables, values, builtIns, prefilled, unfilled, history, setValue, resolve } =
        variableState;

    // One line, because it is read at a glance while writing something else. What is still
    // missing outranks how many there are: an unfilled placeholder is the thing that would
    // reach the model as a literal `{{customer}}`.
    const summary =
        variables.length === 0
            ? null
            : unfilled.length > 0
              ? `${unfilled.length} still to fill in`
              : `${variables.length} variable${variables.length === 1 ? '' : 's'} ready`;

    return (
        <div className="mb-2 rounded-xl border border-edge glass-flat">
            <div className="flex items-center gap-1.5 px-2 py-1.5">
                <button
                    type="button"
                    onClick={() => setOpen((isOpen) => !isOpen)}
                    aria-expanded={open}
                    className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-1 py-0.5 text-left text-xs text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <Lightbulb size={13} className="shrink-0 text-accent" aria-hidden="true" />
                    <span className="truncate font-medium text-text-1">{name}</span>
                    {scopeLabel ? (
                        <span className="shrink-0 truncate text-text-3">{scopeLabel}</span>
                    ) : null}
                    {edited ? (
                        <span className="shrink-0 rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] leading-none font-medium text-accent">
                            Edited
                        </span>
                    ) : null}
                    {summary ? (
                        <span
                            className={clsx(
                                'shrink-0 rounded-full px-1.5 py-0.5 text-[10px] leading-none',
                                unfilled.length > 0
                                    ? 'bg-accent-soft font-medium text-accent'
                                    : 'text-text-3',
                            )}
                        >
                            {summary}
                        </span>
                    ) : null}
                    <ChevronDown
                        size={12}
                        aria-hidden="true"
                        className={clsx('ml-auto shrink-0 transition-transform', open && 'rotate-180')}
                    />
                </button>

                <button
                    type="button"
                    onClick={() => {
                        setOpen(true);
                        setEditing((isEditing) => !isEditing);
                    }}
                    disabled={disabled}
                    aria-label={`Edit ${name} for this message`}
                    title="Edit for this message only"
                    className="shrink-0 rounded-md p-1 text-text-3 hover:bg-surface-3 hover:text-text-1 disabled:opacity-50"
                >
                    <Pencil size={12} />
                </button>
                <button
                    type="button"
                    onClick={onRemove}
                    aria-label={`Remove ${name}`}
                    title="Remove prompt"
                    className="shrink-0 rounded-md p-1 text-text-3 hover:bg-surface-3 hover:text-text-1"
                >
                    <X size={13} />
                </button>
            </div>

            {open ? (
                <div className="space-y-3 border-t border-edge px-3 py-2.5">
                    {variables.map((variable) => (
                        <PromptVariableField
                            key={variable.key}
                            variable={variable}
                            value={values[variable.key] ?? ''}
                            builtInValue={builtIns[variable.key as BuiltInPromptVariable]}
                            prefilled={prefilled.has(variable.key)}
                            history={history[variable.key] ?? []}
                            sources={sources}
                            onChange={(value) => setValue(variable.key, value)}
                            idPrefix="attached-prompt-var"
                        />
                    ))}

                    {editing ? (
                        <div>
                            <div className="mb-1 flex items-center gap-2">
                                <label
                                    htmlFor="attached-prompt-content"
                                    className="text-[11px] font-semibold tracking-wide text-text-3 uppercase"
                                >
                                    Prompt text
                                </label>
                                <span className="text-[11px] text-text-3">
                                    Changes apply to this message only
                                </span>
                                {edited ? (
                                    <button
                                        type="button"
                                        onClick={onResetContent}
                                        className="ml-auto inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-text-1"
                                    >
                                        <RotateCcw size={10} />
                                        Reset
                                    </button>
                                ) : null}
                            </div>
                            <textarea
                                id="attached-prompt-content"
                                rows={6}
                                value={content}
                                disabled={disabled}
                                onChange={(event) => onContentChange(event.target.value)}
                                className="w-full resize-y rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 font-mono text-xs text-text-1 focus:border-accent focus:outline-none"
                            />
                        </div>
                    ) : (
                        <div>
                            <h4 className="mb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                                {variables.length > 0 ? 'Preview' : 'Prompt text'}
                            </h4>
                            <pre className="max-h-48 overflow-y-auto rounded-lg border border-edge bg-surface-sunken px-2.5 py-2 text-xs whitespace-pre-wrap text-text-2">
                                {resolve()}
                            </pre>
                        </div>
                    )}
                </div>
            ) : null}
        </div>
    );
}
