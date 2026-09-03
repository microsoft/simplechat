// ParticipantsPanel.tsx
// The People panel: who is in a shared conversation, and everything membership-related
// that can be done to it.
//
// Also the entry point for *making* a conversation shared. That is why the panel is driven
// by `panelTarget` rather than by the loaded shared conversation: it opens on ordinary
// personal and group conversations too, where there is no membership yet and the whole
// panel is an invite box.
//
// Every action here is gated on a capability flag the server computed
// (`serialize_collaboration_conversation`), never on a rule reimplemented in the browser.
// Those flags fold together membership status, role, visibility mode and whether membership
// is explicit at all, and a group-visibility conversation grants posting with no membership
// record to inspect — so a client-side guess would offer controls the server then refuses.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
    Crown,
    Loader2,
    LogOut,
    Search,
    Shield,
    Trash2,
    TriangleAlert,
    UserMinus,
    UserPlus,
    Users,
    X,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useCollaborationStore, participantName } from '../../stores/collaborationStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { fetchCollaboratorSuggestions, fetchGroupMembers } from '../../lib/collaboration';
import { GlassButton, GlassPanel, Skeleton } from '../ui/primitives';
import type { CollaborationParticipant, CollaboratorSuggestion } from '../../lib/types';

/** How long to wait after a keystroke before searching. */
const SEARCH_DEBOUNCE_MS = 250;

const ROLE_ICON: Record<string, React.ReactNode> = {
    owner: <Crown size={12} />,
    admin: <Shield size={12} />,
};

function RoleBadge({ participant }: { participant: CollaborationParticipant }) {
    const role = String(participant.role ?? 'member').toLowerCase();
    const status = String(participant.membership_status ?? '').toLowerCase();

    return (
        <span className="flex shrink-0 items-center gap-1.5">
            {status === 'pending' && (
                <span
                    title="This person has been invited but has not accepted yet"
                    className="rounded-full bg-warn-soft px-2 py-0.5 text-[10px] font-medium text-warn"
                >
                    invited
                </span>
            )}
            {role !== 'member' && (
                <span className="flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-medium text-accent">
                    {ROLE_ICON[role]}
                    {role}
                </span>
            )}
        </span>
    );
}

/**
 * Find people to add.
 *
 * Where the candidates come from depends on the conversation, and the difference matters: a
 * group conversation may only be shared with members of that group, so offering
 * directory-wide results there would suggest people the server refuses. Anything else draws
 * on the caller's recent collaborators and the directory.
 */
function InviteSearch({
    groupId,
    excludeUserIds,
    onInvite,
    busy,
}: {
    groupId?: string | null;
    excludeUserIds: Set<string>;
    onInvite: (participant: CollaborationParticipant) => void;
    busy: boolean;
}) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<CollaboratorSuggestion[]>([]);
    const [searching, setSearching] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);
    const requestRef = useRef(0);

    useEffect(() => {
        const requestId = requestRef.current + 1;
        requestRef.current = requestId;
        const controller = new AbortController();

        const timer = window.setTimeout(() => {
            setSearching(true);
            setError(null);

            const search = groupId
                ? fetchGroupMembers(groupId, query, controller.signal).then((members) =>
                      // The group route answers with a bare array and spells its fields in
                      // camelCase, unlike everything under /api/collaboration.
                      (members ?? []).map((member) => ({
                          user_id: String(member.userId ?? member.user_id ?? member.id ?? ''),
                          display_name: String(
                              member.displayName ?? member.display_name ?? member.name ?? '',
                          ),
                          email: String(member.email ?? ''),
                          source: 'group',
                      })),
                  )
                : fetchCollaboratorSuggestions(query, { limit: 8 }, controller.signal).then(
                      (payload) => payload.results ?? [],
                  );

            search
                .then((found) => {
                    // Discarded when a newer keystroke has already started its own search,
                    // so a slow earlier response cannot overwrite a fresher list.
                    if (requestRef.current !== requestId) {
                        return;
                    }
                    setResults(found);
                    setSearching(false);
                })
                .catch((cause) => {
                    if (requestRef.current !== requestId || controller.signal.aborted) {
                        return;
                    }
                    setSearching(false);
                    setError(
                        cause instanceof Error ? cause.message : 'Could not search for people.',
                    );
                });
        }, SEARCH_DEBOUNCE_MS);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [query, groupId]);

    const candidates = useMemo(
        () =>
            results.filter((candidate) => {
                const userId = String(candidate.user_id ?? '').trim();
                return userId && userId !== currentUserId && !excludeUserIds.has(userId);
            }),
        [results, excludeUserIds, currentUserId],
    );

    return (
        <div>
            <div className="relative">
                <Search
                    size={14}
                    className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                />
                <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={groupId ? 'Search group members' : 'Search people'}
                    aria-label="Search for people to add"
                    className="w-full rounded-lg border border-edge bg-surface-sunken py-2 pr-2.5 pl-8 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
            </div>

            {error && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-danger">
                    <TriangleAlert size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            )}

            <div className="mt-2 space-y-1">
                {searching && candidates.length === 0 && (
                    <Skeleton className="h-9 w-full" />
                )}

                {!searching && candidates.length === 0 && !error && (
                    <p className="px-1 py-2 text-xs text-text-3">
                        {query
                            ? 'Nobody matching that name can be added.'
                            : groupId
                              ? 'Everyone in this group is already here.'
                              : 'Start typing to find people to add.'}
                    </p>
                )}

                {candidates.map((candidate) => (
                    <button
                        key={candidate.user_id}
                        type="button"
                        disabled={busy}
                        onClick={() =>
                            onInvite({
                                user_id: String(candidate.user_id),
                                display_name: candidate.display_name,
                                email: candidate.email,
                            })
                        }
                        className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-text-1 transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        <UserPlus size={14} className="shrink-0 text-text-3" />
                        <span className="min-w-0 flex-1">
                            <span className="block truncate">
                                {candidate.display_name || candidate.email}
                            </span>
                            {candidate.email && candidate.display_name && (
                                <span className="block truncate text-[11px] text-text-3">
                                    {candidate.email}
                                </span>
                            )}
                        </span>
                    </button>
                ))}
            </div>
        </div>
    );
}

