// PublicSettingsSection.tsx
// The public workspace Settings section (M10C): a thin wrapper that gives the shared
// WorkspaceSettingsSection the public scope -- the public reason texts, the configured workspace label
// and the public test ids. The whole view lives in WorkspaceSettingsSection.tsx.
//
// The danger zone describes deletion as it actually is. Deleting a public workspace removes only its
// record (functions_public_workspaces.delete_public_workspace): its documents, prompts, identities and
// file sources are not deleted with it, and the DELETE route checks nothing but ownership. Like classic's
// manage page, the section holds the delete while the workspace still has documents, so the count it
// quotes and enforces is this workspace's own current documents, from the native file-count read.

import { useMemo } from 'react';
import { Globe } from 'lucide-react';
import type { GroupSettingsManagement } from '../../lib/groupSettings';
import {
    PUBLIC_STATUS_UNAVAILABLE_REASON, PUBLIC_STATUS_UNRECOGNIZED_TEXT, publicSettingsReasonText,
    type PublicSettingsAdapter,
} from '../../lib/publicSettings';
import { usePublicWorkspaceLabels } from '../../lib/publicWorkspaceLabels';
import { WorkspaceSettingsSection, type WorkspaceSettingsSectionScope } from './WorkspaceSettingsSection';

export function PublicSettingsSection({
    adapter, management, interactionDisabled, onBusyChange, onDirtyChange, onAccessChanged, onSaved, onDeleted,
}: {
    adapter: PublicSettingsAdapter;
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
    /** Leave the workspace page once it is deleted: read the workspaces again and return to the list. */
    onDeleted: () => void | Promise<void>;
}) {
    const { singular, lower_singular: lowerSingular } = usePublicWorkspaceLabels();
    // Keyed on the label strings, which the bootstrap re-read may rebuild as a fresh object.
    const scope = useMemo<WorkspaceSettingsSectionScope>(() => ({
        testIdPrefix: 'public-settings',
        reasonText: publicSettingsReasonText,
        // The server's own sentences, kept verbatim rather than relabelled with the configured workspace label.
        statusReason: PUBLIC_STATUS_UNAVAILABLE_REASON,
        statusUnrecognized: PUBLIC_STATUS_UNRECOGNIZED_TEXT,
        introTitle: `${singular} settings`,
        introDescription: `The ${lowerSingular}'s profile, logo and policies. A locked control shows why it's unavailable to you.`,
        loadFailed: `The ${lowerSingular} settings could not be loaded. Please retry.`,
        unavailable: `The ${lowerSingular} settings could not be loaded.`,
        // The server's own refusal text (functions_public_settings.validate_public_workspace_name).
        nameTooLong: 'Workspace names can be at most 80 characters.',
        profileSaved: `${singular} profile saved.`,
        logoUpdated: `${singular} logo updated.`,
        logoRemoved: `${singular} logo removed.`,
        colourLabel: `${singular} colour`,
        previewLabel: `${singular} header preview`,
        previewPlaceholder: `${singular} name`,
        PreviewIcon: Globe,
        logoReadOnlyHint: 'PNG or JPEG, set by the workspace owner.',
        downloadsToggleLabel: `Turn off file downloads for this ${lowerSingular}`,
        downloadsHint: 'Its documents stay available in chat; nobody can download the original files.',
        danger: {
            title: `Delete this ${lowerSingular}`,
            body: `Deleting is permanent. It removes only the ${lowerSingular} record, so everyone loses access to it. `
                + `Its documents have to be removed first, and its prompts, identities and file sources are left behind, `
                + 'not deleted with it.',
            counting: `Counting the ${lowerSingular}\u2019s documents...`,
            count: (count) => (count === 0
                ? `This ${lowerSingular} holds no current documents.`
                : `This ${lowerSingular} holds ${count} current document${count === 1 ? '' : 's'}. `
                    + `Remove them before deleting the ${lowerSingular}.`),
            button: `Delete ${lowerSingular}`,
            confirmTitle: `Delete this ${lowerSingular}?`,
            confirmDescription: (name) => `Delete ${name} permanently? Everyone loses access to it right away, and `
                + 'this can\u2019t be undone.',
            confirmDetail: `The ${lowerSingular} holds no current documents. Its prompts, identities and file sources `
                + 'are left behind, not deleted with it.',
            confirmLabel: `Delete ${lowerSingular}`,
            checkFailed: `The document count couldn\u2019t be checked, so the ${lowerSingular} wasn\u2019t deleted. Try again.`,
            held: `The ${lowerSingular} wasn\u2019t deleted because it still holds documents. Remove them first.`,
            failed: `The ${lowerSingular} couldn\u2019t be deleted. Try again.`,
            gone: `This ${lowerSingular} no longer exists. It may already have been deleted.`,
            deleted: (name) => `${name} was deleted.`,
            leaving: `The ${lowerSingular} was deleted. Returning to the ${lowerSingular} list...`,
            unsaved: `Save or discard your profile and retention changes before deleting the ${lowerSingular}.`,
        },
    }), [singular, lowerSingular]);

    return (
        <WorkspaceSettingsSection scope={scope} adapter={adapter} management={management}
            interactionDisabled={interactionDisabled} onBusyChange={onBusyChange} onDirtyChange={onDirtyChange}
            onAccessChanged={onAccessChanged} onSaved={onSaved} onDeleted={onDeleted} />
    );
}
