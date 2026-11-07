// GovernanceDialogHost.tsx
// Renders whichever governance dialog the store asks for.
//
// Mounted once by the Admin Settings page, so any section can open the item policy editor
// or a resource's access list without owning a dialog of its own.

import { entityTypeLabel, newItemPolicyDraft } from '../../../lib/governance';
import type { Json } from '../../../lib/types';
import {
    governancePoliciesChanged,
    useGovernanceStore,
    type GovernanceResourceTarget,
} from '../../../stores/governanceStore';
import { AdminModal } from '../AdminModal';
import { GlassButton } from '../../ui/primitives';
import { GovernanceItemPolicyEditor } from './GovernanceItemPolicyEditor';
import { GovernanceItemPolicyManager } from './GovernanceItemPolicyManager';

/** What a resource's access list says when no policy narrows it, by resource type. */
const ACCESS_EXPLANATIONS: Partial<Record<string, { intro: string; empty: string }>> = {
    global_endpoint: {
        intro: 'Global endpoint governance is always on. People must pass the Global Endpoints feature policy first, then any one of the policies listed here.',
        empty: 'No policy narrows this connection, so everyone who passes the Global Endpoints feature policy can use it.',
    },
};

function GovernanceResourceAccess({
    target,
    onClose,
}: {
    target: GovernanceResourceTarget;
    onClose: () => void;
}) {
    const explanation = ACCESS_EXPLANATIONS[target.entityType];
    const typeLabel = entityTypeLabel(target.entityType).toLowerCase();
    return (
        <AdminModal
            title={`Access to ${target.label}`}
            description={`Delegated item policies for this ${typeLabel}. They save as soon as you apply them.`}
            size="lg"
            onClose={onClose}
            footer={(
                <GlassButton type="button" size="sm" variant="ghost" onClick={onClose}>
                    Close
                </GlassButton>
            )}
        >
            <div className="@container space-y-3">
                {explanation ? <p className="text-xs leading-relaxed text-text-3">{explanation.intro}</p> : null}
                <GovernanceItemPolicyManager
                    entityTypes={[target.entityType]}
                    itemId={target.itemId}
                    newPolicy={() => newItemPolicyDraft({
                        entity_type: target.entityType,
                        item_id: target.itemId,
                        resource_label: target.label,
                    })}
                    newPolicyLabel="New access policy"
                    returnTo={target}
                    emptyText={explanation?.empty ?? 'No policy narrows this item yet.'}
                    label={`Access policies for ${target.label}`}
                />
            </div>
        </AdminModal>
    );
}

export function GovernanceDialogHost({ settings }: { settings: Json }) {
    const dialog = useGovernanceStore((state) => state.dialog);
    const close = useGovernanceStore((state) => state.close);

    if (!dialog) {
        return null;
    }

    if (dialog.kind === 'editor') {
        const { id } = dialog;
        return (
            <GovernanceItemPolicyEditor
                key={id}
                initial={dialog.request.draft}
                entityTypes={dialog.request.entityTypes}
                settings={settings}
                onClose={(saved) => {
                    if (saved) {
                        governancePoliciesChanged();
                    }
                    close(id);
                }}
            />
        );
    }

    const { id } = dialog;
    return <GovernanceResourceAccess key={id} target={dialog.target} onClose={() => close(id)} />;
}
