// publicStats.ts
// The export adapter for the native public workspace Statistics view (M10C).
//
// The public statistics envelope is the group's (classic totals with document-activity, token-usage
// and storage series, `totalMembers` kept and classic's invented `storageLimit` dropped), so the view
// reuses the group's charts, summary cards and range check, and the export writes the classic
// `exportWorkspaceStats` CSV column for column through the group's CSV builder: the configured
// workspace label's title, no BOM, `\n` rows, the classic byte formatter in the "Formatted" column and
// the classic `public_workspace_stats_export_<YYYY-MM-DD>.csv` file name. Nothing here forks a
// formatter or a column list.

import type { WorkspaceSettingsAdapter } from './groupSettings';
import {
    DEFAULT_GROUP_EXPORT_SECTIONS, GROUP_EXPORT_SECTIONS, buildGroupStatsCsv, validateGroupStatsRange,
} from './groupStats';
import type { PublicWorkspaceLabels } from './types';
import { statsWindowQuery, type StatsExportAdapter } from './userStats';

/** The classic export file name: `public_workspace_stats_export_<YYYY-MM-DD>.csv`. */
export function publicStatsCsvFileName(exportedAt: Date = new Date()): string {
    return `public_workspace_stats_export_${exportedAt.toISOString().split('T')[0]}.csv`;
}

/** The classic export title, from the configured label: `${singular} Stats Export`. */
export function publicStatsCsvTitle(labels: Pick<PublicWorkspaceLabels, 'singular'>): string {
    return `${labels.singular} Stats Export`;
}

/**
 * The public export adapter for the shared dialog. It loads the statistics for the chosen window
 * through the public workspace's own client and assembles the classic CSV.
 */
export function createPublicStatsExportAdapter(
    adapter: WorkspaceSettingsAdapter,
    labels: Pick<PublicWorkspaceLabels, 'singular' | 'lower_singular'>,
): StatsExportAdapter {
    return {
        title: `Export ${labels.lower_singular} statistics`,
        description: `Download the ${labels.lower_singular}\u2019s statistics for the selected period as a CSV file.`,
        sections: GROUP_EXPORT_SECTIONS.map((section) => ({ ...section })),
        defaultSections: { ...DEFAULT_GROUP_EXPORT_SECTIONS },
        successMessage: `${labels.singular} statistics exported.`,
        omitBom: true,
        validateWindow: validateGroupStatsRange,
        build: async (window, sections, signal) => {
            const stats = await adapter.readStats(statsWindowQuery(window), signal);
            return {
                csv: buildGroupStatsCsv({
                    stats, sections, windowLabel: stats.window.label, title: publicStatsCsvTitle(labels),
                }),
                fileName: publicStatsCsvFileName(),
            };
        },
    };
}
