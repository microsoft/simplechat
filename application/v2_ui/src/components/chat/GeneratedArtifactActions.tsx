// GeneratedArtifactActions.tsx
// "Add to workspace" and "Create PowerPoint" on a generated file's card.
//
// Classic's artifact card carries both buttons; V2's offered only Download and View. The rules for
// when each applies are in `lib/generatedArtifactActions.ts`. This draws the buttons, runs the two
// requests, and reports their outcomes the way the rest of V2 does: a pending toast for the
// PowerPoint, which can take a minute, and a status that stays on the card for the file.
//
// The two requests behave differently on purpose. A PowerPoint is built and downloaded, so a
// failure is a toast and the button is simply available again. Adding to a workspace creates
// something on the server, so its dialog stays open on a refusal with the reason inside it, and
// an answer the server could not confirm stays on the card as a warning rather than a success.

import { useState } from 'react';
import { Check, Clock, FolderPlus, Loader2, Presentation } from 'lucide-react';
import { downloadMessageExport, promoteGeneratedArtifact } from '../../lib/endpoints';
import { ApiError } from '../../lib/apiClient';
import { buildMessageVisualAssets } from '../../lib/exportVisuals';
import {
    POWERPOINT_PENDING_MESSAGE,
    POWERPOINT_SUCCESS_MESSAGE,
    artifactConversationId,
    canAddToWorkspace,
    canCreatePowerPoint,
    powerPointArtifactBody,
    promotionConflict,
    promotionErrorMessage,
    promotionOutcome,
    promotionRequestBody,
    resolvePromotionTargets,
    type PromotionTarget,
} from '../../lib/generatedArtifactActions';
import { artifactFileName, type GeneratedArtifact } from '../../lib/generatedArtifacts';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { promotionKey, useGeneratedArtifactActionStore } from '../../stores/generatedArtifactActionStore';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { ArtifactPromotionDialog } from './ArtifactPromotionDialog';

