// ChartDataGrid.tsx
// The chart's numbers, as a grid you can type into.
//
// This is the part of the editor people reach for most: a chart is usually right in shape and
// wrong in one cell. Everything here edits a copy of the draft and hands the whole thing back,
// so a change is one revision rather than one per keystroke.
//
// Numbers are held as text only while a cell has focus. Committing on every keystroke would
// throw away a half-typed "-" or "1.", and keeping every cell as text would let the grid drift
// away from the payload it is supposed to be showing.

import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import {
    MAX_CHART_LABELS,
    MAX_CHART_SERIES,
    isPointChart,
    readChartDataDraft,
    type ChartDataDraft,
} from '../../lib/chartEdits';
import type { ChartSpec } from '../../lib/inlineChartSpec';
import { BufferedTextInput } from './ChartEditorControls';

const CELL_CLASS =
    'w-full rounded border border-edge-strong bg-surface-sunken px-1.5 py-1 text-[11px] text-text-1 outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50';

/** A number as it should appear in a cell, with a gap shown as an empty one. */
function cellText(value: number | null | undefined): string {
    return value === null || value === undefined ? '' : String(value);
}

/** The number a cell now holds, or null when it holds nothing usable yet. */
function readCellNumber(text: string): number | null {
    const trimmed = text.trim();
    if (!trimmed) {
        return null;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
}

function IconButton({
    label,
    disabled,
    onClick,
    children,
}: {
    label: string;
    disabled?: boolean;
    onClick: () => void;
    children: React.ReactNode;
}) {
    return (
        <button
            type="button"
            title={label}
            aria-label={label}
            disabled={disabled}
            onClick={onClick}
            className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
        >
            {children}
        </button>
    );
}

export function ChartDataGrid({
    spec,
    disabled,
    onChange,
}: {
    spec: ChartSpec;
    disabled: boolean;
    onChange: (draft: ChartDataDraft) => void;
}) {
    // Only the focused cell keeps its raw text, so a value being typed is never reformatted
    // under the cursor while every other cell still reflects the payload.
    const [editing, setEditing] = useState<{ key: string; text: string } | null>(null);

    const draft = readChartDataDraft(spec);
    const pointBased = isPointChart(spec.kind);
    const bubble = spec.kind === 'bubble';

    /** Hand a mutated copy of the draft back to the editor. */
    const commit = (mutate: (next: ChartDataDraft) => void) => {
        const next: ChartDataDraft = {
            labels: [...draft.labels],
            series: draft.series.map((series) => ({
                label: series.label,
                values: [...series.values],
                points: series.points.map((point) => ({ ...point })),
            })),
        };
        mutate(next);
        onChange(next);
    };

    const shownText = (key: string, value: number | null | undefined) =>
        editing?.key === key ? editing.text : cellText(value);

    const addSeries = () =>
        commit((next) => {
            next.series.push({
                label: `Series ${next.series.length + 1}`,
                values: next.labels.map(() => null),
                points: pointBased ? [{ x: 0, y: 0, ...(bubble ? { r: 1 } : {}) }] : [],
            });
        });

    const removeSeries = (index: number) =>
        commit((next) => {
            next.series.splice(index, 1);
        });

    const renameSeries = (index: number, label: string) =>
        commit((next) => {
            next.series[index].label = label;
        });

    const atSeriesLimit = draft.series.length >= MAX_CHART_SERIES;
    // A chart with no series at all cannot be parsed back, so the last one is not removable.
    const canRemoveSeries = draft.series.length > 1;

    if (pointBased) {
        return (
            <div className="flex flex-col gap-3">
                {draft.series.map((series, seriesIndex) => (
                    <div
                        key={seriesIndex}
                        className="flex flex-col gap-2 rounded-lg border border-edge-strong p-2"
                    >
                        <div className="flex items-center gap-1">
                            <BufferedTextInput
                                value={series.label}
                                maxLength={80}
                                disabled={disabled}
                                ariaLabel={`Name of series ${seriesIndex + 1}`}
                                onChange={(next) => renameSeries(seriesIndex, next)}
                                className={CELL_CLASS}
                            />
                            <IconButton
                                label={`Remove ${series.label}`}
                                disabled={disabled || !canRemoveSeries}
                                onClick={() => removeSeries(seriesIndex)}
                            >
                                <X size={12} />
                            </IconButton>
                        </div>

                        <table className="w-full border-collapse">
                            <thead>
                                <tr className="text-left text-[11px] text-text-3">
                                    <th scope="col" className="pb-1 font-medium">X</th>
                                    <th scope="col" className="pb-1 font-medium">Y</th>
                                    {bubble && (
                                        <th scope="col" className="pb-1 font-medium">Size</th>
                                    )}
                                    <th scope="col" className="pb-1">
                                        <span className="sr-only">Remove</span>
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {series.points.map((point, pointIndex) => (
                                    <tr key={pointIndex}>
                                        {(bubble ? (['x', 'y', 'r'] as const) : (['x', 'y'] as const)).map(
                                            (field) => {
                                                const key = `p:${seriesIndex}:${pointIndex}:${field}`;
                                                return (
                                                    <td key={field} className="pr-1 align-top">
                                                        <input
                                                            type="text"
                                                            inputMode="decimal"
                                                            disabled={disabled}
                                                            aria-label={`${field.toUpperCase()} of point ${pointIndex + 1} in ${series.label}`}
                                                            value={shownText(key, point[field])}
                                                            onFocus={() =>
                                                                setEditing({
                                                                    key,
                                                                    text: cellText(point[field]),
                                                                })
                                                            }
                                                            onBlur={() => setEditing(null)}
                                                            onChange={(event) => {
                                                                const text = event.target.value;
                                                                setEditing({ key, text });
                                                                commit((next) => {
                                                                    next.series[seriesIndex].points[
                                                                        pointIndex
                                                                    ][field] = readCellNumber(text) ?? 0;
                                                                });
                                                            }}
                                                            className={CELL_CLASS}
                                                        />
                                                    </td>
                                                );
                                            },
                                        )}
                                        <td className="align-top">
                                            <IconButton
                                                label={`Remove point ${pointIndex + 1}`}
                                                disabled={disabled || series.points.length <= 1}
                                                onClick={() =>
                                                    commit((next) => {
                                                        next.series[seriesIndex].points.splice(
                                                            pointIndex,
                                                            1,
                                                        );
                                                    })
                                                }
                                            >
                                                <X size={12} />
                                            </IconButton>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        <IconButton
                            label={`Add a point to ${series.label}`}
                            disabled={disabled || series.points.length >= MAX_CHART_LABELS}
                            onClick={() =>
                                commit((next) => {
                                    next.series[seriesIndex].points.push({
                                        x: 0,
                                        y: 0,
                                        ...(bubble ? { r: 1 } : {}),
                                    });
                                })
                            }
                        >
                            <Plus size={12} />
                            Add point
                        </IconButton>
                    </div>
                ))}

                <IconButton
                    label="Add a series"
                    disabled={disabled || atSeriesLimit}
                    onClick={addSeries}
                >
                    <Plus size={12} />
                    Add series
                </IconButton>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                    <thead>
                        <tr>
                            <th
                                scope="col"
                                className="pb-1 pr-1 text-left text-[11px] font-medium text-text-3"
                            >
                                Label
                            </th>
                            {draft.series.map((series, seriesIndex) => (
                                <th key={seriesIndex} scope="col" className="pb-1 pr-1">
                                    <div className="flex items-center gap-0.5">
                                        <BufferedTextInput
                                            value={series.label}
                                            maxLength={80}
                                            disabled={disabled}
                                            ariaLabel={`Name of series ${seriesIndex + 1}`}
                                            onChange={(next) => renameSeries(seriesIndex, next)}
                                            className={`${CELL_CLASS} min-w-20`}
                                        />
                                        <IconButton
                                            label={`Remove ${series.label}`}
                                            disabled={disabled || !canRemoveSeries}
                                            onClick={() => removeSeries(seriesIndex)}
                                        >
                                            <X size={12} />
                                        </IconButton>
                                    </div>
                                </th>
                            ))}
                            <th scope="col" className="pb-1">
                                <span className="sr-only">Remove row</span>
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {draft.labels.map((label, rowIndex) => (
                            <tr key={rowIndex}>
                                <td className="pr-1 align-top">
                                    <BufferedTextInput
                                        value={label}
                                        maxLength={80}
                                        disabled={disabled}
                                        ariaLabel={`Label for row ${rowIndex + 1}`}
                                        onChange={(next) =>
                                            commit((draftToChange) => {
                                                draftToChange.labels[rowIndex] = next;
                                            })
                                        }
                                        className={`${CELL_CLASS} min-w-24`}
                                    />
                                </td>
                                {draft.series.map((series, seriesIndex) => {
                                    const key = `v:${seriesIndex}:${rowIndex}`;
                                    return (
                                        <td key={seriesIndex} className="pr-1 align-top">
                                            <input
                                                type="text"
                                                inputMode="decimal"
                                                disabled={disabled}
                                                aria-label={`${series.label} for ${label || `row ${rowIndex + 1}`}`}
                                                value={shownText(key, series.values[rowIndex])}
                                                onFocus={() =>
                                                    setEditing({
                                                        key,
                                                        text: cellText(series.values[rowIndex]),
                                                    })
                                                }
                                                onBlur={() => setEditing(null)}
                                                onChange={(event) => {
                                                    const text = event.target.value;
                                                    setEditing({ key, text });
                                                    commit((next) => {
                                                        next.series[seriesIndex].values[rowIndex] =
                                                            readCellNumber(text);
                                                    });
                                                }}
                                                className={`${CELL_CLASS} min-w-16`}
                                            />
                                        </td>
                                    );
                                })}
                                <td className="align-top">
                                    <IconButton
                                        label={`Remove row ${rowIndex + 1}`}
                                        disabled={disabled || draft.labels.length <= 1}
                                        onClick={() =>
                                            commit((next) => {
                                                next.labels.splice(rowIndex, 1);
                                                next.series.forEach((series) =>
                                                    series.values.splice(rowIndex, 1),
                                                );
                                            })
                                        }
                                    >
                                        <X size={12} />
                                    </IconButton>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <div className="flex flex-wrap items-center gap-1">
                <IconButton
                    label="Add a row"
                    disabled={disabled || draft.labels.length >= MAX_CHART_LABELS}
                    onClick={() =>
                        commit((next) => {
                            next.labels.push(`Item ${next.labels.length + 1}`);
                            next.series.forEach((series) => series.values.push(null));
                        })
                    }
                >
                    <Plus size={12} />
                    Add row
                </IconButton>
                <IconButton label="Add a series" disabled={disabled || atSeriesLimit} onClick={addSeries}>
                    <Plus size={12} />
                    Add series
                </IconButton>
            </div>

            <p className="text-[11px] leading-relaxed text-text-3">
                An empty cell is a gap in the series rather than a zero, so a line is drawn
                straight past it instead of dropping to the axis.
            </p>
        </div>
    );
}
