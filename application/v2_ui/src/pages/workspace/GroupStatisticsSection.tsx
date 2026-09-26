// GroupStatisticsSection.tsx
// The group workspace Statistics section (M7C): a thin wrapper that gives the shared
// WorkspaceStatisticsSection the group scope -- the group's wording, its classic `exportGroupStats`
// CSV export and its test ids. The whole view lives in WorkspaceStatisticsSection.tsx; the external
// props are unchanged, so the group page renders it exactly as before.

import type { GroupSettingsAdapter } from '../../lib/groupSettings';
import { createGroupStatsExportAdapter } from '../../lib/groupStats';
import { WorkspaceStatisticsSection, type WorkspaceStatisticsSectionScope } from './WorkspaceStatisticsSection';

const GROUP_STATISTICS_SCOPE: WorkspaceStatisticsSectionScope = {
    testIdPrefix: 'group-statistics',
    description: "The group's totals and day-by-day trends over the selected period.",
    loadFailed: 'The group statistics could not be loaded. Please retry.',
    createExportAdapter: createGroupStatsExportAdapter,
};

export function GroupStatisticsSection({ adapter }: { adapter: GroupSettingsAdapter }) {
    return <WorkspaceStatisticsSection scope={GROUP_STATISTICS_SCOPE} adapter={adapter} />;
}
