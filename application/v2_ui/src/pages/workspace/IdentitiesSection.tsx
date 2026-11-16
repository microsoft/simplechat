// IdentitiesSection.tsx
// Personal workspace credentials use the same native workbench as shared workspaces.

import { useMemo } from 'react';
import { IdentityWorkbenchSection } from '../../components/identities/IdentityWorkbenchSection';
import {
    createPersonalIdentityWorkbench,
    type IdentityWorkbenchAdapter,
} from '../../lib/identityWorkbench';

export { authTypeLabel } from '../../lib/identityFields';

export function IdentitiesSection({
    syncEnabled,
    actionsEnabled,
    ownerId,
    adapter,
}: {
    syncEnabled: boolean;
    actionsEnabled: boolean;
    ownerId?: string;
    adapter?: IdentityWorkbenchAdapter;
}) {
    const personalAdapter = useMemo(() => createPersonalIdentityWorkbench(ownerId), [ownerId]);
    return (
        <IdentityWorkbenchSection
            key={ownerId}
            adapter={adapter ?? personalAdapter}
            syncEnabled={syncEnabled}
            actionsEnabled={actionsEnabled}
            scopeNoun="workspace"
        />
    );
}
