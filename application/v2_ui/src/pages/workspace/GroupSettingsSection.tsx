// GroupSettingsSection.tsx
// The group workspace Settings section (M7C): a thin wrapper that gives the shared
// WorkspaceSettingsSection the group scope -- the group's reason texts, wording and test ids. The
// whole view lives in WorkspaceSettingsSection.tsx; the external props are unchanged, so the group
// page renders it exactly as before.

import { Users } from 'lucide-react';
import {
    GROUP_STATUS_UNAVAILABLE_REASON, GROUP_STATUS_UNRECOGNIZED_TEXT, groupSettingsReasonText,
    type GroupSettingsAdapter, type GroupSettingsManagement,
} from '../../lib/groupSettings';
import { WorkspaceSettingsSection, type WorkspaceSettingsSectionScope } from './WorkspaceSettingsSection';

// The group's scope depends on nothing the page passes, so it is built once.
const GROUP_SETTINGS_SCOPE: WorkspaceSettingsSectionScope = {
    testIdPrefix: 'group-settings',
    reasonText: groupSettingsReasonText,
    statusReason: GROUP_STATUS_UNAVAILABLE_REASON,
    statusUnrecognized: GROUP_STATUS_UNRECOGNIZED_TEXT,
    introTitle: 'Group settings',
    introDescription: "The group's profile, logo and policies. A locked control shows why it's unavailable to you.",
    loadFailed: 'The group settings could not be loaded. Please retry.',
    unavailable: 'The group settings could not be loaded.',
    nameTooLong: 'Group names can be at most 80 characters.',
    profileSaved: 'Group profile saved.',
    logoUpdated: 'Group logo updated.',
    logoRemoved: 'Group logo removed.',
    colourLabel: 'Group colour',
    previewLabel: 'Group header preview',
    previewPlaceholder: 'Group name',
    PreviewIcon: Users,
    logoReadOnlyHint: 'PNG or JPEG, set by a group manager.',
    downloadsToggleLabel: 'Turn off file downloads for this group',
    downloadsHint: 'Members can still read documents in chat; they cannot download the original files.',
    danger: {
        title: 'Delete this group',
        body: "Deleting a group removes its members' access and its shared workspace. This still happens on the "
            + 'classic group page, where the prerequisites are checked.',
        counting: 'Counting the group\u2019s documents...',
        count: (count) => `This group holds ${count} document${count === 1 ? '' : 's'}. Remove them before deleting the group.`,
        button: 'Delete group (classic)',
        confirmTitle: 'Delete this group in classic?',
        confirmDescription: "Deleting a group is permanent and is completed on the classic group page. You'll be taken "
            + 'there to confirm the prerequisites.',
    },
};

export function GroupSettingsSection({
    adapter, management, interactionDisabled, onBusyChange, onDirtyChange, onAccessChanged, onSaved, onOpenClassic,
}: {
    adapter: GroupSettingsAdapter;
    /** The latest `settings_management` hint from the workspace context (see WorkspaceSettingsSection). */
    management: GroupSettingsManagement | undefined;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    onDirtyChange: (dirty: boolean) => void;
    /** Re-read the workspace context after a refusal that means the caller's own standing changed. */
    onAccessChanged: () => void;
    /** Re-read the workspace context after a successful profile or logo save, so the header follows. */
    onSaved: () => void;
    /** Open the classic group page for the delete flow classic still owns. */
    onOpenClassic: () => void;
}) {
    return (
        <WorkspaceSettingsSection scope={GROUP_SETTINGS_SCOPE} adapter={adapter} management={management}
            interactionDisabled={interactionDisabled} onBusyChange={onBusyChange} onDirtyChange={onDirtyChange}
            onAccessChanged={onAccessChanged} onSaved={onSaved} onOpenClassic={onOpenClassic} />
    );
}
