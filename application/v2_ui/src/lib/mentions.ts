// mentions.ts
// The `@` mention grammar of a shared conversation, and the rule that decides whether a
// message is answered by the AI or simply posted to the other participants.
//
// This is the one behaviour that has no counterpart in a personal conversation. There,
// every message is a prompt. In a shared conversation most messages are people talking to
// each other, and invoking the model is the exception — so something has to decide which a
// given message is, and get it right, because guessing wrong either answers a message
// nobody asked the AI about or silently swallows a question.
//
// The rule is taken from `buildCollaborativeInvocationTarget` in chat-messages.js and is
// reproduced here rather than reinterpreted, so the two interfaces cannot disagree about
// what a given message does:
//
//   1. An explicit `@` mention of a model or an agent invokes it.
//   2. Otherwise, any composer option that only makes sense as a request to the AI —
//      an agent, image generation, deep research, URL access, web search, document search,
//      or a saved prompt — invokes the currently selected model.
//   3. Otherwise the message is posted to the participants and the AI never sees it.
//
// Everything here is a pure function so the grammar can be tested without a browser.

import { agentSelectionKey } from './agents';
import { modelSelectionKey, type ModelCatalogEntry } from './models';
import type {
    AgentOption,
    CollaborationConversation,
    CollaborationParticipant,
    CollaboratorSuggestion,
} from './types';

/** How many suggestions the mention menu offers. Matches the classic client. */
export const MENTION_SUGGESTION_LIMIT = 8;

/* -------------------------------------------------------------------------- */
/* Detecting a mention being typed                                             */
/* -------------------------------------------------------------------------- */

/** An `@` token under the caret, and where it sits so it can be replaced. */
export interface MentionMatch {
    /** Text typed after the `@`, which may be empty immediately after typing it. */
    query: string;
    /** Index of the `@` itself. */
    startIndex: number;
    /** Index just past the last character of the token. */
    endIndex: number;
}

/**
 * Find the mention being typed at the caret, if there is one.
 *
 * An `@` only opens a mention at the start of the text or after whitespace, so an email
 * address does not turn into one halfway through. The token ends at the caret rather than
 * at the next space, which is what allows a name containing spaces to keep matching as it
 * is typed.
 */
export function findMentionAtCaret(text: string, caretIndex: number): MentionMatch | null {
    const value = String(text ?? '');
    const caret = Math.max(0, Math.min(caretIndex, value.length));
    const before = value.slice(0, caret);

    const at = before.lastIndexOf('@');
    if (at === -1) {
        return null;
    }

    const preceding = at === 0 ? '' : before[at - 1];
    if (preceding && !/\s/.test(preceding)) {
        return null;
    }

    const query = before.slice(at + 1);
    // A newline ends the mention: the reader has moved on to another line, and continuing
    // to match would let the menu reappear over unrelated text.
    if (query.includes('\n')) {
        return null;
    }

    return { query, startIndex: at, endIndex: caret };
}

/**
 * Replace the mention under the caret with the chosen text.
 *
 * Returns the new value and where the caret should end up, because the caller has to set
 * both on the textarea and computing the offset at the call site is easy to get wrong.
 */
export function replaceMention(
    text: string,
    match: MentionMatch,
    replacement: string,
): { value: string; caretIndex: number } {
    const value = String(text ?? '');
    const before = value.slice(0, match.startIndex);
    const after = value.slice(match.endIndex);
    // A trailing space so the next word does not run into the name, but not a second one
    // when the text already continues with whitespace.
    const spacer = after.startsWith(' ') ? '' : ' ';
    return {
        value: `${before}${replacement}${spacer}${after}`,
        caretIndex: before.length + replacement.length + spacer.length,
    };
}

/* -------------------------------------------------------------------------- */
/* Matching a mention in finished text                                         */
/* -------------------------------------------------------------------------- */

