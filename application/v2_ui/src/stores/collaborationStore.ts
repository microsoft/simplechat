// collaborationStore.ts
// State that only exists for a shared conversation: its membership, who is typing, what
// the composer is replying to, and the participants panel.
//
// Deliberately separate from `chatStore`, and deliberately importing nothing from it. A
// shared conversation is still a conversation — its messages, streaming and rail row are
// `chatStore`'s job exactly as for a personal one — so folding this in would put a large
// amount of state on every reader of a thread that will never have participants. Keeping
// the dependency one-way (chatStore -> collaborationStore) also means the event handler in
// `lib/collaborationEvents.ts` can write to both without a cycle between the two stores.

import { create } from 'zustand';
import {
    collaborationDeleteAction,
    fetchCollaborationConversation,
    fetchGeneratedFileApprovals,
    inviteCollaborationMembers,
    removeCollaborationMember,
    resolveGeneratedFileApproval,
    respondToCollaborationInvite,
    sharePersonalConversation,
    shareGroupConversation,
    updateCollaborationMemberRole,
    type GeneratedFileApproval,
    type InviteResult,
} from '../lib/collaboration';
import { conversationFactsOnly } from '../lib/collaborationEvents';
import { toast } from './toastStore';
import { useUserSettingsStore } from './userSettingsStore';
import type {
    CollaborationConversation,
    CollaborationParticipant,
    CollaborationReplyContext,
    MembershipRole,
} from '../lib/types';

/**
 * How many recent collaborators to remember.
 *
 * Matches `MAX_RECENT_COLLABORATORS` in chat-collaboration.js so the two interfaces read
 * and write the same preference without one of them silently truncating the other's list.
 */
const MAX_RECENT_COLLABORATORS = 12;
const RECENT_COLLABORATORS_KEY = 'recentCollaborators';

/**
 * What the participants panel is acting on.
 *
 * The panel opens on conversations that are *not yet shared*, which is the whole point of
 * the Share action, so it cannot simply read the loaded `CollaborationConversation` —
 * there is not one yet. `kind` is what decides which of the three invite endpoints applies,
 * mirroring `addParticipantToConversation` in the classic client.
 */
export interface ParticipantsPanelTarget {
    conversationId: string;
    kind: 'collaborative' | 'personal' | 'group';
    title?: string;
    /** Set for group-scoped conversations, whose invitees come from the group's members. */
    groupId?: string | null;
}

/** Somebody currently typing, with the moment the server's claim stops being true. */
export interface TypingUser {
    user_id: string;
    display_name: string;
    expiresAt: number;
}

interface CollaborationState {
    /**
     * The conversation the chat page has open, mirrored here by `chatStore`.
     *
     * Held so this store can enforce its own invariant rather than trusting each caller to.
     * Mirrored rather than imported because `chatStore` already depends on this module, and
     * reading back the other way would make the two mutually dependent.
     */
    activeConversationId: string | null;

    /** Membership and capabilities for the open shared conversation, or null. */
    conversation: CollaborationConversation | null;
    conversationLoading: boolean;
    conversationError: string | null;

    /**
     * Membership for whatever the participants panel is showing.
     *
     * Deliberately a second slot rather than reusing `conversation`. The panel can be opened
     * from the rail on a conversation that is not the one on screen, and sharing one slot
     * meant doing so evicted the open conversation's capability flags — after which its
     * composer, invite prompt and per-message controls were all deciding from either
     * nothing or another conversation's permissions.
     */
    panelConversation: CollaborationConversation | null;
    panelLoading: boolean;

    typingUsers: TypingUser[];

    /** The message the composer is replying to, or null when it is not. */
    replyTo: CollaborationReplyContext | null;

    panelTarget: ParticipantsPanelTarget | null;

    approvals: GeneratedFileApproval[];
    approvalsLoading: boolean;

