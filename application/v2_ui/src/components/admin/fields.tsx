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
import { AlertCircle, CheckCircle2, ShieldCheck, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import {
    asBoolean,
    asNumber,
    asString,
    asStringArray,
    countWords,
    isRedactedSecret,
    parseStringList,
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
                type="text"
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
                    // An option can be declared but not yet released. Showing it
                    // disabled says the capability is coming; omitting it would look
                    // like the option had been removed.
                    const optionDisabled = disabled || option.disabled;
                    return (
                        <label
                            key={option.value}
                            htmlFor={id}
                            className={clsx(
                                'flex items-start gap-2 rounded-lg border border-edge px-3 py-2 text-sm',
                                optionDisabled
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
                                className="mt-0.5 accent-[var(--accent)]"
                                checked={selected.includes(option.value)}
                                disabled={optionDisabled}
                                onChange={(event) => toggle(option.value, event.target.checked)}
                            />
                            <span>
                                {option.label}
                                {option.description ? (
                                    <span className="block text-xs text-text-3">
                                        {option.description}
                                    </span>
                                ) : null}
                            </span>
                        </label>
                    );
                })}
            </div>
        </FieldShell>
    );
}

/**
 * A credential.
 *
 * The server never sends a stored secret; it sends `SECRET_REDACTED_VALUE`. Two things
 * follow, and both are the point of this control existing separately from `text`:
 *
 * Revealing a still-redacted value shows the placeholder, not the credential, so the
 * button says "Replace" rather than "Show" until the field is edited. Offering "Show"
 * would promise something it cannot deliver.
 *
 * Clearing the box is a real edit -- an administrator removing a key -- so it is
 * reported upward as an empty string, which the server stores. Only the untouched
 * placeholder means "leave it alone".
 */
function SecretControl({ field, value, error, warning, disabled, onChange }: FieldControlProps) {
    const id = `admin-field-${field.key}`;
    const [revealed, setRevealed] = useState(false);
    const current = asString(value);
    const stored = isRedactedSecret(current);

    return (
        <FieldShell
            field={field}
            error={error}
            warning={warning}
            htmlFor={id}
            trailing={
                stored ? (
                    <span className="flex items-center gap-1 text-xs text-text-3">
                        <ShieldCheck size={12} />
                        Stored
                    </span>
                ) : null
            }
        >
            <div className="flex items-center gap-2">
                <input
                    id={id}
                    type={revealed && !stored ? 'text' : 'password'}
                    className={clsx(inputClass, 'font-mono')}
                    value={current}
                    placeholder={field.placeholder}
                    disabled={disabled}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => onChange(event.target.value)}
                />
                <button
                    type="button"
                    className={clsx(
                        'shrink-0 rounded-lg border border-edge px-3 py-2 text-xs',
                        'text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60',
                    )}
                    disabled={disabled}
                    onClick={() => {
                        if (stored) {
                            // Hand the field over for editing. Blanking it first is what
                            // turns the next keystroke into a real change rather than an
                            // edit of the placeholder text.
                            onChange('');
                            setRevealed(true);
                        } else {
                            setRevealed((previous) => !previous);
                        }
                    }}
                >
                    {stored ? 'Replace' : revealed ? 'Hide' : 'Show'}
                </button>
            </div>
        </FieldShell>
    );
}

