// ChartEditor.tsx
// Edit mode for a rendered chart: numbers, appearance, axes, source, a scoped AI conversation
// and history.
//
// The counterpart to DiagramEditor, and deliberately the same shape: preview on the left, tools
// on the right, every change a revision. It differs in one way that matters. A diagram has two
// layout controls, so each one saves the moment it is clicked. A chart has a few dozen, and
// saving each click would turn the history into a list nobody can read and file twenty documents
// where one would do. So the whole panel edits a draft, the preview follows it live, and one
// "Save version" records the lot with a note saying what changed.
//
// Everything the controls do is a source-to-source transform in lib/chartEdits.ts. Nothing here
// keeps chart state of its own, which is what lets the source editor and the controls be two
// views of the same thing rather than two things that have to be kept in step.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
    History,
    PenLine,
    RotateCcw,
    Send,
    Settings2,
    Sparkles,
    Table2,
    Ruler,
    X,
} from 'lucide-react';
import { GlassPanel } from '../ui/primitives';
import { describeSourceProblem, MAX_INSTRUCTION_LENGTH } from '../../lib/blockRevisions';
import type { BlockRevision, BlockRevisionChatTurn } from '../../lib/blockRevisions';
import {
    CHART_KIND_LABELS,
    chartKindChoices,
    describeChartChanges,
    formatChartSource,
    isEditableAsGrid,
    isPointChart,
    setChartData,
    setChartKind,
    setChartOption,
    setChartText,
} from '../../lib/chartEdits';
import { getBaseChartType, parseInlineChart } from '../../lib/inlineChartSpec';
import type { VisualStyle } from '../../lib/visualPalettes';
import { ChartCanvas } from './ChartCanvas';
import { ChartDataGrid } from './ChartDataGrid';
import {
    ChoiceButton,
    ControlSection,
    NumberField,
    SliderField,
    TextField,
    ToggleField,
} from './ChartEditorControls';

type EditorTab = 'data' | 'design' | 'axes' | 'source' | 'ask' | 'history';

const TABS: { id: EditorTab; label: string; icon: typeof PenLine }[] = [
    { id: 'data', label: 'Data', icon: Table2 },
    { id: 'design', label: 'Design', icon: Settings2 },
    { id: 'axes', label: 'Axes', icon: Ruler },
    { id: 'source', label: 'Source', icon: PenLine },
    { id: 'ask', label: 'Ask AI', icon: Sparkles },
    { id: 'history', label: 'History', icon: History },
];

/** How a revision came about, in words a reader recognises. */
const ORIGIN_LABELS: Record<string, string> = {
    original: 'As generated',
    manual: 'Edited',
    control: 'Changed',
    ai: 'AI edit',
};

const LEGEND_POSITIONS = ['top', 'bottom', 'left', 'right'] as const;
const LEGEND_POSITION_LABELS: Record<string, string> = {
    top: 'Top',
    bottom: 'Bottom',
    left: 'Left',
    right: 'Right',
};

function formatTimestamp(value: string | undefined): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString();
}

/** The number in a percentage string such as "60%", for the doughnut hole control. */
function readPercentage(value: string, fallback: number): number {
    const parsed = Number(String(value ?? '').replace('%', '').trim());
    return Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 90) : fallback;
}

export interface ChartEditorProps {
    title: string;
    /** What the chart currently draws from, and the starting point for an edit. */
    currentSource: string;
    revisions: BlockRevision[];
    currentIndex: number;
    chat: BlockRevisionChatTurn[];
    canPersist: boolean;
    busy: boolean;
    error: string | null;
    /** The reader's colours, so the preview matches the chart in the reply. */
    style: VisualStyle;
    onClearError: () => void;
    onSave: (source: string, origin?: 'manual' | 'control', note?: string) => Promise<boolean>;
    onRestore: (revisionId: string) => Promise<boolean>;
    onAsk: (instruction: string) => Promise<boolean>;
    onClose: () => void;
}

