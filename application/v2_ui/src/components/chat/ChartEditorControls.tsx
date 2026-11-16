// ChartEditorControls.tsx
// The small form controls the chart editor is built out of.
//
// Split from ChartEditor so that file is about what a chart can have changed about it rather
// than about how a slider is put together. Nothing here knows anything about charts.

import { useState } from 'react';
import { clsx } from 'clsx';

/**
 * A text input that keeps what is being typed until the field is left.
 *
 * Every field in this editor is bound to the chart's payload, and the payload is trimmed when it
 * is parsed. Binding an input straight to it therefore makes a space impossible to type: the
 * keystroke produces a value identical to the one already there, React puts the old value back,
 * and the cursor jumps. Holding the in-progress text locally while the field has focus is the
 * same thing the number cells in the data grid do, and for the same reason.
 *
 * The buffer is deliberately not refreshed while the field is focused. A version arriving from
 * elsewhere — an AI edit landing, a revision being restored — should not pull text out from
 * under someone's cursor mid-word.
 */
export function BufferedTextInput({
    id,
    value,
    onChange,
    className,
    maxLength,
    placeholder,
    disabled,
    ariaLabel,
}: {
    id?: string;
    value: string;
    onChange: (value: string) => void;
    className: string;
    maxLength?: number;
    placeholder?: string;
    disabled?: boolean;
    ariaLabel?: string;
}) {
    const [typing, setTyping] = useState<string | null>(null);

    return (
        <input
            id={id}
            type="text"
            value={typing ?? value}
            maxLength={maxLength}
            placeholder={placeholder}
            disabled={disabled}
            aria-label={ariaLabel}
            className={className}
            onFocus={() => setTyping(value)}
            onBlur={() => setTyping(null)}
            onChange={(event) => {
                setTyping(event.target.value);
                onChange(event.target.value);
            }}
        />
    );
}

/** A titled group of controls, with an optional line explaining what the group is for. */
export function ControlSection({
    title,
    hint,
    children,
}: {
    title: string;
    hint?: string;
    children: React.ReactNode;
}) {
    return (
        <section className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-text-2">{title}</h3>
            {hint && <p className="text-[11px] leading-relaxed text-text-3">{hint}</p>}
            {children}
        </section>
    );
}

/** A small pill button, used wherever a choice is one of a short list. */
export function ChoiceButton({
    active,
    disabled,
    onClick,
    children,
}: {
    active: boolean;
    disabled?: boolean;
    onClick: () => void;
    children: React.ReactNode;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-pressed={active}
            className={clsx(
                'rounded-lg border px-2.5 py-1 text-[11px] font-medium transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-50',
                active
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-edge-strong text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {children}
        </button>
    );
}

/** An on/off choice, as a real checkbox so it is reachable and announced as one. */
export function ToggleField({
    label,
    checked,
    disabled,
    hint,
    onChange,
}: {
    label: string;
    checked: boolean;
    disabled?: boolean;
    hint?: string;
    onChange: (value: boolean) => void;
}) {
    return (
        <label
            className={clsx(
                'flex items-start gap-2 text-xs text-text-1',
                disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
            )}
        >
            <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(event) => onChange(event.target.checked)}
                className="mt-0.5 size-3.5 shrink-0 accent-[var(--accent)]"
            />
            <span className="flex flex-col gap-0.5">
                <span>{label}</span>
                {hint && <span className="text-[11px] text-text-3">{hint}</span>}
            </span>
        </label>
    );
}

/** A single-line text setting. */
export function TextField({
    id,
    label,
    value,
    placeholder,
    maxLength,
    disabled,
    onChange,
}: {
    id: string;
    label: string;
    value: string;
    placeholder?: string;
    maxLength?: number;
    disabled?: boolean;
    onChange: (value: string) => void;
}) {
    return (
        <div className="flex flex-col gap-1">
            <label htmlFor={id} className="text-[11px] font-medium text-text-2">
                {label}
            </label>
            <BufferedTextInput
                id={id}
                value={value}
                placeholder={placeholder}
                maxLength={maxLength}
                disabled={disabled}
                onChange={onChange}
                className="rounded-lg border border-edge-strong bg-surface-sunken px-2 py-1.5 text-xs text-text-1 outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50"
            />
        </div>
    );
}

/**
 * A number that may be left unset.
 *
 * Kept as text rather than `type="number"` so a half-typed value like "-" or "1." survives
 * until it becomes a number, instead of the field emptying itself under the cursor.
 */
export function NumberField({
    id,
    label,
    value,
    placeholder,
    disabled,
    onChange,
}: {
    id: string;
    label: string;
    value: number | null;
    placeholder?: string;
    disabled?: boolean;
    onChange: (value: number | null) => void;
}) {
    return (
        <div className="flex flex-1 flex-col gap-1">
            <label htmlFor={id} className="text-[11px] font-medium text-text-2">
                {label}
            </label>
            <input
                id={id}
                type="text"
                inputMode="decimal"
                value={value === null ? '' : String(value)}
                placeholder={placeholder ?? 'Auto'}
                disabled={disabled}
                onChange={(event) => {
                    const text = event.target.value.trim();
                    if (!text) {
                        onChange(null);
                        return;
                    }
                    const parsed = Number(text);
                    if (Number.isFinite(parsed)) {
                        onChange(parsed);
                    }
                }}
                className="rounded-lg border border-edge-strong bg-surface-sunken px-2 py-1.5 text-xs text-text-1 outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50"
            />
        </div>
    );
}

/** A bounded number, with the value it currently holds shown beside its name. */
export function SliderField({
    id,
    label,
    value,
    min,
    max,
    step,
    format,
    disabled,
    onChange,
}: {
    id: string;
    label: string;
    value: number;
    min: number;
    max: number;
    step: number;
    /** How the current value reads, such as "80%" or "2 px". */
    format?: (value: number) => string;
    disabled?: boolean;
    onChange: (value: number) => void;
}) {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2">
                <label htmlFor={id} className="text-[11px] font-medium text-text-2">
                    {label}
                </label>
                <span className="text-[11px] tabular-nums text-text-3">
                    {format ? format(value) : value}
                </span>
            </div>
            <input
                id={id}
                type="range"
                min={min}
                max={max}
                step={step}
                value={value}
                disabled={disabled}
                onChange={(event) => onChange(Number(event.target.value))}
                className="w-full accent-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
            />
        </div>
    );
}
