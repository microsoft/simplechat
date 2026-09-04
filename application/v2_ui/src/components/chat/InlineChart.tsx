// InlineChart.tsx
// Renders ```simplechart fences in assistant messages as charts.
//
// The payload comes from the built-in chart action (functions_chart_operations.py) and is
// drawn with Chart.js, matching what the classic interface shows for the same message.
//
// The drawing itself lives in ChartCanvas so the editor's preview and the chart in the reply
// cannot diverge; Chart.js is loaded from the vendored copy on first use rather than bundled,
// since most conversations contain no chart at all.
//
// A chart can be changed in two independent ways, and it is worth keeping them apart. Series
// colours and the canvas background are a *reader's* preference, stored per person, and never
// touch the payload — see blockVisualStyle.ts. Everything else, from the chart type to the
// numbers, is an *edit*: stored as a revision of the block and seen by everyone — see
// blockRevisions.ts and ChartEditor.tsx. Neither rewrites the message the model produced.

import { useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, Download, PenLine, Table2, TriangleAlert } from 'lucide-react';
import {
    chartColorTargets,
    parseInlineChart,
    resolveChartTable,
    type ChartSpec,
} from '../../lib/inlineChartSpec';
import { readThemeColors } from '../../lib/chartRuntime';
import { useBlockRevisions } from '../../lib/blockRevisions';
import { useBlockVisualStyle } from '../../lib/blockVisualStyle';
import { fileNameStem } from '../../lib/svgRaster';
import { ChartCanvas, resolveChartBackground } from './ChartCanvas';
import { ChartEditor } from './ChartEditor';
import { VisualStyleMenu } from './VisualStyleMenu';

/** A file name for the downloaded image, derived from the chart's own title. */
function downloadName(spec: ChartSpec): string {
    return `${fileNameStem(spec.title, 'chart')}.png`;
}

function ChartToolbar({
    spec,
    tableOpen,
    onToggleTable,
    onDownload,
    onEdit,
    edited,
    tableId,
    hasTable,
    children,
}: {
    spec: ChartSpec;
    tableOpen: boolean;
    onToggleTable: () => void;
    onDownload: () => void;
    onEdit: () => void;
    /** Whether the chart on screen is something other than what the model first produced. */
    edited: boolean;
    tableId: string;
    hasTable: boolean;
    children?: React.ReactNode;
}) {
    return (
        <div className="flex flex-wrap items-center justify-end gap-1 px-3 pb-2">
            {hasTable && (
                <button
                    type="button"
                    onClick={onToggleTable}
                    aria-expanded={tableOpen}
                    aria-controls={tableId}
                    className={clsx(
                        'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors',
                        tableOpen
                            ? 'bg-accent-soft text-accent'
                            : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                    )}
                >
                    <Table2 size={13} />
                    Data
                    <ChevronDown
                        size={12}
                        className={clsx('transition-transform', tableOpen && 'rotate-180')}
                    />
                </button>
            )}
            <button
                type="button"
                onClick={onEdit}
                title="Edit this chart"
                aria-haspopup="dialog"
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
            >
                <PenLine size={13} />
                Edit
                {edited && (
                    <span
                        title="This chart has been edited"
                        aria-label="Edited"
                        className="size-1.5 rounded-full bg-accent"
                    />
                )}
            </button>
            <button
                type="button"
                onClick={onDownload}
                title={`Download "${spec.title || 'chart'}" as PNG`}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
            >
                <Download size={13} />
                PNG
            </button>
            {children}
        </div>
    );
}

/**
 * A rendered chart, with its numbers available but out of the way.
 *
 * The data table is collapsed by default: the chart is the answer, and a 500-row table opened
 * automatically would bury the rest of the reply. It stays one click away because a chart
 * without its numbers cannot be checked.
 *
 * `messageId` and `blockIndex` are what an edit or a saved colour choice is filed under. A chart
 * in a reply that is still streaming has neither, so it draws with the reader's default and its
 * controls say the choice will be kept once the reply finishes.
 */