/**
 * An editable list of short strings, stored newline-delimited.
 *
 * Used for the URL Access allow and block lists. Entries are added one at a time and
 * removed individually, rather than being edited as free text in a textarea, because a
 * stray newline in a domain list is invisible and silently widens or narrows a policy.
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
    const entries = parseStringList(value);
    const [pending, setPending] = useState('');
    const [entryError, setEntryError] = useState<string | null>(null);

    const addEntry = () => {
        const candidate = pending.trim();
        if (!candidate) {
            return;
        }
        if (entries.includes(candidate)) {
            setEntryError('That entry is already in the list.');
            return;
        }
        if (field.entry_pattern && !new RegExp(field.entry_pattern).test(candidate)) {
            setEntryError(`Enter a valid ${field.entry_label ?? 'entry'}.`);
            return;
        }
        if (field.max_entries && entries.length >= field.max_entries) {
            setEntryError(`Enter at most ${field.max_entries} entries.`);
            return;
        }
        setEntryError(null);
        setPending('');
        onChange([...entries, candidate]);
    };

    return (
        <FieldShell
            field={field}
            error={error ?? entryError ?? undefined}
            warning={warning}
            htmlFor={id}
            trailing={
                <span className="text-xs tabular-nums text-text-3">
                    {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
                </span>
            }
        >
            <div className="flex items-center gap-2">
                <input
                    id={id}
                    type="text"
                    className={inputClass}
                    value={pending}
                    placeholder={field.placeholder}
                    disabled={disabled}
                    spellCheck={false}
                    onChange={(event) => {
                        setPending(event.target.value);
                        setEntryError(null);
                    }}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            // This control lives inside the settings form; without this
                            // the key would submit rather than add an entry.
                            event.preventDefault();
                            addEntry();
                        }
                    }}
                />
                <button
                    type="button"
                    className={clsx(
                        'shrink-0 rounded-lg border border-edge px-3 py-2 text-xs',
                        'text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60',
                    )}
                    disabled={disabled || !pending.trim()}
                    onClick={addEntry}
                >
                    Add
                </button>
            </div>

            {entries.length ? (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                    {entries.map((entry) => (
                        <li
                            key={entry}
                            className="flex items-center gap-1.5 rounded-full border border-edge bg-surface-1 py-1 pr-1 pl-3 text-xs text-text-2"
                        >
                            <span className="font-mono">{entry}</span>
                            <button
                                type="button"
                                aria-label={`Remove ${entry}`}
                                className="rounded-full p-0.5 text-text-3 hover:bg-surface-2 hover:text-danger disabled:cursor-not-allowed"
                                disabled={disabled}
                                onClick={() =>
                                    onChange(
                                        entries.filter((item) => item !== entry),
                                    )
                                }
                            >
                                <X size={12} />
                            </button>
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="mt-2 text-xs text-text-3">No entries yet.</p>
            )}
        </FieldShell>
    );
}

/**
 * A server-computed readout.
 *
 * Some of what an administrator needs here is not a setting: whether the FFmpeg audio
 * runtime is present, which Video Indexer endpoint the cloud selection resolves to,
 * whether the Playwright runtime can render JavaScript. V1 renders these as loose markup
 * inside the panes. Declaring them makes them searchable and keeps the reason a control
 * is unavailable next to the control itself.
 */
function StatusControl({ field, value }: FieldControlProps) {
    const tone = statusTone(value);
    const text = readStatusMessage(value);

    return (
        <div className="py-3">
            <div className="mb-1.5 text-sm font-medium text-text-1">{field.label}</div>
            <div
                className={clsx(
                    'flex items-start gap-2 rounded-lg border px-3 py-2 text-xs',
                    tone === 'ok' && 'border-ok/40 bg-ok/5 text-text-2',
                    tone === 'warn' && 'border-warn/40 bg-warn/5 text-warn',
                    tone === 'unknown' && 'border-edge bg-surface-1 text-text-3',
                )}
            >
                {tone === 'ok' ? (
                    <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
                ) : (
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                )}
                <span>{text || 'Not checked yet.'}</span>
            </div>
            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}
        </div>
    );
}

/**
 * Read the tone of a status value.
 *
 * The server sends `{ok, message}`, carrying the tone rather than leaving it to be
 * inferred from the wording. A bare string is still accepted, because a readout added
 * later should not have to be normalised before it can be shown.
 */
function statusTone(value: unknown): 'ok' | 'warn' | 'unknown' {
    if (value && typeof value === 'object' && 'ok' in value) {
        return (value as { ok?: unknown }).ok ? 'ok' : 'warn';
    }
    return asString(value) ? 'ok' : 'unknown';
}

function readStatusMessage(value: unknown): string {
    if (value && typeof value === 'object' && 'message' in value) {
        return asString((value as { message?: unknown }).message);
    }
    return asString(value);
}

/**
 * Render one declared field.
 *
 * `image`, `link_list`, `id_list` and `component` fields are handled by the page, which
 * owns the upload endpoint, the search endpoints and the bespoke widgets, so they are
 * not reached here.
 */
export function SettingField(props: FieldControlProps) {
    switch (props.field.type) {
        case 'text':
            return <TextControl {...props} />;
        case 'textarea':
            return <TextAreaControl {...props} />;
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
        case 'checkbox_set':
            return <CheckboxSetControl {...props} />;
        case 'secret':
            return <SecretControl {...props} />;
        case 'string_list':
            return <StringListControl {...props} />;
        case 'status':
            return <StatusControl {...props} />;
        default:
            return null;
    }
}
