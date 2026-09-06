// ActionFields.tsx

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { GlassButton } from '../ui/primitives';
import { EDITOR_SECRET_MASK, isRecord } from '../../lib/workspaceAuthoring';

export const ACTION_INPUT_CLASS =
    'w-full min-w-0 rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:opacity-60';

export function ActionField({
    id, label, help, error, children, required,
}: {
    id: string;
    label: string;
    help?: string;
    error?: string;
    children: ReactNode;
    required?: boolean;
}) {
    return (
        <div className="min-w-0 space-y-1.5">
            <label htmlFor={id} className="block text-sm font-medium text-text-1">
                {label}{required ? <span aria-hidden="true" className="ml-1 text-danger">*</span> : null}
            </label>
            {children}
            {help ? <p id={`${id}-help`} className="break-words text-xs leading-relaxed text-text-3">{help}</p> : null}
            {error ? <p id={`${id}-error`} role="alert" className="break-words text-sm text-danger">{error}</p> : null}
        </div>
    );
}

export function ActionSecretInput({
    id, label, value, storedValue, onChange, disabled, help, error, multiline = false,
}: {
    id: string;
    label: string;
    value: unknown;
    storedValue?: unknown;
    onChange: (value: string) => void;
    disabled?: boolean;
    help?: string;
    error?: string;
    multiline?: boolean;
}) {
    const configured = value === EDITOR_SECRET_MASK;
    const hadSecret = storedValue === EDITOR_SECRET_MASK;
    return (
        <ActionField id={id} label={label} error={error} help={help}>
            {multiline ? <textarea id={id} rows={7} autoComplete="off" spellCheck={false}
                value={configured ? '' : typeof value === 'string' ? value : ''}
                placeholder={configured ? 'Stored securely — paste a replacement' : 'Paste the complete value, including line breaks'}
                disabled={disabled} className={`${ACTION_INPUT_CLASS} font-mono text-xs`}
                aria-invalid={Boolean(error)} aria-describedby={`${id}-help ${id}-secret-status`}
                onChange={(event) => onChange(event.target.value)} /> : <input id={id} type="password" autoComplete="new-password"
                value={configured ? '' : typeof value === 'string' ? value : ''}
                placeholder={configured ? 'Stored securely — enter a replacement' : 'Enter a secret'}
                disabled={disabled} className={ACTION_INPUT_CLASS}
                aria-invalid={Boolean(error)} aria-describedby={`${id}-help ${id}-secret-status`}
                onChange={(event) => onChange(event.target.value)} />}
            <div className="flex flex-wrap items-center gap-2">
                <p id={`${id}-secret-status`} className="text-xs text-text-3">
                    {configured ? 'Configured. The existing secret will be kept.' :
                        hadSecret && !value ? 'The stored secret will be cleared when you save.' :
                            value ? 'Replacement stays in this tab until saved.' : 'Not configured.'}
                </p>
                {!disabled && (configured || Boolean(value)) ? (
                    <GlassButton size="sm" type="button" onClick={() => onChange('')}>Clear {label.toLowerCase()}</GlassButton>
                ) : null}
                {!disabled && hadSecret && !configured ? (
                    <GlassButton size="sm" type="button" onClick={() => onChange(EDITOR_SECRET_MASK)}>Keep stored {label.toLowerCase()}</GlassButton>
                ) : null}
            </div>
        </ActionField>
    );
}

export function ActionJsonInput({
    id, label, value, onChange, onValidityChange, readOnly, help, error, rows = 8, objectOnly = true, protectArraySecrets = false,
}: {
    id: string;
    label: string;
    value: unknown;
    onChange: (value: unknown) => void;
    onValidityChange?: (key: string, message: string | null) => void;
    readOnly?: boolean;
    help?: string;
    error?: string;
    rows?: number;
    objectOnly?: boolean;
    protectArraySecrets?: boolean;
}) {
    const serialized = JSON.stringify(value ?? (objectOnly ? {} : []), null, 2);
    const lastApplied = useRef(serialized);
    const validityCallback = useRef(onValidityChange);
    validityCallback.current = onValidityChange;
    const [text, setText] = useState(serialized);
    const [parseError, setParseError] = useState<string | null>(null);
    const validityKey = `json:${id}`;
    useEffect(() => {
        if (serialized !== lastApplied.current) {
            lastApplied.current = serialized;
            setText(serialized);
            setParseError(null);
            validityCallback.current?.(validityKey, null);
        }
    }, [serialized, validityKey]);
    useEffect(() => () => validityCallback.current?.(validityKey, null), [validityKey]);

    const change = (next: string) => {
        setText(next);
        try {
            const parsed: unknown = JSON.parse(next);
            if (objectOnly && !isRecord(parsed)) throw new Error('Enter a JSON object, not an array or scalar.');
            lastApplied.current = JSON.stringify(parsed, null, 2);
            onChange(parsed);
            setParseError(null);
            onValidityChange?.(validityKey, null);
        } catch (cause) {
            const message = cause instanceof Error ? cause.message : 'Invalid JSON.';
            setParseError(message);
            onValidityChange?.(validityKey, `${label}: ${message}`);
        }

    };
    return (
        <ActionField id={id} label={label} error={parseError || error}
            help={[help, protectArraySecrets
                ? 'Stored array credentials are tied to their saved positions, not entry names or IDs. Use structured fields, or replace/clear those credentials before editing this JSON.'
                : ''].filter(Boolean).join(' ')}>
            <textarea id={id} rows={rows} value={text} spellCheck={false} readOnly={readOnly || protectArraySecrets}
                className={`${ACTION_INPUT_CLASS} font-mono text-xs`}
                aria-invalid={Boolean(parseError || error)} aria-describedby={`${id}-help ${id}-error`}
                onChange={(event) => change(event.target.value)} />
        </ActionField>
    );
}

export function ActionLinesInput({
    id, label, value, onChange, disabled, help, error,
}: {
    id: string;
    label: string;
    value: unknown;
    onChange: (value: string[]) => void;
    disabled?: boolean;
    help?: string;
    error?: string;
}) {
    const serialized = Array.isArray(value) ? value.map(String).join('\n') : typeof value === 'string' ? value : '';
    const [text, setText] = useState(serialized);
    const lastApplied = useRef(serialized);
    useEffect(() => {
        if (lastApplied.current !== serialized) {
            lastApplied.current = serialized;
            setText(serialized);
        }
    }, [serialized]);
    return (
        <ActionField id={id} label={label} help={help} error={error}>
            <textarea id={id} rows={4} className={ACTION_INPUT_CLASS} value={text} disabled={disabled}
                aria-invalid={Boolean(error)} aria-describedby={`${id}-help ${id}-error`}
                onChange={(event) => {
                    const next = event.target.value;
                    const values = next.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
                    setText(next);
                    lastApplied.current = values.join('\n');
                    onChange(values);
                }} />
        </ActionField>
    );
}
