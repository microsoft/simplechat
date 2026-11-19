// ColorControls.tsx
// Controls shared by the admin color scheme editor and the user's custom color mode: a color
// field, a contrast badge and a small live preview of the chat screen.

import { useEffect, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, Check, Paperclip, Send } from 'lucide-react';
import { contrastRatio, displayedRatio, normalizeHexColor, READABLE_CONTRAST_MIN, type Palette } from '../../lib/colorScheme';

/**
 * A swatch that opens the native color picker, with an editable hex value beside it.
 *
 * The hex input keeps its own text while someone types and only reports a value once it is a
 * complete #RRGGBB color, so a half-typed value never reaches the palette.
 */
export function ColorField({
    value,
    onChange,
    label,
    disabled = false,
}: {
    value: string;
    onChange: (next: string) => void;
    label: string;
    disabled?: boolean;
}) {
    const [text, setText] = useState(value);
    useEffect(() => setText(value), [value]);
    const invalid = normalizeHexColor(text) === null;

    return (
        <span className="inline-flex items-center gap-2">
            <label
                className={clsx(
                    'relative block h-8 w-8 shrink-0 overflow-hidden rounded-lg border border-edge-strong shadow-sm',
                    disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
                )}
                style={{ background: value }}
            >
                <input
                    type="color"
                    aria-label={`${label} color picker`}
                    value={value.toLowerCase()}
                    disabled={disabled}
                    onChange={(event) => onChange(event.target.value.toUpperCase())}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                />
            </label>
            <input
                aria-label={`${label} hex value`}
                aria-invalid={invalid || undefined}
                value={text}
                disabled={disabled}
                maxLength={7}
                spellCheck={false}
                onChange={(event) => {
                    setText(event.target.value);
                    const next = normalizeHexColor(event.target.value);
                    if (next) {
                        onChange(next);
                    }
                }}
                onBlur={() => setText(value)}
                className={clsx(
                    'h-8 w-24 rounded-lg border bg-surface-solid px-2 font-mono text-xs text-text-1 uppercase',
                    invalid ? 'border-danger' : 'border-edge-strong',
                )}
            />
        </span>
    );
}

export function ContrastBadge({ foreground, background }: { foreground: string; background: string }) {
    const ratio = displayedRatio(contrastRatio(foreground, background));
    const pass = ratio >= READABLE_CONTRAST_MIN;
    const large = ratio >= 3;
    return (
        <span
            className={clsx(
                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
                pass
                    ? 'border-ok/30 bg-ok-soft text-ok'
                    : large
                      ? 'border-warn/30 bg-warn-soft text-warn'
                      : 'border-danger/30 bg-danger-soft text-danger',
            )}
            title="Contrast against the color it sits on. 4.5:1 or more is readable for everyone."
        >
            {pass ? <Check size={11} aria-hidden="true" /> : <AlertTriangle size={11} aria-hidden="true" />}
            {ratio.toFixed(1)}:1 {pass ? (ratio >= 7 ? 'AAA' : 'AA') : 'Low'}
        </span>
    );
}

/** A small sketch of the chat screen drawn in a palette, so a change can be judged in place. */
export function ColorPreview({
    palette,
    label,
    height = 280,
    compact = false,
}: {
    palette: Palette;
    label?: string;
    height?: number;
    compact?: boolean;
}) {
    return (
        <figure className="min-w-0">
            {label ? <figcaption className="mb-1.5 text-xs font-medium text-text-2">{label}</figcaption> : null}
            <div
                aria-hidden="true"
                className="flex overflow-hidden rounded-xl border border-edge-strong shadow-sm"
                style={{ background: palette.backdrop, height }}
            >
                <div
                    className={clsx('flex shrink-0 flex-col gap-1 p-2.5', compact ? 'w-28' : 'w-40')}
                    style={{ background: palette.panel, borderRight: `1px solid ${palette.border}` }}
                >
                    <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold" style={{ color: palette.text1 }}>
                        <span className="h-3.5 w-3.5 rounded" style={{ background: palette.accent }} />
                        SimpleChat
                    </div>
                    {['Q3 policy summary', 'Offsite planning', 'Vendor review', 'Budget questions'].map((title, index) => (
                        <div
                            key={title}
                            className="truncate rounded-md px-1.5 py-1 text-[10.5px]"
                            style={
                                index === 0
                                    ? { background: `${palette.accent}22`, color: palette.accent, fontWeight: 600 }
                                    : { color: palette.text2 }
                            }
                        >
                            {title}
                        </div>
                    ))}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-2.5 overflow-hidden p-3 text-[11px] leading-snug">
                    <div
                        className="max-w-[78%] shrink-0 self-end rounded-2xl rounded-br-md px-3 py-2"
                        style={{ background: palette.accent, color: palette.onAccent }}
                    >
                        Summarize the Q3 policy update for my team
                    </div>
                    <div
                        className="min-h-0 max-w-[88%] overflow-hidden rounded-2xl rounded-bl-md px-3 py-2"
                        style={{ background: palette.panel, color: palette.text1, border: `1px solid ${palette.border}` }}
                    >
                        Three changes stand out: remote work approvals move to your manager, travel limits rise 10%, and
                        expense reports are due in 14 days.
                        <span className="mt-1 block" style={{ color: palette.text2 }}>2 sources · just now</span>
                    </div>
                    <div className="flex shrink-0 gap-1.5 text-[10px]">
                        <span className="rounded-full px-2 py-0.5" style={{ background: `${palette.ok}22`, color: palette.ok }}>Saved</span>
                        <span className="rounded-full px-2 py-0.5" style={{ background: `${palette.warn}22`, color: palette.warn }}>Review</span>
                        <span className="rounded-full px-2 py-0.5" style={{ background: `${palette.danger}22`, color: palette.danger }}>Failed</span>
                        <span className="rounded-full px-2 py-0.5" style={{ background: `${palette.info}22`, color: palette.info }}>Info</span>
                    </div>
                    <div
                        className="mt-auto flex shrink-0 items-center justify-between rounded-2xl px-3 py-2"
                        style={{ background: palette.panel, border: `1px solid ${palette.border}`, color: palette.text2 }}
                    >
                        <span className="flex items-center gap-1.5">
                            <Paperclip size={11} /> Ask anything…
                        </span>
                        <span
                            className="flex h-6 w-6 items-center justify-center rounded-full"
                            style={{ background: palette.accent, color: palette.onAccent }}
                        >
                            <Send size={11} />
                        </span>
                    </div>
                </div>
            </div>
        </figure>
    );
}

/** Radio-style choices drawn like the Text size control on Preferences. */
export function ChoiceRow<T extends string>({
    label,
    value,
    choices,
    onChange,
    disabled = false,
}: {
    label: string;
    value: T;
    choices: Array<{ value: T; label: string; icon?: ReactNode }>;
    onChange: (next: T) => void;
    disabled?: boolean;
}) {
    return (
        <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
            {choices.map((choice) => (
                <button
                    key={choice.value}
                    type="button"
                    role="radio"
                    aria-checked={choice.value === value}
                    disabled={disabled}
                    onClick={() => onChange(choice.value)}
                    className={clsx(
                        'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                        choice.value === value
                            ? 'border-accent bg-accent-soft font-medium text-accent'
                            : 'border-edge text-text-2 hover:bg-surface-2 hover:text-text-1',
                    )}
                >
                    {choice.icon}
                    {choice.label}
                </button>
            ))}
        </div>
    );
}
