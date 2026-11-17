// GroupMembersSection.tsx
// The group workspace Members section (M7B): a thin wrapper that gives the shared MembersSection
// the group scope. The whole view lives in MembersSection.tsx; here we name the group's client,
// vocabulary, assignable roles, "leave" capability and error codes. The external props are
// unchanged apart from the group's status, which only words why adding is closed.
//
// The Owner and Admins keep this section in a locked, inactive or unrecognized group, as on the
// classic manage page. The server's membership policy then withholds `add_member` (adding needs an
// active or upload-disabled group) and leaves every other operation, so the section shows its
// usual controls and says why Add member and Import CSV are missing.

import { useMemo } from 'react';
import { groupRoleLabel } from '../../lib/groupWorkspaceNavigation';
import { ASSIGNABLE_ROLE_OPTIONS, GROUP_MEMBER_ROLES, createGroupMembershipClient } from '../../lib/groupMembership';
import type { GroupWorkspaceStatus } from '../../lib/workspaceContext';
import { MembersSection, type MembersSectionScope } from './MembersSection';

const STILL_WORKS = 'Changing roles, removing members and reviewing requests to join still work.';

// Only the statuses the server refuses an add in carry a notice; `active` and `upload_disabled` take members.
const ADD_BLOCKED_NOTICES: Partial<Record<GroupWorkspaceStatus, string>> = {
    locked: `This group is locked, so members can\u2019t be added or imported. ${STILL_WORKS}`,
    inactive: `This group is inactive, so members can\u2019t be added or imported. ${STILL_WORKS}`,
    unknown: `This group\u2019s status isn\u2019t recognized, so members can\u2019t be added or imported. ${STILL_WORKS}`,
};

export function GroupMembersSection({
    groupId, groupName, groupStatus, viewerId, interactionDisabled, onBusyChange, onAccessChanged, onLeft,
}: {
    groupId: string;
    groupName: string;
    /** The group's status from the workspace context. */
    groupStatus: GroupWorkspaceStatus;
    viewerId: string;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    /** Re-read the workspace context after the caller's own role or access changed. */
    onAccessChanged: () => void;
    /** Leave the page after the caller left the group. */
    onLeft: () => void | Promise<void>;
}) {
    // The client is keyed on the group alone, so a status change that only rewords the notice never
    // rebuilds it and never reloads the member list.
    const client = useMemo(() => createGroupMembershipClient(groupId), [groupId]);
    const scope = useMemo<MembersSectionScope>(() => ({
        kind: 'group',
        workspaceId: groupId,
        workspaceName: groupName,
        client,
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
        addBlockedNotice: ADD_BLOCKED_NOTICES[groupStatus],
    }), [groupId, groupName, groupStatus, client]);

    return (
        <MembersSection scope={scope} viewerId={viewerId} interactionDisabled={interactionDisabled}
            onBusyChange={onBusyChange} onAccessChanged={onAccessChanged} onLeft={onLeft} />
    );
}
