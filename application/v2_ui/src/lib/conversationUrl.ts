// conversationUrl.ts
// Reading and writing the conversation that a URL names.
//
// The classic interface puts the open conversation in the address bar so it can be copied
// and shared, and reads it back on load. These helpers hold the same rules for the V2 SPA
// in one place, away from React, so the direction of travel stays explicit: a URL is read
// once when the chat page first renders, and written whenever the open conversation
// changes.

/** The spelling this interface writes. */
export const CONVERSATION_PARAM = 'conversationId';

/**
 * A one-shot parameter that hands a saved prompt to the composer, as `/chat?prompt=<id>`.
 *
 * Declared here rather than beside the prompt code because this module owns the vocabulary of
 * the chat URL, and because `syncedConversationParams` below has to know to strip it. Two
 * components writing the query string independently is how a parameter one of them removed
 * comes back: each `setSearchParams` replaces the *whole* query from its own render snapshot,
 * so the later writer restores whatever the earlier one deleted.
 */
export const PROMPT_PARAM = 'prompt';
/**
 * Optional companions to `prompt`, added for group prompts (M3). A group prompt id is unique,
 * but resolving one by id alone would silently attach a personal prompt that happened to match;
 * these name the scope so the composer resolves by id *and* scope. Personal links never carry
 * them, so a `?prompt=<id>` link already in circulation keeps resolving by id exactly as before.
 * Stripped by `syncedConversationParams` for the same one-shot reason `prompt` is.
 */
export const PROMPT_SCOPE_PARAM = 'prompt_scope';
export const PROMPT_SCOPE_ID_PARAM = 'prompt_scope_id';
export const WORKSPACE_AGENT_PARAM = 'agent_id';
export const AGENT_SCOPE_PARAM = 'agent_scope';
/**
 * The group a group agent link names (M4C). Agent ids are only unique within their scope, and a
 * user can belong to several groups, so a group launch resolves by id, scope *and* this group.
 * Personal and provided (global) links never carry it, so links already in circulation keep their
 * exact spelling. One-shot, and stripped with the other launch parameters.
 */
export const AGENT_SCOPE_ID_PARAM = 'agent_scope_id';
export const NEW_CHAT_PARAM = 'new';

/**
 * The prompt a set of query parameters names, or null when it names none.
 *
 * Read by the composer through a lazy state initialiser, which runs during the first render --
 * before the effect below strips it.
 */
export function readPromptParam(params: URLSearchParams): string | null {
    const value = params.get(PROMPT_PARAM) ?? '';
    return value.trim() || null;
}

/**
 * The scope a prompt link names, or null for a scopeless (personal) link.
 *
 * Both parts are required together: a link with a kind but no id, or the reverse, names no
 * usable scope and is treated as absent so resolution falls back to id-only.
 */
export interface PromptLinkScope {
    kind: string;
    id: string;
}

export function readPromptScope(params: URLSearchParams): PromptLinkScope | null {
    const kind = (params.get(PROMPT_SCOPE_PARAM) ?? '').trim();
    const id = (params.get(PROMPT_SCOPE_ID_PARAM) ?? '').trim();
    if (!kind || !id) {
        return null;
    }
    return { kind, id };
}

/**
 * A link that opens the chat page with a saved prompt ready to insert.
 *
 * A group scope adds `prompt_scope` and `prompt_scope_id` so the composer can tell a group
 * prompt from a personal one with the same id. Personal links pass no scope and keep their
 * exact `/chat?prompt=<id>` spelling, so links already shared stay byte-identical.
 */
export function chatHrefForPrompt(promptId: string, scope?: PromptLinkScope | null): string {
    const base = `/chat?${PROMPT_PARAM}=${encodeURIComponent(promptId)}`;
    if (!scope || scope.kind === 'personal') {
        return base;
    }
    return `${base}&${PROMPT_SCOPE_PARAM}=${encodeURIComponent(scope.kind)}`
        + `&${PROMPT_SCOPE_ID_PARAM}=${encodeURIComponent(scope.id)}`;
}

/** The workspace an agent link names. A group scope must say which group. */
export type AgentLinkScope =
    | { kind: 'personal' }
    | { kind: 'global' }
    | { kind: 'group'; id: string };

/**
 * A link that starts a new chat with a workspace agent selected.
 *
 * Personal and provided links keep their exact `/chat?agent_id=<id>&agent_scope=<scope>&new=1`
 * spelling. A group link adds `agent_scope_id` before `new`, so the chat page can pick the agent
 * from the right group rather than from whichever group the account last selected.
 */
