// Composer.tsx
// The message input surface: textarea, send/stop control, model / agent / prompt pickers
// and the capability toggles that map onto the /api/chat/stream request fields.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { clsx } from 'clsx';
import {
    ArrowUp,
    Bot,
    BookmarkPlus,
    ChevronDown,
    FileText,
    Gauge,
    Globe,
    Image as ImageIcon,
    Link2,
    Loader2,
    Paperclip,
    Reply,
    Search,
    ShieldCheck,
    Square,
    Telescope,
    Workflow,
    X,
} from 'lucide-react';
import { useChatStore, type ComposerOptions } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { uploadDocument } from '../../lib/endpoints';
import { sendCollaborationTyping } from '../../lib/collaboration';
import { agentSelectionKey } from '../../lib/agents';
import { buildSelectionFields, hasResolvableAgent } from '../../lib/chatRequestSelection';
import { modelSelectionKey, findModel, type ModelCatalogEntry } from '../../lib/models';
import { resolveGating } from '../../lib/composerGating';
import { resolveDocumentScope } from '../../lib/documentScope';
import {
    addContextItem,
    contextDocumentDescriptors,
    contextDocumentIds,
    contextFilterMode,
    contextScopes,
    contextTags,
    hasContextItem,
    removeContextItem,
    type ContextItem,
    type ContextOrigin,
} from '../../lib/chatContext';
import {
    appendContextToken,
    insertContextToken,
    readContextQuery,
    reconcileContextItems,
    removeContextToken,
    type ContextQuery,
} from '../../lib/chatContextTokens';
import {
    candidateToContextItem,
    type ContextCandidate,
} from '../../lib/contextMentions';
import { ContextChips } from './ContextChips';
import {
    COMPOSER_TEXT_CLASS,
    COMPOSER_TRANSPARENT_TEXT_STYLE,
    ComposerHighlight,
    useHighlightScrollSync,
} from './ComposerHighlight';
import {
    ContextMenu,
    useContextSuggestions,
    type ContextSearchScope,
} from './ContextMenu';
import { DocumentPickerPopover } from './DocumentPickerPopover';
import {
    CONTEXT_HANDOFF_PARAMS,
    readContextHandoff,
    resolveContextHandoff,
    type ContextHandoffState,
} from '../../lib/chatContextHandoff';
import type { ApprovalMode } from '../../lib/orchestration';
import {
    cancelOrchestration,
    hasActiveOrchestration,
    startOrchestrationPlan,
} from '../../lib/orchestrationController';
import {
    estimateLargeTabularRun,
    type TabularRunEstimate,
    type TabularRunSettings,
} from '../../lib/tabularRunEstimate';
import { LargeRunDialog } from './LargeRunDialog';
import {
    findMentionAtCaret,
    replaceMention,
    type MentionMatch,
    type MentionSuggestion,
} from '../../lib/mentions';
import { useUiStore } from '../../stores/uiStore';
import { toast } from '../../stores/toastStore';
import { chatWidthClass } from '../../lib/chatWidth';
import {
    getModelSupportedLevels,
    reasoningModelKey,
    resolveReasoningEffort,
    REASONING_LABELS,
    supportsReasoning,
    type ReasoningEffortSettings,
} from '../../lib/reasoning';
import { Dropdown, type DropdownOption } from '../ui/Dropdown';
import {
    filterPromptsForSlash,
    insertPromptText,
    readSlashQuery,
    suggestPromptName,
    type SlashQuery,
} from '../../lib/promptSlash';
import { promptNeedsFilling } from '../../lib/promptVariables';
import { readPromptParam } from '../../lib/conversationUrl';
import { createPrompt } from '../../lib/workspaceApi';
import { messageToPlainText } from '../../lib/messageText';
import type { PromptOption, WorkspaceRef } from '../../lib/types';
import {
    EMPTY_PROMPT_DRAFT,
    PromptEditorDialog,
    type PromptDraft,
} from '../prompts/PromptEditorDialog';
import { PromptVariablesDialog, type PromptFillSource } from '../prompts/PromptVariablesDialog';
import { AiNotice } from './AiNotice';
import { MentionMenu, useMentionSuggestions } from './MentionMenu';
import { PromptSlashMenu } from './PromptSlashMenu';
import { VoiceInput } from './VoiceInput';
import { WebSearchNotice } from './WebSearchNotice';

