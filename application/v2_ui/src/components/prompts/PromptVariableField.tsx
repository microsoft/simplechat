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

import { useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, RotateCcw, Sparkles } from 'lucide-react';
import type { PromptKnowledgeUnresolved, PromptKnowledgeValue } from '../../lib/promptKnowledge';
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
    disabled = false,
    /** Distinguishes ids when more than one card is on the page. */
    idPrefix = 'prompt-var',
    aiValue,
    unresolved,
    finding = false,
    onFind,
    onUndo,
    onChooseAlternative,
}: {
    variable: PromptVariable;
    value: string;
    builtInValue?: string;
    prefilled: boolean;
    history?: string[];
    sources?: PromptFillSource[];
    onChange: (value: string) => void;
    disabled?: boolean;
    idPrefix?: string;
    aiValue?: PromptKnowledgeValue;
    unresolved?: PromptKnowledgeUnresolved;
    finding?: boolean;
    onFind?: () => void;
    onUndo?: () => void;
    onChooseAlternative?: (value: PromptKnowledgeValue) => void;
}) {
    const [sourcesOpen, setSourcesOpen] = useState(false);
    const isResolvedBuiltIn = variable.builtIn && Boolean(builtInValue || variable.defaultValue);
    const fieldId = `${idPrefix}-${variable.key}`;
    const offered = history.filter((item) => item !== value);
    const displayName = variable.name.replace(/[_-]+/g, ' ');

    return (
        <div>
            <div className="mb-1 flex flex-wrap items-center gap-2">
                <label id={`${fieldId}-label`} htmlFor={fieldId} className="text-xs font-medium text-text-2">
                    {displayName}
                </label>
                {aiValue ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] text-accent">
                        <Sparkles size={9} /> AI-filled
                    </span>
                ) : prefilled || builtInValue ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] leading-none font-medium text-accent">
                        <Sparkles size={9} />
                        {isResolvedBuiltIn ? 'From this chat' : 'Reused'}
                    </span>
                ) : variable.defaultValue && (!value || value === variable.defaultValue) ? (
                    <span className="text-[10px] text-text-3">Default</span>
                ) : value ? <span className="text-[10px] text-text-3">Your value</span> : null}
                {!variable.builtIn && value ? (
                    <button
                        type="button"
                        disabled={disabled}
                        onClick={() => onChange('')}
                        className="ml-auto inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-text-1"
                    >
                        <RotateCcw size={10} />
                        Clear
                    </button>
                ) : null}
            </div>
            <code className="mb-1 block text-[10px] text-text-3">{`{{${variable.name}}}`}</code>

            {isResolvedBuiltIn ? (
                <p id={fieldId} tabIndex={-1} aria-labelledby={`${fieldId}-label`}
                    className="max-h-24 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-edge bg-surface-sunken px-2.5 py-1.5 text-sm text-text-2">
                    {builtInValue || variable.defaultValue}
                    <span className="mt-0.5 block text-[11px] text-text-3">
                        {BUILT_IN_PROMPT_VARIABLE_LABELS[variable.key as BuiltInPromptVariable]}
                    </span>
                </p>
            ) : variable.builtIn ? (
                <p id={fieldId} tabIndex={-1} aria-labelledby={`${fieldId}-label`} className="rounded-lg border border-edge px-2.5 py-1.5 text-xs text-text-3">
                    Not available in this chat yet. Add the relevant context, supply a template default, or remove this variable.
                </p>
            ) : (
                <textarea
                    id={fieldId}
                    rows={2}
                    value={value}
                    disabled={disabled}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder={variable.defaultValue || `Value for ${variable.name}`}
                    className={clsx(
                        'w-full resize-y rounded-lg border bg-surface-1 px-2.5 py-1.5 text-sm text-text-1',
                        'placeholder:text-text-3 focus:border-accent focus:outline-none',
                        prefilled ? 'border-accent/50' : 'border-edge',
                    )}
                />
            )}

            {!variable.builtIn && (offered.length > 0 || sources.length > 0) ? (
                <div className="mt-1 flex flex-wrap items-center gap-1">
                    {offered.slice(0, 4).map((item) => (
                        <button
                            key={item}
                            type="button"
                            disabled={disabled}
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
                            disabled={disabled}
                            title={source.value}
                            onClick={() => onChange(source.value)}
                            className="rounded-full border border-dashed border-edge px-2 py-0.5 text-[11px] text-text-3 transition-colors hover:border-accent hover:text-text-1"
                        >
                            {source.label}
                        </button>
                    ))}
                </div>
            ) : null}
            {!variable.builtIn && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                    {onFind && (
                        <button type="button" onClick={onFind}
                            disabled={disabled || finding || Boolean(value.trim() || variable.defaultValue)}
                            className="inline-flex items-center gap-1 rounded px-1 py-1 text-accent hover:bg-accent-soft disabled:opacity-50">
                            {finding ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                            {finding ? 'Finding a value...' : 'Find in knowledge'}
                        </button>
                    )}
                    {aiValue && (
                        <>
                            <button type="button" onClick={() => setSourcesOpen((open) => !open)}
                                aria-expanded={sourcesOpen} className="rounded px-1 py-1 text-accent hover:bg-accent-soft">
                                Sources ({aiValue.sources.length})
                            </button>
                            <button type="button" onClick={onUndo} disabled={disabled}
                                aria-label={`Undo AI fill for ${displayName}`}
                                className="inline-flex items-center gap-1 rounded px-1 py-1 text-text-3 hover:bg-surface-2 disabled:opacity-50">
                                <RotateCcw size={10} /> Undo
                            </button>
                        </>
                    )}
                </div>
            )}
            {aiValue && sourcesOpen && (
                <ul aria-label={`Sources for ${displayName}`} className="mt-1 max-h-40 space-y-2 overflow-y-auto rounded-lg bg-surface-sunken p-2 text-xs text-text-2">
                    {aiValue.sources.map((source, index) => (
                        <li key={`${source.document_id}-${source.chunk_id}-${index}`}>
                            <p className="font-medium">{source.title}
                                {source.page_number !== undefined && `, page ${source.page_number}`}
                            </p>
                            <blockquote className="mt-1 whitespace-pre-wrap break-words text-text-3">{source.excerpt}</blockquote>
                        </li>
                    ))}
                </ul>
            )}
            {unresolved && (
                <div className="mt-1 text-xs text-text-3">
                    <p>{unresolved.reason}</p>
                    {unresolved.alternatives?.map((alternative, index) => (
                        <button key={index} type="button" disabled={disabled || Boolean(value.trim())}
                            onClick={() => onChooseAlternative?.(alternative)}
                            className="mt-1 block max-w-full rounded-lg border border-edge px-2 py-1 text-left text-text-2 hover:border-accent disabled:opacity-50">
                            <span className="block whitespace-pre-wrap break-words">Use {alternative.value}</span>
                            <span className="text-[10px] text-text-3">{alternative.sources.map((source) => source.title).join(', ')}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
