// PromptVariablesDialog.tsx
// Filling in a prompt's placeholders before it reaches the composer.
//
// Three rules shape this, and all three exist because a wrong pre-filled value is worse than an
// empty box: an empty box stops you, whereas a plausible wrong value gets sent.
//
//   1. Anything filled in for you is badged and clearable in one click, so it never reads as
//      something you typed.
//   2. Values pulled from the conversation are pulled one field at a time, by you. Nothing
//      reaches in and takes the last assistant reply on its own -- that reply can quote an
//      uploaded document, and text from a document becoming part of your next instruction is
//      how prompt injection gets a foothold.
//   3. In a shared conversation nothing is pre-filled at all. A value remembered from a private
//      chat would become visible to every participant the moment the message is sent, so it is
//      offered as a chip you have to click instead.
//
// Built-ins are resolved and shown read-only: `{{today}}` is not a question worth asking.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { CornerDownLeft, RotateCcw, Sparkles } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import {
    BUILT_IN_PROMPT_VARIABLE_LABELS,
    applyPromptVariables,
    describeUnfilledVariables,
    parsePromptVariables,
    resolveBuiltInPromptVariables,
    type BuiltInPromptVariable,
    type PromptResolutionContext,
} from '../../lib/promptVariables';
import { recallPromptValues, rememberPromptValues } from '../../lib/promptVariableMemory';

export interface PromptFillSource {
    label: string;
    value: string;
}

