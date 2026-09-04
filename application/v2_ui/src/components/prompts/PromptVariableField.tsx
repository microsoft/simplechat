// PromptVariableField.tsx
// One placeholder from a saved prompt, offered as something to fill in.
//
// Extracted from PromptVariablesDialog so the composer's attached-prompt card and anything
// else that fills a prompt render a field the same way. Two surfaces drawing their own field
// is how the badge that marks an auto-filled value ends up on one of them and not the other,
// and a value that does not read as auto-filled is one that gets sent without being read.
//
// The rules this preserves, all of which exist because a wrong pre-filled value is worse than
// an empty box:
//
//   1. Anything filled in for you is badged and clearable in one click, so it never reads as
//      something you typed.
//   2. Values pulled from the conversation are pulled one field at a time, by you. Nothing
//      reaches in and takes the last assistant reply on its own -- that reply can quote an
//      uploaded document, and text from a document becoming part of your next instruction is
//      how prompt injection gets a foothold.
//   3. Built-ins are resolved and shown read-only: `{{today}}` is not a question worth asking.

import { clsx } from 'clsx';
import { RotateCcw, Sparkles } from 'lucide-react';
import {
    BUILT_IN_PROMPT_VARIABLE_LABELS,
    type BuiltInPromptVariable,
    type PromptVariable,
} from '../../lib/promptVariables';

/** A one-click value offered under a field, e.g. the last assistant reply. */
export interface PromptFillSource {
    label: string;
    value: string;
}

export function PromptVariableField({
    variable,
    value,
    builtInValue,
    /** Whether this value arrived on its own rather than from the reader. */
    prefilled,
    history = [],
    sources = [],
    onChange,
    /** Distinguishes ids when more than one card is on the page. */
    idPrefix = 'prompt-var',
}: {
    variable: PromptVariable;
    value: string;
    builtInValue?: string;
    prefilled: boolean;
    history?: string[];
    sources?: PromptFillSource[];
    onChange: (value: string) => void;
    idPrefix?: string;
}) {
    const isResolvedBuiltIn = variable.builtIn && Boolean(builtInValue);
    const fieldId = `${idPrefix}-${variable.key}`;
    const offered = history.filter((item) => item !== value);

    return (
        <div>
            <div className="mb-1 flex items-center gap-2">
                <label htmlFor={fieldId} className="font-mono text-xs font-medium text-text-2">
                    {`{{${variable.name}}}`}
                </label>
                {prefilled ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] leading-none font-medium text-accent">
                        <Sparkles size={9} />
                        {isResolvedBuiltIn ? 'From this chat' : 'Reused'}
                    </span>
                ) : null}
                {!isResolvedBuiltIn && value ? (
                    <button
                        type="button"
                        onClick={() => onChange('')}
                        className="ml-auto inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-text-1"
                    >
                        <RotateCcw size={10} />
                        Clear
                    </button>
                ) : null}
            </div>

            {isResolvedBuiltIn ? (
                <p className="rounded-lg border border-edge bg-surface-sunken px-2.5 py-1.5 text-sm text-text-2">
                    {builtInValue}
                    <span className="mt-0.5 block text-[11px] text-text-3">
                        {BUILT_IN_PROMPT_VARIABLE_LABELS[variable.key as BuiltInPromptVariable]}
                    </span>
                </p>
            ) : (
                <textarea
                    id={fieldId}
                    rows={2}
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder={variable.defaultValue || `Value for ${variable.name}`}
                    className={clsx(
                        'w-full resize-y rounded-lg border bg-surface-1 px-2.5 py-1.5 text-sm text-text-1',
                        'placeholder:text-text-3 focus:border-accent focus:outline-none',
                        prefilled ? 'border-accent/50' : 'border-edge',
                    )}
                />
            )}

            {!isResolvedBuiltIn && (offered.length > 0 || sources.length > 0) ? (
                <div className="mt-1 flex flex-wrap items-center gap-1">
                    {offered.slice(0, 4).map((item) => (
                        <button
                            key={item}
                            type="button"
                            title={item}
                            onClick={() => onChange(item)}
                            className="max-w-[14rem] truncate rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-[11px] text-text-2 transition-colors hover:border-accent hover:text-text-1"
                        >
                            {item}
                        </button>
                    ))}
                    {sources.map((source) => (
                        <button
                            key={source.label}
                            type="button"
                            title={source.value}
                            onClick={() => onChange(source.value)}
                            className="rounded-full border border-dashed border-edge px-2 py-0.5 text-[11px] text-text-3 transition-colors hover:border-accent hover:text-text-1"
                        >
                            {source.label}
                        </button>
                    ))}
                </div>
            ) : null}
        </div>
    );
}