function escapeRegExp(value: string): string {
    return String(value ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Build the pattern that matches `@Name` in finished text.
 *
 * The boundaries matter and are copied from `buildAtMentionPattern`: a mention starts at
 * the beginning or after whitespace, and ends at the end, at whitespace, or at closing
 * punctuation. Without the trailing boundary, mentioning "@Sam" would also match "@Samantha".
 */
function mentionPattern(displayName: string, flags = 'i'): RegExp {
    return new RegExp(`(^|\\s)@${escapeRegExp(displayName)}(?=$|\\s|[.,!?;:])`, flags);
}

/** Whether `text` mentions `displayName`. */
export function mentionsName(text: string, displayName: string): boolean {
    const name = String(displayName ?? '').trim();
    if (!name) {
        return false;
    }
    return mentionPattern(name).test(String(text ?? ''));
}

/**
 * Character used to blank out an already-matched mention.
 *
 * Deliberately not whitespace, so a shorter name cannot match into the span a longer one
 * occupied, and not something a display name can contain.
 */
const CONSUMED = '\u0000';

/**
 * The participants a message mentions.
 *
 * Longest names are matched first, and each match is struck out of the working text before
 * shorter names are tried. That consumption is the point rather than an optimisation: where
 * one person is called "Ada Lovelace" and another "Ada", the text "@Ada Lovelace" literally
 * contains "@Ada" followed by a space, so testing each name independently against the
 * original message reports both — and notifies somebody who was never addressed. Striking
 * the longer match out first leaves nothing for the shorter name to find.
 *
 * A message that genuinely names both still reports both, because their matches occupy
 * different spans.
 */
export function extractMentionedParticipants(
    text: string,
    participants: CollaborationParticipant[] | undefined,
): CollaborationParticipant[] {
    const message = String(text ?? '');
    if (!message.trim() || !participants?.length) {
        return [];
    }

    const byLength = [...participants].sort(
        (left, right) =>
            String(right?.display_name ?? '').length - String(left?.display_name ?? '').length,
    );

    let remaining = message;
    const mentioned: CollaborationParticipant[] = [];
    const seen = new Set<string>();

    for (const participant of byLength) {
        const userId = String(participant?.user_id ?? '').trim();
        const displayName = String(participant?.display_name ?? '').trim();
        if (!userId || !displayName || seen.has(userId)) {
            continue;
        }

        let matched = false;
        remaining = remaining.replace(
            mentionPattern(displayName, 'gi'),
            (whole: string, leading: string) => {
                matched = true;
                // The leading whitespace is preserved so a mention immediately after this
                // one still has the boundary it needs.
                return leading + CONSUMED.repeat(whole.length - leading.length);
            },
        );

        if (!matched) {
            continue;
        }

        seen.add(userId);
        mentioned.push({
            user_id: userId,
            display_name: displayName,
            email: String(participant?.email ?? '').trim(),
        });
    }

    return mentioned;
}

/** Whether a message mentions the reader, used to raise a notification. */
export function mentionsCurrentUser(
    metadata: Record<string, unknown> | undefined,
    currentUserId: string | undefined,
): boolean {
    if (!currentUserId) {
        return false;
    }
    const ids = metadata?.mentioned_user_ids;
    if (!Array.isArray(ids)) {
        return false;
    }
    return ids.map((id) => String(id ?? '').trim()).includes(currentUserId);
}

/* -------------------------------------------------------------------------- */
/* AI targets                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Something the AI side of a shared conversation can be addressed as.
 *
 * Sent to the server as `invocation_target`, where it is stored on the message as
 * `metadata.ai_invocation_target` so the thread records *what* was asked, not merely that
 * something was.
 */
export interface InvocationTarget {
    target_type: 'model' | 'agent' | 'image';
    display_name: string;
    mention_text: string;
    /** How the target was chosen: an explicit tag, or the option that implied it. */
    source_mode: string;
    /** Set for a model target, so the send can carry the full model identity. */
    selection_key?: string;
    /** Set for an agent target, so the send can carry the agent selection. */
    agent_selection_key?: string;
    subtitle?: string;
    [key: string]: unknown;
}

/** A row in the mention menu. */
export type MentionSuggestion =
    | {
          kind: 'participant';
          user_id: string;
          display_name: string;
          email?: string;
          mention_text: string;
          subtitle?: string;
      }
    | {
          kind: 'invite';
          user_id: string;
          display_name: string;
          email?: string;
          mention_text: string;
          subtitle?: string;
      }
    | {
          kind: 'ai';
          target: InvocationTarget;
          display_name: string;
          mention_text: string;
          subtitle?: string;
      };

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function matchesQuery(haystack: string[], query: string): boolean {
    const needle = String(query ?? '')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();
    if (!needle) {
        return true;
    }
    return haystack
        .filter(Boolean)
        .join(' ')
        .replace(/\s+/g, ' ')
        .toLowerCase()
        .includes(needle);
}

/** The agents in the catalog, as mention targets. */
export function agentTargets(agents: AgentOption[] | undefined): InvocationTarget[] {
    return (agents ?? [])
        .map((agent): InvocationTarget | null => {
            const displayName = text(agent.display_name) || text(agent.name);
            if (!displayName) {
                return null;
            }
            const scope = text(agent.scope_type).toLowerCase();
            return {
                target_type: 'agent',
                display_name: displayName,
                mention_text: `@${displayName}`,
                source_mode: 'explicit_tag',
                agent_selection_key: agentSelectionKey(agent as Record<string, unknown>),
                subtitle:
                    scope === 'group'
                        ? 'Group agent'
                        : scope === 'global'
                          ? 'Global agent'
                          : 'Personal agent',
            };
        })
        .filter((target): target is InvocationTarget => target !== null);
}

/** The models in the catalog, as mention targets. */
export function modelTargets(models: ModelCatalogEntry[] | undefined): InvocationTarget[] {
    return (models ?? [])
        .map((model): InvocationTarget | null => {
            const displayName =
                text(model.display_name) || text(model.deployment_name) || text(model.model_id);
            if (!displayName) {
                return null;
            }
            return {
                target_type: 'model',
                display_name: displayName,
                mention_text: `@${displayName}`,
                source_mode: 'explicit_tag',
                selection_key: modelSelectionKey(model),
                subtitle: 'Model',
            };
        })
        .filter((target): target is InvocationTarget => target !== null);
}

/**
 * The AI target a finished message explicitly addresses, if any.
 *
 * Agents are tested before models, and longer names before shorter ones, so the most
 * specific tag in the text is the one that wins.
 */
export function resolveInvocationTarget(
    message: string,
    agents: AgentOption[] | undefined,
    models: ModelCatalogEntry[] | undefined,
): InvocationTarget | null {
    const value = String(message ?? '');
    if (!value.includes('@')) {
        return null;
    }

    const targets = [...agentTargets(agents), ...modelTargets(models)].sort(
        (left, right) => right.display_name.length - left.display_name.length,
    );

    return targets.find((target) => mentionsName(value, target.display_name)) ?? null;
}

/* -------------------------------------------------------------------------- */
/* The send decision                                                           */
/* -------------------------------------------------------------------------- */

/** The composer options that bear on whether the AI is being addressed. */
export interface InvocationOptions {
    agentSelection?: string;
    promptId?: string;
    documentSearch?: boolean;
    webSearch?: boolean;
    imageGeneration?: boolean;
    deepResearch?: boolean;
    urlAccess?: boolean;
    modelDeployment?: string;
}

/**
 * Decide what, if anything, this message asks the AI to do.
 *
 * Returns null when the message is simply for the other participants. The order of the
 * checks is `buildCollaborativeInvocationTarget`'s and is significant: image generation
 * outranks an agent, which outranks deep research, and so on, so a message with several
 * options set is attributed to one of them consistently rather than to whichever happened
 * to be tested first.
 */
export function resolveSendTarget(
    message: string,
    options: InvocationOptions,
    catalogs: { agents?: AgentOption[]; models?: ModelCatalogEntry[] },
): InvocationTarget | null {
    const explicit = resolveInvocationTarget(message, catalogs.agents, catalogs.models);
    if (explicit) {
        return explicit;
    }

    const sourceMode = options.imageGeneration
        ? 'image_generation'
        : options.agentSelection
          ? 'agent'
          : options.deepResearch
            ? 'deep_research'
            : options.urlAccess
              ? 'url_access'
              : options.webSearch
                ? 'web_search'
                : options.documentSearch
                  ? 'workspace'
                  : options.promptId
                    ? 'prompt'
                    : null;

    if (!sourceMode) {
        return null;
    }

    if (options.imageGeneration) {
        return {
            target_type: 'image',
            display_name: 'Image',
            mention_text: '@Image',
            source_mode: sourceMode,
        };
    }

    if (options.agentSelection) {
        const agent = (catalogs.agents ?? []).find(
            (candidate) =>
                agentSelectionKey(candidate as Record<string, unknown>) === options.agentSelection,
        );
        const label = text(agent?.display_name) || text(agent?.name) || 'Agent';
        return {
            target_type: 'agent',
            display_name: label,
            mention_text: `@${label}`,
            source_mode: sourceMode,
            agent_selection_key: options.agentSelection,
        };
    }

    const model = (catalogs.models ?? []).find(
        (candidate) => modelSelectionKey(candidate) === options.modelDeployment,
    );
    const label =
        text(model?.display_name) || text(model?.deployment_name) || options.modelDeployment || 'Model';
    return {
        target_type: 'model',
        display_name: label,
        mention_text: `@${label}`,
        source_mode: sourceMode,
        selection_key: options.modelDeployment,
    };
}

/** Whether this message should be streamed through the AI rather than merely posted. */
export function shouldInvokeAi(
    message: string,
    options: InvocationOptions,
    catalogs: { agents?: AgentOption[]; models?: ModelCatalogEntry[] },
): boolean {
    return resolveSendTarget(message, options, catalogs) !== null;
}

/* -------------------------------------------------------------------------- */
/* The mention menu                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Build the rows the mention menu shows for a query.
 *
 * Ordered participants, then AI targets, then people who could be invited. That order is
 * the classic client's and reflects how often each is wanted: naming somebody already in
 * the conversation is the common case, and adding a new person to it from the composer is
 * the rarest.
 *
 * Invitable people are only offered when the caller may actually add them, so the menu
 * never suggests an action the server would reject.
 */
export function buildMentionSuggestions(input: {
    query: string;
    participants?: CollaborationParticipant[];
    agents?: AgentOption[];
    models?: ModelCatalogEntry[];
    invitable?: CollaboratorSuggestion[];
    canInvite?: boolean;
    currentUserId?: string;
    limit?: number;
}): MentionSuggestion[] {
    const {
        query,
        participants = [],
        agents,
        models,
        invitable = [],
        canInvite = false,
        currentUserId,
        limit = MENTION_SUGGESTION_LIMIT,
    } = input;

    const known = new Set<string>();
    const rows: MentionSuggestion[] = [];

    for (const participant of participants) {
        const userId = String(participant?.user_id ?? '').trim();
        const displayName = String(participant?.display_name ?? '').trim();
        if (!userId || !displayName) {
            continue;
        }
        known.add(userId);
        if (!matchesQuery([displayName, String(participant?.email ?? '')], query)) {
            continue;
        }
        rows.push({
            kind: 'participant',
            user_id: userId,
            display_name: displayName,
            email: String(participant?.email ?? '').trim(),
            mention_text: `@${displayName}`,
            subtitle:
                String(participant?.membership_status ?? '') === 'pending'
                    ? 'Invited'
                    : String(participant?.email ?? '').trim() || undefined,
        });
    }

    for (const target of [...agentTargets(agents), ...modelTargets(models)]) {
        if (!matchesQuery([target.display_name, target.subtitle ?? ''], query)) {
            continue;
        }
        rows.push({
            kind: 'ai',
            target,
            display_name: target.display_name,
            mention_text: target.mention_text,
            subtitle: target.subtitle,
        });
    }

    if (canInvite) {
        for (const candidate of invitable) {
            const userId = String(candidate?.user_id ?? '').trim();
            const displayName =
                String(candidate?.display_name ?? '').trim() ||
                String(candidate?.email ?? '').trim();
            if (!userId || !displayName || known.has(userId) || userId === currentUserId) {
                continue;
            }
            known.add(userId);
            rows.push({
                kind: 'invite',
                user_id: userId,
                display_name: displayName,
                email: String(candidate?.email ?? '').trim(),
                mention_text: `@${displayName}`,
                subtitle: 'Add to this conversation',
            });
        }
    }

    return rows.slice(0, limit);
}

/**
 * Everyone in a shared conversation who can be named, including the reader.
 *
 * The reader is included because a message they wrote may mention them — quoting somebody
 * else's message, for instance — and dropping them would leave the stored mention list
 * disagreeing with the visible text.
 */
export function conversationParticipants(
    conversation: CollaborationConversation | null | undefined,
): CollaborationParticipant[] {
    return (conversation?.participants ?? []).filter((participant) =>
        Boolean(String(participant?.user_id ?? '').trim()),
    );
}
