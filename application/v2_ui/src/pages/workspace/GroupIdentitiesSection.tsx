// GroupIdentitiesSection.tsx
// Bind the shared identities workbench to group or public workspace policy.

import { useMemo } from 'react';
import { IdentityWorkbenchSection } from '../../components/identities/IdentityWorkbenchSection';
import { createPublicIdentityWorkbench } from '../../lib/identityWorkbench';
import type { PublicWorkspaceContext } from '../../lib/workspaceContext';

export { IdentityWorkbenchSection as GroupIdentitiesSection };

export function PublicIdentitiesSection({ context }: { context: PublicWorkspaceContext }) {
    const adapter = useMemo(
        () => createPublicIdentityWorkbench(
            { kind: 'public', id: context.scope.id, name: context.workspace.name },
            context.identity_management,
        ),
        [context.scope.id, context.workspace.name, context.identity_management],
    );
    return (
        <IdentityWorkbenchSection
            adapter={adapter}
            syncEnabled={context.sections.sync.enabled}
            actionsEnabled={false}
            scopeNoun="workspace"
            connectorSurfaces="file sources"
            identityCapabilities={['file_sync']}
        />
    );
}