export function InlineChart({
    source,
    messageId,
    blockIndex,
}: {
    source: string;
    messageId?: string;
    blockIndex?: number;
}) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [tableOpen, setTableOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [editing, setEditing] = useState(false);
    const tableId = useMemo(
        () => `chart-data-${Math.random().toString(36).slice(2, 9)}`,
        [],
    );

    // Deliberately keyed off `source`, the block's original payload, not the version being
    // shown. Colours are filed under the original's fingerprint, so editing a chart keeps
    // whatever colours were chosen for it instead of silently resetting them.
    const { style, setStyle, reset, canPersist, error } = useBlockVisualStyle(
        'simplechart',
        source,
        messageId,
        blockIndex,
    );

    const revisions = useBlockRevisions('simplechart', source, messageId, blockIndex);
    /** The version to draw, download and edit from: the current revision, or the original. */
    const shownSource = revisions.source;

    const spec = useMemo(() => parseInlineChart(shownSource), [shownSource]);
    const table = useMemo(() => (spec ? resolveChartTable(spec) : null), [spec]);
    const background = useMemo(() => resolveChartBackground(style), [style]);
    const targets = useMemo(
        () => (spec ? chartColorTargets(spec, style) : []),
        [spec, style],
    );

    // Not a chart this client can draw: show the block as written rather than an error, so
    // the content is still there to read.
    if (!spec) {
        return (
            <div className="my-3 overflow-hidden rounded-xl border border-edge-strong">
                <div className="flex items-center gap-1.5 border-b border-edge-strong bg-surface-sunken px-3 py-1.5 text-xs text-text-3">
                    <TriangleAlert size={12} />
                    Chart data could not be read
                </div>
                <pre className="overflow-x-auto p-3">
                    <code className="font-mono text-[13px]">{shownSource.trim()}</code>
                </pre>
            </div>
        );
    }

    const showTable = Boolean(table) && spec.options.showDataTable;

    const downloadPng = () => {
        const canvas = canvasRef.current;
        if (!canvas) {
            return;
        }

        // The chart canvas is transparent unless a background was chosen, which produces an
        // unreadable PNG on a light background. Compositing onto an opaque colour first —
        // the chosen one, or the theme's own surface — gives an image that works wherever it
        // is pasted.
        const target = document.createElement('canvas');
        target.width = canvas.width;
        target.height = canvas.height;
        const context = target.getContext('2d');
        if (!context) {
            return;
        }
        context.fillStyle = background ?? readThemeColors().surface;
        context.fillRect(0, 0, target.width, target.height);
        context.drawImage(canvas, 0, 0);

        const link = document.createElement('a');
        link.href = target.toDataURL('image/png');
        link.download = downloadName(spec);
        link.click();
    };

    return (
        <>
            <figure className="my-3 overflow-hidden rounded-xl border border-edge-strong bg-surface-sunken">
                {(spec.title || spec.subtitle) && (
                    <figcaption className="px-3 pt-3">
                        {spec.title && (
                            <div className="text-sm font-semibold text-text-1">{spec.title}</div>
                        )}
                        {spec.subtitle && (
                            <div className="mt-0.5 text-xs text-text-2">{spec.subtitle}</div>
                        )}
                    </figcaption>
                )}

                <div className="h-72 px-3 pt-3">
                    <ChartCanvas
                        spec={spec}
                        style={style}
                        label={spec.title || 'Chart'}
                        canvasRef={canvasRef}
                    />
                </div>

                {spec.description && (
                    <p className="px-3 pt-3 text-xs text-text-2">{spec.description}</p>
                )}

                <ChartToolbar
                    spec={spec}
                    tableOpen={tableOpen}
                    onToggleTable={() => setTableOpen((open) => !open)}
                    onDownload={downloadPng}
                    onEdit={() => setEditing(true)}
                    edited={revisions.isEdited}
                    tableId={tableId}
                    hasTable={showTable}
                >
                    <VisualStyleMenu
                        style={style}
                        onChange={setStyle}
                        onReset={reset}
                        targets={targets}
                        open={menuOpen}
                        onToggle={() => setMenuOpen((open) => !open)}
                        canPersist={canPersist}
                        error={error}
                        noun="chart"
                    />
                </ChartToolbar>

                {table && showTable && (
                    <div id={tableId} hidden={!tableOpen} className="border-t border-edge-strong">
                        <div className="max-h-64 overflow-auto">
                            <table className="w-full border-collapse text-xs">
                                <thead>
                                    <tr>
                                        {table.columns.map((column) => (
                                            <th
                                                key={column}
                                                scope="col"
                                                // The surrounding prose styles set a translucent
                                                // background on every `th`, which a sticky header
                                                // would show the scrolling rows through. An inline
                                                // style is the one thing those class rules cannot
                                                // out-specify.
                                                style={{ background: 'var(--surface-solid)' }}
                                                className="sticky top-0 z-10 text-left font-medium text-text-2"
                                            >
                                                {column}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {table.rows.map((row, rowIndex) => (
                                        <tr key={rowIndex}>
                                            {table.columns.map((column, columnIndex) => (
                                                <td key={column} className="text-text-1">
                                                    {String(row[columnIndex] ?? '')}
                                                </td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <div className="px-3 py-1.5 text-[11px] text-text-3">
                            {table.rows.length} row{table.rows.length === 1 ? '' : 's'}
                        </div>
                    </div>
                )}
            </figure>

            {/* Outside the figure, which clips its overflow and would otherwise be an odd place
                to nest a dialog. */}
            {editing && (
                <ChartEditor
                    title={spec.title || 'Chart'}
                    currentSource={shownSource}
                    revisions={revisions.revisions}
                    currentIndex={revisions.currentIndex}
                    chat={revisions.chat}
                    canPersist={revisions.canPersist}
                    busy={revisions.busy}
                    error={revisions.error}
                    style={style}
                    onClearError={revisions.clearError}
                    onSave={revisions.save}
                    onRestore={revisions.restore}
                    onAsk={revisions.ask}
                    onClose={() => setEditing(false)}
                />
            )}
        </>
    );
}
