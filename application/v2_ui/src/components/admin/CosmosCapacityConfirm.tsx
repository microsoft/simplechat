// CosmosCapacityConfirm.tsx
// The confirmation in front of a Cosmos throughput change, shared by both throughput cards.
//
// A scale or conversion changes provisioned capacity -- and with it cost -- in Azure as soon
// as it is sent. Before it is, the dialog says which target changes, from what, and to what
// the server will most likely set it. The estimate follows `calculate_manual_scale_target`
// on the saved settings, because that is what the server uses; it is labelled an estimate,
// and the server's own result is reported once the change is made. When the estimate
// already says the change cannot happen, the dialog says why instead of sending it.

import { useMemo, useState } from 'react';
import type { Json } from '../../lib/types';
import {
    containerScalePolicy,
    databaseScalePolicy,
    estimateManualScaleTarget,
    readGlobalPolicy,
    type CosmosThroughputTarget,
    type ManualScalePolicy,
} from '../../lib/cosmosThroughput';
import { formatRu } from '../../lib/scaleFormat';
import { useScaleStatusStore, type PendingCapacityAction } from '../../stores/scaleStatusStore';
import { ConfirmActionModal } from './ConfirmActionModal';

export function CosmosCapacityConfirm({
    settings,
    unsavedThroughputEdits,
}: {
    /** The saved settings. Never the draft: the server applies what is saved. */
    settings: Json;
    unsavedThroughputEdits: boolean;
}) {
    const action = useScaleStatusStore((state) => state.pendingCapacityAction);
    const clearCapacityAction = useScaleStatusStore((state) => state.clearCapacityAction);
    const performCapacityAction = useScaleStatusStore((state) => state.performCapacityAction);
    const status = useScaleStatusStore((state) => state.throughput.status);
    const acting = useScaleStatusStore((state) => state.throughput.acting);
    // Each request is confirmed once. Another click before the dialog closes would send a
    // second change, a step on from the first.
    const [submitted, setSubmitted] = useState<PendingCapacityAction | null>(null);
    const sent = action !== null && submitted === action;

    const details = useMemo(() => {
        if (!action) {
            return null;
        }
        const globals = readGlobalPolicy((key) => settings[key]);
        let target: CosmosThroughputTarget | null | undefined;
        let policy: ManualScalePolicy;
        let subject: string;
        if (action.containerName) {
            const container = (status?.containers ?? []).find((item) => item.container_name === action.containerName);
            target = container;
            policy = container ? containerScalePolicy(container, globals) : databaseScalePolicy(globals);
            subject = `the ${action.containerName} container`;
        } else {
            target = status?.throughput;
            policy = databaseScalePolicy(globals);
            subject = `the ${status?.resource?.database_name || 'SimpleChat'} database`;
        }
        const estimate =
            action.kind === 'scale' && action.direction
                ? estimateManualScaleTarget(target, policy, action.direction)
                : null;
        return { target, policy, subject, estimate };
    }, [action, settings, status]);

    if (!action || !details) {
        return null;
    }

    const { target, policy, subject, estimate } = details;
    const blocked = Boolean(estimate?.error);
    const busy = acting || sent;
    const close = () => {
        if (!busy) {
            clearCapacityAction();
        }
    };
    const confirm = async () => {
        if (sent) {
            return;
        }
        setSubmitted(action);
        await performCapacityAction(action);
        clearCapacityAction();
    };

    const title =
        action.kind === 'convert'
            ? 'Convert to Cosmos autoscale'
            : action.direction === 'up'
                ? 'Scale throughput up'
                : 'Scale throughput down';

    return (
        <ConfirmActionModal
            title={title}
            confirmLabel={action.kind === 'convert' ? 'Convert to autoscale' : action.direction === 'up' ? 'Scale up' : 'Scale down'}
            busy={busy}
            confirmDisabled={blocked}
            onConfirm={() => void confirm()}
            onClose={close}
        >
            {action.kind === 'convert' ? (
                <>
                    <p>
                        Converts {subject} from manual {formatRu(target?.current_ru)} to native Cosmos autoscale. The
                        autoscale maximum keeps the current RU/s, rounded up to Cosmos autoscale increments, within
                        the saved guardrails.
                    </p>
                    <p className="text-text-3">
                        SimpleChat does not convert throughput back to manual; that is done in the Azure portal.
                    </p>
                </>
            ) : blocked ? (
                <p role="alert" className="text-warn">
                    {estimate?.error}
                </p>
            ) : (
                <>
                    <p>
                        Scales {subject} {action.direction} from{' '}
                        <span className="font-semibold text-text-1">{formatRu(target?.current_ru)}</span> to about{' '}
                        <span className="font-semibold text-text-1">{formatRu(estimate?.target)}</span>.
                    </p>
                    <p className="text-text-3">
                        {action.direction === 'up'
                            ? `Uses the saved step of ${formatRu(policy.scale_up_step_ru)}${policy.ignore_max_limit ? ', ignoring the maximum guardrail' : ` and stops at the ${formatRu(policy.max_ru)} maximum`}. SimpleChat never scales above 10,000 RU/s.`
                            : `Uses the saved step of ${formatRu(policy.scale_down_step_ru)}${policy.ignore_min_limit ? ', ignoring the minimum guardrail' : ` and stops at the ${formatRu(policy.min_ru)} minimum`}.`}{' '}
                        The change is made in Azure immediately and recorded in the admin activity log.
                    </p>
                </>
            )}
            {unsavedThroughputEdits ? (
                <p className="text-warn">
                    You have unsaved throughput changes. This uses the saved policy; save first if the change depends
                    on them.
                </p>
            ) : null}
        </ConfirmActionModal>
    );
}
