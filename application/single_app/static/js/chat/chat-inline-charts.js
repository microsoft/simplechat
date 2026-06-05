// chat-inline-charts.js

const INLINE_CHART_LANGUAGE = 'simplechart';
const INLINE_CHART_REGEX = new RegExp(`\`\`\`${INLINE_CHART_LANGUAGE}\\s*([\\s\\S]*?)\`\`\``, 'gi');
const INLINE_CHART_PENDING_REGEX = new RegExp(`\`\`\`${INLINE_CHART_LANGUAGE}\\b[\\s\\S]*$`, 'i');
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
const CHART_COLOR_PRESETS = Object.freeze([
    { name: 'Default', colors: ['#1c6ea4', '#d75b35', '#277b54', '#995c20', '#7e4d8c', '#bf4270', '#3a8d79', '#657830'] },
    { name: 'Calm', colors: ['#2563eb', '#0f766e', '#65a30d', '#0891b2', '#7c3aed', '#4b5563', '#ca8a04', '#be123c'] },
    { name: 'Vivid', colors: ['#dc2626', '#ea580c', '#ca8a04', '#16a34a', '#0891b2', '#2563eb', '#9333ea', '#db2777'] },
    { name: 'Warm', colors: ['#b91c1c', '#c2410c', '#ca8a04', '#a16207', '#92400e', '#be123c', '#9f1239', '#7f1d1d'] },
    { name: 'Contrast', colors: ['#111827', '#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#7c3aed', '#0891b2', '#db2777'] }
]);
const CHART_COLOR_BACKGROUND_ALPHA = 0.18;
const CHART_COLOR_MAX_EDIT_TARGETS = 12;
const NAMED_CHART_COLORS = Object.freeze({
    apple: '#c2410c',
    apples: '#c2410c',
    red: '#dc2626',
    orange: '#ea580c',
    oranges: '#ea580c',
    pear: '#16a34a',
    pears: '#16a34a',
    green: '#16a34a',
    blue: '#2563eb',
    purple: '#7c3aed',
    yellow: '#ca8a04',
    gold: '#ca8a04',
    brown: '#92400e',
    gray: '#64748b',
    grey: '#64748b',
    black: '#111827',
    white: '#f8fafc'
});

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]
    ));
}

function getPalette(index) {
    return DEFAULT_PALETTE[index % DEFAULT_PALETTE.length];
}

function expandShortHexColor(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (!/^#[0-9a-f]{3}$/.test(normalized)) {
        return normalized;
    }

    return `#${normalized[1]}${normalized[1]}${normalized[2]}${normalized[2]}${normalized[3]}${normalized[3]}`;
}

function rgbStringToHex(value) {
    const match = String(value || '').trim().match(/^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/i);
    if (!match) {
        return '';
    }

    const channels = match.slice(1, 4).map(channel => Math.max(0, Math.min(255, Number(channel) || 0)));
    return `#${channels.map(channel => channel.toString(16).padStart(2, '0')).join('')}`;
}

function normalizeHexColor(value, fallback = '#1c6ea4') {
    const namedColor = typeof value === 'string' ? NAMED_CHART_COLORS[value.trim().toLowerCase()] : '';
    const candidate = expandShortHexColor(namedColor || value || fallback);
    if (/^#[0-9a-f]{6}$/i.test(candidate)) {
        return candidate.toLowerCase();
    }

    const rgbHex = rgbStringToHex(candidate);
    if (rgbHex) {
        return rgbHex.toLowerCase();
    }

    const normalizedFallback = expandShortHexColor(fallback);
    return /^#[0-9a-f]{6}$/i.test(normalizedFallback) ? normalizedFallback.toLowerCase() : '#1c6ea4';
}

