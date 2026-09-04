// usePromptVariableValues.ts
// The values behind a prompt's placeholders, while that prompt is attached to a turn.
//
// Extracted from PromptVariablesDialog, which filled a prompt once and flattened it to text.
// A prompt that stays attached until send has a longer life than a modal does, and one thing
// changes because of it: built-ins are **not** frozen into the values map.
//
// That matters most for `{{composer}}`, "what you have already typed". Resolved when the
// prompt was picked it is almost always empty, because picking the prompt is the first thing
// you do. Resolved at send it is the message you wrote underneath it, which is the whole point
// of letting the prompt sit above the box while you type.
//
// So `values` holds only what a person supplied, and `resolve()` merges freshly resolved
// built-ins underneath them at the moment it is called. `setValue` refuses built-in keys for
// the same reason the field renders them read-only: `{{today}}` is not a question worth asking,
// and a stale answer to it would shadow the real one.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
    applyPromptVariables,
    isBuiltInPromptVariable,
    parsePromptVariables,
    resolveBuiltInPromptVariables,
    type BuiltInPromptVariable,
    type PromptResolutionContext,
    type PromptVariable,
} from './promptVariables';
import { recallPromptValues, rememberPromptValues } from './promptVariableMemory';

export interface PromptVariableValues {
    /** The placeholders this content declares, in the order they first appear. */
    variables: PromptVariable[];
    /** What the reader supplied, keyed by normalised variable name. Never holds a built-in. */
    values: Record<string, string>;
    /** Built-ins resolved from the context passed in, for display. */
    builtIns: Partial<Record<BuiltInPromptVariable, string>>;
    /** Keys whose value arrived on its own, so the field can say so. */
    prefilled: Set<string>;
    /** Placeholders with nothing behind them and no inline default. */
    unfilled: PromptVariable[];
    /** Previously used values per key, offered as chips. Empty in a shared conversation. */
    history: Record<string, string[]>;
    setValue: (key: string, value: string) => void;
    /**
     * The prompt with its placeholders substituted.
     *
     * Pass the live context at send so the conversation built-ins reflect the message as it is
     * actually being sent rather than as it looked when the prompt was picked.
     */
    resolve: (context?: PromptResolutionContext) => string;
    /** Remember what the reader supplied. Called on send, not on every keystroke. */
    commit: () => void;
}

/** A stable identity for a context object the caller rebuilds on every render. */
function contextKey(context: PromptResolutionContext): string {
    return [
        context.userName ?? '',
        context.conversationTitle ?? '',
        (context.selectedDocuments ?? []).join('\u0000'),
        context.lastAssistantMessage ?? '',
        context.lastUserMessage ?? '',
        context.composerText ?? '',
    ].join('\u0001');
}

export function usePromptVariableValues({
    promptId,
    content,
    context,
    /** Suppresses pre-filling from memory. True for a collaborative conversation. */
    shared = false,
}: {
    promptId: string;
    content: string;
    context: PromptResolutionContext;
    shared?: boolean;
}): PromptVariableValues {
    const variables = useMemo(() => parsePromptVariables(content), [content]);

    // Recomputed only when something behind a built-in actually changed. The caller rebuilds
    // `context` every render, so depending on the object itself would resolve `{{now}}` afresh
    // on every keystroke and make the preview flicker.
    const key = contextKey(context);
    const builtIns = useMemo(
        () => resolveBuiltInPromptVariables(context),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [key],
    );

    // Nothing is offered back in a shared conversation: a value remembered from a private chat
    // would become visible to every participant the moment the message is sent.
    const history = useMemo(
        () => (shared ? {} : recallPromptValues(promptId)),
        [promptId, shared],
    );

    const [values, setValues] = useState<Record<string, string>>({});
    const [prefilled, setPrefilled] = useState<Set<string>>(() => new Set());

    // Seeding runs once per variable, not once per render, and again only for a placeholder
    // that editing the wording has newly introduced. Tracked by key rather than inferred from
    // the values map, because a field the reader cleared is still a field that has been seeded:
    // re-seeding it would put the remembered value back and re-badge it as auto-filled after
    // they had deliberately emptied it.
    const seededFor = useRef<string | null>(null);
    const seeded = useRef<Set<string>>(new Set());
    useEffect(() => {
        const restart = seededFor.current !== promptId;
        seededFor.current = promptId;
        if (restart) {
            seeded.current = new Set();
        }

        const fresh = variables.filter((variable) => !seeded.current.has(variable.key));
        if (fresh.length === 0 && !restart) {
            return;
        }
        for (const variable of fresh) {
            seeded.current.add(variable.key);
        }

        setValues((current) => {
            const next = restart ? {} : { ...current };
            for (const variable of fresh) {
                if (variable.builtIn) {
                    continue;
                }
                next[variable.key] = history[variable.key]?.[0] ?? variable.defaultValue;
            }
            return next;
        });

        setPrefilled((current) => {
            const next = restart ? new Set<string>() : new Set(current);
            for (const variable of fresh) {
                if (variable.builtIn) {
                    if (builtIns[variable.key as BuiltInPromptVariable]) {
                        next.add(variable.key);
                    }
                    continue;
                }
                if ((history[variable.key]?.length ?? 0) > 0) {
                    next.add(variable.key);
                }
            }
            return next;
        });
        // `builtIns` is deliberately absent: a built-in resolving later must not re-badge a
        // field the reader has since edited.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [promptId, variables, history]);

    const setValue = (variableKey: string, value: string) => {
        if (isBuiltInPromptVariable(variableKey)) {
            return;
        }
        setValues((current) => ({ ...current, [variableKey]: value }));
        // Edited, so it is no longer something that was filled in for you.
        setPrefilled((current) => {
            if (!current.has(variableKey)) {
                return current;
            }
            const next = new Set(current);
            next.delete(variableKey);
            return next;
        });
    };

    const resolve = (override?: PromptResolutionContext) =>
        applyPromptVariables(content, {
            ...resolveBuiltInPromptVariables(override ?? context),
            ...values,
        });

    const unfilled = variables.filter((variable) => {
        if (variable.builtIn) {
            return !builtIns[variable.key as BuiltInPromptVariable];
        }
        return !String(values[variable.key] ?? '').trim() && !variable.defaultValue;
    });

    const commit = () => {
        // Only what the reader actually supplied is remembered. Resolved built-ins are not
        // values they chose, and storing them would offer today's date back to them tomorrow.
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
    };

    return { variables, values, builtIns, prefilled, unfilled, history, setValue, resolve, commit };
}
