// VisualStyleMenu.tsx
// The colour controls shared by rendered diagrams and charts.
//
// Presentational: the block that owns the style passes it in and receives the change, because
// a diagram and a chart persist their choice through the same call but apply it in very
// different ways.
//
// It expands in place rather than floating. A popover positioned against a block inside a
// scrolling, streaming message list has to be re-anchored constantly, and the chart's data
// table already establishes in-place expansion as the pattern for this toolbar.

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Palette, RotateCcw } from 'lucide-react';
import type { ChartColorTarget } from '../../lib/inlineChartSpec';
import {
    PALETTE_PRESETS,
    THEME_BACKGROUND,
    normalizeHexColor,
    resolveBackgroundColor,
    type PaletteId,
    type VisualStyle,
} from '../../lib/visualPalettes';

/** Preset swatches shown per button. Five reads as a palette without crowding the row. */
const SWATCH_COUNT = 5;

/**
 * How long to coalesce a colour input's stream of events.
 *
 * A native colour input reports every step of a drag. Each report re-draws the block, and a
 * diagram re-draw means a full mermaid render, so passing them straight through queues dozens
 * of renders for one adjustment. Short enough to still feel live.
 */
const COLOR_INPUT_COALESCE_MS = 120;

/**
 * A colour input that shows every step of a drag but only reports the ones worth acting on.
 *
 * The swatch is driven by local state so the control never lags behind the pointer, while the
 * value handed upward — and therefore the work of re-drawing — is coalesced.
 */
function ColorInput({
    value,
    label,
    onCommit,
    className,
}: {
    value: string;
    label: string;
    onCommit: (color: string) => void;
    className?: string;
}) {
    const [local, setLocal] = useState(value);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pendingRef = useRef<string | null>(null);

    // Follows the resolved value when it changes for any other reason, such as a preset being
    // applied or the theme being switched.
    useEffect(() => {
        setLocal(value);
    }, [value]);

    const flush = useCallback(() => {
        if (timerRef.current !== null) {
            clearTimeout(timerRef.current);
            timerRef.current = null;
        }
        if (pendingRef.current !== null) {
            const next = pendingRef.current;
            pendingRef.current = null;
            onCommit(next);
        }
    }, [onCommit]);

    useEffect(() => () => flush(), [flush]);

    return (
        <input
            type="color"
            value={local}
            aria-label={label}
            onChange={(event) => {
                const next = normalizeHexColor(event.target.value, local);
                setLocal(next);
                pendingRef.current = next;
                if (timerRef.current === null) {
                    timerRef.current = setTimeout(() => {
                        timerRef.current = null;
                        const queued = pendingRef.current;
                        pendingRef.current = null;
                        if (queued !== null) {
                            onCommit(queued);
                        }
                    }, COLOR_INPUT_COALESCE_MS);
                }
            }}
            onBlur={flush}
            className={clsx(
                'cursor-pointer rounded border border-edge-strong bg-transparent p-0',
                className ?? 'h-6 w-6',
            )}
        />
    );
}

