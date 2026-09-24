// groupStats.ts
// Presentation and export helpers for the native group Statistics view (M7C).
//
// The group statistics envelope has a different shape from the personal one -- classic-style totals
// with document-activity, token-usage and storage series and no login or conversation history -- so
// this module turns that envelope into the chart inputs and summary cards the group view renders,
// and rebuilds the classic `exportGroupStats` CSV column for column so a saved spreadsheet keeps
// working across both interfaces. The classic export uses its own byte formatter (`0 B`, `B`/`KB`)
// distinct from the personal `formatBytes` (`0 Bytes`), so the "Formatted" column is produced here
// with a classic-matching formatter rather than the personal one.

import {
    SERIES_COLORS,
    barDataset,
    cartesianOptions,
    lineDataset,
    type StatsChartConfigBuilder,
} from '../components/settings/StatsChart';
import { isCustomWindow, type StatsExportAdapter, type StatsWindow } from './userStats';
import type { GroupSettingsAdapter, GroupStatsPayload } from './groupSettings';
import { statsWindowQuery } from './userStats';

export const GROUP_STATS_DATE_RANGE_MESSAGE = 'Choose dates between 2000-01-01 and 9998-12-31.';
export const GROUP_STATS_RANGE_TOO_LONG_MESSAGE = 'Choose a date range of 366 days or fewer.';

const MIN_STATS_DATE = Date.UTC(2000, 0, 1);
const MAX_STATS_DATE = Date.UTC(9998, 11, 31);
const MAX_STATS_DAYS = 366;
const MS_PER_DAY = 86_400_000;

/**
 * Pre-validate a custom range against the server's rules so a guaranteed 400 never leaves. The
 * server stays authoritative; this only avoids a request that cannot succeed, with its own message.
 */
export function validateGroupStatsRange(window: StatsWindow): string | null {
    if (!isCustomWindow(window)) {
        return null;
    }
    const start = Date.parse(`${window.startDate}T00:00:00Z`);
    const end = Date.parse(`${window.endDate}T00:00:00Z`);
    if (Number.isNaN(start) || Number.isNaN(end)) {
        return GROUP_STATS_DATE_RANGE_MESSAGE;
    }
    if (start < MIN_STATS_DATE || end > MAX_STATS_DATE || start > end) {
        return GROUP_STATS_DATE_RANGE_MESSAGE;
    }
    const days = Math.floor((end - start) / MS_PER_DAY) + 1;
    if (days > MAX_STATS_DAYS) {
        return GROUP_STATS_RANGE_TOO_LONG_MESSAGE;
    }
    return null;
}

/** One summary card as the group view renders it. */
export interface GroupStatSummaryCard {
    key: string;
    label: string;
    value: string;
}

/** The classic byte formatter (`0 B`, units `B/KB/MB/GB/TB`), distinct from personal `formatBytes`. */
export function formatClassicBytes(bytes: number): string {
    if (!bytes) {
        return '0 B';
    }
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const clamped = Math.min(i, sizes.length - 1);
    return `${Math.round((bytes / Math.pow(k, clamped)) * 100) / 100} ${sizes[clamped]}`;
}

function formatCount(value: number): string {
    return new Intl.NumberFormat().format(value);
}

export function groupStatSummaryCards(stats: GroupStatsPayload): GroupStatSummaryCard[] {
    return [
        { key: 'documents', label: 'Documents', value: formatCount(stats.totalDocuments) },
        { key: 'storage', label: 'Storage used', value: formatClassicBytes(stats.storageUsed) },
        { key: 'tokens', label: 'Tokens', value: formatCount(stats.totalTokens) },
        { key: 'members', label: 'Members', value: formatCount(stats.totalMembers) },
    ];
}

/** The document-activity chart: uploads and deletes per day. */
export function documentActivityConfig(stats: GroupStatsPayload): StatsChartConfigBuilder {
    return (theme) => ({
        type: 'bar',
        data: {
            labels: stats.documentActivity.labels,
            datasets: [
                barDataset('Uploads', stats.documentActivity.uploads, SERIES_COLORS.uploaded.line, SERIES_COLORS.uploaded.fill),
                barDataset('Deletes', stats.documentActivity.deletes, SERIES_COLORS.deleted.line, SERIES_COLORS.deleted.fill),
            ],
        },
        options: cartesianOptions(theme, true),
    });
}

/** The token-usage chart: total tokens per day. */
export function tokenUsageConfig(stats: GroupStatsPayload): StatsChartConfigBuilder {
    return (theme) => ({
        type: 'line',
        data: {
            labels: stats.tokenUsage.labels,
            datasets: [lineDataset('Tokens', stats.tokenUsage.data, SERIES_COLORS.tokens.line, SERIES_COLORS.tokens.fill)],
        },
        options: cartesianOptions(theme, false),
    });
}

/** The storage split: AI Search index versus blob storage. */
export function storageBreakdownConfig(stats: GroupStatsPayload): StatsChartConfigBuilder {
    return (theme) => ({
        type: 'doughnut',
        data: {
            labels: ['AI Search', 'Blob storage'],
            datasets: [
                {
                    label: 'Storage',
                    data: [stats.storage.ai_search_size, stats.storage.storage_account_size],
                    backgroundColor: [SERIES_COLORS.aiSearch, SERIES_COLORS.blobStorage],
                    borderWidth: 0,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: theme.text },
                },
            },
        },
    });
}

