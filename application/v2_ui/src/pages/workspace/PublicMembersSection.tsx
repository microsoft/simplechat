// PublicMembersSection.tsx
// The public workspace Members section (M10A): a thin wrapper that gives the shared MembersSection
// the public scope. The whole view lives in MembersSection.tsx; here we name the public client,
// vocabulary and error codes, the public assignable roles (Admin and Document manager only), and
// the deliberate absence of a "leave" control (decision 17: a public manager can't step down).
//
// A public workspace has no `users[]` roster: its members are exactly the Owner, the Admins and
// the Document managers, so the copy speaks of managing the workspace rather than everyone in it,
// and it never says "group".

import { useMemo } from 'react';
import { PUBLIC_ASSIGNABLE_ROLE_OPTIONS, PUBLIC_MEMBER_ROLES, createPublicMembershipClient } from '../../lib/groupMembership';
import { publicRoleLabel } from '../../lib/publicWorkspaceNavigation';
import { MembersSection, type MembersSectionScope } from './MembersSection';

export function PublicMembersSection({
    workspaceId, workspaceName, viewerId, interactionDisabled, onBusyChange, onAccessChanged,
}: {
    workspaceId: string;
    workspaceName: string;
    viewerId: string;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    /** Re-read the workspace context after the caller's own role or access changed. */
    onAccessChanged: () => void;
}) {
    const scope = useMemo<MembersSectionScope>(() => ({
        kind: 'public',
        workspaceId,
        workspaceName,
        client: createPublicMembershipClient(workspaceId),
        roleLabel: publicRoleLabel,
        assignableOptions: PUBLIC_ASSIGNABLE_ROLE_OPTIONS,
        defaultBulkRole: 'DocumentManager',
        supportsLeave: false,
        noun: 'public workspace',
        introDescription: `The owner, admins and document managers of ${workspaceName}, and what each person can do here. The owner and admins manage membership.`,
        statusUnavailableCode: 'public_status_unavailable',
        writeConflictCode: 'public_workspace_write_conflict',
        demotedOwnerRole: 'DocumentManager',
        filterRoles: PUBLIC_MEMBER_ROLES,
    }), [workspaceId, workspaceName]);

    return (
        <MembersSection scope={scope} viewerId={viewerId} interactionDisabled={interactionDisabled}
            onBusyChange={onBusyChange} onAccessChanged={onAccessChanged} />
    );
}
