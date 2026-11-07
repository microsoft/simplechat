// PublicStatisticsSection.tsx
// The public workspace Statistics section (M10C): a thin wrapper that gives the shared
// WorkspaceStatisticsSection the public scope -- the configured workspace label, the classic
// `exportWorkspaceStats` CSV export and the public test ids. The whole view lives in
// WorkspaceStatisticsSection.tsx.

import { useMemo } from 'react';
import type { PublicSettingsAdapter } from '../../lib/publicSettings';
import { createPublicStatsExportAdapter } from '../../lib/publicStats';
import { usePublicWorkspaceLabels } from '../../lib/publicWorkspaceLabels';
import { WorkspaceStatisticsSection, type WorkspaceStatisticsSectionScope } from './WorkspaceStatisticsSection';

export function PublicStatisticsSection({ adapter }: { adapter: PublicSettingsAdapter }) {
    const { singular, lower_singular: lowerSingular } = usePublicWorkspaceLabels();
    const scope = useMemo<WorkspaceStatisticsSectionScope>(() => ({
        testIdPrefix: 'public-statistics',
        description: `The ${lowerSingular}'s totals and day-by-day trends over the selected period.`,
        loadFailed: `The ${lowerSingular} statistics could not be loaded. Please retry.`,
        createExportAdapter: (workspaceAdapter) => createPublicStatsExportAdapter(
            workspaceAdapter, { singular, lower_singular: lowerSingular },
        ),
    }), [singular, lowerSingular]);

    return <WorkspaceStatisticsSection scope={scope} adapter={adapter} />;
}