    /** Record which conversation the chat page has open. Called only by `chatStore`. */
    setActiveConversation: (conversationId: string | null) => void;
    /**
     * Replace the loaded conversation with one fetched for this user.
     *
     * Ignores anything that is not the open conversation. Several callers write here after
     * an `await` — a metadata load, a posted message, an invite response — and the reader can
     * have moved on by then. Enforcing it once here rather than at each call site is what
     * makes it impossible to forget: a stale write leaves the composer, the reply controls
     * and the mention roster all deciding from another conversation's membership.
     */
    setConversation: (conversation: CollaborationConversation | null) => void;
    /**
     * Apply a conversation that arrived over the event stream.
     *
     * Only the fields that mean the same thing to everybody are taken; the viewer-scoped
     * ones are left alone, because a broadcast carries the permissions of whoever triggered
     * the event rather than the reader's. See `conversationFactsOnly`.
     */
    applyBroadcast: (conversation: CollaborationConversation) => void;
    loadConversation: (conversationId: string) => Promise<void>;
    /** Drop everything belonging to the conversation being left. */
    reset: () => void;

    applyTyping: (
        user: CollaborationParticipant | undefined,
        isTyping: boolean,
        expiresAt: string | undefined,
        currentUserId: string | undefined,
    ) => void;

    setReplyTo: (reply: CollaborationReplyContext | null) => void;

    openPanel: (target: ParticipantsPanelTarget) => void;
    closePanel: () => void;
    /**
     * Add people, sharing the conversation first if it is not shared yet.
     *
     * Resolves with the server's result so the caller can follow the conversation id it
     * returns — sharing mints a new conversation rather than converting this one in place.
     */
    inviteParticipants: (participants: CollaborationParticipant[]) => Promise<InviteResult>;
    removeParticipant: (memberUserId: string) => Promise<void>;
    changeParticipantRole: (memberUserId: string, role: MembershipRole) => Promise<void>;
    respondToInvite: (action: 'accept' | 'decline') => Promise<boolean>;
    /** Leave, or delete for everybody. Resolves true when the conversation is gone for this user. */
    leaveOrDelete: (
        action: 'leave' | 'delete',
        newOwnerUserId?: string,
    ) => Promise<boolean>;

    loadApprovals: () => Promise<void>;
    resolveApproval: (
        approval: GeneratedFileApproval,
        decision: 'approve' | 'deny',
    ) => Promise<void>;
}

/**
 * Timer that sweeps expired typing entries.
 *
 * Held outside the store because it is bookkeeping, not render state. A single sweep is
 * used rather than one timeout per typist so a busy conversation does not accumulate
 * timers, and so an entry whose `expires_at` has passed disappears even if that person's
 * "stopped typing" ping never arrived.
 */
let typingSweep: ReturnType<typeof setInterval> | null = null;

/**
 * The conversation id of the most recent detail request.
 *
 * Used to discard a response that arrives after the reader has moved to another
 * conversation, which would otherwise apply one thread's capability flags to another.
 */
let latestConversationRequest: string | null = null;

function stopTypingSweep() {
    if (typingSweep !== null) {
        clearInterval(typingSweep);
        typingSweep = null;
    }
}

/**
 * Read a member's display name, falling back to something showable.
 *
 * Typed on the two fields it reads rather than on `CollaborationParticipant`, because it is
 * also used on a message's `sender`, which carries the same names but no guaranteed id.
 */
export function participantName(
    participant: { display_name?: string; email?: string } | undefined,
): string {
    const name = String(participant?.display_name ?? '').trim();
    if (name) {
        return name;
    }
    const email = String(participant?.email ?? '').trim();
    return email || 'Unknown participant';
}

