// PromptVariablePicker.tsx

import { useEffect, useId, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Braces, X } from 'lucide-react';
import {
    BUILT_IN_PROMPT_VARIABLES,
    BUILT_IN_PROMPT_VARIABLE_LABELS,
    parsePromptVariables,
    type BuiltInPromptVariable,
} from '../../lib/promptVariables';

export function usePromptVariableInsertion(
    fieldRef: RefObject<HTMLTextAreaElement>,
    value: string,
    onChange: (value: string) => void,
) {
    const selection = useRef({ start: 0, end: 0 });
    const rememberSelection = () => {
        const field = fieldRef.current;
        selection.current = {
            start: field?.selectionStart ?? value.length,
            end: field?.selectionEnd ?? value.length,
        };
    };
    const insert = (token: string) => {
        const { start, end } = selection.current;
        onChange(`${value.slice(0, start)}${token}${value.slice(end)}`);
        window.requestAnimationFrame(() => {
            fieldRef.current?.focus();
            fieldRef.current?.setSelectionRange(start + token.length, start + token.length);
        });
    };
    return { rememberSelection, insert };
}

export function PromptVariablePicker({
    onInsert,
    onOpen,
    disabled = false,
    builtIns,
}: {
    onInsert: (token: string) => void;
    onOpen: () => void;
    disabled?: boolean;
    builtIns?: Partial<Record<BuiltInPromptVariable, string>>;
}) {
    const [open, setOpen] = useState(false);
    const [name, setName] = useState('');
    const [defaultValue, setDefaultValue] = useState('');
    const [position, setPosition] = useState({ top: 0, left: 0, maxHeight: 420 });
    const trigger = useRef<HTMLButtonElement>(null);
    const panel = useRef<HTMLDivElement>(null);
    const nameField = useRef<HTMLInputElement>(null);
    const id = useId();
    const token = `{{${name.trim()}${defaultValue.trim() ? `|${defaultValue.trim()}` : ''}}}`;
    const parsed = parsePromptVariables(token);
    const valid = parsed.length === 1 && !parsed[0].builtIn
        && parsed[0].name === name.trim() && parsed[0].defaultValue === defaultValue.trim()
        && token === `{{${parsed[0].name}${parsed[0].defaultValue ? `|${parsed[0].defaultValue}` : ''}}}`;

    useEffect(() => {
        if (!open) {
            return;
        }
        const measure = () => {
            const rect = trigger.current?.getBoundingClientRect();
            if (!rect) {
                return;
            }
            const below = window.innerHeight - rect.bottom - 16;
            const above = rect.top - 16;
            const height = Math.min(420, Math.max(below, above));
            setPosition({
                top: below >= above ? rect.bottom + 8 : Math.max(8, rect.top - height - 8),
                left: Math.max(8, Math.min(rect.left, window.innerWidth - 336)),
                maxHeight: Math.max(120, height),
            });
        };
        const closeOutside = (event: PointerEvent) => {
            const target = event.target;
            if (target instanceof Node && !panel.current?.contains(target)
                && !trigger.current?.contains(target)) {
                setOpen(false);
            }
        };
        measure();
        nameField.current?.focus();
        document.addEventListener('pointerdown', closeOutside);
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        return () => {
            document.removeEventListener('pointerdown', closeOutside);
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [open]);

    const close = () => {
        setOpen(false);
        trigger.current?.focus();
    };
    const insert = (value: string) => {
        setOpen(false);
        setName('');
        setDefaultValue('');
        onInsert(value);
    };

    return (
        <>
            <button
                ref={trigger}
                type="button"
                disabled={disabled}
                aria-expanded={open}
                aria-haspopup="dialog"
                aria-controls={open ? id : undefined}
                onClick={() => {
                    onOpen();
                    setOpen((current) => !current);
                }}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-accent hover:bg-accent-soft disabled:opacity-50"
            >
                <Braces size={13} />
                Insert variable
            </button>
            {open && createPortal(
                <div
                    ref={panel}
                    id={id}
                    role="dialog"
                    aria-label="Insert a prompt variable"
                    style={position}
                    className="glass-modal fixed z-[60] w-80 max-w-[calc(100vw-1rem)] overflow-y-auto rounded-xl border border-edge p-3 shadow-xl"
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => {
                        if (event.key === 'Escape') {
                            event.preventDefault();
                            event.stopPropagation();
                            close();
                        }
                    }}
                >
                    <div className="mb-2 flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-text-1">Insert variable</h3>
                        <button type="button" aria-label="Close variable picker" onClick={close}
                            className="rounded p-1 text-text-3 hover:bg-surface-2">
                            <X size={14} />
                        </button>
                    </div>
                    <p className="mb-3 text-xs text-text-3">
                        Custom fields are filled when you use the prompt. Built-ins use your chat context.
                    </p>
                    <label className="mb-2 block text-xs text-text-2">
                        Variable name
                        <input
                            ref={nameField}
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            placeholder="customer name"
                            maxLength={40}
                            className="mt-1 w-full rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-text-1"
                        />
                    </label>
                    <label className="block text-xs text-text-2">
                        Default value (optional)
                        <input
                            value={defaultValue}
                            onChange={(event) => setDefaultValue(event.target.value)}
                            placeholder="Used when no value is entered"
                            className="mt-1 w-full rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-text-1"
                        />
                    </label>
                    {name.trim() && !valid && (
                        <p className="mt-1 text-xs text-warn">
                            Use a custom name with letters, numbers, spaces, underscores or hyphens.
                            Defaults cannot contain braces. Choose built-ins below.
                        </p>
                    )}
                    <button
                        type="button"
                        disabled={!valid || disabled}
                        onClick={() => insert(token)}
                        className="my-3 w-full rounded-lg bg-accent px-2 py-1.5 text-xs font-medium text-on-accent disabled:opacity-50"
                    >
                        Add custom variable
                    </button>
                    <h4 className="mb-1 text-xs font-semibold text-text-2">Built-in variables</h4>
                    {BUILT_IN_PROMPT_VARIABLES.map((key) => (
                        <button
                            key={key}
                            type="button"
                            disabled={disabled}
                            onClick={() => insert(`{{${key}}}`)}
                            className="block w-full rounded-lg px-2 py-2 text-left hover:bg-surface-2 disabled:opacity-50"
                        >
                            <span className="block text-xs font-medium text-text-1">
                                {BUILT_IN_PROMPT_VARIABLE_LABELS[key]}
                            </span>
                            <code className="text-[11px] text-accent">{`{{${key}}}`}</code>
                            <span className="block truncate text-[11px] text-text-3">
                                {builtIns
                                    ? builtIns[key] || 'Not available in this chat yet'
                                    : 'Filled from context when used in chat'}
                            </span>
                        </button>
                    ))}
                </div>,
                document.body,
            )}
        </>
    );
}
