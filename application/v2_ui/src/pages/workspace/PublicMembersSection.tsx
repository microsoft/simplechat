// PublicMembersSection.tsx
// The public workspace Members section (M10A): a thin wrapper that gives the shared MembersSection
// the public scope. The whole view lives in MembersSection.tsx; here we name the public client,
// vocabulary and error codes, the public assignable roles (Admin and Document manager only), and
// the deliberate absence of a "leave" control (decision 17: a public manager can't step down).
//
// A public workspace has no `users[]` roster: its members are exactly the Owner, the Admins and
// the Document managers, so the copy speaks of managing the workspace rather than everyone in it,
// and it never says "group".
//
// The Owner and Admins keep this section in a locked, inactive or unrecognized-status workspace, as
// on the classic manage page. The server's membership policy then withholds `add_member` and
// `change_role` (both need an active or upload-disabled workspace) and leaves removing members,
// reviewing requests and transferring ownership, so the section shows its remaining controls and
// says why Add member, Import CSV and the role selects are missing.

import { useMemo } from 'react';
import { PUBLIC_ASSIGNABLE_ROLE_OPTIONS, PUBLIC_MEMBER_ROLES, createPublicMembershipClient } from '../../lib/groupMembership';
import { publicRoleLabel } from '../../lib/publicWorkspaceNavigation';
import type { GroupWorkspaceStatus } from '../../lib/workspaceContext';
import { MembersSection, type MembersSectionScope } from './MembersSection';

const STILL_WORKS = 'Removing members, reviewing requests to join and, for the owner, transferring ownership still work.';

// Only the statuses the server refuses an add and a role change in carry a notice; `active` and
// `upload_disabled` take members. The words say "workspace" because this section's copy doesn't
// carry the administrator's workspace label.
const MEMBER_CHANGES_BLOCKED_NOTICES: Partial<Record<GroupWorkspaceStatus, string>> = {
    locked: `This workspace is locked, so members can\u2019t be added or imported and roles can\u2019t be changed. ${STILL_WORKS}`,
    inactive: `This workspace is inactive, so members can\u2019t be added or imported and roles can\u2019t be changed. ${STILL_WORKS}`,
    unknown: `This workspace\u2019s status isn\u2019t recognized, so members can\u2019t be added or imported and roles can\u2019t be changed. ${STILL_WORKS}`,
};

export function PublicMembersSection({
    workspaceId, workspaceName, workspaceStatus, viewerId, interactionDisabled, onBusyChange, onAccessChanged,
}: {
    workspaceId: string;
    workspaceName: string;
    /** The workspace's status from the workspace context. */
    workspaceStatus: GroupWorkspaceStatus;
    viewerId: string;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    /** Re-read the workspace context after the caller's own role or access changed. */
    onAccessChanged: () => void;
}) {
    // The client is keyed on the workspace alone, so a status change that only rewords the notice never
    // rebuilds it and never reloads the member list.
    const client = useMemo(() => createPublicMembershipClient(workspaceId), [workspaceId]);
    const scope = useMemo<MembersSectionScope>(() => ({
        kind: 'public',
        workspaceId,
        workspaceName,
        client,
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
        addBlockedNotice: MEMBER_CHANGES_BLOCKED_NOTICES[workspaceStatus],
    }), [workspaceId, workspaceName, workspaceStatus, client]);

    return (
        <MembersSection scope={scope} viewerId={viewerId} interactionDisabled={interactionDisabled}
            onBusyChange={onBusyChange} onAccessChanged={onAccessChanged} />
    );
}