export const useCollaborationStore = create<CollaborationState>((set, get) => {
    /** Drop typists whose claim has expired, and stop sweeping once none are left. */
    const sweepTyping = () => {
        const now = Date.now();
        const remaining = get().typingUsers.filter((entry) => entry.expiresAt > now);
        if (remaining.length !== get().typingUsers.length) {
            set({ typingUsers: remaining });
        }
        if (remaining.length === 0) {
            stopTypingSweep();
        }
    };

    const startTypingSweep = () => {
        if (typingSweep === null) {
            typingSweep = setInterval(sweepTyping, 1000);
        }
    };

    /** The conversation actions operate on, or a rejection describing why there is none. */
    const requireConversationId = (): string => {
        // The panel target wins over the loaded conversation. The panel can be opened on a
        // conversation that is not the one currently loaded — sharing a personal
        // conversation from the rail, for instance — and acting on the loaded one would
        // silently address a different conversation from the one on screen.
        const conversationId =
            get().panelTarget?.conversationId ?? get().conversation?.id ?? '';
        if (!conversationId) {
            throw new Error('No shared conversation is open.');
        }
        return conversationId;
    };

    /**
     * Apply a conversation the server serialized for *this* reader.
     *
     * Written to whichever slots hold that conversation. Unlike `applyBroadcast` this takes
     * the capability flags as they stand, because a direct response is computed for the
     * caller rather than for whoever triggered an event.
     */
    const applyForViewer = (conversation: CollaborationConversation) => {
        set((state) => ({
            conversation:
                state.conversation?.id === conversation.id ? conversation : state.conversation,
            panelConversation:
                state.panelTarget?.conversationId === conversation.id
                    ? conversation
                    : state.panelConversation,
        }));
    };

    return {
        activeConversationId: null,
        conversation: null,
        conversationLoading: false,
        conversationError: null,
        panelConversation: null,
        panelLoading: false,
        typingUsers: [],
        replyTo: null,
        panelTarget: null,
        approvals: [],
        approvalsLoading: false,

        setActiveConversation: (activeConversationId) => set({ activeConversationId }),

        setConversation: (conversation) => {
            if (conversation && conversation.id !== get().activeConversationId) {
                return;
            }
            set({ conversation });
        },

        applyBroadcast: (conversation) => {
            const facts = conversationFactsOnly(conversation);
            set((state) => ({
                conversation:
                    state.conversation?.id === conversation.id
                        ? { ...state.conversation, ...facts }
                        : state.conversation,
                panelConversation:
                    state.panelConversation?.id === conversation.id
                        ? { ...state.panelConversation, ...facts }
                        : state.panelConversation,
            }));
        },

        loadConversation: async (conversationId) => {
            latestConversationRequest = conversationId;
            set({ conversationLoading: true, conversationError: null });
            try {
                const { conversation } = await fetchCollaborationConversation(conversationId);
                // The load is fired on every conversation change and the reader can move on
                // while one is in flight. Without this check the previous thread's membership
                // and capability flags would land on the newly opened one, which decides
                // whether the composer is enabled.
                if (latestConversationRequest !== conversationId) {
                    return;
                }
                set({ conversationLoading: false });
                // Through the guarded setter, so a conversation that is no longer the open
                // one is dropped rather than applied.
                get().setConversation(conversation);
            } catch (error) {
                if (latestConversationRequest !== conversationId) {
                    return;
                }
                set({
                    conversationLoading: false,
                    conversationError:
                        error instanceof Error
                            ? error.message
                            : 'Failed to load the shared conversation.',
                });
            }
        },

        reset: () => {
            stopTypingSweep();
            latestConversationRequest = null;
            set({
                conversation: null,
                conversationLoading: false,
                conversationError: null,
                typingUsers: [],
                replyTo: null,
            });
        },
        applyTyping: (user, isTyping, expiresAt, currentUserId) => {
            const userId = String(user?.user_id ?? '').trim();
            // The event stream echoes the sender's own pings back. Showing "You are typing"
            // under the composer would be absurd, so they are dropped here rather than at
            // every read site.
            if (!userId || userId === currentUserId) {
                return;
            }

            if (!isTyping) {
                set((state) => ({
                    typingUsers: state.typingUsers.filter((entry) => entry.user_id !== userId),
                }));
                return;
            }

            // The server's own expiry is preferred over a local guess so every participant
            // agrees on when the indicator goes away; eight seconds matches what
            // `collaboration_typing_api` sets when the header is missing or unparseable.
            const parsed = expiresAt ? Date.parse(expiresAt) : Number.NaN;
            const expires = Number.isFinite(parsed) ? parsed : Date.now() + 8000;

            set((state) => ({
                typingUsers: [
                    ...state.typingUsers.filter((entry) => entry.user_id !== userId),
                    { user_id: userId, display_name: participantName(user), expiresAt: expires },
                ],
            }));
            startTypingSweep();
        },

        setReplyTo: (replyTo) => set({ replyTo }),

        openPanel: (panelTarget) => {
            set({ panelTarget, panelConversation: null });

            if (panelTarget.kind !== 'collaborative') {
                // Not shared yet, so there is no membership to fetch: the panel is purely an
                // invite box until somebody is added.
                return;
            }

            // Reused when the panel is opened on the conversation already on screen, which
            // is the header button's case and needs no request.
            const open = get().conversation;
            if (open?.id === panelTarget.conversationId) {
                set({ panelConversation: open });
                return;
            }

            set({ panelLoading: true });
            void fetchCollaborationConversation(panelTarget.conversationId)
                .then(({ conversation }) => {
                    // Discarded if the panel has since been closed or re-pointed, so a slow
                    // response cannot show one conversation's membership under another's
                    // heading.
                    if (get().panelTarget?.conversationId !== conversation.id) {
                        return;
                    }
                    set({ panelConversation: conversation, panelLoading: false });
                })
                .catch(() => {
                    if (get().panelTarget?.conversationId !== panelTarget.conversationId) {
                        return;
                    }
                    // Left unloaded rather than guessed at: the panel treats an unloaded
                    // shared conversation as offering nothing, which is the safe direction.
                    set({ panelLoading: false });
                });
        },
        closePanel: () => set({ panelTarget: null, panelConversation: null, panelLoading: false }),

        inviteParticipants: async (participants) => {
            const target = get().panelTarget;
            const conversationId = target?.conversationId ?? requireConversationId();
            const kind = target?.kind ?? 'collaborative';

            const result =
                kind === 'collaborative'
                    ? await inviteCollaborationMembers(conversationId, participants)
                    : kind === 'group'
                      ? await shareGroupConversation(conversationId, participants)
                      : await sharePersonalConversation(conversationId, participants);

            // The response is serialized for the caller, so unlike a broadcast its
            // capability flags are this reader's and can be applied as they stand.
            applyForViewer(result.conversation);
            // Only re-pointed when the panel is actually open. Inviting somebody from the
            // composer's mention menu goes through here too, and setting a target there
            // would pop the panel open over the conversation the user is writing in.
            if (result.conversation?.id && get().panelTarget) {
                set({
                    panelConversation: result.conversation,
                    // After sharing, the server has returned a *different* conversation from
                    // the one the panel was opened on, so the panel follows it.
                    panelTarget: {
                        conversationId: result.conversation.id,
                        kind: 'collaborative',
                        title: result.conversation.title,
                        groupId: result.conversation.group_id ?? null,
                    },
                });
            }
            rememberRecentCollaborators(participants);
            return result;
        },

        removeParticipant: async (memberUserId) => {
            const conversationId = requireConversationId();
            const result = await removeCollaborationMember(conversationId, memberUserId);
            applyForViewer(result.conversation);
        },

        changeParticipantRole: async (memberUserId, role) => {
            const conversationId = requireConversationId();
            const result = await updateCollaborationMemberRole(conversationId, memberUserId, role);
            applyForViewer(result.conversation);
        },

        respondToInvite: async (action) => {
            // Deliberately the open conversation rather than the panel's: the invitation
            // prompt sits above the thread on screen, and a panel opened on some other
            // conversation must not become the thing that gets joined.
            const conversationId = String(get().conversation?.id ?? '').trim();
            if (!conversationId) {
                return false;
            }
            try {
                const { conversation } = await respondToCollaborationInvite(conversationId, action);
                applyForViewer(conversation);
                toast.success(
                    action === 'accept'
                        ? 'You have joined the shared conversation.'
                        : 'Invitation declined.',
                );
                return true;
            } catch (error) {
                toast.error(
                    error instanceof Error ? error.message : 'Could not respond to the invitation.',
                );
                return false;
            }
        },

        leaveOrDelete: async (action, newOwnerUserId) => {
            const conversationId = requireConversationId();
            try {
                await collaborationDeleteAction(conversationId, action, newOwnerUserId);
                // Only the thread on screen is torn down, and only when it is the one that
                // was left: leaving a conversation from the rail must not empty a different
                // one the reader is reading.
                if (get().conversation?.id === conversationId) {
                    get().reset();
                }
                set({ panelTarget: null, panelConversation: null });
                toast.success(
                    action === 'delete'
                        ? 'Shared conversation deleted.'
                        : 'You have left the shared conversation.',
                );
                return true;
            } catch (error) {
                toast.error(
                    error instanceof Error
                        ? error.message
                        : 'Could not update your membership of this conversation.',
                );
                return false;
            }
        },

        loadApprovals: async () => {
            set({ approvalsLoading: true });
            try {
                const { approvals } = await fetchGeneratedFileApprovals();
                set({ approvals: approvals ?? [], approvalsLoading: false });
            } catch {
                // Advisory. A conversation is perfectly readable without knowing that a
                // generated file elsewhere is waiting on a decision.
                set({ approvalsLoading: false });
            }
        },

        resolveApproval: async (approval, decision) => {
            try {
                await resolveGeneratedFileApproval(
                    approval.source_conversation_id,
                    approval.artifact_message_id,
                    decision,
                );
                set((state) => ({
                    approvals: state.approvals.filter(
                        (entry) =>
                            entry.artifact_message_id !== approval.artifact_message_id ||
                            entry.source_conversation_id !== approval.source_conversation_id,
                    ),
                }));
                toast.success(
                    decision === 'approve'
                        ? 'File released to the conversation.'
                        : 'File withheld.',
                );
            } catch (error) {
                toast.error(
                    error instanceof Error ? error.message : 'Could not resolve the file approval.',
                );
            }
        },
    };
});

