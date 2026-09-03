// MentionMenu.tsx
// The `@` autocomplete offered while writing in a shared conversation.
//
// It serves three quite different purposes through one control, which is why the rows are
// typed rather than uniform:
//
//   - naming a participant, which notifies them;
//   - addressing a model or agent, which is what makes the message a question for the AI
//     rather than a remark to the other people in it;
//   - adding somebody who is not in the conversation yet.
//
// The third is the reason the menu exists at all rather than a plain participant list: in
// the classic interface, typing a colleague's name is how you invite them.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { Bot, Cpu, UserPlus, User } from 'lucide-react';
import { fetchCollaboratorSuggestions, fetchGroupMembers } from '../../lib/collaboration';
import { buildMentionSuggestions, type MentionSuggestion } from '../../lib/mentions';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import type { CollaboratorSuggestion, ModelOption, AgentOption } from '../../lib/types';
import type { ModelCatalogEntry } from '../../lib/models';

/** How long to wait after a keystroke before asking the server for more candidates. */
const SEARCH_DEBOUNCE_MS = 250;

const ROW_ICON: Record<MentionSuggestion['kind'], React.ReactNode> = {
    participant: <User size={14} />,
    invite: <UserPlus size={14} />,
    ai: <Bot size={14} />,
};

/**
 * Assemble the rows for a query.
 *
 * Participants and AI targets are already in memory, so they appear immediately; invitable
 * people require a request and arrive a moment later. Building from whatever is available
 * at each render, rather than waiting for the search, is what keeps the menu responsive
 * while typing a name that is already in the conversation.
 */
export function useMentionSuggestions(query: string | null): MentionSuggestion[] {
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const loaded = useCollaborationStore((state) => state.conversation);
    // Guarded on the id for the same reason the composer is: the participants panel loads a
    // different conversation's membership into its own slot, and an unguarded read here
    // would offer one conversation's people while writing in another.
    const conversation = loaded?.id === activeConversationId ? loaded : null;
    const bootstrap = useBootstrapStore((state) => state.data);
    const currentUserId = bootstrap?.user?.id;
    const [invitable, setInvitable] = useState<CollaboratorSuggestion[]>([]);

    const canInvite = Boolean(conversation?.can_manage_members);
    const groupId = conversation?.group_id ?? null;

    useEffect(() => {
        if (query === null || !canInvite) {
            setInvitable([]);
            return;
        }

        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            const search = groupId
                ? fetchGroupMembers(groupId, query, controller.signal).then((members) =>
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
                    if (!controller.signal.aborted) {
                        setInvitable(found);
                    }
                })
                .catch(() => {
                    // Advisory: the participant and AI rows are unaffected, and offering no
                    // invitations is better than an error over the composer.
                });
        }, SEARCH_DEBOUNCE_MS);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [query, canInvite, groupId]);

    if (query === null) {
        return [];
    }

    return buildMentionSuggestions({
        query,
        participants: conversation?.participants,
        agents: bootstrap?.catalogs?.agents as AgentOption[] | undefined,
        models: bootstrap?.catalogs?.models as (ModelOption & ModelCatalogEntry)[] | undefined,
        invitable,
        canInvite,
        currentUserId,
    });
}

export function MentionMenu({
    suggestions,
    activeIndex,
    onSelect,
}: {
    suggestions: MentionSuggestion[];
    activeIndex: number;
    onSelect: (suggestion: MentionSuggestion) => void;
}) {
    if (suggestions.length === 0) {
        return null;
    }

    return (
        <div
            role="listbox"
            aria-label="Mention suggestions"
            className="glass-modal absolute bottom-full left-2 z-50 mb-2 max-h-64 w-72 overflow-y-auto rounded-xl p-1"
        >
            {suggestions.map((suggestion, index) => (
                <button
                    key={`${suggestion.kind}-${
                        suggestion.kind === 'ai' ? suggestion.display_name : suggestion.user_id
                    }`}
                    type="button"
                    role="option"
                    aria-selected={index === activeIndex}
                    // Pointer-down rather than click: the textarea loses focus on mouse-up,
                    // and a blur handler that closes the menu would remove the button before
                    // the click ever landed.
                    onMouseDown={(event) => {
                        event.preventDefault();
                        onSelect(suggestion);
                    }}
                    className={clsx(
                        'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm',
                        index === activeIndex
                            ? 'bg-accent-soft text-accent'
                            : 'text-text-1 hover:bg-surface-2',
                    )}
                >
                    <span className="shrink-0 text-text-3">
                        {suggestion.kind === 'ai' && suggestion.target.target_type === 'model' ? (
                            <Cpu size={14} />
                        ) : (
                            ROW_ICON[suggestion.kind]
                        )}
                    </span>
                    <span className="min-w-0 flex-1">
                        <span className="block truncate">{suggestion.display_name}</span>
                        {suggestion.subtitle && (
                            <span className="block truncate text-[11px] text-text-3">
                                {suggestion.subtitle}
                            </span>
                        )}
                    </span>
                </button>
            ))}
        </div>
    );
}