export function PromptVariablesDialog({
    promptId,
    promptName,
    content,
    context,
    /** Suppresses pre-filling from memory. True for a collaborative conversation. */
    shared = false,
    /** One-click values offered per field, e.g. the last assistant reply. */
    sources = [],
    onCancel,
    onSubmit,
}: {
    promptId: string;
    promptName: string;
    content: string;
    context: PromptResolutionContext;
    shared?: boolean;
    sources?: PromptFillSource[];
    onCancel: () => void;
    onSubmit: (text: string) => void;
}) {
    const variables = useMemo(() => parsePromptVariables(content), [content]);

    const builtIns = useMemo(
        () => resolveBuiltInPromptVariables(context),
        // The context object is rebuilt by the caller on each render; resolving from a snapshot
        // taken when the dialog opened is also what makes `{{now}}` stable while it is open.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [],
    );

    const remembered = useMemo(() => recallPromptValues(promptId), [promptId]);

    // Which keys were filled in for you, so they can be badged. Recomputed only on mount: once
    // a field is edited it stops being pre-filled, which `edited` below records.
    const [prefilled] = useState<Set<string>>(() => {
        const keys = new Set<string>();
        for (const variable of variables) {
            if (variable.builtIn && builtIns[variable.key as BuiltInPromptVariable]) {
                keys.add(variable.key);
                continue;
            }
            if (!shared && (remembered[variable.key]?.length ?? 0) > 0) {
                keys.add(variable.key);
            }
        }
        return keys;
    });

    const [values, setValues] = useState<Record<string, string>>(() => {
        const initial: Record<string, string> = {};
        for (const variable of variables) {
            const builtIn = builtIns[variable.key as BuiltInPromptVariable];
            if (variable.builtIn && builtIn) {
                initial[variable.key] = builtIn;
                continue;
            }
            if (!shared) {
                const previous = remembered[variable.key]?.[0];
                if (previous) {
                    initial[variable.key] = previous;
                    continue;
                }
            }
            initial[variable.key] = variable.defaultValue;
        }
        return initial;
    });

    const [edited, setEdited] = useState<Set<string>>(() => new Set());

    const setValue = (key: string, value: string) => {
        setValues((current) => ({ ...current, [key]: value }));
        setEdited((current) => new Set(current).add(key));
    };

    const preview = useMemo(() => applyPromptVariables(content, values), [content, values]);
    const unfilled = describeUnfilledVariables(variables, values);

    useEffect(() => {
        // Nothing to ask: the caller should not have opened this. Closing straight through
        // rather than showing an empty dialog keeps the failure recoverable.
        if (variables.length === 0) {
            onSubmit(content);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const submit = () => {
        // Only what you actually supplied is remembered. Resolved built-ins are not values you
        // chose, and storing them would offer today's date back to you tomorrow.
        const toRemember: Record<string, string> = {};
        for (const variable of variables) {
            if (variable.builtIn) {
                continue;
            }
            const value = values[variable.key];
            if (value) {
                toRemember[variable.key] = value;
            }
        }
        rememberPromptValues(promptId, toRemember);
        onSubmit(preview);
    };

    return (
        <Modal
            title={`Use "${promptName}"`}
            description={
                shared
                    ? 'Values are not filled in automatically in a shared conversation.'
                    : 'Values you enter are remembered in this browser, and never sent to the server.'
            }
            onClose={onCancel}
            size="lg"
            footer={
                <>
                    <span className="mr-auto text-xs text-text-3">
                        {unfilled.length === 0
                            ? 'Ready to insert'
                            : `${unfilled.length} still to fill in`}
                    </span>
                    <GlassButton size="sm" onClick={onCancel}>
                        Cancel
                    </GlassButton>
                    <GlassButton variant="primary" size="sm" onClick={submit}>
                        <CornerDownLeft size={14} />
                        Insert
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-3">
                {variables.map((variable) => {
                    const builtInValue = builtIns[variable.key as BuiltInPromptVariable];
                    const isResolvedBuiltIn = variable.builtIn && Boolean(builtInValue);
                    const wasPrefilled = prefilled.has(variable.key) && !edited.has(variable.key);
                    const history = (remembered[variable.key] ?? []).filter(
                        (item) => item !== values[variable.key],
                    );

                    return (
                        <div key={variable.key}>
                            <div className="mb-1 flex items-center gap-2">
                                <label
                                    htmlFor={`prompt-var-${variable.key}`}
                                    className="font-mono text-xs font-medium text-text-2"
                                >
                                    {`{{${variable.name}}}`}
                                </label>
                                {wasPrefilled ? (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] leading-none font-medium text-accent">
                                        <Sparkles size={9} />
                                        {isResolvedBuiltIn ? 'From this chat' : 'Reused'}
                                    </span>
                                ) : null}
                                {!isResolvedBuiltIn && values[variable.key] ? (
                                    <button
                                        type="button"
                                        onClick={() => setValue(variable.key, '')}
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
                                        {
                                            BUILT_IN_PROMPT_VARIABLE_LABELS[
                                                variable.key as BuiltInPromptVariable
                                            ]
                                        }
                                    </span>
                                </p>
                            ) : (
                                <textarea
                                    id={`prompt-var-${variable.key}`}
                                    rows={2}
                                    value={values[variable.key] ?? ''}
                                    onChange={(event) =>
                                        setValue(variable.key, event.target.value)
                                    }
                                    placeholder={variable.defaultValue || `Value for ${variable.name}`}
                                    className={clsx(
                                        'w-full resize-y rounded-lg border bg-surface-1 px-2.5 py-1.5 text-sm text-text-1',
                                        'placeholder:text-text-3 focus:border-accent focus:outline-none',
                                        wasPrefilled ? 'border-accent/50' : 'border-edge',
                                    )}
                                />
                            )}

                            {!isResolvedBuiltIn && (history.length > 0 || sources.length > 0) ? (
                                <div className="mt-1 flex flex-wrap items-center gap-1">
                                    {history.slice(0, 4).map((item) => (
                                        <button
                                            key={item}
                                            type="button"
                                            title={item}
                                            onClick={() => setValue(variable.key, item)}
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
                                            onClick={() => setValue(variable.key, source.value)}
                                            className="rounded-full border border-dashed border-edge px-2 py-0.5 text-[11px] text-text-3 transition-colors hover:border-accent hover:text-text-1"
                                        >
                                            {source.label}
                                        </button>
                                    ))}
                                </div>
                            ) : null}
                        </div>
                    );
                })}

                <div>
                    <h4 className="mb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                        Preview
                    </h4>
                    <pre className="max-h-48 overflow-y-auto rounded-lg border border-edge bg-surface-sunken px-2.5 py-2 text-xs whitespace-pre-wrap text-text-2">
                        {preview}
                    </pre>
                </div>
            </div>
        </Modal>
    );
}