function hexToRgba(hexColor, alpha = CHART_COLOR_BACKGROUND_ALPHA) {
    const normalized = normalizeHexColor(hexColor);
    const red = parseInt(normalized.slice(1, 3), 16);
    const green = parseInt(normalized.slice(3, 5), 16);
    const blue = parseInt(normalized.slice(5, 7), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function resolveColorValue(value, fallbackHex) {
    if (Array.isArray(value)) {
        return normalizeHexColor(value[0], fallbackHex);
    }

    return normalizeHexColor(value, fallbackHex);
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

    const namedColor = NAMED_CHART_COLORS[trimmed.toLowerCase()];
    if (namedColor) {
        return namedColor;
    }

    if (trimmed.startsWith('#') || trimmed.startsWith('rgb(') || trimmed.startsWith('rgba(') || trimmed.startsWith('hsl(') || trimmed.startsWith('hsla(')) {
        return trimmed;
    }

    return fallback;
}

function sanitizeColorList(value, targetLength, fallbackResolver) {
    if (!Array.isArray(value) || value.length === 0) {
        return [];
    }

    const colors = value.slice(0, targetLength).map((item, colorIndex) => (
        sanitizeColor(item, fallbackResolver(colorIndex))
    ));
    while (colors.length < targetLength) {
        colors.push(fallbackResolver(colors.length));
    }
    return colors;
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

function normalizeChartKindValue(value) {
    const normalized = sanitizeText(value, 40).toLowerCase().replace(/[\s-]+/g, '_');
    if (!normalized || normalized === 'chart') {
        return '';
    }
    if (normalized === 'polararea') {
        return 'polar_area';
    }
    if (normalized === 'donut') {
        return 'doughnut';
    }
    return normalized;
}

function parseInlineArray(value) {
    const trimmed = String(value ?? '').trim();
    if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) {
        return null;
    }

    const inner = trimmed.slice(1, -1).trim();
    if (!inner) {
        return [];
    }

    return inner.split(',').map(item => parseLooseScalarValue(item));
}

function parseLooseScalarValue(value) {
    const trimmed = String(value ?? '').trim();
    if (!trimmed) {
        return '';
    }

    const arrayValue = parseInlineArray(trimmed);
    if (arrayValue) {
        return arrayValue;
    }

    if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
        return trimmed.slice(1, -1);
    }

    const lowered = trimmed.toLowerCase();
    if (lowered === 'true') {
        return true;
    }
    if (lowered === 'false') {
        return false;
    }
    if (lowered === 'null') {
        return null;
    }

    const numericValue = Number(trimmed.replace(/,/g, ''));
    if (Number.isFinite(numericValue) && /^-?[0-9][0-9,]*(\.[0-9]+)?$/.test(trimmed)) {
        return numericValue;
    }

    return trimmed;
}

function parseLooseKeyValue(line) {
    const separatorIndex = line.indexOf(':');
    if (separatorIndex < 0) {
        return null;
    }

    return {
        key: line.slice(0, separatorIndex).trim(),
        value: line.slice(separatorIndex + 1).trim()
    };
}

function assignLooseChartOption(spec, key, value, optionPath) {
    if (!spec.options || typeof spec.options !== 'object') {
        spec.options = {};
    }

    const normalizedKey = String(key || '').trim();
    const parsedValue = parseLooseScalarValue(value);
    const inLegendPath = optionPath.includes('legend');

    if (inLegendPath && (normalizedKey === 'display' || normalizedKey === 'position')) {
        spec.options.plugins = spec.options.plugins && typeof spec.options.plugins === 'object'
            ? spec.options.plugins
            : {};
        spec.options.plugins.legend = spec.options.plugins.legend && typeof spec.options.plugins.legend === 'object'
            ? spec.options.plugins.legend
            : {};
        spec.options.plugins.legend[normalizedKey] = parsedValue;
        return;
    }

    spec.options[normalizedKey] = parsedValue;
}

function parseLooseChartSpec(payloadText) {
    const spec = {
        data: {
            datasets: []
        },
        options: {}
    };
    let section = '';
    let currentDataset = null;
    let optionPath = [];

    String(payloadText || '').replace(/\r/g, '').split('\n').forEach(rawLine => {
        const normalizedLine = rawLine.replace(/\t/g, '    ');
        const trimmed = normalizedLine.trim();
        if (!trimmed || trimmed.startsWith('#')) {
            return;
        }

        const indent = normalizedLine.length - normalizedLine.trimStart().length;
        const listItemText = trimmed.startsWith('- ') ? trimmed.slice(2).trim() : '';
        if (listItemText && section === 'data') {
            currentDataset = {};
            spec.data.datasets.push(currentDataset);
            const listKeyValue = parseLooseKeyValue(listItemText);
            if (listKeyValue) {
                currentDataset[listKeyValue.key] = parseLooseScalarValue(listKeyValue.value);
            }
            return;
        }

        const keyValue = parseLooseKeyValue(trimmed);
        if (!keyValue) {
            return;
        }

        const { key, value } = keyValue;
        if (indent === 0) {
            optionPath = [];
            currentDataset = null;
            if (!value && (key === 'data' || key === 'options')) {
                section = key;
                return;
            }
            section = '';
            spec[key] = parseLooseScalarValue(value);
            return;
        }

        if (section === 'data') {
            if (key === 'datasets' && !value) {
                currentDataset = null;
                return;
            }

            if (currentDataset) {
                currentDataset[key] = parseLooseScalarValue(value);
                return;
            }

            spec.data[key] = parseLooseScalarValue(value);
            return;
        }

        if (section === 'options') {
            if (!value) {
                if (key === 'plugins') {
                    optionPath = ['plugins'];
                } else if (key === 'legend') {
                    optionPath = ['plugins', 'legend'];
                }
                return;
            }

            assignLooseChartOption(spec, key, value, optionPath);
        }
    });

    return spec;
}

function parseInlineChartPayload(payloadText) {
    const normalizedPayload = String(payloadText || '').trim();
    if (!normalizedPayload) {
        return null;
    }

    try {
        return JSON.parse(normalizedPayload);
    } catch (error) {
        return parseLooseChartSpec(normalizedPayload);
    }
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
            normalized.backgroundColor = sanitizeColorList(
                dataset?.backgroundColor,
                labels.length,
                colorIndex => getPalette(colorIndex).background
            );
            normalized.borderColor = sanitizeColorList(
                dataset?.borderColor,
                labels.length,
                colorIndex => getPalette(colorIndex).border
            );
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

    let kind = normalizeChartKindValue(rawSpec.kind);
    if (!ALLOWED_KINDS.has(kind)) {
        kind = normalizeChartKindValue(rawSpec.chartType);
    }
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

    const rawLegendOptions = rawOptions.plugins
        && typeof rawOptions.plugins === 'object'
        && !Array.isArray(rawOptions.plugins)
        && rawOptions.plugins.legend
        && typeof rawOptions.plugins.legend === 'object'
        && !Array.isArray(rawOptions.plugins.legend)
        ? rawOptions.plugins.legend
        : {};
    const legendPosition = sanitizeText(rawOptions.legendPosition || rawLegendOptions.position || 'top', 10).toLowerCase();
    const normalizedOptions = {
        legendPosition: ['top', 'bottom', 'left', 'right'].includes(legendPosition) ? legendPosition : 'top',
        showLegend: rawOptions.showLegend !== false && rawLegendOptions.display !== false,
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

function buildColorEditorButtonHtml(panelId) {
    return `
        <button type="button" class="btn btn-sm btn-outline-secondary sc-inline-chart-colors-toggle" aria-expanded="false" aria-controls="${escapeHtml(panelId)}" aria-label="Edit chart colors" title="Edit chart colors">
            <i class="bi bi-palette" aria-hidden="true"></i>
        </button>
    `;
}

function buildSafeChartDomId(prefix, source, fallback) {
    const normalizedSource = sanitizeText(source, 64).replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '');
    return `${prefix}-${normalizedSource || fallback}`;
}

function buildPlaceholderHtml(block, index) {
    const encodedSpec = encodeURIComponent(JSON.stringify(block.spec));
    const captionParts = [block.spec.description, block.spec.summary].filter(Boolean);
    const captionHtml = captionParts.length
        ? `<div class="small text-muted mt-2">${escapeHtml(captionParts.join(' '))}</div>`
        : '';
    const fallbackIdSource = `${index}-${Math.random().toString(36).slice(2, 10)}`;
    const colorPanelId = buildSafeChartDomId('chart-color-panel', block.spec.chartId, fallbackIdSource);

    return `
        <section class="sc-inline-chart card border-0 shadow-sm my-3" data-chart-hydrated="false" data-chart-spec="${encodedSpec}" aria-label="Inline chart ${index + 1}">
            <div class="card-body p-3">
                <div class="sc-inline-chart-header d-flex align-items-start justify-content-between gap-2 mb-2">
                    <div class="sc-inline-chart-heading min-w-0 d-flex flex-column gap-1">
                        ${block.spec.title ? `<div class="fw-semibold sc-inline-chart-title">${escapeHtml(block.spec.title)}</div>` : ''}
                        ${block.spec.subtitle ? `<div class="small text-muted sc-inline-chart-subtitle">${escapeHtml(block.spec.subtitle)}</div>` : ''}
                    </div>
                    <div class="sc-inline-chart-actions d-flex align-items-center gap-1">
                        ${buildColorEditorButtonHtml(colorPanelId)}
                    </div>
                </div>
                <div class="sc-inline-chart-stage position-relative">
                    <canvas role="img" aria-label="${escapeHtml(block.spec.title || block.spec.kind)}"></canvas>
                </div>
                <div class="sc-inline-chart-color-panel d-none mt-3" id="${escapeHtml(colorPanelId)}"></div>
                ${captionHtml}
                ${buildTableHtml(block.spec)}
            </div>
        </section>
    `;
}

function buildStatusPlaceholderHtml(block, index) {
    const title = block.pending ? 'Preparing chart...' : 'Chart unavailable';
    const detail = block.pending
        ? 'Rendering will start when the chart data is complete.'
        : sanitizeText(block.error || 'The chart data could not be rendered.', 180);

    return `
        <section class="sc-inline-chart card border-0 shadow-sm my-3" data-chart-hydrated="status" aria-label="Inline chart ${index + 1}">
            <div class="card-body p-3">
                <div class="fw-semibold">${escapeHtml(title)}</div>
                <div class="small text-muted mt-1">${escapeHtml(detail)}</div>
            </div>
        </section>
    `;
}

function createInlineChartToken(blocks, block) {
    const token = `SIMPLECHAT_INLINE_CHART_TOKEN_${blocks.length}__`;
    blocks.push({ token, ...block });
    return `\n\n${token}\n\n`;
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

function isSegmentColorChart(spec) {
    return ['pie', 'doughnut', 'polar_area'].includes(spec?.kind);
}

function getEditableColorTargets(spec) {
    if (!spec?.data?.datasets?.length) {
        return [];
    }

    if (isSegmentColorChart(spec) && Array.isArray(spec.data.labels) && spec.data.labels.length) {
        return spec.data.labels.slice(0, CHART_COLOR_MAX_EDIT_TARGETS).map((label, dataIndex) => ({
            datasetIndex: 0,
            dataIndex,
            label: label || `Slice ${dataIndex + 1}`,
        }));
    }

    return spec.data.datasets.slice(0, CHART_COLOR_MAX_EDIT_TARGETS).map((dataset, datasetIndex) => ({
        datasetIndex,
        dataIndex: null,
        label: dataset.label || `Series ${datasetIndex + 1}`,
    }));
}

function getTargetColor(spec, target) {
    const dataset = spec?.data?.datasets?.[target.datasetIndex];
    const palette = getPalette(target.dataIndex ?? target.datasetIndex);
    if (!dataset) {
        return normalizeHexColor(palette.border);
    }

    if (target.dataIndex !== null && target.dataIndex !== undefined) {
        const borderColor = Array.isArray(dataset.borderColor) ? dataset.borderColor[target.dataIndex] : dataset.borderColor;
        const backgroundColor = Array.isArray(dataset.backgroundColor) ? dataset.backgroundColor[target.dataIndex] : dataset.backgroundColor;
        return resolveColorValue(borderColor || backgroundColor, palette.border);
    }

    return resolveColorValue(dataset.borderColor || dataset.backgroundColor, palette.border);
}

function buildColorArray(existingValue, targetLength, fallbackResolver) {
    const values = Array.isArray(existingValue)
        ? existingValue.slice(0, targetLength)
        : [];
    while (values.length < targetLength) {
        values.push(fallbackResolver(values.length));
    }
    return values;
}

function setTargetColor(spec, target, colorHex) {
    const dataset = spec?.data?.datasets?.[target.datasetIndex];
    if (!dataset) {
        return;
    }

    const normalizedHex = normalizeHexColor(colorHex, getPalette(target.datasetIndex).border);
    if (target.dataIndex !== null && target.dataIndex !== undefined) {
        const targetLength = Array.isArray(spec.data.labels) && spec.data.labels.length
            ? spec.data.labels.length
            : dataset.data.length;
        const backgroundColors = buildColorArray(
            dataset.backgroundColor,
            targetLength,
            colorIndex => getPalette(colorIndex).background
        );
        const borderColors = buildColorArray(
            dataset.borderColor,
            targetLength,
            colorIndex => getPalette(colorIndex).border
        );
        backgroundColors[target.dataIndex] = normalizedHex;
        borderColors[target.dataIndex] = normalizedHex;
        dataset.backgroundColor = backgroundColors;
        dataset.borderColor = borderColors;
        return;
    }

    dataset.borderColor = normalizedHex;
    dataset.backgroundColor = hexToRgba(normalizedHex);
}

function applyColorPreset(spec, preset) {
    const targets = getEditableColorTargets(spec);
    targets.forEach((target, targetIndex) => {
        setTargetColor(spec, target, preset.colors[targetIndex % preset.colors.length]);
    });
}

function getChartIndexWithinMessage(container) {
    const messageElement = container.closest('.message');
    if (!messageElement) {
        return -1;
    }

    return Array.from(messageElement.querySelectorAll('.sc-inline-chart[data-chart-spec]')).indexOf(container);
}

function updateHiddenChartMarkdown(container, spec) {
    const messageElement = container.closest('.message');
    const hiddenTextarea = messageElement?.querySelector('textarea[id^="copy-md-"]');
    const chartIndex = getChartIndexWithinMessage(container);
    if (!hiddenTextarea || chartIndex < 0) {
        return;
    }

    let currentIndex = -1;
    INLINE_CHART_REGEX.lastIndex = 0;
    hiddenTextarea.value = hiddenTextarea.value.replace(INLINE_CHART_REGEX, match => {
        currentIndex += 1;
        if (currentIndex !== chartIndex) {
            return match;
        }

        return `\`\`\`${INLINE_CHART_LANGUAGE}\n${JSON.stringify(spec)}\n\`\`\``;
    });
}

function updateStoredChartSpec(container, spec) {
    container._chartSpec = spec;
    container.setAttribute('data-chart-spec', encodeURIComponent(JSON.stringify(spec)));
    updateHiddenChartMarkdown(container, spec);
}

function applyChartSpecToInstance(container, spec) {
    const chartInstance = container._chartInstance;
    if (!chartInstance) {
        return;
    }

    const chartConfig = buildChartJsConfig(spec);
    chartInstance.data.labels = chartConfig.data.labels || [];
    chartInstance.data.datasets = chartConfig.data.datasets;
    chartInstance.options = chartConfig.options;
    chartInstance.update();
}

function createPaletteSwatch(colorHex) {
    const swatch = document.createElement('span');
    swatch.className = 'sc-inline-chart-palette-swatch';
    swatch.style.backgroundColor = normalizeHexColor(colorHex);
    swatch.setAttribute('aria-hidden', 'true');
    return swatch;
}

function renderColorPanel(container, spec) {
    const panel = container.querySelector('.sc-inline-chart-color-panel');
    if (!panel) {
        return;
    }

    panel.replaceChildren();
    const targets = getEditableColorTargets(spec);
    if (!targets.length) {
        return;
    }

    const paletteGroup = document.createElement('div');
    paletteGroup.className = 'sc-inline-chart-palette-group';
    CHART_COLOR_PRESETS.forEach(preset => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-secondary sc-inline-chart-palette-btn';
        button.title = `${preset.name} palette`;
        button.setAttribute('aria-label', `Apply ${preset.name} palette`);
        preset.colors.slice(0, 5).forEach(colorHex => {
            button.appendChild(createPaletteSwatch(colorHex));
        });
        button.addEventListener('click', () => {
            applyColorPreset(spec, preset);
            updateStoredChartSpec(container, spec);
            applyChartSpecToInstance(container, spec);
            renderColorPanel(container, spec);
        });
        paletteGroup.appendChild(button);
    });

    const swatchGrid = document.createElement('div');
    swatchGrid.className = 'sc-inline-chart-color-grid';
    targets.forEach(target => {
        const colorRow = document.createElement('label');
        colorRow.className = 'sc-inline-chart-color-row';

        const input = document.createElement('input');
        input.type = 'color';
        input.className = 'form-control form-control-color sc-inline-chart-color-input';
        input.value = getTargetColor(spec, target);
        input.setAttribute('aria-label', `Color for ${target.label}`);
        input.addEventListener('input', () => {
            setTargetColor(spec, target, input.value);
            updateStoredChartSpec(container, spec);
            applyChartSpecToInstance(container, spec);
        });

        const labelText = document.createElement('span');
        labelText.className = 'sc-inline-chart-color-label';
        labelText.textContent = target.label;

        colorRow.appendChild(input);
        colorRow.appendChild(labelText);
        swatchGrid.appendChild(colorRow);
    });

    panel.appendChild(paletteGroup);
    panel.appendChild(swatchGrid);

    const totalTargetCount = isSegmentColorChart(spec)
        ? spec.data.labels.length
        : spec.data.datasets.length;
    if (totalTargetCount > targets.length) {
        const clippedNote = document.createElement('div');
        clippedNote.className = 'small text-muted mt-2';
        clippedNote.textContent = `Showing first ${targets.length} colors.`;
        panel.appendChild(clippedNote);
    }
}

function bindChartColorControls(container, spec) {
    const toggleButton = container.querySelector('.sc-inline-chart-colors-toggle');
    const panel = container.querySelector('.sc-inline-chart-color-panel');
    if (!toggleButton || !panel || toggleButton.dataset.bound) {
        return;
    }

    toggleButton.dataset.bound = 'true';
    renderColorPanel(container, spec);
    toggleButton.addEventListener('click', () => {
        const isHidden = panel.classList.contains('d-none');
        panel.classList.toggle('d-none', !isHidden);
        toggleButton.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
    });
}

export function extractInlineChartBlocks(markdownText = '') {
    const blocks = [];
    let markdown = String(markdownText ?? '').replace(INLINE_CHART_REGEX, (match, payload) => {
        const parsed = parseInlineChartPayload(payload);
        const spec = normalizeChartSpec(parsed);
        if (!spec) {
            return createInlineChartToken(blocks, {
                originalBlock: match,
                error: 'The chart data format was not recognized.'
            });
        }

        return createInlineChartToken(blocks, { spec, originalBlock: match });
    });

    markdown = markdown.replace(INLINE_CHART_PENDING_REGEX, match => createInlineChartToken(blocks, {
        originalBlock: match,
        pending: true,
    }));

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
        const placeholderHtml = block.spec
            ? buildPlaceholderHtml(block, index)
            : buildStatusPlaceholderHtml(block, index);
        renderedHtml = replaceAllOccurrences(renderedHtml, `<p>${block.token}</p>`, placeholderHtml);
        renderedHtml = replaceAllOccurrences(renderedHtml, block.token, placeholderHtml);
    });

    return renderedHtml;
}