/** A capability toggle in the composer toolbar. */
function ToolToggle({
    active,
    onClick,
    icon,
    label,
    disabled = false,
}: {
    active: boolean;
    onClick: () => void;
    icon: React.ReactNode;
    label: string;
    disabled?: boolean;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-pressed={active}
            title={label}
            className={clsx(
                'inline-flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-sm transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-40',
                active
                    ? 'border-transparent bg-accent-soft text-accent'
                    : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {icon}
            <span className="hidden lg:inline">{label}</span>
        </button>
    );
}

export function Composer() {
    const { streaming, sendMessage, stopStreaming, activeConversationId } = useChatStore();
    // Read for the built-in prompt variables ({{last_response}} and friends) and for the name
    // suggested when saving what is written as a prompt.
    const messages = useChatStore((state) => state.messages);
    const conversations = useChatStore((state) => state.conversations);
    const bootstrap = useBootstrapStore((state) => state.data);
    const upsertPromptInCatalog = useBootstrapStore((state) => state.upsertPromptInCatalog);
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const features = bootstrap?.features ?? {};
    // Thresholds for the large-run confirmation. These are administrator settings rather
    // than capability flags, so they come from the settings payload rather than `features`.
    const tabularRunSettings = (bootstrap?.settings ?? {}) as TabularRunSettings;

    // Declared here rather than beside the picker below because the `?prompt=` handoff effect
    // resolves against it, and that effect runs before the picker's options are built.
    const promptCatalog = useMemo(
        () => (bootstrap?.catalogs?.prompts ?? []) as PromptOption[],
        [bootstrap],
    );
    // The level chosen per model, shared with the classic interface. Read from the store
    // rather than held here so a change made anywhere is reflected without a reload.
    const reasoningEffortSettings = useUserSettingsStore(
        (state) => state.settings.reasoningEffortSettings as ReasoningEffortSettings | undefined,
    );
    // Unlike every other preference V2 writes, this one is a map rather than a scalar, and
    // the route stores it whole. The app renders as soon as the bootstrap resolves, which is
    // not necessarily after the settings have arrived, so merging into a map that has not
    // been read would replace every other model's level with the single entry just chosen.
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const settingsFailed = useUserSettingsStore((state) => state.error !== null);
    const settingsLoaded = !settingsLoading && !settingsFailed;

    /**
     * Whether this is a shared conversation, and whether the reader may write in it.
     *
     * `can_post_messages` is the server's decision. A pending invitee can read a shared
     * conversation but not write in it, and a group-visibility conversation grants posting
     * with no membership record at all, so this cannot be worked out from the participant
     * list in the browser.
     */
    const shared = useChatStore((state) => state.activeConversationKind === 'collaborative');
    const loadedCollaboration = useCollaborationStore((state) => state.conversation);
    // Only trusted when it is this conversation's membership. The participants panel used to
    // share this slot, and an unrelated conversation's flags gating the thread on screen was
    // exactly the failure that split them apart.
    const collaboration =
        loadedCollaboration?.id === activeConversationId ? loadedCollaboration : null;
    /**
     * Whether the reader may write here.
     *
     * Deny-by-default in a shared conversation: `can_post_messages` must be explicitly true,
     * so a membership that has not loaded yet — or failed to — leaves the composer disabled
     * rather than offering a Send button to somebody who has not joined. A personal
     * conversation is unaffected.
     */
    const canPost = !shared || collaboration?.can_post_messages === true;
    const awaitingInvite = Boolean(shared && collaboration?.can_accept_invite);
    const checkingAccess = shared && !collaboration;
    const replyTo = useCollaborationStore((state) => state.replyTo);
    const setReplyTo = useCollaborationStore((state) => state.setReplyTo);

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [text, setText] = useState('');
    const [uploading, setUploading] = useState(false);
    const [uploadNotice, setUploadNotice] = useState<string | null>(null);
    const chatWidth = useUiStore((state) => state.chatWidth);

    /** The `@` token under the caret, when the menu should be offering completions for it. */
    const [mention, setMention] = useState<MentionMatch | null>(null);
    const [mentionIndex, setMentionIndex] = useState(0);
    const suggestions = useMentionSuggestions(shared && canPost ? (mention?.query ?? null) : null);

    /** Set while a prompt is waiting on its large-run confirmation. */
    const [largeRun, setLargeRun] = useState<TabularRunEstimate | null>(null);

    /** The `/` token under the caret, when one is being typed. */
    const [slash, setSlash] = useState<SlashQuery | null>(null);
    const [slashIndex, setSlashIndex] = useState(0);

    /** The `#` token under the caret, when the menu should be offering references for it. */
    const [contextQuery, setContextQuery] = useState<ContextQuery | null>(null);
    const [contextIndex, setContextIndex] = useState(0);
    /** Whether the Documents button's picker is open. */
    const [pickerOpen, setPickerOpen] = useState(false);
    const backdropRef = useRef<HTMLDivElement>(null);

    /** The prompt whose variables are being filled in, if any. */
    const [fillingPrompt, setFillingPrompt] = useState<PromptOption | null>(null);
    /** A prompt being saved from what is currently written, if any. */
    const [savingDraft, setSavingDraft] = useState<PromptDraft | null>(null);
    const [savingPrompt, setSavingPrompt] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);

    const [options, setOptions] = useState<ComposerOptions>({
        documentSearch: false,
        webSearch: false,
        imageGeneration: false,
        deepResearch: false,
        urlAccess: false,
        contextItems: [],
    });

    /**
     * Orchestration mode.
     *
     * The toggle only exists where the deployment has orchestration on, so `orchestrating`
     * folds the feature flag and the bootstrap switch into the one boolean every branch below
     * reads.
     *
     * On by default wherever the deployment offers it. Defaulting it off was a mistake: an
     * administrator who switched orchestration on has already made the deliberate choice, and
     * asking every user to find a toggle before the feature does anything is how it stays
     * unused. Worse, the composer meanwhile keeps showing the row of capability buttons --
     * documents, web, image, deep research -- inviting exactly the decisions the planner
     * exists to make on the user's behalf.
     *
     * The toggle remains, because going back to the composer everyone already knows has to
     * stay one click away.
     */
    const orchestrationConfig = bootstrap?.orchestration;
    const orchestrationAvailable = Boolean(
        features.enable_chat_orchestration && orchestrationConfig?.enabled,
    );
    const [orchestrationOn, setOrchestrationOn] = useState(orchestrationAvailable);
    // Whether the user has expressed an opinion. The bootstrap resolves after the first
    // render, so the deployment's answer has to be adopted when it lands -- but adopting it
    // unconditionally would switch orchestration back on every time the payload refreshed,
    // overriding somebody who had just turned it off.
    const orchestrationChosen = useRef(false);
    useEffect(() => {
        if (!orchestrationChosen.current) {
            setOrchestrationOn(orchestrationAvailable);
        }
    }, [orchestrationAvailable]);
    const toggleOrchestration = () => {
        orchestrationChosen.current = true;
        setOrchestrationOn((on) => !on);
    };
    const orchestrating = orchestrationOn && orchestrationAvailable;

    // The disclosure that hides the manual controls while orchestrating. Only reachable when the
    // administrator leaves them reachable; otherwise the planner owns every decision and there is
    // nothing under the disclosure to open.
    const [manualControlsOpen, setManualControlsOpen] = useState(false);
    const manualControlsGovernable = Boolean(orchestrationConfig?.show_manual_controls);
    // Visible inline when not orchestrating (the classic composer), and behind the disclosure
    // when orchestrating with manual controls left reachable.
    const manualControlsVisible =
        !orchestrating || (manualControlsGovernable && manualControlsOpen);

    // The approval mode the plan will carry. Seeded from the deployment default and only editable
    // where the administrator allows an override; where they do not, the control is hidden and the
    // default is what ships.
    const [approvalMode, setApprovalMode] = useState<ApprovalMode>(
        orchestrationConfig?.default_approval_mode ?? 'manual',
    );
    // The default arrives with the bootstrap, which can resolve after the first render, so adopt it
    // when it lands. Keyed on the value itself, so a later refresh carrying the same default does
    // not overwrite a choice the user has since made.
    useEffect(() => {
        if (orchestrationConfig?.default_approval_mode) {
            setApprovalMode(orchestrationConfig.default_approval_mode);
        }
    }, [orchestrationConfig?.default_approval_mode]);
    const approvalOverridable = Boolean(orchestrationConfig?.allow_user_approval_override);
    const effectiveApprovalMode: ApprovalMode = approvalOverridable
        ? approvalMode
        : (orchestrationConfig?.default_approval_mode ?? 'manual');

    // An agent supplies its own deployment and never receives a reasoning level, so a
    // selection the server can actually resolve is what puts the model picker into its
    // overridden state. Resolved against the catalog, not the raw key, so a stale selection
    // does not silently deactivate a control that is still in force.
    const agentActive = useMemo(
        () =>
            hasResolvableAgent(
                bootstrap?.catalogs?.agents as Record<string, unknown>[] | undefined,
                options.agentSelection,
            ),
        [bootstrap, options.agentSelection],
    );

    // Which controls are relevant right now. Deep research and Read URLs depend on what is
    // currently typed, not only on what is enabled.
    const gating = useMemo(
        () =>
            resolveGating({
                prompt: text,
                features: features as Record<string, unknown>,
                webSearchActive: options.webSearch,
                urlAccessActive: options.urlAccess,
                imageGenerationActive: options.imageGeneration,
                agentActive,
            }),
        [
            text,
            features,
            options.webSearch,
            options.urlAccess,
            options.imageGeneration,
            agentActive,
        ],
    );

    // A control that stops being relevant must not leave its option set behind it, or the
    // request would carry a capability the user can no longer see they enabled.
    useEffect(() => {
        setOptions((current) => {
            const next = { ...current };
            let changed = false;
            if (!gating.showUrlAccess && next.urlAccess) {
                next.urlAccess = false;
                changed = true;
            }
            if (!gating.showDeepResearch && next.deepResearch) {
                next.deepResearch = false;
                changed = true;
            }
            return changed ? next : current;
        });
    }, [gating.showUrlAccess, gating.showDeepResearch]);

    // Apply the server's preferred model once bootstrap resolves. Stored as the same
    // selection key the picker uses, so the full identity can be resolved from it.
    useEffect(() => {
        const initial = bootstrap?.catalogs?.initial_model_selection;
        if (!initial) {
            return;
        }
        const key = modelSelectionKey(initial as ModelCatalogEntry);
        if (!key) {
            return;
        }
        setOptions((current) =>
            current.modelDeployment ? current : { ...current, modelDeployment: key },
        );
    }, [bootstrap]);

    const autoGrow = () => {
        const element = textareaRef.current;
        if (!element) {
            return;
        }
        element.style.height = 'auto';
        element.style.height = `${Math.min(element.scrollHeight, 224)}px`;
    };

    useEffect(autoGrow, [text]);
    useHighlightScrollSync(textareaRef, backdropRef, text);

    /**
     * Tell the other participants that this person is writing.
     *
     * Sent as a state change rather than per keystroke — one ping when typing starts and
     * one when it stops — because the server broadcasts every one of these to every other
     * participant's event stream. The stop is also sent on a short idle timer, so walking
     * away mid-sentence clears the indicator instead of leaving it up until the server's own
     * eight-second expiry.
     */
    const typingRef = useRef(false);
    const typingIdleTimer = useRef<number | null>(null);

    const setTyping = (isTyping: boolean) => {
        if (!shared || !activeConversationId || !canPost || typingRef.current === isTyping) {
            return;
        }
        typingRef.current = isTyping;
        void sendCollaborationTyping(activeConversationId, isTyping).catch(() => {
            /* Presence is advisory; a lost ping expires on its own. */
        });
    };

    const stopTyping = () => {
        if (typingIdleTimer.current !== null) {
            window.clearTimeout(typingIdleTimer.current);
            typingIdleTimer.current = null;
        }
        setTyping(false);
    };

    const noteTyping = (value: string) => {
        if (!shared) {
            return;
        }
        setTyping(Boolean(value.trim()));
        if (typingIdleTimer.current !== null) {
            window.clearTimeout(typingIdleTimer.current);
        }
        typingIdleTimer.current = window.setTimeout(() => {
            typingIdleTimer.current = null;
            setTyping(false);
        }, 3000);
    };

    // Leaving the conversation, or the page, must not leave a stale "is typing" behind for
    // everybody else.
    useEffect(
        () => () => {
            if (typingIdleTimer.current !== null) {
                window.clearTimeout(typingIdleTimer.current);
            }
            typingRef.current = false;
        },
        [],
    );

    useEffect(() => {
        // A conversation change invalidates both the draft's mention state and any typing
        // claim made in the conversation being left.
        setMention(null);
        setSlash(null);
        typingRef.current = false;
    }, [activeConversationId]);

    /**
     * Consume a prompt handed over from the workspace as `/chat?prompt=<id>`.
     *
     * The id is captured in a lazy state initialiser, which runs during the first render --
     * before ChatPage's URL sync effect strips the parameter. Reading it in the effect instead
     * would race that strip and sometimes find nothing.
     *
     * This deliberately does not write the URL. ChatPage is the single writer of the chat
     * query string, and `setSearchParams` replaces the whole query from the caller's render
     * snapshot, so a parameter removed here would simply be restored by that effect.
     *
     * The ref guards against StrictMode running effects twice on mount: a state flag is still
     * false in the second invocation's closure, so the prompt would be inserted twice.
     */
    const [searchParams, setSearchParams] = useSearchParams();
    const location = useLocation();
    const [linkedPromptId] = useState(() => readPromptParam(searchParams));
    const promptLinkConsumed = useRef(false);
    useEffect(() => {
        if (promptLinkConsumed.current || !linkedPromptId || !bootstrap) {
            return;
        }
        promptLinkConsumed.current = true;

        const prompt = promptCatalog.find((item) => item.id === linkedPromptId);
        if (!prompt) {
            toast.error('That prompt is no longer available.');
            return;
        }
        setOptions((current) => ({ ...current, promptId: prompt.id }));
        insertPromptIntoComposer(prompt);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bootstrap, promptCatalog, linkedPromptId]);

    // A model is identified by endpoint + id + provider + deployment together, so the
    // option is keyed on `selection_key` (unique per endpoint) rather than the deployment
    // name, which can repeat across endpoints.
    const modelOptions: DropdownOption[] = (bootstrap?.catalogs?.models ?? []).map(
        (model, index) => ({
            value: modelSelectionKey(model as ModelCatalogEntry) || String(index),
            label:
                (model.display_name as string) ||
                (model.deployment_name as string) ||
                'Model',
        }),
    );

    // The catalog record has no `selection_key` (that is a model concept), so the agent is
    // identified by id, falling back to name for a record that somehow lacks one.
    const agentOptions: DropdownOption[] = (bootstrap?.catalogs?.agents ?? []).map(
        (agent, index) => ({
            value: agentSelectionKey(agent) || String(index),
            label: (agent.display_name as string) || (agent.name as string) || 'Agent',
            description: agent.description as string | undefined,
            group: agent.scope_type ? String(agent.scope_type) : undefined,
        }),
    );

    const promptOptions: DropdownOption[] = promptCatalog.map((prompt, index) => ({
        value: (prompt.id as string) ?? String(index),
        label: (prompt.name as string) || 'Prompt',
        description: prompt.description as string | undefined,
        group: prompt.scope_type ? String(prompt.scope_type) : undefined,
    }));

    // The approval-mode choices. "After Ns" names the actual countdown so the reader knows how
    // long a timed plan waits before it approves itself, rather than being told only that it will.
    const approvalOptions: DropdownOption[] = [
        { value: 'auto', label: 'Auto', description: 'Run the plan as soon as it is ready' },
        {
            value: 'timed',
            label: `After ${orchestrationConfig?.timed_approval_seconds ?? 0}s`,
            description: 'Approve automatically unless you step in',
        },
        { value: 'manual', label: 'Review', description: 'Wait for your approval every time' },
    ];

    /**
     * What the `/` menu is currently offering.
     *
     * An empty result is also what closes the menu, which is what makes a query containing
     * spaces safe: an ordinary sentence that happens to start with a slash stops matching
     * almost immediately and the menu goes away, rather than hovering over the composer.
     */
    const slashResults = useMemo(
        () => (slash && canPost ? filterPromptsForSlash(promptCatalog, slash.query) : []),
        [slash, canPost, promptCatalog],
    );

    // Names the agent in the model picker's tooltip. Saying which one is holding the model
    // back is the difference between an explanation and a control that has simply gone dim.
    const activeAgentLabel = agentActive
        ? (agentOptions.find((option) => option.value === options.agentSelection)?.label ??
          'the selected agent')
        : null;

    // Reasoning support is per-model, so the control appears only when the current model
    // actually offers a choice. Resolved from the catalog record rather than the label,
    // since the display name can be anything an administrator typed.
    const selectedModel = findModel(
        bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
        options.modelDeployment,
    );

    // Both the offered levels and the key the chosen level is stored under come from this
    // one name, so the classic interface finds the same entry in the shared map.
    const reasoningKey = reasoningModelKey(
        selectedModel,
        modelOptions.find((option) => option.value === options.modelDeployment)?.label ||
            options.modelDeployment,
    );

    const reasoningLevels: DropdownOption[] = useMemo(() => {
        if (!supportsReasoning(reasoningKey)) {
            return [];
        }
        return getModelSupportedLevels(reasoningKey).map((level) => ({
            value: level,
            label: REASONING_LABELS[level],
        }));
    }, [reasoningKey]);

    // The level in effect is derived from the model and what has been stored for it, never
    // remembered on its own. A level chosen for one model must not follow the user to
    // another, and a model that offers no choice must not carry one into the request at all.
    //
    // Nothing is derived without a model to derive it from. A single-endpoint deployment has
    // no model catalog, so the offered levels are a guess and a default would attach a
    // parameter to every request that the user never asked for. There the control stays
    // opt-in for the session, as it was before.
    //
    // Agent mode is deliberately not a condition here. It hides the control and drops the
    // level from the request in `buildSelectionFields`, which is where that rule lives; the
    // level stays derived from the model underneath, so clearing the agent brings it back.
    const derivedReasoning =
        reasoningKey && reasoningLevels.length > 0
            ? resolveReasoningEffort(reasoningKey, reasoningEffortSettings)
            : undefined;

    useEffect(() => {
        if (!reasoningKey) {
            return;
        }
        setOptions((current) =>
            current.reasoningEffort === derivedReasoning
                ? current
                : { ...current, reasoningEffort: derivedReasoning },
        );
    }, [reasoningKey, derivedReasoning]);

    /**
     * Levels chosen before the stored map arrived.
     *
     * Held rather than written, because the map is stored whole and merging into one that
     * has not been read would discard every other model's level. Held rather than dropped,
     * because a preference that quietly fails to save is the defect this change is fixing.
     * A map rather than a single entry, so choosing for two models in that window keeps both.
     */
    const pendingLevels = useRef<ReasoningEffortSettings>({});

    const storeReasoningLevels = (levels: ReasoningEffortSettings) => {
        // Read at write time rather than from the render's closure, so a map that arrived
        // between the choice and the write is merged into rather than replaced.
        const saved = useUserSettingsStore.getState().settings
            .reasoningEffortSettings as ReasoningEffortSettings | undefined;
        useUserSettingsStore.getState().update({
            reasoningEffortSettings: { ...saved, ...levels },
        });
    };

    useEffect(() => {
        if (!settingsLoaded || Object.keys(pendingLevels.current).length === 0) {
            return;
        }
        const held = pendingLevels.current;
        pendingLevels.current = {};
        storeReasoningLevels(held);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [settingsLoaded]);

    /** Store a chosen level against the current model, for both interfaces to read back. */
    const chooseReasoningLevel = (level: string | undefined) => {
        if (!level) {
            // Only reachable where the control is clearable, which is where no level is
            // stored, so there is nothing to clear but the session's own choice.
            setOptions((current) => ({ ...current, reasoningEffort: undefined }));
            return;
        }

        setOptions((current) => ({ ...current, reasoningEffort: level }));

        // A single-endpoint deployment has no model catalog, so there is no identity to
        // store the choice against. It still applies for the rest of the session.
        if (!reasoningKey) {
            return;
        }

        if (settingsLoaded) {
            storeReasoningLevels({ [reasoningKey]: level });
            return;
        }

        if (settingsFailed) {
            // The map was never read, so writing would replace it. Saying so is better than
            // a control that appears to save and does not.
            toast.error(
                'Your preferences could not be loaded, so this reasoning level applies to this conversation only.',
            );
            return;
        }

        pendingLevels.current = { ...pendingLevels.current, [reasoningKey]: level };
    };

    /**
     * Remember the chosen model.
     *
     * The bootstrap resolves `initial_model_selection` from these keys on the next visit;
     * without them the composer silently falls back to the first entry in the catalog.
     */
    const rememberModelSelection = (selection: string | undefined) => {
        const model = findModel(
            bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
            selection,
        );
        if (!model) {
            return;
        }

        const deployment =
            typeof model.deployment_name === 'string' ? model.deployment_name.trim() : '';
        useUserSettingsStore.getState().update({
            preferredModelId: modelSelectionKey(model),
            // The server falls back to the deployment name when the selection key no longer
            // resolves, which is what happens after an endpoint is replaced.
            ...(deployment ? { preferredModelDeployment: deployment } : {}),
        });
    };

    /**
     * Send, unless the prompt is about to start a long row-level export.
     *
     * The confirmation is raised before anything is sent and before the composer is cleared,
     * so declining leaves the typed prompt exactly where it was to be edited.
     */
    const submit = () => {
        if (!text.trim() || streaming || !canPost) {
            return;
        }

        // Orchestration takes a different road entirely: the server plans the work rather than
        // running a chat stream, so the large-run confirmation — a manual-flow concern about a
        // tabular export the planner has not chosen — does not apply.
        if (orchestrating) {
            dispatchOrchestration(text);
            return;
        }

        const estimate = estimateLargeTabularRun(text, tabularRunSettings);
        if (estimate.shouldConfirm) {
            setLargeRun(estimate);
            return;
        }

        dispatch(text);
    };

    /**
     * Clear the draft once it has been sent.
     *
     * The chips go with the text, because they are two views of one thing. The references are
     * not lost: they are in the message that was just sent, both in its wording and in its
     * stored `requested_document_ids`. Keeping them here instead would leave a row of chips
     * whose tokens are no longer in the box -- which the next keystroke would reconcile away,
     * so the references would appear to survive the send and then vanish one character into
     * the following message.
     */
    const clearDraft = () => {
        setText('');
        setMention(null);
        setContextQuery(null);
        setOptions((current) =>
            current.contextItems.length === 0 ? current : { ...current, contextItems: [] },
        );
    };

    const dispatch = (message: string) => {
        // `options` is read before the clear below replaces it, so the request carries the
        // references this message was written with.
        void sendMessage(message, options);
        clearDraft();
        // Sent, so the indicator other people can see must stop now rather than when the
        // idle timer happens to fire.
        stopTyping();
    };

    /**
     * Assemble the seeds a plan request carries from the manual controls.
     *
     * These do not replace the planner's judgement, they constrain it: a document the user
     * pinned, an agent or model they chose, a saved prompt, a web-search preference. Only the
     * capabilities with a documented seed field travel — the planner owns image, deep research
     * and URL access, so those toggles inform the classic path alone. `buildSelectionFields`
     * keeps the agent-XOR-model exclusivity the chat request already relies on.
     */
    const buildOrchestrationSeeds = (): Record<string, unknown> => {
        const workspaces = contextScopes(options.contextItems);
        const scope = resolveDocumentScope({
            activeGroupId: bootstrap?.scope?.active_group_id,
            activePublicWorkspaceId: bootstrap?.scope?.active_public_workspace_id,
            contextGroupIds: workspaces.groupIds,
            contextPublicWorkspaceIds: workspaces.publicWorkspaceIds,
        });

        const seeds: Record<string, unknown> = {
            web_search_enabled: options.webSearch,
            selected_document_ids: contextDocumentIds(options.contextItems),
            // Names for those ids, so the planner can reason about "the Q3 contract" and the
            // approval card can be read. Display only -- the server authorizes from the ids.
            context_documents: contextDocumentDescriptors(options.contextItems),
            // `resolve_seeds` reads doc_scope and the workspace ids alongside the document
            // ids, and `seeds_are_explicit` turns the planner's candidate probe off once
            // documents are named. Sending the ids without the scope that reaches them would
            // suppress the probe and then find nothing.
            ...scope,
        };
        const tags = contextTags(options.contextItems);
        if (tags.length > 0) {
            seeds.tags = tags;
        }
        // Without this a picked document beside an unrelated tag chip intersects to nothing,
        // exactly as it did on the chat path before the same field was sent there.
        const filterMode = contextFilterMode(options.contextItems);
        if (filterMode) {
            seeds.document_filter_mode = filterMode;
        }
        Object.assign(
            seeds,
            buildSelectionFields({
                agents: bootstrap?.catalogs?.agents as Record<string, unknown>[] | undefined,
                models: bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
                agentSelection: options.agentSelection,
                modelDeployment: options.modelDeployment,
                reasoningEffort: options.reasoningEffort,
            }),
        );
        if (options.promptId) {
            const prompt = promptCatalog.find((item) => item.id === options.promptId);
            if (prompt) {
                // No shared prompt_info builder exists yet, so the shape is assembled here:
                // enough for the planner to resolve the saved prompt without re-reading the
                // catalog it already holds.
                seeds.prompt_info = {
                    id: prompt.id,
                    name: prompt.name,
                    content: prompt.content,
                };
            }
        }
        return seeds;
    };

    const dispatchOrchestration = (message: string) => {
        void startOrchestrationPlan({
            conversationId: activeConversationId ?? null,
            message,
            approvalMode: effectiveApprovalMode,
            seeds: buildOrchestrationSeeds(),
        });
        clearDraft();
        stopTyping();
    };

    /**
     * Stop the work in flight, whichever kind it is.
     *
     * A plan or run has no server-side cancel endpoint the way a chat stream does, so Stop can
     * only abort the reader; the controller settles the thread either way and keeps the partial
     * answer. Routed by whether the conversation has an orchestration stream open, so Stop does
     * the right thing without the button needing to know which mode produced the work.
     */
    const handleStop = () => {
        if (activeConversationId && hasActiveOrchestration(activeConversationId)) {
            cancelOrchestration(activeConversationId);
            return;
        }
        stopStreaming();
    };

    /**
     * Track the `@` token under the caret.
     *
     * Recomputed from the value and the caret on every change, rather than tracked
     * incrementally, so editing in the middle of a line, pasting and undo all behave the
     * same as typing.
     */
    const syncMention = (element: HTMLTextAreaElement) => {
        if (!shared || !canPost) {
            return;
        }
        const found = findMentionAtCaret(element.value, element.selectionStart ?? 0);
        setMention(found);
        setMentionIndex(0);
    };

    /* ---------------------------------------------------------------------- */
    /* Context references                                                      */
    /* ---------------------------------------------------------------------- */

    const contextItems = options.contextItems;
    const contextKeys = useMemo(
        () => new Set(contextItems.map((item) => item.key)),
        [contextItems],
    );
    const contextTokens = useMemo(
        () => new Set(contextItems.map((item) => item.token)),
        [contextItems],
    );

    /** Which workspaces the picker and the `#` menu may search. */
    const searchScope: ContextSearchScope = useMemo(
        () => ({
            groups: (bootstrap?.scope?.groups ?? []) as WorkspaceRef[],
            publicWorkspaces: (bootstrap?.scope?.public_workspaces ?? []) as WorkspaceRef[],
            groupsEnabled: Boolean(features.enable_group_workspaces),
            publicEnabled: Boolean(features.enable_public_workspaces),
        }),
        [bootstrap?.scope, features.enable_group_workspaces, features.enable_public_workspaces],
    );

    const { candidates: contextCandidates, loading: contextLoading } = useContextSuggestions(
        canPost ? (contextQuery?.query ?? null) : null,
        searchScope,
    );

    const syncContext = (element: HTMLTextAreaElement) => {
        if (!canPost) {
            return;
        }
        const found = readContextQuery(element.value, element.selectionStart ?? 0);
        setContextQuery(found);
        setContextIndex(0);
    };

    /**
     * Write new text and retire any reference it no longer names.
     *
     * Every path that changes the message goes through here, because the reconciliation is the
     * thing that keeps a chip from outliving the token it belongs to -- and a chip that
     * outlives its token still puts its document into the request.
     */
    const applyText = (value: string) => {
        setText(value);
        setOptions((current) => {
            const kept = reconcileContextItems(value, current.contextItems);
            return kept.length === current.contextItems.length
                ? current
                : { ...current, contextItems: kept };
        });
    };

    const addContextCandidate = (candidate: ContextCandidate, origin: ContextOrigin = 'user') => {
        if (hasContextItem(contextItems, candidate.key)) {
            return;
        }
        // Built against the current row so the label collision check sees the tokens already
        // in play. Nothing is mutated here; both updates below are plain state writes.
        const item = candidateToContextItem(candidate, contextItems, origin);
        // The token is appended rather than spliced at the caret: the picker has no caret
        // position to speak of, and the reference still ends up in the sentence.
        setText((value) => appendContextToken(value, item.token));
        setOptions((current) => ({
            ...current,
            contextItems: addContextItem(current.contextItems, item),
        }));
    };

    /** Pick from the `#` menu: the token replaces the query it was typed for. */
    const applyContextCandidate = (candidate: ContextCandidate) => {
        const element = textareaRef.current;
        if (!element || !contextQuery) {
            return;
        }

        const { start, end } = contextQuery;
        setContextQuery(null);

        const focusAt = (caret: number) => {
            window.requestAnimationFrame(() => {
                element.focus();
                element.setSelectionRange(caret, caret);
            });
        };

        if (hasContextItem(contextItems, candidate.key)) {
            // Already referenced. The half-typed `#doc` is still cleared, so it does not stay
            // behind looking like a reference that failed to resolve.
            setText(`${text.slice(0, start)}${text.slice(end)}`);
            focusAt(start);
            return;
        }

        const item = candidateToContextItem(candidate, contextItems);
        const next = insertContextToken(text, start, end, item.token);
        setText(next.text);
        setOptions((current) => ({
            ...current,
            contextItems: addContextItem(current.contextItems, item),
        }));
        focusAt(next.caret);
    };

    /**
     * Take a reference off the row, and its text with it.
     *
     * The token is only stripped when no *other* remaining chip still uses it. Two chips can
     * share one token when two documents share a title, and blanking the text while a second
     * chip still points at it would orphan that chip: reconciliation drops it on the next
     * keystroke, but a message sent before that keystroke would still carry its document id --
     * grounding the answer in something the user had already removed.
     */
    const removeContextChip = (item: ContextItem) => {
        const remaining = removeContextItem(contextItems, item.key);
        if (!remaining.some((entry) => entry.token === item.token)) {
            setText((value) => removeContextToken(value, item.token));
        }
        setOptions((current) => ({
            ...current,
            contextItems: removeContextItem(current.contextItems, item.key),
        }));
    };

    const removeContextChips = (items: ContextItem[]) => {
        const dropped = new Set(items.map((item) => item.key));
        const remaining = contextItems.filter((entry) => !dropped.has(entry.key));
        const stillReferenced = new Set(remaining.map((entry) => entry.token));
        const strip = [...new Set(items.map((item) => item.token))].filter(
            (token) => !stillReferenced.has(token),
        );

        setText((value) =>
            strip.reduce((carry, token) => removeContextToken(carry, token), value),
        );
        setOptions((current) => ({
            ...current,
            contextItems: current.contextItems.filter((entry) => !dropped.has(entry.key)),
        }));
    };

    /** Used by the picker, where clicking a ticked row unticks it. */
    const toggleContextCandidate = (candidate: ContextCandidate) => {
        const existing = contextItems.find((item) => item.key === candidate.key);
        if (existing) {
            removeContextChip(existing);
            return;
        }
        addContextCandidate(candidate);
    };

    const clearContextChips = () => removeContextChips(contextItems);

    /**
     * Adopt a selection handed over from the workspace.
     *
     * The hand-off is captured during the first render rather than read inside the effect, for
     * the same reason the prompt link above is: effects that rewrite the query string also run
     * on mount, and whichever ran first would decide whether the selection survived.
     *
     * The ref guards against StrictMode running effects twice, which would otherwise seed the
     * chips -- and append their tokens -- a second time.
     */
    const [linkedHandoff] = useState(() => readContextHandoff(searchParams));
    const [linkedHandoffState] = useState(
        () => (location.state ?? null) as ContextHandoffState | null,
    );
    const handoffApplied = useRef(false);

    useEffect(() => {
        if (handoffApplied.current || !linkedHandoff || !canPost) {
            return;
        }
        handoffApplied.current = true;

        const controller = new AbortController();
        void resolveContextHandoff(linkedHandoff, {
            groups: (bootstrap?.scope?.groups ?? []) as WorkspaceRef[],
            publicWorkspaces: (bootstrap?.scope?.public_workspaces ?? []) as WorkspaceRef[],
            state: linkedHandoffState,
            signal: controller.signal,
        })
            .then((items) => {
                if (controller.signal.aborted || items.length === 0) {
                    return;
                }
                setOptions((current) => ({
                    ...current,
                    // Arriving with documents named is a request to search them, so the
                    // toggle is not left off underneath a full chip row.
                    documentSearch: true,
                    contextItems: items.reduce(
                        (carry, item) => addContextItem(carry, item),
                        current.contextItems,
                    ),
                }));
                setText((value) =>
                    items.reduce((carry, item) => appendContextToken(carry, item.token), value),
                );
                textareaRef.current?.focus();
            })
            .catch(() => {
                // The composer is still usable; the references simply have to be re-picked.
            });

        // Stripped so reloading or re-sharing the link does not silently re-apply a selection
        // the user may since have cleared.
        setSearchParams(
            (current) => {
                const next = new URLSearchParams(current);
                for (const key of CONTEXT_HANDOFF_PARAMS) {
                    next.delete(key);
                }
                return next;
            },
            { replace: true },
        );

        return () => controller.abort();
    }, [canPost, linkedHandoff, linkedHandoffState, setSearchParams, bootstrap?.scope]);

    const applySuggestion = (suggestion: MentionSuggestion) => {
        const element = textareaRef.current;
        if (!element || !mention) {
            return;
        }
        const { value, caretIndex } = replaceMention(text, mention, suggestion.mention_text);
        setText(value);
        setMention(null);

        // An "Add to this conversation" row is an action, not just a completion. Inserting
        // the name without performing it left the row dead: the person was neither added nor
        // mentioned, because the mention list is resolved against existing participants only
        // and the server filters it again.
        if (suggestion.kind === 'invite' && activeConversationId) {
            void useCollaborationStore
                .getState()
                .inviteParticipants([
                    {
                        user_id: suggestion.user_id,
                        display_name: suggestion.display_name,
                        email: suggestion.email,
                    },
                ])
                .then(() => {
                    toast.success(`${suggestion.display_name} was added to this conversation.`);
                })
                .catch((error: unknown) => {
                    toast.error(
                        error instanceof Error
                            ? error.message
                            : `${suggestion.display_name} could not be added.`,
                    );
                });
        }

        // Applied after the value change has been rendered, or the browser would put the
        // caret back at the end of the new value.
        window.requestAnimationFrame(() => {
            element.focus();
            element.setSelectionRange(caretIndex, caretIndex);
        });
    };

    /* ---------------------------------------------------------------- Saved prompts */

    /**
     * Put text into the composer over a range, instead of replacing everything.
     *
     * Picking a prompt used to call `setText(prompt.content)`, which discarded whatever had
     * already been written. That is the reason this exists: a prompt is something you reach for
     * part-way through composing, and losing the half-sentence you reached for it from is the
     * worst possible response to being asked for help.
     */
    const insertIntoComposer = (addition: string, range?: { start: number; end: number }) => {
        const element = textareaRef.current;
        const start = range?.start ?? element?.selectionStart ?? text.length;
        const end = range?.end ?? element?.selectionEnd ?? start;

        const result = insertPromptText(text, start, end, addition);
        // Through applyText because a prompt inserted over a selection can overwrite a
        // reference, and the chip for it has to go with the text it replaced.
        applyText(result.text);
        setSlash(null);
        setMention(null);

        // After React has written the new value back, or the browser puts the caret at the end.
        window.requestAnimationFrame(() => {
            element?.focus();
            element?.setSelectionRange(result.caret, result.caret);
        });
    };

    /**
     * The conversation facts the built-in variables resolve from.
     *
     * Assembled here rather than inside the dialog because only the composer knows what has
     * been typed but not yet sent. Nothing in this object is applied on its own: the last
     * assistant reply is offered as a chip the reader has to click, because that reply can be
     * quoting an uploaded document and text from a document should not become part of the next
     * instruction without a deliberate act.
     */
    const promptContext = () => {
        const lastOfRole = (role: string) =>
            [...messages].reverse().find((message) => message.role === role);
        const assistant = lastOfRole('assistant');
        const user = lastOfRole('user');
        const conversation = conversations.find((item) => item.id === activeConversationId);

        return {
            userName: String(bootstrap?.user?.display_name ?? ''),
            conversationTitle: String(conversation?.title ?? ''),
            lastAssistantMessage: assistant ? messageToPlainText(assistant) : '',
            lastUserMessage: user ? messageToPlainText(user) : '',
            composerText: text,
        };
    };

    /** The one-click values each variable field offers, beyond what is remembered. */
    const promptFillSources = (): PromptFillSource[] => {
        const context = promptContext();
        return (
            [
                { label: 'Last reply', value: context.lastAssistantMessage },
                { label: 'My last message', value: context.lastUserMessage },
                { label: 'What I have typed', value: context.composerText },
            ] as PromptFillSource[]
        ).filter((source) => source.value.trim().length > 0);
    };

    /** The range a pending fill will be inserted over, captured before the dialog opens. */
    const fillRangeRef = useRef<{ start: number; end: number } | null>(null);

    /**
     * Use a saved prompt, asking for its variables first when it has any.
     *
     * Not named `usePrompt`: React reserves the `use` prefix for hooks, and this is an event
     * handler called conditionally.
     */
    const insertPromptIntoComposer = (
        prompt: PromptOption,
        range?: { start: number; end: number },
    ) => {
        const content = String(prompt.content ?? '');
        if (!content) {
            return;
        }
        if (promptNeedsFilling(content)) {
            fillRangeRef.current = range ?? null;
            setFillingPrompt(prompt);
            return;
        }
        insertIntoComposer(content, range);
    };

    const pickSlashPrompt = (prompt: PromptOption) => {
        if (!slash) {
            return;
        }
        // The `/weekly` token is what the prompt replaces, so it does not survive as literal
        // text in the message.
        const range = { start: slash.start, end: slash.end };
        setSlash(null);
        setOptions((current) => ({ ...current, promptId: prompt.id }));
        insertPromptIntoComposer(prompt, range);
    };

    /**
     * Track the `/` token under the caret.
     *
     * Recomputed from the value and the caret for the same reason `syncMention` is: editing in
     * the middle of a line, pasting and undo should behave the way typing does.
     */
    const syncSlash = (element: HTMLTextAreaElement) => {
        if (!canPost) {
            return;
        }
        setSlash(readSlashQuery(element.value, element.selectionStart ?? 0));
        setSlashIndex(0);
    };

    const saveWrittenTextAsPrompt = () => {
        const written = text.trim();
        if (!written) {
            return;
        }
        setSaveError(null);
        setSavingDraft({
            ...EMPTY_PROMPT_DRAFT,
            name: suggestPromptName(written),
            content: written,
        });
    };

    const savePromptDraft = async () => {
        if (!savingDraft) {
            return;
        }
        setSavingPrompt(true);
        setSaveError(null);
        try {
            const created = await createPrompt(savingDraft.name.trim(), savingDraft.content, {
                description: savingDraft.description.trim(),
            });
            // Applied to the catalog immediately: the picker and the `/` menu read from
            // bootstrap, and the point of saving from here is to use the prompt now.
            upsertPromptInCatalog({
                id: created?.id,
                name: savingDraft.name.trim(),
                content: savingDraft.content,
                description: savingDraft.description.trim(),
                scope_type: 'personal',
            });
            void refreshBootstrap();
            setSavingDraft(null);
            toast.success('Saved to your prompts');
        } catch (error) {
            setSaveError(
                error instanceof Error ? error.message : 'Could not save the prompt.',
            );
        } finally {
            setSavingPrompt(false);
        }
    };

    const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
        // The context menu owns these keys first. A `#` token and a `/` or `@` token cannot
        // both be under the caret, so the order between the three is arbitrary — but all
        // three must be tested before the send, or Enter posts a message containing a
        // half-typed reference instead of completing it.
        if (contextQuery && contextCandidates.length > 0) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                setContextIndex((index) => (index + 1) % contextCandidates.length);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                setContextIndex(
                    (index) => (index - 1 + contextCandidates.length) % contextCandidates.length,
                );
                return;
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                applyContextCandidate(contextCandidates[contextIndex]);
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                setContextQuery(null);
                return;
            }
        }

        // The slash menu owns these keys while it has something to offer, and is tested before
        // the mention menu because a `/` token and an `@` token cannot both be under the caret.
        if (slashResults.length > 0) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                setSlashIndex((index) => (index + 1) % slashResults.length);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                setSlashIndex(
                    (index) => (index - 1 + slashResults.length) % slashResults.length,
                );
                return;
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                pickSlashPrompt(slashResults[slashIndex]);
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                setSlash(null);
                return;
            }
        }

        // The mention menu owns these keys while it is open, which is why it is handled
        // before the send: Enter should complete the highlighted name, not send a message
        // containing a half-typed one.
        if (mention && suggestions.length > 0) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                setMentionIndex((index) => (index + 1) % suggestions.length);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                setMentionIndex(
                    (index) => (index - 1 + suggestions.length) % suggestions.length,
                );
                return;
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                applySuggestion(suggestions[mentionIndex]);
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                setMention(null);
                return;
            }
        }

        // Escape also cancels a reply, which is otherwise easy to forget is armed.
        if (event.key === 'Escape' && replyTo) {
            event.preventDefault();
            setReplyTo(null);
            return;
        }

        // Enter sends; Shift+Enter inserts a newline. Matches the classic UI.
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
        }
    };

    const onPickPrompt = (promptId: string | undefined) => {
        setOptions((current) => ({ ...current, promptId }));
        const prompt = bootstrap?.catalogs?.prompts?.find((item) => item.id === promptId);
        if (prompt) {
            insertPromptIntoComposer(prompt as PromptOption);
        }
    };

    const onSelectFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) {
            return;
        }

        setUploading(true);
        setUploadNotice(null);
        try {
            const result = await uploadDocument(file, activeConversationId);
            setUploadNotice(
                result.error ? result.error : `Attached ${file.name}. Processing has started.`,
            );
        } catch (error) {
            setUploadNotice(
                error instanceof Error ? error.message : `Could not upload ${file.name}.`,
            );
        } finally {
            setUploading(false);
            // Reset so re-selecting the same file fires a change event.
            event.target.value = '';
        }
    };

    return (
        <div className="shrink-0 px-4 pb-4">
            {largeRun && (
                <LargeRunDialog
                    estimate={largeRun}
                    onContinue={() => {
                        setLargeRun(null);
                        dispatch(text);
                    }}
                    onCancel={() => setLargeRun(null)}
                />
            )}
            <div className={clsx('mx-auto w-full', chatWidthClass(chatWidth))}>
                {uploadNotice && (
                    <p className="mb-2 rounded-xl border border-edge bg-surface-1 px-3 py-2 text-xs text-text-2">
                        {uploadNotice}
                    </p>
                )}

                {/* Above the input, matching the classic interface: the warning belongs
                    next to the message it is about, not below the send button. */}
                <WebSearchNotice active={options.webSearch} />

                <div className="glass glass-edge relative rounded-2xl p-2">
                    {mention && (
                        <MentionMenu
                            suggestions={suggestions}
                            activeIndex={mentionIndex}
                            onSelect={applySuggestion}
                        />
                    )}

                    {slashResults.length > 0 && (
                        <PromptSlashMenu
                            prompts={slashResults}
                            activeIndex={slashIndex}
                            onSelect={pickSlashPrompt}
                        />
                    )}

                    {contextQuery && !pickerOpen && (
                        <ContextMenu
                            candidates={contextCandidates}
                            loading={contextLoading}
                            activeIndex={contextIndex}
                            selectedKeys={contextKeys}
                            onSelect={applyContextCandidate}
                        />
                    )}

                    {pickerOpen && (
                        <DocumentPickerPopover
                            scope={searchScope}
                            searchAll={options.documentSearch}
                            selectedKeys={contextKeys}
                            onToggleSearchAll={() =>
                                setOptions((current) => ({
                                    ...current,
                                    documentSearch: !current.documentSearch,
                                }))
                            }
                            onToggle={toggleContextCandidate}
                            onClear={clearContextChips}
                            onClose={() => setPickerOpen(false)}
                        />
                    )}

                    {replyTo && (
                        <div className="mb-1 flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2">
                            <Reply size={13} className="mt-0.5 shrink-0 text-text-3" />
                            <span className="min-w-0 flex-1 text-xs text-text-2">
                                {replyTo.display_name && (
                                    <span className="font-medium">Replying to {replyTo.display_name}: </span>
                                )}
                                <span className="line-clamp-2">{replyTo.preview}</span>
                            </span>
                            <button
                                type="button"
                                onClick={() => setReplyTo(null)}
                                aria-label="Cancel reply"
                                className="shrink-0 rounded-md p-0.5 text-text-3 hover:bg-surface-3 hover:text-text-1"
                            >
                                <X size={13} />
                            </button>
                        </div>
                    )}

                    <label htmlFor="composer-input" className="sr-only">
                        Message
                    </label>

                    <ContextChips
                        items={contextItems}
                        onRemove={removeContextChip}
                        onRemoveAll={removeContextChips}
                        onClear={clearContextChips}
                    />

                    {/* The backdrop is positioned against this wrapper rather than the whole
                        composer, so it lines up with the textarea and not with the toolbar
                        below it. */}
                    <div className="relative">
                        <ComposerHighlight
                            text={text}
                            tokens={contextTokens}
                            backdropRef={backdropRef}
                        />
                        <textarea
                            id="composer-input"
                            ref={textareaRef}
                            rows={1}
                            value={text}
                            disabled={!canPost}
                            onChange={(event) => {
                                applyText(event.target.value);
                                syncMention(event.target);
                                syncSlash(event.target);
                                syncContext(event.target);
                                noteTyping(event.target.value);
                            }}
                            // The caret can move without the value changing — clicking, or an
                            // arrow key — and the token under it changes with it.
                            onSelect={(event) => {
                                syncMention(event.currentTarget);
                                syncSlash(event.currentTarget);
                                syncContext(event.currentTarget);
                            }}
                            onBlur={stopTyping}
                            onKeyDown={onKeyDown}
                            placeholder={
                                checkingAccess
                                    ? 'Checking your access to this conversation…'
                                    : awaitingInvite
                                      ? 'Join this conversation to reply'
                                      : !canPost
                                        ? 'You do not have permission to write in this conversation'
                                        : shared
                                          ? 'Message the group, or @mention a model or agent to ask the assistant…'
                                          : 'Send a message, or type # to add a document…'
                            }
                            // Metrics come from the shared constant so the backdrop cannot
                            // drift out of step with the text it is drawing behind.
                            className={clsx(
                                COMPOSER_TEXT_CLASS,
                                'relative resize-none bg-transparent',
                                'placeholder:text-text-3 focus:outline-none',
                                'selection:bg-accent-soft disabled:cursor-not-allowed',
                            )}
                            style={COMPOSER_TRANSPARENT_TEXT_STYLE}
                        />
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 px-1 pt-1">
                        {orchestrationAvailable && (
                            <ToolToggle
                                active={orchestrating}
                                onClick={toggleOrchestration}
                                icon={<Workflow size={15} />}
                                label="Orchestrate"
                            />
                        )}

                        {orchestrating && approvalOverridable && (
                            <Dropdown
                                options={approvalOptions}
                                value={effectiveApprovalMode}
                                placeholder="Approval"
                                icon={<ShieldCheck size={15} />}
                                onChange={(value) =>
                                    value && setApprovalMode(value as ApprovalMode)
                                }
                            />
                        )}

                        {/* A disclosure, not a toggle: it hides the manual controls rather than
                            switching a capability, so it carries aria-expanded rather than the
                            aria-pressed the capability buttons use. Offered only where the
                            administrator leaves the controls reachable. */}
                        {orchestrating && manualControlsGovernable && (
                            <button
                                type="button"
                                onClick={() => setManualControlsOpen((open) => !open)}
                                aria-expanded={manualControlsOpen}
                                title="Manual controls"
                                className={clsx(
                                    'inline-flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-sm transition-colors',
                                    manualControlsOpen
                                        ? 'border-transparent bg-accent-soft text-accent'
                                        : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2 hover:text-text-1',
                                )}
                            >
                                <ChevronDown
                                    size={15}
                                    className={clsx(
                                        'transition-transform',
                                        manualControlsOpen && 'rotate-180',
                                    )}
                                />
                                <span className="hidden lg:inline">Manual controls</span>
                            </button>
                        )}

                        {manualControlsVisible && (
                            <>
                                {/* Hidden while generating an image: the request goes to an image
                                    endpoint that does not take a chat model. Shown but overridden
                                    while an agent is selected, since the agent brings its own
                                    deployment — picking a model here is how the user gets back to
                                    using one, so it stays usable rather than disabled. */}
                                {gating.showModelPicker && (
                                    <Dropdown
                                        options={modelOptions}
                                        value={options.modelDeployment}
                                        placeholder="Model"
                                        inactive={gating.modelPickerInactive}
                                        title={
                                            activeAgentLabel
                                                ? `${activeAgentLabel} supplies its own model. Pick a model to use one instead.`
                                                : undefined
                                        }
                                        onChange={(value) => {
                                            setOptions((current) => ({
                                                ...current,
                                                modelDeployment: value,
                                                // Choosing a model is the way out of agent mode. The
                                                // two cannot both apply, and the server reads a model
                                                // sent alongside an agent as an override of it.
                                                agentSelection: undefined,
                                            }));
                                            rememberModelSelection(value);
                                        }}
                                    />
                                )}

                                {agentOptions.length > 0 && (
                                    <Dropdown
                                        options={agentOptions}
                                        value={options.agentSelection}
                                        placeholder="Agent"
                                        clearable
                                        icon={<Bot size={15} />}
                                        onChange={(value) =>
                                            setOptions((current) => ({
                                                ...current,
                                                // The model selection is kept, not cleared: it is
                                                // simply not in force, and it comes back the moment
                                                // the agent is cleared.
                                                agentSelection: value,
                                            }))
                                        }
                                    />
                                )}

                                {promptOptions.length > 0 && (
                                    <Dropdown
                                        options={promptOptions}
                                        value={options.promptId}
                                        placeholder="Prompt"
                                        clearable
                                        icon={<FileText size={15} />}
                                        onChange={onPickPrompt}
                                    />
                                )}

                                {/* Only offered once there is something to save. A prompt is wording
                                    you have already refined, so the moment worth catching is after it
                                    has been written, not before. */}
                                {canPost && text.trim().length > 0 && (
                                    <ToolToggle
                                        active={false}
                                        onClick={saveWrittenTextAsPrompt}
                                        icon={<BookmarkPlus size={15} />}
                                        label="Save as prompt"
                                    />
                                )}

                                <span className="mx-0.5 h-6 w-px bg-edge-strong" aria-hidden="true" />

                                <ToolToggle
                                    active={options.documentSearch || contextItems.length > 0}
                                    disabled={gating.disabledByImageGeneration}
                                    onClick={() => setPickerOpen((open) => !open)}
                                    icon={<Search size={15} />}
                                    label={
                                        contextItems.length > 0
                                            ? `Documents · ${contextItems.length}`
                                            : 'Documents'
                                    }
                                />

                                {gating.showWeb && (
                                    <ToolToggle
                                        active={options.webSearch}
                                        disabled={gating.disabledByImageGeneration}
                                        onClick={() =>
                                            setOptions((current) => ({
                                                ...current,
                                                webSearch: !current.webSearch,
                                            }))
                                        }
                                        icon={<Globe size={15} />}
                                        label="Web"
                                    />
                                )}

                                {gating.showImage && (
                                    <ToolToggle
                                        active={options.imageGeneration}
                                        onClick={() =>
                                            setOptions((current) => ({
                                                ...current,
                                                imageGeneration: !current.imageGeneration,
                                            }))
                                        }
                                        icon={<ImageIcon size={15} />}
                                        label="Image"
                                    />
                                )}

                                {/* Deep research sets both source_review_enabled and
                                    deep_research_enabled, matching the existing client. It appears
                                    only once there is something to research: web search, or URLs
                                    in the prompt. */}
                                {gating.showDeepResearch && (
                                    <ToolToggle
                                        active={options.deepResearch}
                                        disabled={gating.disabledByImageGeneration}
                                        onClick={() =>
                                            setOptions((current) => ({
                                                ...current,
                                                deepResearch: !current.deepResearch,
                                            }))
                                        }
                                        icon={<Telescope size={15} />}
                                        label="Deep research"
                                    />
                                )}

                                {/* Only offered when the prompt actually contains a URL. */}
                                {gating.showUrlAccess && (
                                    <ToolToggle
                                        active={options.urlAccess}
                                        disabled={gating.disabledByImageGeneration}
                                        onClick={() =>
                                            setOptions((current) => ({
                                                ...current,
                                                urlAccess: !current.urlAccess,
                                            }))
                                        }
                                        icon={<Link2 size={15} />}
                                        label="Read URLs"
                                    />
                                )}

                                {/* Only shown when a reasoning level is a real choice: the selected
                                    model has to offer one, and neither an agent nor image generation
                                    can be in play, because neither carries the parameter. The level
                                    is stored per model, so it survives a reload and applies to this
                                    model alone. It is clearable only where no level is in effect —
                                    a deployment with no model catalog — because that is the one case
                                    where "no level" is a state to get back to. */}
                                {gating.showReasoning && reasoningLevels.length > 0 && (
                                    <Dropdown
                                        options={reasoningLevels}
                                        value={options.reasoningEffort}
                                        placeholder="Reasoning"
                                        clearable={!reasoningKey}
                                        icon={<Gauge size={15} />}
                                        onChange={chooseReasoningLevel}
                                    />
                                )}
                            </>
                        )}

                        <div className="ml-auto flex items-center gap-1.5">
                            <input
                                ref={fileInputRef}
                                type="file"
                                className="hidden"
                                onChange={onSelectFile}
                            />

                            {features.enable_speech_to_text_input && (
                                <VoiceInput
                                    onTranscribed={(transcript) =>
                                        setText((current) =>
                                            current ? `${current} ${transcript}` : transcript,
                                        )
                                    }
                                />
                            )}

                            <button
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={
                                    uploading ||
                                    !gating.showFileUpload ||
                                    gating.disabledByImageGeneration
                                }
                                title="Attach a file"
                                aria-label="Attach a file"
                                className={clsx(
                                    'inline-flex h-9 w-9 items-center justify-center rounded-xl border border-edge',
                                    'bg-surface-1 text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1',
                                    'disabled:cursor-not-allowed disabled:opacity-40',
                                )}
                            >
                                {uploading ? (
                                    <Loader2 size={16} className="animate-spin" />
                                ) : (
                                    <Paperclip size={16} />
                                )}
                            </button>

                            {streaming ? (
                                <button
                                    type="button"
                                    onClick={handleStop}
                                    aria-label="Stop generating"
                                    className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-danger-soft text-danger transition-colors hover:bg-danger hover:text-white"
                                >
                                    <Square size={15} className="fill-current" />
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    onClick={submit}
                                    disabled={!text.trim() || !canPost}
                                    aria-label={
                                        shared && !streaming
                                            ? 'Send to this conversation'
                                            : 'Send message'
                                    }
                                    className={clsx(
                                        'inline-flex h-9 w-9 items-center justify-center rounded-xl',
                                        'bg-accent text-on-accent transition-colors hover:bg-accent-hover',
                                        'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent',
                                    )}
                                >
                                    <ArrowUp size={17} />
                                </button>
                            )}
                        </div>
                    </div>
                </div>

                <AiNotice />
            </div>

            {fillingPrompt ? (
                <PromptVariablesDialog
                    promptId={String(fillingPrompt.id ?? '')}
                    promptName={String(fillingPrompt.name ?? 'Prompt')}
                    content={String(fillingPrompt.content ?? '')}
                    context={promptContext()}
                    // Nothing is pre-filled in a shared conversation: a value remembered from a
                    // private chat would become visible to every participant on send.
                    shared={shared}
                    sources={promptFillSources()}
                    onCancel={() => {
                        fillRangeRef.current = null;
                        setFillingPrompt(null);
                    }}
                    onSubmit={(filled) => {
                        const range = fillRangeRef.current ?? undefined;
                        fillRangeRef.current = null;
                        setFillingPrompt(null);
                        insertIntoComposer(filled, range);
                    }}
                />
            ) : null}

            {savingDraft ? (
                <PromptEditorDialog
                    draft={savingDraft}
                    saving={savingPrompt}
                    error={saveError}
                    onChange={setSavingDraft}
                    onSave={() => void savePromptDraft()}
                    onCancel={() => {
                        setSavingDraft(null);
                        setSaveError(null);
                    }}
                />
            ) : null}
        </div>
    );
}
