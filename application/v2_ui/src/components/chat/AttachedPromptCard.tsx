// AttachedPromptCard.tsx
// The draft's prompt stays separate from the message and exposes its inputs before send.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, Pencil, RotateCcw, Sparkles, X } from 'lucide-react';
import type { BuiltInPromptVariable } from '../../lib/promptVariables';
import type { PromptVariableValues } from '../../lib/usePromptVariableValues';
import type { usePromptKnowledgeFill } from '../../lib/usePromptKnowledgeFill';
import {
    PromptVariableField,
    type PromptFillSource,
} from '../prompts/PromptVariableField';
import { PromptVariablePicker, usePromptVariableInsertion } from '../prompts/PromptVariablePicker';
import { PromptCard } from './PromptCard';

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
    knowledge,
    knowledgeEnabled = false,
    knowledgeControls,
    reviewRequest = 0,
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
    knowledge?: ReturnType<typeof usePromptKnowledgeFill>;
    knowledgeEnabled?: boolean;
    knowledgeControls?: ReactNode;
    reviewRequest?: number;
}) {
    const [open, setOpen] = useState(false);
    const [editing, setEditing] = useState(false);
    const [variablesOpen, setVariablesOpen] = useState(true);
    const contentRef = useRef<HTMLTextAreaElement>(null);
    const insertion = usePromptVariableInsertion(contentRef, content, onContentChange);

    const { variables, values, builtIns, prefilled, unfilled, history, setValue, resolve } =
        variableState;
    const firstMissing = useRef<string>();
    firstMissing.current = unfilled[0]?.key;
    useEffect(() => {
        if (reviewRequest === 0) {
            return;
        }
        setVariablesOpen(true);
        const frame = window.requestAnimationFrame(() => {
            document.getElementById(`attached-prompt-var-${firstMissing.current}`)?.focus();
        });
        return () => window.cancelAnimationFrame(frame);
    }, [reviewRequest]);

    const variableSummary =
        variables.length === 0
            ? null
            : unfilled.length > 0
              ? `${unfilled.length} ${unfilled.length === 1 ? 'value' : 'values'} still to fill in`
              : `${variables.length} variable${variables.length === 1 ? '' : 's'} ready`;
    const aiCount = variables.filter((variable) => variableState.aiValues[variable.key]).length;
    const summary = [variableSummary, aiCount > 0 ? `${aiCount} AI-filled` : ''].filter(Boolean).join('; ');

    return (
        <PromptCard
            className="max-h-[40vh] overflow-y-auto"
            name={name}
            scopeLabel={scopeLabel}
            edited={edited}
            summary={summary}
            content={resolve()}
            open={open}
            onToggle={() => setOpen((isOpen) => !isOpen)}
            actions={<>
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
                    disabled={disabled}
                    aria-label={`Remove ${name}`}
                    title="Remove prompt"
                    className="shrink-0 rounded-md p-1 text-text-3 hover:bg-surface-3 hover:text-text-1"
                >
                    <X size={13} />
                </button>
            </>}
            footer={variables.length > 0 ? (
                <div className="border-t border-edge px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <button type="button" onClick={() => setVariablesOpen((current) => !current)}
                            aria-expanded={variablesOpen}
                            className="inline-flex items-center gap-1 text-xs font-medium text-text-2">
                            <ChevronDown size={12} className={clsx(!variablesOpen && '-rotate-90')} />
                            Variables ({variables.length})
                        </button>
                        {knowledge && variables.some((variable) => !variable.builtIn) && (
                            <button type="button" onClick={() => void knowledge.fill()}
                                disabled={disabled || !knowledgeEnabled || knowledge.pendingKeys.length > 0
                                    || !unfilled.some((variable) => !variable.builtIn)}
                                className="inline-flex items-center gap-1 rounded px-1 py-1 text-xs text-accent hover:bg-accent-soft disabled:opacity-50">
                                <Sparkles size={12} /> Fill missing fields
                            </button>
                        )}
                    </div>
                    {variablesOpen && (
                        <div className="mt-2 max-h-64 space-y-3 overflow-y-auto">
                            {variables.some((variable) => !variable.builtIn) && knowledgeControls}
                            {knowledge?.notice && <p role="status" className="text-xs text-text-2">{knowledge.notice}</p>}
                            {knowledge?.error && <p role="alert" className="text-xs text-danger">{knowledge.error}</p>}
                            {knowledge && knowledge.pendingKeys.length > 0 && (
                                <button type="button" onClick={knowledge.cancel} className="text-xs text-accent">
                                    Cancel lookup
                                </button>
                            )}
                            <div className="grid gap-3 sm:grid-cols-2">
                                {variables.map((variable) => (
                                    <PromptVariableField
                                        key={variable.key}
                                        variable={variable}
                                        value={values[variable.key] ?? ''}
                                        builtInValue={builtIns[variable.key as BuiltInPromptVariable]}
                                        prefilled={prefilled.has(variable.key)}
                                        history={history[variable.key] ?? []}
                                        sources={sources}
                                        disabled={disabled}
                                        aiValue={variableState.aiValues[variable.key]}
                                        onUndo={() => {
                                            knowledge?.cancel();
                                            variableState.undoAiValue(variable.key);
                                        }}
                                        onFind={knowledge && knowledgeEnabled ? () => void knowledge.fill([variable.key]) : undefined}
                                        finding={knowledge?.pendingKeys.includes(variable.key)}
                                        unresolved={knowledge?.unresolved.find((item) => item.key === variable.key)}
                                        onChooseAlternative={(value) => knowledge?.chooseAlternative(variable.key, value)}
                                        onChange={(value) => {
                                            knowledge?.cancel();
                                            setValue(variable.key, value);
                                        }}
                                        idPrefix="attached-prompt-var"
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            ) : null}
        >
            {editing ? (
                <div>
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                        <label
                            htmlFor="attached-prompt-content"
                            className="text-[11px] font-semibold tracking-wide text-text-3 uppercase"
                        >
                            Prompt text
                        </label>
                        <span className="text-[11px] text-text-3">
                            Changes apply to this message only
                        </span>
                        <PromptVariablePicker
                            onOpen={insertion.rememberSelection}
                            onInsert={insertion.insert}
                            disabled={disabled}
                            builtIns={builtIns}
                        />
                        {edited ? (
                            <button
                                type="button"
                                onClick={onResetContent}
                                disabled={disabled}
                                className="ml-auto inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-text-1"
                            >
                                <RotateCcw size={10} />
                                Reset
                            </button>
                        ) : null}
                    </div>
                    <textarea
                        id="attached-prompt-content"
                        ref={contentRef}
                        rows={6}
                        value={content}
                        disabled={disabled}
                        onChange={(event) => onContentChange(event.target.value)}
                        className="w-full resize-y rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 font-mono text-xs text-text-1 focus:border-accent focus:outline-none"
                    />
                </div>
            ) : undefined}
        </PromptCard>
    );
}