/** The export sections the group dialog offers, distinct from personal's sections. */
export const GROUP_EXPORT_SECTIONS = [
    { key: 'summary', label: 'Summary totals', hint: 'Documents, storage, tokens and members' },
    { key: 'documents', label: 'Document activity', hint: 'Uploads and deletes per day' },
    { key: 'tokens', label: 'Token usage', hint: 'Total tokens per day' },
    { key: 'storage', label: 'Storage usage', hint: 'AI Search and blob storage sizes' },
] as const;

export const DEFAULT_GROUP_EXPORT_SECTIONS: Record<string, boolean> = {
    summary: true,
    documents: true,
    tokens: true,
    storage: true,
};

/** The classic `escapeCsvValue`: quote on comma, quote, newline or carriage return; double quotes. */
function classicCsvField(value: unknown): string {
    if (value === null || value === undefined) {
        return '';
    }
    const text = String(value);
    if (text.includes(',') || text.includes('"') || text.includes('\n') || text.includes('\r')) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function classicCsvRow(values: unknown[]): string {
    return values.map(classicCsvField).join(',');
}

/**
 * Build the group statistics CSV, column for column with classic `exportGroupStats`. Rows are joined
 * by `\n`, there is no BOM, and the "Formatted" storage column uses the classic byte formatter.
 */
export function buildGroupStatsCsv({
    stats,
    sections,
    windowLabel,
    exportedAt = new Date(),
}: {
    stats: GroupStatsPayload;
    sections: Record<string, boolean>;
    windowLabel: string;
    exportedAt?: Date;
}): string {
    const rows: string[] = [];
    rows.push(classicCsvField('Group Stats Export'));
    rows.push(classicCsvRow(['Export Date', exportedAt.toLocaleString()]));
    rows.push(classicCsvRow(['Data Period', windowLabel]));
    rows.push('');

    if (sections.summary) {
        rows.push(classicCsvField('SUMMARY METRICS'));
        rows.push(classicCsvRow(['Metric', 'Value']));
        rows.push(classicCsvRow(['Total Documents', stats.totalDocuments]));
        rows.push(classicCsvRow(['Storage Used (bytes)', stats.storageUsed]));
        rows.push(classicCsvRow(['Total Tokens', stats.totalTokens]));
        rows.push(classicCsvRow(['Total Members', stats.totalMembers]));
        rows.push('');
    }

    if (sections.documents) {
        rows.push(classicCsvField(`DOCUMENT ACTIVITY (${windowLabel})`));
        rows.push(classicCsvRow(['Date', 'Uploads', 'Deletes']));
        stats.documentActivity.labels.forEach((label, index) => {
            rows.push(classicCsvRow([
                label,
                stats.documentActivity.uploads[index] ?? 0,
                stats.documentActivity.deletes[index] ?? 0,
            ]));
        });
        rows.push('');
    }

    if (sections.tokens) {
        rows.push(classicCsvField(`TOKEN USAGE (${windowLabel})`));
        rows.push(classicCsvRow(['Date', 'Total Tokens']));
        stats.tokenUsage.labels.forEach((label, index) => {
            rows.push(classicCsvRow([label, stats.tokenUsage.data[index] ?? 0]));
        });
        rows.push('');
    }

    if (sections.storage) {
        rows.push(classicCsvField('STORAGE USAGE'));
        rows.push(classicCsvRow(['Metric', 'Bytes', 'Formatted']));
        rows.push(classicCsvRow([
            'AI Search', stats.storage.ai_search_size, formatClassicBytes(stats.storage.ai_search_size),
        ]));
        rows.push(classicCsvRow([
            'Blob Storage', stats.storage.storage_account_size, formatClassicBytes(stats.storage.storage_account_size),
        ]));
        rows.push('');
    }

    return rows.join('\n');
}

/** The classic export file name: `group_stats_export_<YYYY-MM-DD>.csv`. */
export function groupStatsCsvFileName(exportedAt: Date = new Date()): string {
    return `group_stats_export_${exportedAt.toISOString().split('T')[0]}.csv`;
}

/**
 * The group export adapter for the shared dialog. It loads the statistics for the chosen window and
 * assembles the classic CSV, so the dialog drives group export without knowing the group shape.
 */
export function createGroupStatsExportAdapter(adapter: GroupSettingsAdapter): StatsExportAdapter {
    return {
        title: 'Export group statistics',
        description: 'Download the group\u2019s statistics for the selected period as a CSV file.',
        sections: GROUP_EXPORT_SECTIONS.map((section) => ({ ...section })),
        defaultSections: { ...DEFAULT_GROUP_EXPORT_SECTIONS },
        successMessage: 'Group statistics exported.',
        omitBom: true,
        validateWindow: validateGroupStatsRange,
        build: async (window, sections, signal) => {
            const stats = await adapter.readStats(statsWindowQuery(window), signal);
            return {
                csv: buildGroupStatsCsv({ stats, sections, windowLabel: stats.window.label }),
                fileName: groupStatsCsvFileName(),
            };
        },
    };
}
