// ConversationBadges.tsx
// Classification pills, the workspace badge, and the scope-lock indicator shown beside a
// conversation title.

import { clsx } from 'clsx';
import { Lock, Unlock } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    classificationColor,
    classificationLabels,
    isLightColor,
    scopeLockState,
    workspaceBadge,
    type ClassificationCategory,
    type WorkspaceBadgeTone,
} from '../../lib/conversationBadges';
import type { ConversationMetadata } from '../../lib/types';

/** Tones mirror the classic interface's badge colours so the two read the same. */
const TONE_CLASS: Record<WorkspaceBadgeTone, string> = {
    group: 'bg-info-soft text-info border-info/30',
    public: 'bg-ok-soft text-ok border-ok/30',
    shared: 'bg-accent-soft text-accent border-accent/30',
};

const TONE_TITLE: Record<WorkspaceBadgeTone, string> = {
    group: 'This conversation is working in a group workspace',
    public: 'This conversation is working in a public workspace',
    shared: 'This conversation is shared with other people',
};

export function ConversationBadges({
    metadata,
}: {
    metadata: ConversationMetadata | null | undefined;
}) {
    const classificationEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_document_classification),
    );
    const categories = useBootstrapStore(
        (state) =>
            (state.data?.settings?.document_classification_categories ?? []) as
                | ClassificationCategory[]
                | undefined,
    );

    const badge = workspaceBadge(metadata);
    const labels = classificationEnabled ? classificationLabels(metadata) : [];
    const lock = scopeLockState(metadata);

    if (!badge && labels.length === 0 && lock === 'hidden') {
        return null;
    }

    return (
        <div className="flex shrink-0 items-center gap-1.5">
            {lock !== 'hidden' && (
                <span
                    title={
                        lock === 'locked'
                            ? 'Workspace scope is locked for this conversation'
                            : 'Workspace scope is unlocked for this conversation'
                    }
                    className={clsx(lock === 'locked' ? 'text-warn' : 'text-text-3')}
                >
                    {lock === 'locked' ? <Lock size={13} /> : <Unlock size={13} />}
                </span>
            )}

            {labels.map((label) => {
                const color = classificationColor(label, categories);
                return (
                    <span
                        key={label}
                        title={
                            color
                                ? `Classification: ${label}`
                                : `Classification "${label}" has no definition in this deployment`
                        }
                        style={color ? { backgroundColor: color } : undefined}
                        className={clsx(
                            'rounded-full px-2 py-0.5 text-[11px] font-medium',
                            color
                                ? isLightColor(color)
                                    ? 'text-slate-900'
                                    : 'text-white'
                                : 'bg-warn-soft text-warn',
                        )}
                    >
                        {label}
                    </span>
                );
            })}

            {badge && (
                <span
                    title={TONE_TITLE[badge.tone]}
                    className={clsx(
                        'max-w-[12rem] truncate rounded-full border px-2 py-0.5 text-[11px] font-medium',
                        TONE_CLASS[badge.tone],
                    )}
                >
                    {badge.label}
                </span>
            )}
        </div>
    );
}
