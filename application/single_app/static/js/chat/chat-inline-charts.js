// chat-inline-charts.js

const INLINE_CHART_LANGUAGE = 'simplechart';
const INLINE_CHART_REGEX = new RegExp(`\`\`\`${INLINE_CHART_LANGUAGE}\\s*([\\s\\S]*?)\`\`\``, 'gi');
const ALLOWED_KINDS = new Set(['line', 'bar', 'pie', 'doughnut', 'scatter', 'area', 'bubble', 'radar', 'stacked_bar', 'stacked_line', 'polar_area']);
const DEFAULT_PALETTE = [
    { background: 'rgba(28, 110, 164, 0.18)', border: '#1c6ea4' },
    { background: 'rgba(215, 91, 53, 0.18)', border: '#d75b35' },
    { background: 'rgba(39, 123, 84, 0.18)', border: '#277b54' },
    { background: 'rgba(153, 92, 32, 0.18)', border: '#995c20' },
    { background: 'rgba(126, 77, 140, 0.18)', border: '#7e4d8c' },
    { background: 'rgba(191, 66, 112, 0.18)', border: '#bf4270' },
    { background: 'rgba(58, 141, 121, 0.18)', border: '#3a8d79' },
    { background: 'rgba(101, 120, 48, 0.18)', border: '#657830' }
];

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]
    ));
}

function getPalette(index) {
    return DEFAULT_PALETTE[index % DEFAULT_PALETTE.length];
}

function sanitizeText(value, maxLength = 240) {
    return String(value ?? '').trim().slice(0, maxLength);
}