export function ChartEditor({
    title,
    currentSource,
    revisions,
    currentIndex,
    chat,
    canPersist,
    busy,
    error,
    style,
    onClearError,
    onSave,
    onRestore,
    onAsk,
    onClose,
}: ChartEditorProps) {
    const [tab, setTab] = useState<EditorTab>('data');
    const [draft, setDraft] = useState(currentSource);
    const [instruction, setInstruction] = useState('');
    // Which kind of edit produced the pending change, which is only used to label it in the
    // history. Typing in the source box is an edit; moving a slider is a change.
    const [typedInSource, setTypedInSource] = useState(false);
    const closeRef = useRef<HTMLButtonElement>(null);

    // The stored source is the source of truth. When it changes underneath — an AI edit landed,
    // a revision was restored — the draft follows it, because the reader is now looking at
    // something else and an unsynced editor would silently overwrite it on the next save.
    useEffect(() => {
        setDraft(currentSource);
        setTypedInSource(false);
    }, [currentSource]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    // Opening a dialog moves focus into it; closing hands it back to whatever opened it.
    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        return () => previous?.focus?.();
    }, []);

    const dirty = draft.trim() !== currentSource.trim();
    const problem = useMemo(
        () => (dirty ? describeSourceProblem(draft, 'simplechart') : null),
        [dirty, draft],
    );
    const note = useMemo(
        () => (dirty ? describeChartChanges(currentSource, draft) : ''),
        [currentSource, dirty, draft],
    );

    const draftSpec = useMemo(() => parseInlineChart(draft), [draft]);
    const currentSpec = useMemo(() => parseInlineChart(currentSource), [currentSource]);

    // The preview follows the draft, so a change is visible before it is saved. A draft that
    // cannot be read keeps showing the last good version rather than blanking on every keystroke.
    const previewSpec = draftSpec ?? currentSpec;

    // Controls are driven by the draft, and are unavailable when it cannot be read — there is
    // nothing coherent for a slider to be set to, and moving one would overwrite whatever the
    // reader is halfway through typing in the source box.
    const spec = draftSpec;
    const locked = busy || !canPersist || !spec;

    const baseType = spec ? getBaseChartType(spec.kind) : '';
    const cartesian = ['bar', 'line', 'scatter', 'bubble'].includes(baseType);
    const barLike = spec?.kind === 'bar' || spec?.kind === 'stacked_bar';
    const lineLike = spec ? ['line', 'area', 'stacked_line'].includes(spec.kind) : false;
    const pointBased = spec ? isPointChart(spec.kind) : false;
    const kindChoices = useMemo(() => (spec ? chartKindChoices(spec) : null), [spec]);

    const setOption = (key: string, value: unknown) => setDraft(setChartOption(draft, key, value));
    const setText = (key: 'title' | 'subtitle' | 'description', value: string) =>
        setDraft(setChartText(draft, key, value));

    const save = async () => {
        const kept = await onSave(draft, typedInSource ? 'manual' : 'control', note);
        if (kept) {
            setTypedInSource(false);
        }
    };

    const discard = () => {
        setDraft(currentSource);
        setTypedInSource(false);
    };

    const submitInstruction = async () => {
        const asked = instruction.trim();
        if (!asked) {
            return;
        }
        const ok = await onAsk(asked);
        if (ok) {
            setInstruction('');
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label={`Editing ${title}`}
        >
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-[90vh] w-full max-w-7xl flex-col overflow-hidden"
            >
                <div className="flex shrink-0 items-center gap-2 border-b border-edge px-5 py-3">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-1">
                        {title}
                    </h2>
                    {busy && <span className="text-xs text-text-3">Working…</span>}
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        title="Close"
                        aria-label="Close the editor"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                {!canPersist && (
                    <p className="shrink-0 border-b border-edge bg-surface-sunken px-5 py-2 text-xs text-text-3">
                        This chart cannot be edited until the reply has finished.
                    </p>
                )}

                {error && (
                    <div className="flex shrink-0 items-start gap-2 border-b border-edge bg-danger/10 px-5 py-2">
                        <p className="flex-1 text-xs text-danger">{error}</p>
                        <button
                            type="button"
                            onClick={onClearError}
                            className="text-xs text-danger underline"
                        >
                            Dismiss
                        </button>
                    </div>
                )}

                <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                    <div className="flex min-h-0 flex-1 flex-col gap-2 border-b border-edge p-4 lg:border-b-0 lg:border-r">
                        {previewSpec ? (
                            <>
                                {(previewSpec.title || previewSpec.subtitle) && (
                                    <div className="shrink-0">
                                        {previewSpec.title && (
                                            <div className="text-sm font-semibold text-text-1">
                                                {previewSpec.title}
                                            </div>
                                        )}
                                        {previewSpec.subtitle && (
                                            <div className="mt-0.5 text-xs text-text-2">
                                                {previewSpec.subtitle}
                                            </div>
                                        )}
                                    </div>
                                )}
                                <div className="relative min-h-64 flex-1">
                                    <ChartCanvas
                                        spec={previewSpec}
                                        style={style}
                                        label={previewSpec.title || 'Chart preview'}
                                    />
                                </div>
                                {previewSpec.description && (
                                    <p className="shrink-0 text-xs text-text-2">
                                        {previewSpec.description}
                                    </p>
                                )}
                            </>
                        ) : (
                            <p className="text-xs text-text-3">
                                This chart cannot be drawn from its current data.
                            </p>
                        )}
                    </div>

                    <div className="flex min-h-0 w-full flex-col lg:w-[27rem]">
                        <div
                            role="tablist"
                            aria-label="Chart editing tools"
                            className="flex shrink-0 flex-wrap gap-1 border-b border-edge px-3 py-2"
                        >
                            {TABS.map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    type="button"
                                    role="tab"
                                    aria-selected={tab === id}
                                    onClick={() => setTab(id)}
                                    className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors ${
                                        tab === id
                                            ? 'bg-surface-2 text-text-1'
                                            : 'text-text-3 hover:bg-surface-2 hover:text-text-1'
                                    }`}
                                >
                                    <Icon size={13} />
                                    {label}
                                </button>
                            ))}
                        </div>

                        <div className="min-h-0 flex-1 overflow-auto p-3">
                            {tab === 'data' && (
                                <>
                                    {!spec && (
                                        <p className="text-xs text-text-3">
                                            The chart data cannot be read. Fix it in the Source tab
                                            and the grid comes back.
                                        </p>
                                    )}
                                    {spec && !isEditableAsGrid(spec) && (
                                        <p className="text-xs leading-relaxed text-text-3">
                                            This chart has too many rows to edit as a grid. Its
                                            numbers are all in the Source tab, and Ask AI can
                                            change them in bulk.
                                        </p>
                                    )}
                                    {spec && isEditableAsGrid(spec) && (
                                        <ChartDataGrid
                                            spec={spec}
                                            disabled={locked}
                                            onChange={(next) =>
                                                setDraft(setChartData(draft, next, spec.kind))
                                            }
                                        />
                                    )}
                                </>
                            )}

                            {tab === 'design' && spec && (
                                <div className="flex flex-col gap-5">
                                    <ControlSection title="Chart type" hint={kindChoices?.note ?? undefined}>
                                        <div className="flex flex-wrap gap-1.5">
                                            {(kindChoices?.kinds ?? []).map((kind) => (
                                                <ChoiceButton
                                                    key={kind}
                                                    active={spec.kind === kind}
                                                    disabled={locked}
                                                    onClick={() => setDraft(setChartKind(draft, kind))}
                                                >
                                                    {CHART_KIND_LABELS[kind] ?? kind}
                                                </ChoiceButton>
                                            ))}
                                        </div>
                                    </ControlSection>

                                    <ControlSection title="Titles">
                                        <TextField
                                            id="chart-title"
                                            label="Title"
                                            value={spec.title}
                                            maxLength={160}
                                            disabled={locked}
                                            onChange={(value) => setText('title', value)}
                                        />
                                        <TextField
                                            id="chart-subtitle"
                                            label="Subtitle"
                                            value={spec.subtitle}
                                            maxLength={160}
                                            disabled={locked}
                                            onChange={(value) => setText('subtitle', value)}
                                        />
                                        <TextField
                                            id="chart-description"
                                            label="Caption"
                                            value={spec.description}
                                            maxLength={320}
                                            disabled={locked}
                                            onChange={(value) => setText('description', value)}
                                        />
                                    </ControlSection>

                                    <ControlSection title="Legend">
                                        <ToggleField
                                            label="Show the legend"
                                            checked={spec.options.showLegend}
                                            disabled={locked}
                                            onChange={(value) => setOption('showLegend', value)}
                                        />
                                        <div className="flex flex-wrap gap-1.5">
                                            {LEGEND_POSITIONS.map((position) => (
                                                <ChoiceButton
                                                    key={position}
                                                    active={spec.options.legendPosition === position}
                                                    disabled={locked || !spec.options.showLegend}
                                                    onClick={() => setOption('legendPosition', position)}
                                                >
                                                    {LEGEND_POSITION_LABELS[position]}
                                                </ChoiceButton>
                                            ))}
                                        </div>
                                    </ControlSection>

                                    {barLike && (
                                        <ControlSection title="Bars">
                                            <SliderField
                                                id="chart-bar-width"
                                                label="Bar width"
                                                value={spec.options.barWidth}
                                                min={0.1}
                                                max={1}
                                                step={0.05}
                                                format={(value) => `${Math.round(value * 100)}%`}
                                                disabled={locked}
                                                onChange={(value) =>
                                                    setOption('barWidth', Number(value.toFixed(2)))
                                                }
                                            />
                                            <ToggleField
                                                label="Lay the bars on their side"
                                                hint="Useful when the category names are too long to read across the bottom."
                                                checked={spec.options.horizontal}
                                                disabled={locked}
                                                onChange={(value) => setOption('horizontal', value)}
                                            />
                                        </ControlSection>
                                    )}

                                    {(lineLike || spec.kind === 'radar' || pointBased) && (
                                        <ControlSection title="Lines and points">
                                            {(lineLike || spec.kind === 'radar') && (
                                                <>
                                                    <ToggleField
                                                        label="Curve the lines"
                                                        checked={spec.options.smooth}
                                                        disabled={locked || spec.kind === 'radar'}
                                                        onChange={(value) => setOption('smooth', value)}
                                                    />
                                                    <ToggleField
                                                        label="Fill under the lines"
                                                        checked={spec.options.fill}
                                                        disabled={locked}
                                                        onChange={(value) => setOption('fill', value)}
                                                    />
                                                </>
                                            )}
                                            <SliderField
                                                id="chart-line-width"
                                                label="Line thickness"
                                                value={spec.options.lineWidth}
                                                min={0}
                                                max={8}
                                                step={1}
                                                format={(value) => `${value} px`}
                                                disabled={locked}
                                                onChange={(value) => setOption('lineWidth', value)}
                                            />
                                            {spec.kind !== 'bubble' && (
                                                <SliderField
                                                    id="chart-point-radius"
                                                    label="Point size"
                                                    value={spec.options.pointRadius}
                                                    min={0}
                                                    max={12}
                                                    step={1}
                                                    format={(value) =>
                                                        value === 0 ? 'Hidden' : `${value} px`
                                                    }
                                                    disabled={locked}
                                                    onChange={(value) => setOption('pointRadius', value)}
                                                />
                                            )}
                                        </ControlSection>
                                    )}

                                    {spec.kind === 'doughnut' && (
                                        <ControlSection title="Hole">
                                            <SliderField
                                                id="chart-cutout"
                                                label="Hole size"
                                                value={readPercentage(spec.options.cutout, 60)}
                                                min={0}
                                                max={90}
                                                step={5}
                                                format={(value) => `${value}%`}
                                                disabled={locked}
                                                onChange={(value) => setOption('cutout', `${value}%`)}
                                            />
                                        </ControlSection>
                                    )}

                                    {cartesian && (
                                        <ControlSection title="Gridlines">
                                            <ToggleField
                                                label="Vertical gridlines"
                                                checked={spec.options.showGridX}
                                                disabled={locked}
                                                onChange={(value) => setOption('showGridX', value)}
                                            />
                                            <ToggleField
                                                label="Horizontal gridlines"
                                                checked={spec.options.showGridY}
                                                disabled={locked}
                                                onChange={(value) => setOption('showGridY', value)}
                                            />
                                            {!pointBased && (
                                                <ToggleField
                                                    label="Stack the series on top of each other"
                                                    checked={spec.options.stacked}
                                                    disabled={locked}
                                                    onChange={(value) => setOption('stacked', value)}
                                                />
                                            )}
                                        </ControlSection>
                                    )}

                                    <ControlSection title="Data table">
                                        <ToggleField
                                            label="Offer the numbers under the chart"
                                            hint="The table stays collapsed until a reader opens it."
                                            checked={spec.options.showDataTable}
                                            disabled={locked}
                                            onChange={(value) => setOption('showDataTable', value)}
                                        />
                                    </ControlSection>
                                </div>
                            )}

                            {tab === 'axes' && spec && (
                                <div className="flex flex-col gap-5">
                                    {!cartesian && spec.kind !== 'radar' ? (
                                        <p className="text-xs leading-relaxed text-text-3">
                                            A {CHART_KIND_LABELS[spec.kind]?.toLowerCase() ?? 'chart'}{' '}
                                            chart has no axes to scale or name. Its slices are read
                                            against each other rather than against a scale.
                                        </p>
                                    ) : (
                                        <>
                                            {cartesian && (
                                                <ControlSection title="Axis names">
                                                    <TextField
                                                        id="chart-x-label"
                                                        label="Category axis"
                                                        value={spec.options.xAxisLabel}
                                                        placeholder="e.g. Month"
                                                        maxLength={80}
                                                        disabled={locked}
                                                        onChange={(value) =>
                                                            setOption('xAxisLabel', value.trim() || null)
                                                        }
                                                    />
                                                    <TextField
                                                        id="chart-y-label"
                                                        label="Value axis"
                                                        value={spec.options.yAxisLabel}
                                                        placeholder="e.g. Revenue (£)"
                                                        maxLength={80}
                                                        disabled={locked}
                                                        onChange={(value) =>
                                                            setOption('yAxisLabel', value.trim() || null)
                                                        }
                                                    />
                                                </ControlSection>
                                            )}

                                            <ControlSection
                                                title="Value axis"
                                                hint={
                                                    spec.options.horizontal
                                                        ? 'This chart lays its bars on their side, so the value axis runs along the bottom.'
                                                        : undefined
                                                }
                                            >
                                                <div className="flex gap-2">
                                                    <NumberField
                                                        id="chart-y-min"
                                                        label="Minimum"
                                                        value={spec.options.yMin}
                                                        disabled={locked}
                                                        onChange={(value) => setOption('yMin', value)}
                                                    />
                                                    <NumberField
                                                        id="chart-y-max"
                                                        label="Maximum"
                                                        value={spec.options.yMax}
                                                        disabled={locked}
                                                        onChange={(value) => setOption('yMax', value)}
                                                    />
                                                </div>
                                                <ToggleField
                                                    label="Start the axis at zero"
                                                    hint={
                                                        spec.options.yScale === 'logarithmic'
                                                            ? 'A logarithmic axis cannot show zero, so this is ignored while that is chosen.'
                                                            : 'Turning this off zooms in on the differences, which can also exaggerate them.'
                                                    }
                                                    checked={spec.options.beginAtZero}
                                                    disabled={
                                                        locked || spec.options.yScale === 'logarithmic'
                                                    }
                                                    onChange={(value) => setOption('beginAtZero', value)}
                                                />
                                                {cartesian && (
                                                    <div className="flex flex-wrap gap-1.5">
                                                        <ChoiceButton
                                                            active={spec.options.yScale === 'linear'}
                                                            disabled={locked}
                                                            onClick={() => setOption('yScale', 'linear')}
                                                        >
                                                            Even steps
                                                        </ChoiceButton>
                                                        <ChoiceButton
                                                            active={spec.options.yScale === 'logarithmic'}
                                                            disabled={locked}
                                                            onClick={() =>
                                                                setOption('yScale', 'logarithmic')
                                                            }
                                                        >
                                                            Logarithmic
                                                        </ChoiceButton>
                                                    </div>
                                                )}
                                            </ControlSection>

                                            {cartesian && !pointBased && (
                                                <ControlSection
                                                    title="Category labels"
                                                    hint="For an axis with more names on it than will fit side by side."
                                                >
                                                    <SliderField
                                                        id="chart-tick-rotation"
                                                        label="Angle"
                                                        value={spec.options.xTickRotation}
                                                        min={0}
                                                        max={90}
                                                        step={15}
                                                        format={(value) =>
                                                            value === 0 ? 'Straight' : `${value}°`
                                                        }
                                                        disabled={locked}
                                                        onChange={(value) =>
                                                            setOption('xTickRotation', value)
                                                        }
                                                    />
                                                    <NumberField
                                                        id="chart-tick-limit"
                                                        label="Most labels to show"
                                                        value={spec.options.xTickLimit}
                                                        disabled={locked}
                                                        onChange={(value) =>
                                                            setOption(
                                                                'xTickLimit',
                                                                value === null
                                                                    ? null
                                                                    : Math.round(value),
                                                            )
                                                        }
                                                    />
                                                </ControlSection>
                                            )}
                                        </>
                                    )}
                                </div>
                            )}

                            {tab === 'source' && (
                                <div className="flex h-full flex-col gap-2">
                                    <div className="flex items-center justify-between gap-2">
                                        <label
                                            htmlFor="chart-source"
                                            className="text-xs font-medium text-text-2"
                                        >
                                            Chart data
                                        </label>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setDraft(formatChartSource(draft));
                                                setTypedInSource(true);
                                            }}
                                            className="rounded px-1.5 py-0.5 text-[11px] text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                                        >
                                            Lay it out
                                        </button>
                                    </div>
                                    <textarea
                                        id="chart-source"
                                        value={draft}
                                        spellCheck={false}
                                        onChange={(event) => {
                                            setDraft(event.target.value);
                                            setTypedInSource(true);
                                        }}
                                        className="min-h-0 flex-1 resize-none rounded-lg border border-edge-strong bg-surface-sunken p-2 font-mono text-xs text-text-1 outline-none focus:border-accent"
                                    />
                                    <p className="text-[11px] leading-relaxed text-text-3">
                                        The chart action writes this as one long line. "Lay it out"
                                        spreads it over several so it can be read.
                                    </p>
                                </div>
                            )}

                            {tab === 'ask' && (
                                <div className="flex h-full flex-col gap-2">
                                    {chat.length === 0 ? (
                                        <p className="text-xs leading-relaxed text-text-3">
                                            Describe a change and it is applied to this chart alone.
                                            Nothing here is added to the conversation, and only the
                                            version you keep is used as context later.
                                        </p>
                                    ) : (
                                        <ul className="flex min-h-0 flex-1 list-none flex-col gap-2 overflow-auto">
                                            {chat.map((turn, index) => (
                                                <li
                                                    key={`${turn.timestamp ?? ''}-${index}`}
                                                    className={
                                                        turn.role === 'user'
                                                            ? 'self-end rounded-lg bg-accent/10 px-2.5 py-1.5 text-xs text-text-1'
                                                            : 'self-start rounded-lg bg-surface-sunken px-2.5 py-1.5 font-mono text-[11px] text-text-2'
                                                    }
                                                >
                                                    {turn.role === 'assistant'
                                                        ? 'Updated the chart.'
                                                        : turn.content}
                                                </li>
                                            ))}
                                        </ul>
                                    )}

                                    <div className="mt-auto flex flex-col gap-2">
                                        <label htmlFor="chart-instruction" className="sr-only">
                                            Describe the change you want
                                        </label>
                                        <textarea
                                            id="chart-instruction"
                                            value={instruction}
                                            rows={3}
                                            maxLength={MAX_INSTRUCTION_LENGTH}
                                            placeholder="Drop the 2019 column and show the rest as a stacked bar"
                                            onChange={(event) => setInstruction(event.target.value)}
                                            onKeyDown={(event) => {
                                                if (event.key === 'Enter' && !event.shiftKey) {
                                                    event.preventDefault();
                                                    void submitInstruction();
                                                }
                                            }}
                                            className="resize-none rounded-lg border border-edge-strong bg-surface-sunken p-2 text-xs text-text-1 outline-none focus:border-accent"
                                        />
                                        <button
                                            type="button"
                                            disabled={!instruction.trim() || busy || !canPersist}
                                            onClick={() => void submitInstruction()}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            <Send size={13} />
                                            {busy ? 'Updating…' : 'Update chart'}
                                        </button>
                                        {dirty && (
                                            <p className="text-[11px] text-text-3">
                                                Unsaved changes are not sent. Save them first if the
                                                model should build on them.
                                            </p>
                                        )}
                                    </div>
                                </div>
                            )}

                            {tab === 'history' && (
                                <ul className="flex list-none flex-col gap-1.5">
                                    {revisions.length === 0 && (
                                        <li className="text-xs text-text-3">
                                            This chart has not been edited yet.
                                        </li>
                                    )}
                                    {revisions
                                        .map((revision, index) => ({ revision, index }))
                                        .reverse()
                                        .map(({ revision, index }) => (
                                            <li
                                                key={revision.id}
                                                className={`rounded-lg border p-2 ${
                                                    index === currentIndex
                                                        ? 'border-accent bg-accent/5'
                                                        : 'border-edge-strong'
                                                }`}
                                            >
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-medium text-text-1">
                                                        {ORIGIN_LABELS[revision.origin] ?? 'Edited'}
                                                    </span>
                                                    {index === currentIndex && (
                                                        <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                                                            Showing
                                                        </span>
                                                    )}
                                                    {index !== currentIndex && (
                                                        <button
                                                            type="button"
                                                            disabled={busy || !canPersist}
                                                            onClick={() => void onRestore(revision.id)}
                                                            className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                                                        >
                                                            <RotateCcw size={11} />
                                                            Restore
                                                        </button>
                                                    )}
                                                </div>
                                                {revision.note && (
                                                    <p className="mt-1 text-[11px] text-text-2">
                                                        {revision.note}
                                                    </p>
                                                )}
                                                <p className="mt-1 text-[11px] text-text-3">
                                                    {[
                                                        revision.author_name,
                                                        formatTimestamp(revision.timestamp),
                                                    ]
                                                        .filter(Boolean)
                                                        .join(' · ')}
                                                </p>
                                            </li>
                                        ))}
                                </ul>
                            )}
                        </div>

                        {/* One save for the whole panel, so a chart adjusted in six places
                            produces one entry in the history rather than six. */}
                        {tab !== 'ask' && tab !== 'history' && (
                            <div className="flex shrink-0 flex-col gap-1.5 border-t border-edge px-3 py-2">
                                {problem && <p className="text-xs text-danger">{problem}</p>}
                                {!problem && dirty && note && (
                                    <p className="truncate text-[11px] text-text-3" title={note}>
                                        Unsaved: {note}
                                    </p>
                                )}
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        disabled={!dirty || Boolean(problem) || busy || !canPersist}
                                        onClick={() => void save()}
                                        className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        Save version
                                    </button>
                                    <button
                                        type="button"
                                        disabled={!dirty || busy}
                                        onClick={discard}
                                        className="rounded-lg px-3 py-1.5 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        Discard changes
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </GlassPanel>
        </div>
    );
}
