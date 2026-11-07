// FileApprovals.tsx
// Files the assistant generated in a shared conversation that are waiting on this reader's
// decision before anyone can download them.
//
// A generated file in a shared conversation is staged rather than released: the request
// came from one participant, but the file would become available to all of them, so the
// conversation's owner (or a group manager) decides. Until that decision the content is
// withheld from everybody, including the person who asked for it.
//
// Presented as a banner over the thread rather than inline on the message, because the
// endpoint answers across conversations — a file staged in a thread the reader is not
// currently looking at is exactly the one most likely to be forgotten.

import { useEffect, useState } from 'react';
import { FileLock2, Loader2 } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import { GlassButton } from '../ui/primitives';
import type { GeneratedFileApproval } from '../../lib/collaboration';

function describe(approval: GeneratedFileApproval): string {
    const requester = String(approval.approval?.requested_by_name ?? '').trim();
    const name = String(approval.file_name ?? '').trim() || 'A file';
    return requester
        ? `${requester} generated ${name} in a shared conversation.`
        : `${name} was generated in a shared conversation.`;
}

export function FileApprovals() {
    const enabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_collaborative_conversations),
    );
    const approvals = useCollaborationStore((state) => state.approvals);
    const loadApprovals = useCollaborationStore((state) => state.loadApprovals);
    const resolveApproval = useCollaborationStore((state) => state.resolveApproval);
    const [busyId, setBusyId] = useState<string | null>(null);

    useEffect(() => {
        if (enabled) {
            void loadApprovals();
        }
    }, [enabled, loadApprovals]);

    if (!enabled || approvals.length === 0) {
        return null;
    }

    const decide = async (approval: GeneratedFileApproval, decision: 'approve' | 'deny') => {
        setBusyId(approval.artifact_message_id);
        await resolveApproval(approval, decision);
        setBusyId(null);
    };

    return (
        <div className="mx-4 mt-4 space-y-2">
            {approvals.map((approval) => (
                <div
                    key={`${approval.source_conversation_id}:${approval.artifact_message_id}`}
                    className="glass-flat flex flex-wrap items-center gap-3 rounded-xl px-4 py-3"
                >
                    <FileLock2 size={16} className="shrink-0 text-warn" />
                    <p className="min-w-0 flex-1 text-sm text-text-1">
                        {describe(approval)} Approve it to make it available to everyone in
                        that conversation.
                    </p>
                    <div className="flex shrink-0 items-center gap-2">
                        {busyId === approval.artifact_message_id ? (
                            <Loader2 size={14} className="animate-spin text-text-3" />
                        ) : (
                            <>
                                <GlassButton
                                    size="sm"
                                    variant="primary"
                                    onClick={() => void decide(approval, 'approve')}
                                >
                                    Approve
                                </GlassButton>
                                <GlassButton
                                    size="sm"
                                    variant="danger"
                                    onClick={() => void decide(approval, 'deny')}
                                >
                                    Deny
                                </GlassButton>
                            </>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
}
