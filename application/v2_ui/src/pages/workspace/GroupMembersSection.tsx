// GroupMembersSection.tsx
// The group workspace Members section (M7B): a thin wrapper that gives the shared MembersSection
// the group scope. The whole view lives in MembersSection.tsx; here we name the group's client,
// vocabulary, assignable roles, "leave" capability and error codes. The external props are
// unchanged, so the group page renders it exactly as before.

import { useMemo } from 'react';
import { groupRoleLabel } from '../../lib/groupWorkspaceNavigation';
import { ASSIGNABLE_ROLE_OPTIONS, GROUP_MEMBER_ROLES, createGroupMembershipClient } from '../../lib/groupMembership';
import { MembersSection, type MembersSectionScope } from './MembersSection';

export function GroupMembersSection({
    groupId, groupName, viewerId, interactionDisabled, onBusyChange, onAccessChanged, onLeft,
}: {
    groupId: string;
    groupName: string;
    viewerId: string;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    /** Re-read the workspace context after the caller's own role or access changed. */
    onAccessChanged: () => void;
    /** Leave the page after the caller left the group. */
    onLeft: () => void | Promise<void>;
}) {
    const scope = useMemo<MembersSectionScope>(() => ({
        kind: 'group',
        workspaceId: groupId,
        workspaceName: groupName,
        client: createGroupMembershipClient(groupId),
        roleLabel: groupRoleLabel,
        assignableOptions: ASSIGNABLE_ROLE_OPTIONS,
        defaultBulkRole: 'User',
        supportsLeave: true,
        noun: 'group',
        introDescription: `Everyone in ${groupName}, and what each person can do here. The owner and admins manage membership; anyone else can leave.`,
        statusUnavailableCode: 'group_status_unavailable',
        writeConflictCode: 'group_write_conflict',
        demotedOwnerRole: 'User',
        filterRoles: GROUP_MEMBER_ROLES,
    }), [groupId, groupName]);

    return (
        <MembersSection scope={scope} viewerId={viewerId} interactionDisabled={interactionDisabled}
            onBusyChange={onBusyChange} onAccessChanged={onAccessChanged} onLeft={onLeft} />
    );
}