export function GeneratedArtifactActions({
    artifact,
    conversationId,
    messageId,
}: {
    artifact: GeneratedArtifact;
    /** The conversation the card is drawn in, for a file that does not name its own. */
    conversationId?: string;
    /** The reply carrying the file; a PowerPoint is built beside it. */
    messageId?: string;
}) {
    const storedIn = artifactConversationId(artifact, conversationId);
    const artifactMessageId = String(artifact.artifact_message_id ?? '').trim();
    const fileName = artifactFileName(artifact);

    const shared = useChatStore((state) => state.activeConversationKind === 'collaborative');
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const metadata = useChatStore((state) => state.metadata);
    const features = useBootstrapStore((state) => state.data?.features);
    const groups = useBootstrapStore((state) => state.data?.scope?.groups);
    const publicWorkspaces = useBootstrapStore((state) => state.data?.scope?.public_workspaces);
    const promotion = useGeneratedArtifactActionStore(
        (state) => state.promotions[promotionKey(storedIn, artifactMessageId)],
    );

    const [choosing, setChoosing] = useState(false);
    const [promoting, setPromoting] = useState(false);
    const [promoteError, setPromoteError] = useState<string | null>(null);
    const [exporting, setExporting] = useState(false);

    // The destination comes from the conversation's own metadata, so it is not offered until that
    // describes the conversation on screen: a stale or missing read would default to "personal".
    const loaded = metadata?.conversation_id === activeConversationId;
    const targets = loaded
        ? resolvePromotionTargets({
              metadata,
              groups: groups ?? [],
              publicWorkspaces: publicWorkspaces ?? [],
              available: {
                  personal: features?.enable_user_workspace !== false,
                  group: Boolean(features?.enable_group_workspaces),
                  public: Boolean(features?.enable_public_workspaces),
              },
          })
        : [];
    const mayAdd = canAddToWorkspace(artifact, storedIn, targets);
    const mayPowerPoint = canCreatePowerPoint(artifact, storedIn, {
        shared,
        messageId: messageId ?? '',
    });

    if (!mayAdd && !mayPowerPoint) {
        return null;
    }

    const promote = async (target: PromotionTarget) => {
        setPromoting(true);
        setPromoteError(null);
        const key = promotionKey(storedIn, artifactMessageId);
        try {
            const data = await promoteGeneratedArtifact(
                promotionRequestBody(storedIn, artifactMessageId, target),
            );
            const outcome = promotionOutcome(data, target);
            useGeneratedArtifactActionStore.getState().recordPromotion(key, {
                status: outcome.status,
                targetName: target.name,
                message: outcome.message,
            });
            if (outcome.status === 'unconfirmed') {
                toast.info(outcome.message);
            } else {
                toast.success(outcome.message);
            }
            setChoosing(false);
        } catch (error) {
            const conflict = promotionConflict(error);
            if (conflict) {
                useGeneratedArtifactActionStore.getState().recordPromotion(key, {
                    status: conflict.status,
                    targetName: target.name,
                    message: conflict.message,
                });
                toast.info(conflict.message);
                setChoosing(false);
            } else {
                setPromoteError(promotionErrorMessage(error));
            }
        } finally {
            setPromoting(false);
        }
    };

    const createPowerPoint = async () => {
        if (exporting || !messageId) {
            return;
        }
        setExporting(true);
        const pendingId = toast.pending(POWERPOINT_PENDING_MESSAGE);
        try {
            // Diagrams already drawn in the reply save the server a browser launch. It draws any
            // the file holds that were not sent, so a missing picture costs only the shortcut.
            const body = powerPointArtifactBody(
                artifact,
                storedIn,
                messageId,
                await buildMessageVisualAssets(messageId),
            );
            await downloadMessageExport('powerpoint', body);
            toast.settle(pendingId, 'success', POWERPOINT_SUCCESS_MESSAGE);
        } catch (error) {
            toast.settle(
                pendingId,
                'error',
                error instanceof ApiError && error.message
                    ? `PowerPoint export failed: ${error.message}`
                    : 'PowerPoint export failed.',
            );
        } finally {
            setExporting(false);
        }
    };

    const unconfirmed = promotion?.status === 'unconfirmed';

    return (
        <>
            {mayPowerPoint && (
                <GlassButton
                    size="sm"
                    variant="subtle"
                    onClick={() => void createPowerPoint()}
                    disabled={exporting}
                    aria-busy={exporting || undefined}
                    aria-label={`Create PowerPoint from ${fileName}`}
                >
                    {exporting ? (
                        <Loader2 size={13} className="animate-spin" aria-hidden="true" />
                    ) : (
                        <Presentation size={13} aria-hidden="true" />
                    )}
                    {exporting ? 'Creating' : 'Create PowerPoint'}
                </GlassButton>
            )}

            {mayAdd && promotion && !unconfirmed && (
                <span
                    role="status"
                    className={
                        promotion.status === 'added'
                            ? 'inline-flex h-8 items-center gap-1.5 rounded-xl bg-ok-soft px-3 text-sm font-medium text-ok'
                            : 'inline-flex h-8 items-center gap-1.5 rounded-xl bg-warn-soft px-3 text-sm font-medium text-warn'
                    }
                    title={`${promotion.message} (${promotion.targetName})`}
                >
                    {promotion.status === 'added' ? (
                        <Check size={13} aria-hidden="true" />
                    ) : (
                        <Clock size={13} aria-hidden="true" />
                    )}
                    {promotion.status === 'added' ? 'Added to workspace' : 'Pending approval'}
                </span>
            )}

            {mayAdd && (!promotion || unconfirmed) && (
                <GlassButton
                    size="sm"
                    variant="subtle"
                    onClick={() => {
                        setPromoteError(null);
                        setChoosing(true);
                    }}
                    disabled={promoting}
                    aria-haspopup="dialog"
                    aria-label={`${unconfirmed ? 'Check again' : 'Add to workspace'}: ${fileName}`}
                >
                    <FolderPlus size={13} aria-hidden="true" />
                    {unconfirmed ? 'Check again' : 'Add to workspace'}
                </GlassButton>
            )}

            {unconfirmed && promotion && (
                <p role="status" className="basis-full text-xs text-warn">
                    {promotion.message}
                </p>
            )}

            {choosing && targets.length > 0 && (
                <ArtifactPromotionDialog
                    fileName={fileName}
                    targets={targets}
                    busy={promoting}
                    error={promoteError}
                    onConfirm={(target) => void promote(target)}
                    onClose={() => setChoosing(false)}
                />
            )}
        </>
    );
}