export function chatHrefForAgent(agentId: string, scope: AgentLinkScope): string {
    const base = `/chat?${WORKSPACE_AGENT_PARAM}=${encodeURIComponent(agentId)}`
        + `&${AGENT_SCOPE_PARAM}=${scope.kind}`;
    const group = scope.kind === 'group' ? `&${AGENT_SCOPE_ID_PARAM}=${encodeURIComponent(scope.id)}` : '';
    return `${base}${group}&${NEW_CHAT_PARAM}=1`;
}

/**
 * Also accepted when reading, never written.
 *
 * The server emits both spellings and they are already in circulation: notifications and
 * workflow runs build `/chats?conversationId=`, while chat responses and workspace document
 * rows build `/chats?conversation_id=`. The classic client accepts either, so a link that
 * works there must work here too.
 */
export const LEGACY_CONVERSATION_PARAM = 'conversation_id';

/** Where the classic interface serves the chat page. */
const CLASSIC_CHAT_PATH = '/chats';

/**
 * The conversation a set of query parameters names, or null when it names none.
 *
 * The canonical spelling wins when both are present, so normalising a legacy link cannot
 * change which conversation it opens.
 */
export function readConversationParam(params: URLSearchParams): string | null {
    const value =
        params.get(CONVERSATION_PARAM) ?? params.get(LEGACY_CONVERSATION_PARAM) ?? '';
    const trimmed = value.trim();
    return trimmed || null;
}

/**
 * The query parameters a URL should carry for `conversationId`, or null when it already
 * carries exactly that.
 *
 * The null return is doing real work: it is what keeps the effect that writes the URL from
 * re-entering itself, and it means leaving and returning to the chat page costs no
 * navigation. A legacy parameter always counts as a difference, so an incoming
 * `?conversation_id=` link is rewritten to the canonical spelling on arrival.
 *
 * `prompt` is stripped here for the same reason, and deliberately by this one writer. The
 * composer reads it during its first render and must not remove it itself: `setSearchParams`
 * replaces the entire query from the caller's render snapshot, so a parameter the composer
 * deleted would be restored by this effect's own snapshot moments later -- leaving a URL that
 * re-inserts the prompt on every reload.
 */
export function syncedConversationParams(
    params: URLSearchParams,
    conversationId: string | null,
): URLSearchParams | null {
    const current = params.get(CONVERSATION_PARAM);
    const hasLegacy = params.has(LEGACY_CONVERSATION_PARAM);
    const hasPrompt = params.has(PROMPT_PARAM);
    const hasPromptScope = params.has(PROMPT_SCOPE_PARAM) || params.has(PROMPT_SCOPE_ID_PARAM);
    const hasAgentLaunch = params.has(WORKSPACE_AGENT_PARAM) || params.has(AGENT_SCOPE_PARAM)
        || params.has(AGENT_SCOPE_ID_PARAM);

    if (!hasLegacy && !hasPrompt && !hasPromptScope && !hasAgentLaunch
        && (current ?? null) === conversationId) {
        return null;
    }

    const next = new URLSearchParams(params);
    next.delete(LEGACY_CONVERSATION_PARAM);
    next.delete(PROMPT_PARAM);
    next.delete(PROMPT_SCOPE_PARAM);
    next.delete(PROMPT_SCOPE_ID_PARAM);
    if (hasAgentLaunch) {
        next.delete(WORKSPACE_AGENT_PARAM);
        next.delete(AGENT_SCOPE_PARAM);
        next.delete(AGENT_SCOPE_ID_PARAM);
        next.delete(NEW_CHAT_PARAM);
    }
    if (conversationId) {
        next.set(CONVERSATION_PARAM, conversationId);
    } else {
        next.delete(CONVERSATION_PARAM);
    }
    return next;
}

/**
 * A link to the classic chat page, carrying the open conversation when there is one.
 *
 * Crossing between the two interfaces otherwise lands on the conversation list, which
 * means finding your place again in a rail that may be paged.
 */
export function classicChatHref(conversationId: string | null): string {
    if (!conversationId) {
        return CLASSIC_CHAT_PATH;
    }
    return `${CLASSIC_CHAT_PATH}?${CONVERSATION_PARAM}=${encodeURIComponent(conversationId)}`;
}
