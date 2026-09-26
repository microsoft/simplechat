// PublicSettingsSection.tsx
// The public workspace Settings section (M10C): a thin wrapper that gives the shared
// WorkspaceSettingsSection the public scope -- the public reason texts, the configured workspace label
// and the public test ids. The whole view lives in WorkspaceSettingsSection.tsx.
//
// The danger zone describes deletion as it actually is. Deleting a public workspace removes only its
// record (functions_public_workspaces.delete_public_workspace): its documents, prompts, identities and
// file sources are not deleted with it, and the classic DELETE route checks nothing but ownership. The
// classic page itself refuses to start a delete while its own document count (every stored document
// record, earlier versions included) is above zero, so the copy says that of the page, never that the
// server enforces it. The count shown here is this workspace's own current documents, from the native
// file-count read, never classic's number.

import { useMemo } from 'react';
import { Globe } from 'lucide-react';
import type { GroupSettingsManagement } from '../../lib/groupSettings';
import { publicSettingsReasonText, type PublicSettingsAdapter } from '../../lib/publicSettings';
import { usePublicWorkspaceLabels } from '../../lib/publicWorkspaceLabels';
import { WorkspaceSettingsSection, type WorkspaceSettingsSectionScope } from './WorkspaceSettingsSection';

export function PublicSettingsSection({
    adapter, management, interactionDisabled, onBusyChange, onDirtyChange, onAccessChanged, onSaved, onOpenClassic,
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
    /** Open the classic public workspace page for the delete flow classic still owns. */
    onOpenClassic: () => void;
}) {
    const { singular, lower_singular: lowerSingular } = usePublicWorkspaceLabels();
    // Keyed on the label strings, which the bootstrap re-read may rebuild as a fresh object.
    const scope = useMemo<WorkspaceSettingsSectionScope>(() => ({
        testIdPrefix: 'public-settings',
        reasonText: publicSettingsReasonText,
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
            body: `Deleting removes only the ${lowerSingular} record. Its documents, prompts, identities and file `
                + `sources are left behind, not deleted with it. Deletion still happens on the classic ${lowerSingular} `
                + 'page, which counts documents itself, earlier versions included, and won\u2019t start while it finds any.',
            counting: `Counting the ${lowerSingular}\u2019s documents...`,
            count: (count) => (count === 0
                ? `This ${lowerSingular} holds no current documents.`
                : `This ${lowerSingular} holds ${count} current document${count === 1 ? '' : 's'}.`),
            button: `Delete ${lowerSingular} (classic)`,
            confirmTitle: `Delete this ${lowerSingular} in classic?`,
            confirmDescription: `Deletion is permanent and is completed on the classic ${lowerSingular} page. It removes `
                + `only the ${lowerSingular} record; its documents, prompts, identities and file sources stay behind. `
                + 'You\u2019ll be taken there to confirm.',
        },
    }), [singular, lowerSingular]);

    return (
        <WorkspaceSettingsSection scope={scope} adapter={adapter} management={management}
            interactionDisabled={interactionDisabled} onBusyChange={onBusyChange} onDirtyChange={onDirtyChange}
            onAccessChanged={onAccessChanged} onSaved={onSaved} onOpenClassic={onOpenClassic} />
    );
}
