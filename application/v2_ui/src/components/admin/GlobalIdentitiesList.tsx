// GlobalIdentitiesList.tsx
// The administrator's deployment-wide saved credentials, created, edited and deleted in place.
//
// "Identity" reliably reads as a user sign-in rather than as a stored credential, so the card's
// own help text (from the section schema) is explicit about what these are and what consumes
// them, and it is shown as it is. The list, the editor, the conflict handling and the refusal to
// delete an identity something still uses are the identities workbench the workspaces use; what is
// specific here is the adapter, which reads and writes through the admin routes that name the
// global scope (lib/identityWorkbench.ts). Each change saves on its own, as the global agents and
// actions do, because these are records and not settings.

import { IdentityWorkbenchSection } from '../identities/IdentityWorkbenchSection';
import { GLOBAL_IDENTITY_WORKBENCH } from '../../lib/identityWorkbench';

export function GlobalIdentitiesList({ help }: { help?: string }) {
    return (
        <div className="min-w-0 py-3" data-testid="global-identities-list">
            <IdentityWorkbenchSection
                adapter={GLOBAL_IDENTITY_WORKBENCH}
                syncEnabled
                actionsEnabled
                scopeNoun="deployment"
                connectorSurfaces="File Sync sources and actions"
                presentation="admin"
                leadText={help}
            />
        </div>
    );
}
