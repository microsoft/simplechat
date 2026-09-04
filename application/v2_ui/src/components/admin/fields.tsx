// fields.tsx
// Generic controls that render one server-declared Admin Settings field.
//
// Every control here is driven entirely by the field definition, so describing a new
// setting in `admin_settings_fields.py` is enough to make it appear and save. Nothing in
// this file knows about a specific setting.
//
// Two conventions worth stating: edits are reported upward and buffered by the page rather
// than saved per keystroke, and a field's own validation error is rendered beneath it so a
// rejected save points at the control that caused it.

import { clsx } from 'clsx';
import { AlertCircle, Check, Info, KeyRound, RotateCcw, TriangleAlert } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import {
    asBoolean,
    asNumber,
    asString,
    asStringArray,
    countWords,
    SECRET_PLACEHOLDER,
    type AdminField,
} from '../../lib/adminFields';
import { Toggle } from '../ui/primitives';

const inputClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

/** Label, help text, control and error, laid out consistently for every field type. */
export function FieldShell({
    field,
    error,
    warning,
    htmlFor,
    children,
    trailing,
}: {
    field: AdminField;
    error?: string;
    warning?: string;
    htmlFor?: string;
    children: ReactNode;
    trailing?: ReactNode;
}) {
    return (
        <div className="py-3">
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <label
                    htmlFor={htmlFor}
                    className="text-sm font-medium text-text-1"
                >
                    {field.label}
                </label>
                {trailing}
            </div>

            {children}

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {warning ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {warning}
                </p>
            ) : null}

            {error ? (
                <p
                    role="alert"
                    className="mt-1.5 flex items-start gap-1.5 text-xs text-danger"
                >
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}

export interface FieldControlProps {
    field: AdminField;
    value: unknown;
    error?: string;
    warning?: string;
    disabled?: boolean;
    onChange: (next: unknown) => void;
}

function TextControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <input
                id={id}
                type={field.input_type ?? 'text'}
                className={inputClass}
                value={asString(value)}
                maxLength={field.max_length}
                placeholder={field.placeholder}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            />
        </FieldShell>
    );
}

/**
 * A write-only credential.
 *
 * The server sends a placeholder rather than the stored value, so there is nothing to
 * reveal and no toggle to reveal it. What an administrator actually needs to know is
 * whether a secret is stored at all, and to be able to replace it without being able to
 * clear it by accident — hence the explicit Replace step rather than an editable input
 * pre-filled with something that is not the real value.
 */
function SecretControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    const current = asString(value);
    const isStored = current === SECRET_PLACEHOLDER;

    // Replace only switches this control into entry mode; it deliberately stages
    // nothing. Staging an empty value there would queue a deletion of a working
    // credential from a click that means "let me type a new one" -- and this control can
    // unmount before anything is typed, because moving between groups, searching, or
    // flipping a switch this field depends on all drop it. The escape hatch would go
    // with it and the queued deletion would not.
    const [replacing, setReplacing] = useState(false);
    const [emitted, setEmitted] = useState(current);

    if (current !== emitted) {
        // Changed for a reason other than typing here: a save that restored the
        // placeholder, or a discarded draft. Either way this edit is over.
        setEmitted(current);
        setReplacing(false);
    }

    const commit = (next: string) => {
        setEmitted(next);
        onChange(next);
    };

    if (isStored && !replacing) {
        return (
            <FieldShell field={field} error={error} warning={warning}>
                <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-2">
                        <Check size={14} className="text-ok" />
                        Stored
                    </span>
                    <button
                        type="button"
                        disabled={disabled}
                        onClick={() => setReplacing(true)}
                        className={clsx(
                            'inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-2',
                            'text-sm text-text-2 transition-colors',
                            disabled
                                ? 'cursor-not-allowed opacity-60'
                                : 'hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        <RotateCcw size={14} />
                        Replace
                    </button>
                </div>
                <p className="mt-1.5 text-xs text-text-3">
                    The stored value is never sent to the browser, so it cannot be shown
                    here. Replacing it overwrites it.
                </p>
            </FieldShell>
        );
    }

    return (
        <FieldShell
            field={field}
            error={error}
            warning={warning}
            htmlFor={id}
            trailing={
                replacing ? (
                    <button
                        type="button"
                        className="text-xs text-text-3 transition-colors hover:text-text-1"
                        onClick={() => setReplacing(false)}
                    >
                        Cancel
                    </button>
                ) : null
            }
        >
            <div className="flex items-center gap-2">
                <KeyRound size={15} className="shrink-0 text-text-3" />
                <input
                    id={id}
                    type="password"
                    autoComplete="new-password"
                    spellCheck={false}
                    className={inputClass}
                    // While replacing, the placeholder is the untouched stored value, and
                    // showing it in the box would invite someone to edit a string that is
                    // not their secret.
                    value={isStored ? '' : current}
                    placeholder={field.placeholder ?? 'Paste the new value'}
                    disabled={disabled}
                    onChange={(event) => commit(event.target.value)}
                />
            </div>
            {replacing ? (
                <p className="mt-1.5 text-xs text-text-3">
                    Left blank, the stored value is kept. Type a value to replace it, or
                    clear a typed value to remove the secret entirely.
                </p>
            ) : null}
        </FieldShell>
    );
}

/**
 * Standing prose declared by the schema rather than hard-coded in this file.
 *
 * Some settings carry a consequence that no label can hold — enabling Key Vault is
 * effectively one-way — and that warning has to sit next to the control, visible, rather
 * than behind a tooltip.
 */
function NoteControl({ field }: FieldControlProps) {
    const isWarning = field.tone === 'warning';
    const Icon = isWarning ? TriangleAlert : Info;

    return (
        <div className="py-3">
            <div
                className={clsx(
                    'flex items-start gap-2.5 rounded-lg border p-3',
                    isWarning
                        ? 'border-warn/30 bg-warn-soft'
                        : 'border-edge bg-surface-1',
                )}
            >
                <Icon
                    size={15}
                    className={clsx('mt-0.5 shrink-0', isWarning ? 'text-warn' : 'text-text-3')}
                />
                <div className="min-w-0">
                    <p className="text-sm font-medium text-text-1">{field.label}</p>
                    {field.body ? (
                        <p className="mt-1 text-xs leading-relaxed text-text-2">{field.body}</p>
                    ) : null}
                </div>
            </div>
        </div>
    );
}

/**
 * A short list of tokens, edited as comma-separated text.
 *
 * Stored as an array, so the control parses on the way out and joins on the way in. The
 * chips below the input show what will actually be saved, which is the only way to see
 * that stray whitespace and duplicates were folded away.
 */
function StringListControl({
    field,
    value,
    error,
    warning,
    disabled,
    onChange,
}: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    const items = asStringArray(value);
    const incoming = items.join('\u0000');

    const [text, setText] = useState(() => items.join(', '));
    const [emitted, setEmitted] = useState(incoming);

    if (incoming !== emitted) {
        // The value changed for a reason other than typing here — a discarded draft, or
        // a save that normalized the list. The text has to follow, or it keeps showing
        // an edit that no longer exists anywhere.
        setEmitted(incoming);
        setText(items.join(', '));
    }

    const commit = (next: string) => {
        setText(next);
        const parsed: string[] = [];
        for (const part of next.split(/[,;]/)) {
            const item = part.trim().replace(/\s+/g, ' ').slice(0, field.max_item_length ?? 80);
            if (item && !parsed.includes(item)) {
                parsed.push(item);
            }
        }
        setEmitted(parsed.join('\u0000'));
        onChange(parsed);
    };

    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <input
                id={id}
                type="text"
                className={inputClass}
                value={text}
                placeholder={field.placeholder}
                disabled={disabled}
                onChange={(event) => commit(event.target.value)}
            />
            {items.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                    {items.map((item) => (
                        <span
                            key={item}
                            className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-xs text-text-2"
                        >
                            {item}
                        </span>
                    ))}
                </div>
            ) : null}
        </FieldShell>
    );
}

function TextAreaControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    const text = asString(value);
    const words = field.word_limit ? countWords(text) : 0;
    const overLimit = Boolean(field.word_limit && words > field.word_limit);

    return (
        <FieldShell
            field={field}
            error={error}
            warning={warning}
            htmlFor={id}
            trailing={
                field.word_limit ? (
                    <span
                        className={clsx(
                            'text-xs tabular-nums',
                            overLimit ? 'text-warn' : 'text-text-3',
                        )}
                    >
                        {words} / {field.word_limit} words
                    </span>
                ) : field.max_length ? (
                    <span className="text-xs tabular-nums text-text-3">
                        {text.length} / {field.max_length}
                    </span>
                ) : null
            }
        >
            <textarea
                id={id}
                className={clsx(inputClass, 'resize-y font-mono text-xs leading-relaxed')}
                rows={field.rows ?? 4}
                value={text}
                maxLength={field.max_length}
                placeholder={field.placeholder}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            />
        </FieldShell>
    );
}

function SelectControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <select
                id={id}
                className={clsx(inputClass, 'appearance-none pr-8')}
                value={asString(value, asString(field.default))}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            >
                {(field.options ?? []).map((option) => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))}
            </select>
        </FieldShell>
    );
}

function SwitchControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    return (
        <div className="py-1">
            <Toggle
                label={field.label}
                description={field.help}
                checked={asBoolean(value)}
                disabled={disabled}
                onChange={(next) => onChange(next)}
            />
            {warning ? (
                <p className="mt-1 ml-14 text-xs text-warn">{warning}</p>
            ) : null}
            {error ? (
                <p role="alert" className="mt-1 ml-14 text-xs text-danger">
                    {error}
                </p>
            ) : null}
        </div>
    );
}

function ColorControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    const current = asString(value, asString(field.default, '#000000'));

    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <div className="flex items-center gap-2">
                <input
                    id={id}
                    type="color"
                    className="h-9 w-14 shrink-0 cursor-pointer rounded-lg border border-edge bg-surface-1 p-1 disabled:cursor-not-allowed"
                    value={/^#[0-9a-fA-F]{6}$/.test(current) ? current : '#000000'}
                    disabled={disabled}
                    onChange={(event) => onChange(event.target.value)}
                />
                {/* The hex is editable too: picking a brand colour by eye is harder than
                    pasting the value from a brand guide. */}
                <input
                    type="text"
                    aria-label={`${field.label} hex value`}
                    className={clsx(inputClass, 'font-mono')}
                    value={current}
                    disabled={disabled}
                    spellCheck={false}
                    onChange={(event) => onChange(event.target.value)}
                />
            </div>
        </FieldShell>
    );
}

function RangeControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const current = asNumber(value, asNumber(field.default, min));

    return (
        <FieldShell
            field={field}
            error={error}
            warning={warning}
            htmlFor={id}
            trailing={
                <span className="text-xs font-semibold tabular-nums text-text-2">
                    {current}
                    {field.suffix ?? ''}
                </span>
            }
        >
            <input
                id={id}
                type="range"
                className="w-full accent-[var(--accent)] disabled:cursor-not-allowed"
                min={min}
                max={max}
                step={field.step ?? 1}
                value={current}
                disabled={disabled}
                onChange={(event) => onChange(Number(event.target.value))}
            />
            <div className="flex justify-between text-xs text-text-3">
                <span>
                    {min}
                    {field.suffix ?? ''}
                </span>
                <span>
                    {max}
                    {field.suffix ?? ''}
                </span>
            </div>
        </FieldShell>
    );
}

function NumberControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <input
                id={id}
                type="number"
                className={inputClass}
                min={field.min}
                max={field.max}
                step={field.step ?? 1}
                value={asNumber(value, asNumber(field.default, 0))}
                disabled={disabled}
                onChange={(event) => onChange(Number(event.target.value))}
            />
        </FieldShell>
    );
}

function CheckboxSetControl({
    field,
    value,
    error,
    warning,
    disabled,
    onChange,
}: FieldControlProps) {
    const selected = asStringArray(value);
    const options = field.options ?? [];

    const toggle = (optionValue: string, checked: boolean) => {
        const next = checked
            ? [...selected, optionValue]
            : selected.filter((item) => item !== optionValue);
        // Keep the declared order so the saved array does not depend on click order.
        onChange(options.map((option) => option.value).filter((item) => next.includes(item)));
    };

    return (
        <FieldShell field={field} error={error} warning={warning}>
            <div className="grid gap-1.5 sm:grid-cols-2">
                {options.map((option) => {
                    const id = `admin-field-${field.key}-${option.value}`;
                    return (
                        <label
                            key={option.value}
                            htmlFor={id}
                            className={clsx(
                                'flex items-center gap-2 rounded-lg border border-edge px-3 py-2 text-sm',
                                disabled
                                    ? 'cursor-not-allowed opacity-60'
                                    : 'cursor-pointer hover:bg-surface-2',
                                selected.includes(option.value)
                                    ? 'bg-accent-soft text-text-1'
                                    : 'text-text-2',
                            )}
                        >
                            <input
                                id={id}
                                type="checkbox"
                                className="accent-[var(--accent)]"
                                checked={selected.includes(option.value)}
                                disabled={disabled}
                                onChange={(event) => toggle(option.value, event.target.checked)}
                            />
                            {option.label}
                        </label>
                    );
                })}
            </div>
        </FieldShell>
    );
}

/**
 * Render one declared field.
 *
 * `image`, `link_list` and `component` fields are handled by the page, which owns the
 * upload endpoint and the bespoke widgets, so they are not reached here.
 */
export function SettingField(props: FieldControlProps) {
    switch (props.field.type) {
        case 'text':
            return <TextControl {...props} />;
        case 'textarea':
            return <TextAreaControl {...props} />;
        case 'secret':
            return <SecretControl {...props} />;
        case 'select':
            return <SelectControl {...props} />;
        case 'switch':
            return <SwitchControl {...props} />;
        case 'color':
            return <ColorControl {...props} />;
        case 'range':
            return <RangeControl {...props} />;
        case 'number':
            return <NumberControl {...props} />;
        case 'string_list':
            return <StringListControl {...props} />;
        case 'note':
            return <NoteControl {...props} />;
        case 'checkbox_set':
            return <CheckboxSetControl {...props} />;
        default:
            return null;
    }
}
