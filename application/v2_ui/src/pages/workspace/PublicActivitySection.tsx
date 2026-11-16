// PublicActivitySection.tsx
// The public workspace Activity section (M10C): a thin wrapper that gives the shared
// WorkspaceActivitySection the public scope -- the configured workspace label, the public actor labels
// and the public test ids. The whole view lives in WorkspaceActivitySection.tsx.
//
// The public projection names a current member (the owner, an admin or a document manager) by the
// display name the workspace holds, reports any other signed-in person as `non_member` ("Not a
// member": a reader who holds no role here, not necessarily someone who left), and an event with no
// person behind it, or a status change made by someone who holds no role here, as the system.

import { useMemo } from 'react';
import type { PublicSettingsAdapter } from '../../lib/publicSettings';
import { usePublicWorkspaceLabels } from '../../lib/publicWorkspaceLabels';
import { WorkspaceActivitySection, type WorkspaceActivitySectionScope } from './WorkspaceActivitySection';

export function PublicActivitySection({ adapter }: { adapter: PublicSettingsAdapter }) {
    const { lower_singular: lowerSingular } = usePublicWorkspaceLabels();
    const scope = useMemo<WorkspaceActivitySectionScope>(() => ({
        testIdPrefix: 'public-activity',
        description: `Recent changes in this ${lowerSingular}, most recent first.`,
        loadFailed: `The ${lowerSingular} activity could not be loaded. Please retry.`,
        emptyDescription: `Uploads, conversations, status changes and File Sync runs in this ${lowerSingular} will appear here.`,
        actorLabels: {
            memberFallback: 'A workspace member',
            // The public projection never reports a former member; the label stays for completeness.
            formerMember: 'Former member',
            nonMember: 'Not a member',
            system: 'System',
        },
    }), [lowerSingular]);

    return <WorkspaceActivitySection scope={scope} adapter={adapter} />;
}
