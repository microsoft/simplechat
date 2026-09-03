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
import { AlertCircle } from 'lucide-react';
import type { ReactNode } from 'react';
import {
    asBoolean,
    asNumber,
    asString,
    asStringArray,
    countWords,
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
        default:
            return null;
    }
}
