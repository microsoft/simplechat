// InlineChart.tsx
// Renders ```simplechart fences in assistant messages as charts.
//
// The payload comes from the built-in chart action (functions_chart_operations.py) and is
// drawn with Chart.js, matching what the classic interface shows for the same message.
//
// Chart.js is loaded from the vendored copy on first use rather than bundled: most
// conversations contain no chart, and there is no reason to make every user pay for it.
//
// Series colours and the canvas background can be changed per chart; see blockVisualStyle.ts
// for where a change is stored. Unlike the classic client's colour editor, nothing here
// rewrites the message markdown — the payload the model produced stays as it was written.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, Download, Table2, TriangleAlert } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import {
    buildChartConfig,
    chartColorTargets,
    parseInlineChart,
    resolveChartTable,
    type ChartSpec,
} from '../../lib/inlineChartSpec';
import type { ChartJsConstructor, ChartJsInstance } from '../../lib/vendor';
import { VENDOR_PATHS, loadVendorScript } from '../../lib/vendorAssets';
import { useBlockVisualStyle } from '../../lib/blockVisualStyle';
import {
    THEME_BACKGROUND,
    resolveBackgroundColor,
    visualStyleSignature,
} from '../../lib/visualPalettes';
import { fileNameStem } from '../../lib/svgRaster';
import { VisualStyleMenu } from './VisualStyleMenu';

let chartRuntime: ChartJsConstructor | null = null;
let chartRuntimeLoad: Promise<ChartJsConstructor> | null = null;

/** Load Chart.js once per session. The UMD build self-registers every controller and scale. */
function loadChartRuntime(): Promise<ChartJsConstructor> {
    if (chartRuntime) {
        return Promise.resolve(chartRuntime);
    }
    if (!chartRuntimeLoad) {
        chartRuntimeLoad = loadVendorScript(VENDOR_PATHS.chartJs)
            .then(() => {
                if (!window.Chart) {
                    throw new Error('Chart.js did not register a global after loading');
                }
                chartRuntime = window.Chart;
                return chartRuntime;
            })
            .catch((error) => {
                chartRuntimeLoad = null;
                throw error;
            });
    }
    return chartRuntimeLoad;
}

/**
 * Chart colours taken from the live theme.
 *
 * Read from the custom properties rather than hard-coded, so a chart follows the light/dark
 * switch without a second definition of the palette drifting out of step with `theme.css`.
 */
function readThemeColors(): { text: string; grid: string; surface: string } {
    const fallback = { text: '#475569', grid: 'rgba(15, 23, 42, 0.10)', surface: '#ffffff' };
    if (typeof window === 'undefined') {
        return fallback;
    }

    const styles = window.getComputedStyle(document.documentElement);
    const read = (name: string, backup: string) => styles.getPropertyValue(name).trim() || backup;

    return {
        text: read('--text-2', fallback.text),
        grid: read('--edge-strong', fallback.grid),
        surface: read('--surface-solid', fallback.surface),
    };
}

/** A file name for the downloaded image, derived from the chart's own title. */
function downloadName(spec: ChartSpec): string {
    return `${fileNameStem(spec.title, 'chart')}.png`;
}

function ChartToolbar({
    spec,
    tableOpen,
    onToggleTable,
    onDownload,
    tableId,
    hasTable,
    children,
}: {
    spec: ChartSpec;
    tableOpen: boolean;
    onToggleTable: () => void;
    onDownload: () => void;
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
 * `messageId` and `blockIndex` are what a saved colour choice is filed under. A chart in a
 * reply that is still streaming has neither, so it draws with the reader's default and its
 * colour control says the choice will be kept once the reply finishes.
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
    const theme = useUiStore((state) => state.theme);
    const spec = useMemo(() => parseInlineChart(source), [source]);
    const table = useMemo(() => (spec ? resolveChartTable(spec) : null), [spec]);

    const canvasRef = useRef<HTMLCanvasElement>(null);
    const instanceRef = useRef<ChartJsInstance | null>(null);
    const [tableOpen, setTableOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [failed, setFailed] = useState(false);
    const tableId = useMemo(
        () => `chart-data-${Math.random().toString(36).slice(2, 9)}`,
        [],
    );

    const { style, setStyle, reset, canPersist, error } = useBlockVisualStyle(
        'simplechart',
        source,
        messageId,
        blockIndex,
    );

    /**
     * The colour to paint behind the chart, or null to leave the canvas transparent.
     *
     * Null while the background is left on "match theme", because the canvas has always been
     * transparent over the surrounding panel and filling it would visibly change every chart
     * nobody has touched.
     */
    const background = useMemo(
        () => (style.background === THEME_BACKGROUND ? null : resolveBackgroundColor(style)),
        [style],
    );
    const signature = useMemo(
        () => visualStyleSignature(style, background ?? THEME_BACKGROUND),
        [style, background],
    );
    const targets = useMemo(
        () => (spec ? chartColorTargets(spec, style) : []),
        [spec, style],
    );

    useEffect(() => {
        if (!spec) {
            return;
        }

        let cancelled = false;

        loadChartRuntime()
            .then((Chart) => {
                if (cancelled || !canvasRef.current) {
                    return;
                }
                instanceRef.current?.destroy();
                instanceRef.current = new Chart(
                    canvasRef.current,
                    buildChartConfig(spec, readThemeColors(), style, background),
                );
            })
            .catch(() => {
                if (!cancelled) {
                    setFailed(true);
                }
            });

        return () => {
            cancelled = true;
            instanceRef.current?.destroy();
            instanceRef.current = null;
        };
        // `theme` is a dependency because the axis, tick and legend colours are baked into
        // the configuration when the chart is built, and `signature` because the series and
        // background colours are too.
    }, [spec, theme, style, background, signature]);

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
                    <code className="font-mono text-[13px]">{source.trim()}</code>
                </pre>
            </div>
        );
    }

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
                {failed ? (
                    <div className="flex h-full items-center justify-center text-xs text-text-3">
                        Chart could not be displayed
                    </div>
                ) : (
                    <canvas ref={canvasRef} role="img" aria-label={spec.title || 'Chart'} />
                )}
            </div>

            {spec.description && (
                <p className="px-3 pt-3 text-xs text-text-2">{spec.description}</p>
            )}

            <ChartToolbar
                spec={spec}
                tableOpen={tableOpen}
                onToggleTable={() => setTableOpen((open) => !open)}
                onDownload={downloadPng}
                tableId={tableId}
                hasTable={Boolean(table)}
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

            {table && (
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
    );
}
