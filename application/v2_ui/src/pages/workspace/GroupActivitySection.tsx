// GroupActivitySection.tsx
// The group workspace Activity section (M7C): a thin wrapper that gives the shared
// WorkspaceActivitySection the group scope -- the group's wording, actor labels and test ids. The
// whole view lives in WorkspaceActivitySection.tsx; the external props are unchanged, so the group
// page renders it exactly as before.

import type { GroupSettingsAdapter } from '../../lib/groupSettings';
import { WorkspaceActivitySection, type WorkspaceActivitySectionScope } from './WorkspaceActivitySection';

const GROUP_ACTIVITY_SCOPE: WorkspaceActivitySectionScope = {
    testIdPrefix: 'group-activity',
    description: 'Recent changes in this group, most recent first.',
    loadFailed: 'The group activity could not be loaded. Please retry.',
    emptyDescription: 'Uploads, conversations, agents and File Sync runs in this group will appear here.',
    actorLabels: {
        memberFallback: 'A group member',
        formerMember: 'Former member',
        // The group projection never reports `non_member` (that kind is the public workspace's); the
        // group view names any actor it doesn't recognize as the system, as it always has.
        nonMember: 'System',
        system: 'System',
    },
};

export function GroupActivitySection({ adapter }: { adapter: GroupSettingsAdapter }) {
    return <WorkspaceActivitySection scope={GROUP_ACTIVITY_SCOPE} adapter={adapter} />;
}
