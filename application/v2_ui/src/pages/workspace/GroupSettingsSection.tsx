// GroupSettingsSection.tsx
// The group workspace Settings section (M7C): a thin wrapper that gives the shared
// WorkspaceSettingsSection the group scope -- the group's reason texts, wording and test ids. The
// whole view lives in WorkspaceSettingsSection.tsx. The owner deletes the group from its danger
// zone, natively; `onDeleted` is how the page leaves once the group is gone.

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
        body: 'Deleting a group is permanent. It removes only the group and every member\u2019s access to it: its documents '
            + 'have to be removed first, and its conversations, prompts, agents, actions and other saved items are left '
            + 'behind, not deleted with it.',
        counting: 'Counting the group\u2019s documents...',
        count: (count) => (count === 0
            ? 'This group holds no documents.'
            : `This group holds ${count} document${count === 1 ? '' : 's'}. Remove them before deleting the group.`),
        button: 'Delete group',
        confirmTitle: 'Delete this group?',
        confirmDescription: (name) => `Delete ${name} permanently? Every member loses access to it right away, and `
            + 'this can\u2019t be undone.',
        confirmDetail: 'The group holds no documents. Its conversations, prompts, agents, actions and other saved items '
            + 'are left behind, not deleted with it.',
        confirmLabel: 'Delete group',
        checkFailed: 'The document count couldn\u2019t be checked, so the group wasn\u2019t deleted. Try again.',
        held: 'The group wasn\u2019t deleted because it still holds documents. Remove them first.',
        failed: 'The group couldn\u2019t be deleted. Try again.',
        gone: 'This group no longer exists. It may already have been deleted.',
        deleted: (name) => `${name} was deleted.`,
        leaving: 'The group was deleted. Returning to the group list...',
        unsaved: 'Save or discard your profile and retention changes before deleting the group.',
    },
};

export function GroupSettingsSection({
    adapter, management, interactionDisabled, onBusyChange, onDirtyChange, onAccessChanged, onSaved, onDeleted,
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
    /** Leave the group page once the group is deleted: read the groups again and return to the list. */
    onDeleted: () => void | Promise<void>;
}) {
    return (
        <WorkspaceSettingsSection scope={GROUP_SETTINGS_SCOPE} adapter={adapter} management={management}
            interactionDisabled={interactionDisabled} onBusyChange={onBusyChange} onDirtyChange={onDirtyChange}
            onAccessChanged={onAccessChanged} onSaved={onSaved} onDeleted={onDeleted} />
    );
}
