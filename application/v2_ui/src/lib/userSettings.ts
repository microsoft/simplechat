// userSettings.ts
// The per-user preferences V2 reads and writes through /api/user/settings.
//
// The route keeps a whitelist (`allowed_keys` in route_backend_users.py). A key outside it
// is dropped **silently** -- the POST still returns success and the value simply never
// arrives. Every key below therefore has to exist in that set, which a functional test
// asserts rather than leaving to review.
//
// Two keys are deliberately absent. `activeGroupOid` and `activePublicWorkspaceOid` look
// like ordinary settings but are popped from the payload and routed to
// `update_active_group_for_user()` / `update_active_public_workspace_for_user()`; they never
// come back from a later GET, so treating them as settings would make the store believe a
// save had been lost. They get their own call when the workspace tabs are built.

import type { DocumentExplorerPrefs, DocumentSavedView } from './types';

/** Text scale, matching the values the route normalises to. */
export type FontSizePreference = 'xs' | 's' | 'm' | 'l' | 'xl';

/** Sidebar hide-control style, matching the route's accepted values. */
export type SidebarToggleStyle = 'large' | 'compact';

/**
 * Preferences V2 owns.
 *
 * Deliberately a subset of what the route accepts: these are the ones V2 actually has a
 * control for. Reading a key V2 never writes is harmless, so the shape stays open.
 */
export interface UserSettings {
    /** Shared with the classic interface, so the two agree on light/dark. */
    darkModeEnabled?: boolean;
    fontSizePreference?: FontSizePreference;
    sidebarToggleStyle?: SidebarToggleStyle;
    showTutorialButtons?: boolean;
    desktopNotificationsEnabled?: boolean;
    conversationContentsDrawerEnabled?: boolean;
    /**
     * Whether the conversation list labels group, public and shared conversations.
     *
     * Defaults to on when absent: the information is useful and was previously missing
     * entirely, so a user who has never seen the setting gets the more informative
     * behaviour.
     */
    showConversationWorkspaceTags?: boolean;
    /**
     * Shell preferences owned by this interface.
     *
     * Namespaced rather than reusing the classic interface's `dockedSidebarHidden` and
     * `chatLayout`: those describe its own sidebar and chat layout, and writing them from
     * here would rearrange that interface as a side effect of a choice made in this one.
     */
    v2RailCollapsed?: boolean;
    v2ChatWidth?: string;

    /**
     * How the workspace documents explorer is presented, and the views pinned in its rail.
     *
     * Namespaced like the shell preferences above. The classic interface stores its own
     * documents view mode in `localStorage` under `personalWorkspaceViewPreference` and
     * offers four modes to this interface's two, so the two settings describe genuinely
     * different things and must not be shared.
     */
    v2DocumentsPrefs?: Partial<DocumentExplorerPrefs>;
    v2DocumentSavedViews?: DocumentSavedView[];

    /**
     * The chat model last chosen in the picker, as a catalog `selection_key`.
     *
     * Deliberately NOT namespaced like `v2RailCollapsed`: both interfaces mean the same
     * thing by it, and `/api/v2/bootstrap` resolves `initial_model_selection` from this key
     * (falling back to `preferredModelDeployment`). Without it the composer restores
     * whatever the other interface last saved, or the first entry in the catalog.
     */
    preferredModelId?: string;
    preferredModelDeployment?: string;

    /**
     * The reasoning level chosen per model, `{ 'gpt-5-mini': 'medium' }`.
     *
     * Shared with the classic interface, which owns the same map, so a level chosen in one
     * is in effect in the other. Keyed by model id (falling back to deployment name), which
     * is what `getCurrentModelName()` in chat-reasoning.js uses.
     */
    reasoningEffortSettings?: Record<string, string>;

    chatCompletionAudioEnabled?: boolean;
    chatCompletionAudioMuted?: boolean;
    chatCompletionAudioSound?: string;
    /** The route requires an integer 1-10. */
    chatCompletionAudioVolume?: number;

    ttsEnabled?: boolean;
    ttsVoice?: string;
    ttsSpeed?: number;
    ttsAutoplay?: boolean;

    /** Read-only here; the route sets it when the user hides the shortcut. */
    latestFeaturesHiddenVersion?: string | null;

    /**
     * The AI notice dismissal.
     *
     * Written through `dismissAiNotice()` rather than this store, and read back in a
     * different shape: the client posts `{ hash, frequency }` and the route stores a
     * server-timestamped record. Only the server reads it, at bootstrap.
     */
    aiNoticeDismissal?: { hash: string; frequency: string };

    [key: string]: unknown;
}

/**
 * Every key V2 may write.
 *
 * Kept as a literal array rather than derived from the interface because a functional test
 * parses it out of this file and checks each entry against the route's whitelist. A type
 * cannot be read at test time; a literal can.
 */
export const WRITABLE_USER_SETTING_KEYS = [
    'darkModeEnabled',
    'fontSizePreference',
    'sidebarToggleStyle',
    'showTutorialButtons',
    'desktopNotificationsEnabled',
    'conversationContentsDrawerEnabled',
    'showConversationWorkspaceTags',
    'v2RailCollapsed',
    'v2ChatWidth',
    'v2MermaidStyle',
    'v2ChartStyle',
    // Workspace documents explorer: how the list is presented, and the saved filter
    // combinations pinned in its navigation rail.
    'v2DocumentsPrefs',
    'v2DocumentSavedViews',
    // Shared with the classic interface rather than namespaced: the chosen model and its
    // reasoning level mean the same thing in both, and the bootstrap resolves the initial
    // model selection from these keys.
    'preferredModelId',
    'preferredModelDeployment',
    'reasoningEffortSettings',
    'chatCompletionAudioEnabled',
    'chatCompletionAudioMuted',
    'chatCompletionAudioSound',
    'chatCompletionAudioVolume',
    'ttsEnabled',
    'ttsVoice',
    'ttsSpeed',
    'ttsAutoplay',
    // Written by dismissAiNotice() rather than the preferences store, but listed here so
    // the whitelist test still proves the route will accept it.
    'aiNoticeDismissal',
] as const;

export type WritableUserSettingKey = (typeof WRITABLE_USER_SETTING_KEYS)[number];

/** Response of GET /api/user/settings. */
export interface UserSettingsResponse {
    settings?: UserSettings;
}

export const FONT_SIZE_PREFERENCES: FontSizePreference[] = ['xs', 's', 'm', 'l', 'xl'];

export const FONT_SIZE_LABELS: Record<FontSizePreference, string> = {
    xs: 'Extra small',
    s: 'Small',
    m: 'Default',
    l: 'Large',
    xl: 'Extra large',
};

/**
 * Sound ids the route accepts for the completion cue.
 *
 * Quoted from CHAT_COMPLETION_AUDIO_SOUND_IDS; an unknown id is rejected outright rather
 * than falling back, so the picker must not offer anything outside this list.
 */
export const COMPLETION_AUDIO_SOUNDS = [
    'aurora',
    'bell',
    'bloom',
    'chime',
    'crystal',
    'glimmer',
    'marimba',
    'pulse',
    'spark',
    'summit',
] as const;