function sanitizeNumber(value) {
    if (value === null || value === undefined || value === '') {
        return null;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function sanitizeColor(value, fallback) {
    if (typeof value !== 'string') {
        return fallback;
    }

    const trimmed = value.trim();
    if (!trimmed || trimmed.length > 40) {
        return fallback;
    }

    if (trimmed.startsWith('#') || trimmed.startsWith('rgb(') || trimmed.startsWith('rgba(') || trimmed.startsWith('hsl(') || trimmed.startsWith('hsla(')) {
        return trimmed;
    }

    return fallback;
}

function getBaseChartType(kind) {
    if (kind === 'area' || kind === 'stacked_line') {
        return 'line';
    }
    if (kind === 'stacked_bar') {
        return 'bar';
    }
    if (kind === 'polar_area') {
        return 'polarArea';
    }
    return kind;
}

function normalizePoint(point, kind) {
    if (!point || typeof point !== 'object') {
        return null;
    }

    const normalized = {
        x: sanitizeNumber(point.x),
        y: sanitizeNumber(point.y)
    };

    if (normalized.x === null || normalized.y === null) {
        return null;
    }

    if (kind === 'bubble') {
        normalized.r = sanitizeNumber(point.r);
        if (normalized.r === null) {
            return null;
        }
    }

    return normalized;
}

function normalizeDatasets(kind, rawDatasets, labels) {
    if (!Array.isArray(rawDatasets) || rawDatasets.length === 0) {
        return [];
    }

    return rawDatasets.slice(0, 20).map((dataset, datasetIndex) => {
        const palette = getPalette(datasetIndex);
        const normalized = {
            label: sanitizeText(dataset?.label || `Series ${datasetIndex + 1}`, 80),
            borderColor: sanitizeColor(dataset?.borderColor, palette.border),
            backgroundColor: sanitizeColor(dataset?.backgroundColor, palette.background),
            borderWidth: 2
        };

        if (kind === 'scatter' || kind === 'bubble') {
            normalized.data = Array.isArray(dataset?.data)
                ? dataset.data.map(point => normalizePoint(point, kind)).filter(Boolean)
                : [];
        } else {
            normalized.data = Array.isArray(dataset?.data)
                ? dataset.data.slice(0, 200).map(value => sanitizeNumber(value))
                : [];
        }

        if (kind === 'line' || kind === 'area' || kind === 'stacked_line') {
            normalized.fill = dataset?.fill === true || kind === 'area';
            normalized.tension = dataset?.tension === 0 ? 0 : 0.35;
        }

        if (kind === 'radar') {
            normalized.fill = dataset?.fill === true;
        }

        if ((kind === 'pie' || kind === 'doughnut' || kind === 'polar_area') && Array.isArray(labels) && labels.length) {
            normalized.backgroundColor = labels.map((_, colorIndex) => getPalette(colorIndex).background);
            normalized.borderColor = labels.map((_, colorIndex) => getPalette(colorIndex).border);
        }

        if (dataset?.type === 'line' || dataset?.type === 'bar') {
            normalized.type = dataset.type;
        }

        return normalized;
    }).filter(dataset => Array.isArray(dataset.data) && dataset.data.length > 0);
}

function normalizeTable(rawTable) {
    if (!rawTable || typeof rawTable !== 'object') {
        return null;
    }

    const columns = Array.isArray(rawTable.columns)
        ? rawTable.columns.slice(0, 12).map(column => sanitizeText(column, 80)).filter(Boolean)
        : [];
    const rows = Array.isArray(rawTable.rows)
        ? rawTable.rows.slice(0, 500).map(row => Array.isArray(row) ? row.slice(0, columns.length || 12) : []).filter(row => row.length > 0)
        : [];

    if (!columns.length || !rows.length) {
        return null;
    }

    return { columns, rows };
}

function normalizeChartSpec(rawSpec) {
    if (!rawSpec || typeof rawSpec !== 'object' || Array.isArray(rawSpec)) {
        return null;
    }

    const kind = sanitizeText(rawSpec.kind || rawSpec.chartType, 40).toLowerCase();
    if (!ALLOWED_KINDS.has(kind)) {
        return null;
    }

    const rawData = rawSpec.data;
    if (!rawData || typeof rawData !== 'object' || Array.isArray(rawData)) {
        return null;
    }

    const labels = Array.isArray(rawData.labels)
        ? rawData.labels.slice(0, 200).map(label => sanitizeText(label, 80))
        : [];
    const datasets = normalizeDatasets(kind, rawData.datasets, labels);
    if (!datasets.length) {
        return null;
    }

    const rawOptions = rawSpec.options && typeof rawSpec.options === 'object' && !Array.isArray(rawSpec.options)
        ? rawSpec.options
        : {};

    const legendPosition = sanitizeText(rawOptions.legendPosition || 'top', 10).toLowerCase();
    const normalizedOptions = {
        legendPosition: ['top', 'bottom', 'left', 'right'].includes(legendPosition) ? legendPosition : 'top',
        showLegend: rawOptions.showLegend !== false,
        showDataTable: rawOptions.showDataTable !== false,
        beginAtZero: rawOptions.beginAtZero !== false,
        horizontal: Boolean(rawOptions.horizontal) && (kind === 'bar' || kind === 'stacked_bar'),
        fill: Boolean(rawOptions.fill) || kind === 'area',
        smooth: rawOptions.smooth !== false,
        stacked: Boolean(rawOptions.stacked) || kind === 'stacked_bar' || kind === 'stacked_line',
        xAxisLabel: sanitizeText(rawOptions.xAxisLabel, 80),
        yAxisLabel: sanitizeText(rawOptions.yAxisLabel, 80),
        cutout: sanitizeText(rawOptions.cutout || '60%', 20)
    };

    return {
        version: Number(rawSpec.version) || 1,
        chartId: sanitizeText(rawSpec.chartId || '', 40),
        kind,
        chartType: getBaseChartType(kind),
        title: sanitizeText(rawSpec.title, 160),
        subtitle: sanitizeText(rawSpec.subtitle, 160),
        description: sanitizeText(rawSpec.description, 320),
        summary: sanitizeText(rawSpec.summary, 220),
        data: {
            labels,
            datasets
        },
        options: normalizedOptions,
        table: normalizeTable(rawSpec.table)
    };
}

function buildTableHtml(spec) {
    if (!spec.table || spec.options.showDataTable === false) {
        return '';
    }

    const tableId = `chart-table-${spec.chartId || Math.random().toString(36).slice(2, 10)}`;
    const headHtml = spec.table.columns.map(column => `<th scope="col">${escapeHtml(column)}</th>`).join('');
    const bodyHtml = spec.table.rows.map(row => `
        <tr>${row.map(cell => `<td>${escapeHtml(cell ?? '')}</td>`).join('')}</tr>
    `).join('');

    return `
        <div class="mt-3">
            <button type="button" class="btn btn-sm btn-outline-secondary sc-inline-chart-table-toggle" data-target-id="${escapeHtml(tableId)}" aria-expanded="false">
                Show data table
            </button>
            <div class="table-responsive mt-2 d-none" id="${escapeHtml(tableId)}">
                <table class="table table-sm table-striped align-middle mb-0">
                    <thead><tr>${headHtml}</tr></thead>
                    <tbody>${bodyHtml}</tbody>
                </table>
            </div>
        </div>
    `;
}

function buildPlaceholderHtml(block, index) {
    const encodedSpec = encodeURIComponent(JSON.stringify(block.spec));
    const captionParts = [block.spec.description, block.spec.summary].filter(Boolean);
    const captionHtml = captionParts.length
        ? `<div class="small text-muted mt-2">${escapeHtml(captionParts.join(' '))}</div>`
        : '';

    return `
        <section class="sc-inline-chart card border-0 shadow-sm my-3" data-chart-hydrated="false" data-chart-spec="${encodedSpec}" aria-label="Inline chart ${index + 1}">
            <div class="card-body p-3">
                <div class="d-flex flex-column gap-1 mb-2">
                    ${block.spec.title ? `<div class="fw-semibold">${escapeHtml(block.spec.title)}</div>` : ''}
                    ${block.spec.subtitle ? `<div class="small text-muted">${escapeHtml(block.spec.subtitle)}</div>` : ''}
                </div>
                <div class="sc-inline-chart-stage position-relative">
                    <canvas role="img" aria-label="${escapeHtml(block.spec.title || block.spec.kind)}"></canvas>
                </div>
                ${captionHtml}
                ${buildTableHtml(block.spec)}
            </div>
        </section>
    `;
}

function replaceAllOccurrences(source, target, replacement) {
    return source.split(target).join(replacement);
}

function buildChartJsConfig(spec) {
    const baseType = getBaseChartType(spec.kind);
    const config = {
        type: baseType,
        data: {
            datasets: spec.data.datasets.map(dataset => ({ ...dataset }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'nearest',
                intersect: false
            },
            plugins: {
                legend: {
                    display: spec.options.showLegend,
                    position: spec.options.legendPosition
                },
                title: {
                    display: Boolean(spec.title),
                    text: spec.title
                },
                subtitle: {
                    display: Boolean(spec.subtitle),
                    text: spec.subtitle
                }
            }
        }
    };

    if (spec.data.labels.length) {
        config.data.labels = [...spec.data.labels];
    }

    if (['bar', 'line', 'scatter', 'bubble'].includes(baseType)) {
        config.options.scales = {
            x: {
                stacked: spec.options.stacked,
                title: {
                    display: Boolean(spec.options.xAxisLabel),
                    text: spec.options.xAxisLabel
                }
            },
            y: {
                stacked: spec.options.stacked,
                beginAtZero: spec.options.beginAtZero,
                title: {
                    display: Boolean(spec.options.yAxisLabel),
                    text: spec.options.yAxisLabel
                }
            }
        };

        if (spec.options.horizontal && baseType === 'bar') {
            config.options.indexAxis = 'y';
        }
    }

    if (baseType === 'doughnut') {
        config.options.cutout = spec.options.cutout || '60%';
    }

    if (baseType === 'radar') {
        config.options.scales = {
            r: {
                beginAtZero: spec.options.beginAtZero
            }
        };
    }

    return config;
}

export function extractInlineChartBlocks(markdownText = '') {
    const blocks = [];
    const markdown = String(markdownText ?? '').replace(INLINE_CHART_REGEX, (match, payload) => {
        try {
            const parsed = JSON.parse(String(payload || '').trim());
            const spec = normalizeChartSpec(parsed);
            if (!spec) {
                return match;
            }

            const token = `SIMPLECHAT_INLINE_CHART_TOKEN_${blocks.length}__`;
            blocks.push({ token, spec, originalBlock: match });
            return `\n\n${token}\n\n`;
        } catch (error) {
            console.warn('Failed to parse inline chart block:', error);
            return match;
        }
    });

    return { markdown, blocks };
}

export function restoreInlineChartTokens(markdownText = '', blocks = []) {
    let restored = String(markdownText ?? '');
    blocks.forEach(block => {
        restored = replaceAllOccurrences(restored, block.token, block.originalBlock || '');
    });
    return restored;
}

export function injectInlineChartHtml(html = '', blocks = []) {
    let renderedHtml = String(html ?? '');

    blocks.forEach((block, index) => {
        const placeholderHtml = buildPlaceholderHtml(block, index);
        renderedHtml = replaceAllOccurrences(renderedHtml, `<p>${block.token}</p>`, placeholderHtml);
        renderedHtml = replaceAllOccurrences(renderedHtml, block.token, placeholderHtml);
    });

    return renderedHtml;
}

export function hydrateInlineCharts(root = document) {
    const chartContainers = root.querySelectorAll('.sc-inline-chart[data-chart-hydrated="false"]');
    chartContainers.forEach(container => {
        const specText = container.getAttribute('data-chart-spec');
        const stage = container.querySelector('.sc-inline-chart-stage');
        const canvas = container.querySelector('canvas');
        if (!specText || !stage || !canvas) {
            return;
        }

        stage.style.height = '320px';

        if (typeof window.Chart === 'undefined') {
            stage.innerHTML = '<div class="alert alert-warning mb-0">Chart library is unavailable for this message.</div>';
            container.setAttribute('data-chart-hydrated', 'true');
            return;
        }

        try {
            const spec = normalizeChartSpec(JSON.parse(decodeURIComponent(specText)));
            if (!spec) {
                throw new Error('Invalid inline chart specification.');
            }

            const chartConfig = buildChartJsConfig(spec);
            if (container._chartInstance) {
                container._chartInstance.destroy();
            }
            container._chartInstance = new window.Chart(canvas.getContext('2d'), chartConfig);
            container.setAttribute('data-chart-hydrated', 'true');

            const toggleButton = container.querySelector('.sc-inline-chart-table-toggle');
            if (toggleButton && !toggleButton.dataset.bound) {
                toggleButton.dataset.bound = 'true';
                toggleButton.addEventListener('click', () => {
                    const targetId = toggleButton.getAttribute('data-target-id');
                    const target = targetId ? container.querySelector(`#${targetId}`) : null;
                    if (!target) {
                        return;
                    }
                    const isHidden = target.classList.contains('d-none');
                    target.classList.toggle('d-none', !isHidden);
                    toggleButton.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
                    toggleButton.textContent = isHidden ? 'Hide data table' : 'Show data table';
                });
            }
        } catch (error) {
            console.warn('Failed to hydrate inline chart:', error);
            stage.innerHTML = `<div class="alert alert-warning mb-0">Unable to render chart: ${escapeHtml(error.message || 'invalid data')}</div>`;
            container.setAttribute('data-chart-hydrated', 'true');
        }
    });
}