function PalettePresets({
    selected,
    onSelect,
}: {
    selected: PaletteId;
    onSelect: (id: PaletteId) => void;
}) {
    return (
        <div role="radiogroup" aria-label="Colour palette" className="flex flex-wrap gap-1.5">
            {PALETTE_PRESETS.map((preset) => {
                const active = preset.id === selected;
                return (
                    <button
                        key={preset.id}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        title={`${preset.name} palette`}
                        onClick={() => onSelect(preset.id)}
                        className={clsx(
                            'flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium transition-colors',
                            active
                                ? 'border-accent bg-accent-soft text-accent'
                                : 'border-edge-strong text-text-2 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        <span className="flex" aria-hidden="true">
                            {preset.colors.slice(0, SWATCH_COUNT).map((color) => (
                                <span
                                    key={color}
                                    className="h-3 w-2 first:rounded-l-sm last:rounded-r-sm"
                                    style={{ backgroundColor: color }}
                                />
                            ))}
                        </span>
                        {preset.name}
                        {active && <Check size={11} aria-hidden="true" />}
                    </button>
                );
            })}
        </div>
    );
}

function SeriesColors({
    targets,
    onChange,
}: {
    targets: ChartColorTarget[];
    onChange: (index: number, color: string) => void;
}) {
    return (
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {targets.map((target) => (
                <label
                    key={target.index}
                    className="flex items-center gap-1.5 text-xs text-text-2"
                >
                    <ColorInput
                        value={target.color}
                        label={`Colour for ${target.label}`}
                        onCommit={(color) => onChange(target.index, color)}
                    />
                    <span className="truncate">{target.label}</span>
                </label>
            ))}
        </div>
    );
}

export interface VisualStyleMenuProps {
    style: VisualStyle;
    onChange: (next: VisualStyle) => void;
    /** Drop the block's own style so it follows the reader's default again. */
    onReset: () => void;
    /** Series or slices to offer individual colours for. Omitted for diagrams. */
    targets?: ChartColorTarget[];
    open: boolean;
    onToggle: () => void;
    /** False on a reply that is still streaming: there is no message to save against yet. */
    canPersist: boolean;
    /** Set when the last save failed, so the reader is not left thinking it was stored. */
    error?: string | null;
    /** "diagram" or "chart", used in the control's accessible name. */
    noun: string;
}

/**
 * A palette, optional per-series colours, and a background, for one block.
 *
 * The background offers "Match theme" as a distinct choice rather than a colour that happens to
 * match: a block saved while reading in light mode should follow the reader into dark mode
 * unless they asked for a specific colour.
 */
export function VisualStyleMenu({
    style,
    onChange,
    onReset,
    targets,
    open,
    onToggle,
    canPersist,
    error,
    noun,
}: VisualStyleMenuProps) {
    const panelId = useId();
    const followsTheme = style.background === THEME_BACKGROUND;
    const backgroundValue = resolveBackgroundColor(style);

    return (
        <>
            <button
                type="button"
                onClick={onToggle}
                aria-expanded={open}
                aria-controls={panelId}
                title={`Change ${noun} colours`}
                className={clsx(
                    'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors',
                    open
                        ? 'bg-accent-soft text-accent'
                        : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                )}
            >
                <Palette size={13} />
                Colors
            </button>

            {open && (
                <div
                    id={panelId}
                    className="mt-1 w-full space-y-3 border-t border-edge-strong px-3 pt-3"
                >
                    <PalettePresets
                        selected={style.palette}
                        onSelect={(palette) =>
                            // A preset is a fresh start: keeping individual picks would leave
                            // the chart showing a palette it is not actually on.
                            onChange({ ...style, palette, colors: {} })
                        }
                    />

                    {targets && targets.length > 0 && (
                        <SeriesColors
                            targets={targets}
                            onChange={(index, color) =>
                                onChange({
                                    ...style,
                                    colors: {
                                        ...style.colors,
                                        [String(index)]: normalizeHexColor(
                                            color,
                                            targets[index]?.color ?? '#1c6ea4',
                                        ),
                                    },
                                })
                            }
                        />
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-text-2">Background</span>
                        <button
                            type="button"
                            aria-pressed={followsTheme}
                            onClick={() =>
                                onChange({ ...style, background: THEME_BACKGROUND })
                            }
                            className={clsx(
                                'rounded-md border px-2 py-1 text-xs font-medium transition-colors',
                                followsTheme
                                    ? 'border-accent bg-accent-soft text-accent'
                                    : 'border-edge-strong text-text-2 hover:bg-surface-2 hover:text-text-1',
                            )}
                        >
                            Match theme
                        </button>
                        <label className="flex items-center gap-1.5 text-xs text-text-2">
                            <ColorInput
                                value={backgroundValue}
                                label={`Background colour for this ${noun}`}
                                onCommit={(color) =>
                                    onChange({ ...style, background: color })
                                }
                            />
                            Custom
                        </label>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <button
                            type="button"
                            onClick={onReset}
                            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <RotateCcw size={12} />
                            Reset to my default
                        </button>
                        {!canPersist && (
                            <span className="text-[11px] text-text-3">
                                Saved once the reply finishes.
                            </span>
                        )}
                    </div>

                    {error && <p className="text-[11px] text-danger">{error}</p>}
                </div>
            )}
        </>
    );
}