/**
 * Record people just invited so they rank first in the next mention search.
 *
 * Written through `userSettingsStore`, so it lands in the same `recentCollaborators`
 * preference `/api/user/collaboration-suggestions` reads on the server. Best-effort: a
 * failed write costs a slightly worse suggestion order and nothing else, which is why it is
 * not awaited and its failure is not surfaced.
 */
function rememberRecentCollaborators(participants: CollaborationParticipant[]): void {
    const additions = participants
        .map((participant) => ({
            user_id: String(participant.user_id ?? '').trim(),
            display_name: participantName(participant),
            email: String(participant.email ?? '').trim(),
            last_used_at: new Date().toISOString(),
        }))
        .filter((participant) => participant.user_id);

    if (additions.length === 0) {
        return;
    }

    const settingsStore = useUserSettingsStore.getState();
    const existing = Array.isArray(settingsStore.settings[RECENT_COLLABORATORS_KEY])
        ? (settingsStore.settings[RECENT_COLLABORATORS_KEY] as Array<Record<string, unknown>>)
        : [];

    const addedIds = new Set(additions.map((participant) => participant.user_id));
    const merged = [
        ...additions,
        ...existing.filter(
            (entry) => !addedIds.has(String(entry?.user_id ?? entry?.id ?? '').trim()),
        ),
    ].slice(0, MAX_RECENT_COLLABORATORS);

    settingsStore.update({ [RECENT_COLLABORATORS_KEY]: merged });
}