function getChartInstanceForCanvas(canvas) {
    if (!canvas || typeof window.Chart === 'undefined' || typeof window.Chart.getChart !== 'function') {
        return null;
    }
    return window.Chart.getChart(canvas);
}

export function destroyInlineCharts(root = document) {
    const chartContainers = root.matches?.('.sc-inline-chart')
        ? [root]
        : root.querySelectorAll('.sc-inline-chart');
    chartContainers.forEach(container => {
        const canvas = container.querySelector('canvas');
        const chartInstance = container._chartInstance || getChartInstanceForCanvas(canvas);
        if (chartInstance && typeof chartInstance.destroy === 'function') {
            chartInstance.destroy();
        }
        container._chartInstance = null;
    });
}

export function hydrateInlineCharts(root = document) {
    const chartContainers = root.querySelectorAll('.sc-inline-chart:not([data-chart-hydrated="status"])');
    chartContainers.forEach(container => {
        const specText = container.getAttribute('data-chart-spec');
        const stage = container.querySelector('.sc-inline-chart-stage');
        const canvas = container.querySelector('canvas');
        if (!specText || !stage || !canvas) {
            return;
        }

        const existingChart = container._chartInstance || getChartInstanceForCanvas(canvas);
        if (container.getAttribute('data-chart-hydrated') === 'true' && existingChart) {
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
            if (existingChart && typeof existingChart.destroy === 'function') {
                existingChart.destroy();
            }
            container._chartInstance = new window.Chart(canvas.getContext('2d'), chartConfig);
            container._chartSpec = spec;
            container.setAttribute('data-chart-hydrated', 'true');
            bindChartColorControls(container, spec);

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