export function ParticipantsPanel() {
    const panelTarget = useCollaborationStore((state) => state.panelTarget);
    const conversation = useCollaborationStore((state) => state.panelConversation);
    const panelLoading = useCollaborationStore((state) => state.panelLoading);
    const closePanel = useCollaborationStore((state) => state.closePanel);
    const inviteParticipants = useCollaborationStore((state) => state.inviteParticipants);
    const removeParticipant = useCollaborationStore((state) => state.removeParticipant);
    const changeParticipantRole = useCollaborationStore((state) => state.changeParticipantRole);
    const leaveOrDelete = useCollaborationStore((state) => state.leaveOrDelete);
    const loadConversations = useChatStore((state) => state.loadConversations);
    const selectConversation = useChatStore((state) => state.selectConversation);
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);

    const [busy, setBusy] = useState(false);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                closePanel();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [closePanel]);

    if (!panelTarget) {
        return null;
    }

    /**
     * Whether this panel is showing a conversation that is already shared.
     *
     * An unshared conversation has no membership to load, and the panel is purely an invite
     * box. A shared one whose membership has not arrived is a third state, and is treated as
     * offering nothing rather than everything — the safe direction, since these flags decide
     * whether a "Delete for everyone" button appears.
     */
    const isSharedTarget = panelTarget.kind === 'collaborative';
    const shared = isSharedTarget && conversation?.id === panelTarget.conversationId;
    const loadingMembership = isSharedTarget && !shared;
    const participants = shared ? (conversation?.participants ?? []) : [];
    const canManageMembers = isSharedTarget
        ? shared && Boolean(conversation?.can_manage_members)
        : true;
    const canManageRoles = shared && Boolean(conversation?.can_manage_roles);
    const canDelete = shared && Boolean(conversation?.can_delete_conversation);
    const canLeave = shared && Boolean(conversation?.can_leave_conversation);
    const groupId = panelTarget.groupId ?? (shared ? conversation?.group_id : null) ?? null;

    const existingIds = new Set(
        participants.map((participant) => String(participant.user_id ?? '').trim()),
    );

    const invite = async (participant: CollaborationParticipant) => {
        setBusy(true);
        try {
            const result = await inviteParticipants([participant]);
            // Sharing an unshared conversation creates a *new* one and leaves the original
            // in place as the hidden source the AI runs in, so the reader has to be moved to
            // the conversation that now holds the thread.
            const nextId = result.conversation?.id;
            await loadConversations({ reset: true });
            if (nextId && nextId !== panelTarget.conversationId) {
                await selectConversation(nextId, { kind: 'collaborative' });
            }
            toast.success(`${participantName(participant)} was invited.`);
        } catch (error) {
            toast.error(
                error instanceof Error ? error.message : 'Could not add that person.',
            );
        } finally {
            setBusy(false);
        }
    };

    const remove = async (participant: CollaborationParticipant) => {
        setBusy(true);
        try {
            await removeParticipant(String(participant.user_id));
            toast.success(`${participantName(participant)} was removed.`);
        } catch (error) {
            toast.error(
                error instanceof Error ? error.message : 'Could not remove that person.',
            );
        } finally {
            setBusy(false);
        }
    };

    const setRole = async (participant: CollaborationParticipant, role: 'admin' | 'member') => {
        setBusy(true);
        try {
            await changeParticipantRole(String(participant.user_id), role);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not change that role.');
        } finally {
            setBusy(false);
        }
    };

    const exitConversation = async (action: 'leave' | 'delete') => {
        setBusy(true);
        const done = await leaveOrDelete(action);
        setBusy(false);
        if (done) {
            await loadConversations({ reset: true });
            await selectConversation(null);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Conversation participants"
        >
            <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={closePanel} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[85vh] w-full max-w-lg flex-col"
            >
                <div className="flex h-14 shrink-0 items-center gap-2 border-b border-edge px-5">
                    <Users size={16} className="text-text-3" />
                    <h2 className="min-w-0 truncate text-[15px] font-semibold text-text-1">
                        {shared ? 'People in this conversation' : 'Share this conversation'}
                    </h2>
                    <button
                        type="button"
                        onClick={closePanel}
                        aria-label="Close participants"
                        className="ml-auto rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
                    {!isSharedTarget && (
                        <p className="text-sm text-text-2">
                            Adding somebody turns this into a shared conversation. Everyone
                            invited can read the whole thread and reply in it.
                        </p>
                    )}

                    {loadingMembership && (
                        <div className="space-y-2">
                            {panelLoading ? (
                                Array.from({ length: 3 }).map((_, index) => (
                                    <Skeleton key={index} className="h-9 w-full" />
                                ))
                            ) : (
                                <p className="flex items-start gap-1.5 text-sm text-danger">
                                    <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                                    The people in this conversation could not be loaded.
                                </p>
                            )}
                        </div>
                    )}

                    {shared && participants.length > 0 && (
                        <ul className="space-y-1">
                            {participants.map((participant) => {
                                const userId = String(participant.user_id ?? '').trim();
                                const isSelf = userId === currentUserId;
                                const role = String(participant.role ?? 'member').toLowerCase();
                                return (
                                    <li
                                        key={userId}
                                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-2"
                                    >
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-sm text-text-1">
                                                {participantName(participant)}
                                                {isSelf && (
                                                    <span className="text-text-3"> (you)</span>
                                                )}
                                            </span>
                                            {participant.email && (
                                                <span className="block truncate text-[11px] text-text-3">
                                                    {participant.email}
                                                </span>
                                            )}
                                        </span>

                                        <RoleBadge participant={participant} />

                                        {/* Ownership is not assignable: it moves by being
                                            handed on when an owner leaves, so an owner row
                                            offers no role control. */}
                                        {canManageRoles && !isSelf && role !== 'owner' && (
                                            <button
                                                type="button"
                                                disabled={busy}
                                                onClick={() =>
                                                    void setRole(
                                                        participant,
                                                        role === 'admin' ? 'member' : 'admin',
                                                    )
                                                }
                                                className="shrink-0 rounded-md p-1.5 text-text-3 transition-colors hover:bg-surface-3 hover:text-text-1 disabled:opacity-40"
                                                title={
                                                    role === 'admin'
                                                        ? 'Make a member'
                                                        : 'Make an admin'
                                                }
                                                aria-label={
                                                    role === 'admin'
                                                        ? `Make ${participantName(participant)} a member`
                                                        : `Make ${participantName(participant)} an admin`
                                                }
                                            >
                                                <Shield size={14} />
                                            </button>
                                        )}

                                        {canManageMembers && !isSelf && role !== 'owner' && (
                                            <button
                                                type="button"
                                                disabled={busy}
                                                onClick={() => void remove(participant)}
                                                className="shrink-0 rounded-md p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                                                title="Remove from conversation"
                                                aria-label={`Remove ${participantName(participant)}`}
                                            >
                                                <UserMinus size={14} />
                                            </button>
                                        )}
                                    </li>
                                );
                            })}
                        </ul>
                    )}

                    {canManageMembers ? (
                        <InviteSearch
                            groupId={groupId}
                            excludeUserIds={existingIds}
                            onInvite={(participant) => void invite(participant)}
                            busy={busy}
                        />
                    ) : (
                        shared && (
                            <p className="text-xs text-text-3">
                                Only an owner or admin of this conversation can add or remove
                                people.
                            </p>
                        )
                    )}
                </div>

                {(canLeave || canDelete) && (
                    <div className="flex shrink-0 items-center gap-2 border-t border-edge px-5 py-3">
                        {canLeave && (
                            <GlassButton
                                size="sm"
                                disabled={busy}
                                onClick={() => void exitConversation('leave')}
                            >
                                <LogOut size={14} /> Leave conversation
                            </GlassButton>
                        )}
                        {canDelete && (
                            <GlassButton
                                size="sm"
                                variant="danger"
                                disabled={busy}
                                onClick={() => void exitConversation('delete')}
                            >
                                <Trash2 size={14} /> Delete for everyone
                            </GlassButton>
                        )}
                        {busy && <Loader2 size={14} className="ml-auto animate-spin text-text-3" />}
                    </div>
                )}
            </GlassPanel>
        </div>
    );
}
