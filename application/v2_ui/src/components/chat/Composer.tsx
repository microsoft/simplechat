// Composer.tsx
// The message input surface: textarea, send/stop control, model / agent / prompt pickers
// and the capability toggles that map onto the /api/chat/stream request fields.

import { useEffect, useId, useMemo, useRef, useState } from 'react';
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
import { sendCollaborationTyping } from '../../lib/collaboration';
import { agentSelectionKey } from '../../lib/agents';
import { buildSelectionFields, hasResolvableAgent } from '../../lib/chatRequestSelection';
import { modelSelectionKey, findModel, type ModelCatalogEntry } from '../../lib/models';
import { promptUrls, resolveGating } from '../../lib/composerGating';
import { resolveDocumentScope } from '../../lib/documentScope';
import {
    addContextItem,
    contextDocumentDescriptors,
    contextDocumentIds,
    contextFilterMode,
    contextScopes,
    contextTags,
} from '../../lib/chatContext';
import {
    reconcileContextItems,
} from '../../lib/chatContextTokens';
import {
    attachPromptToDraft,
    buildComposerDraftSubmission,
    composerDraftContextItems,
    composerDraftHasPendingUploads,
    composerDraftUnfilledVariables,
    composerDraftUserPromptValues,
    createComposerDraft,
} from '../../lib/composerDraft';
import { ComposerEditor, type ComposerEditorActions } from './ComposerEditor';
import {
    CONTEXT_HANDOFF_PARAMS,
    readContextHandoff,
    resolveContextHandoff,
    type ContextHandoffState,
} from '../../lib/chatContextHandoff';
import {
    isApprovalMode,
    resolveOrchestrationApproval,
} from '../../lib/orchestrationApproval';
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
import type { MentionSuggestion } from '../../lib/mentions';
import { useUiStore } from '../../stores/uiStore';
import { toast } from '../../stores/toastStore';
import { chatWidthClass } from '../../lib/chatWidth';
import {
    getModelSupportedLevels,
    reasoningModelKey,
    resolveReasoningSelection,
    reasoningAdjustmentMessage,
    REASONING_LABELS,
    type ReasoningEffortSettings,
} from '../../lib/reasoning';
import { Dropdown, type DropdownOption } from '../ui/Dropdown';
import { suggestPromptName } from '../../lib/promptSlash';
import { readPromptParam } from '../../lib/conversationUrl';
import { createPrompt } from '../../lib/workspaceApi';
import { messageToPlainText } from '../../lib/messageText';
import type { Json, PromptOption, WorkspaceRef } from '../../lib/types';
import { rememberPromptValues } from '../../lib/promptVariableMemory';
import {
    EMPTY_PROMPT_DRAFT,
    PromptEditorDialog,
    type PromptDraft,
} from '../prompts/PromptEditorDialog';
import { AiNotice } from './AiNotice';
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

export function Composer({ initialAgentSelection }: { initialAgentSelection?: string } = {}) {
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
    const editorActionsRef = useRef<ComposerEditorActions>(null);

    const [draft, setDraft] = useState(createComposerDraft);
    const { text, attachedPrompt } = draft;
    const promptInstance = draft.promptInstance ?? 0;
    const contextItems = composerDraftContextItems(draft);
    const uploading = composerDraftHasPendingUploads(draft);
    const uploadsBlocked = uploading || draft.uploads.some((upload) => upload.state === 'failed');
    const uploadConversationRef = useRef<string | null>(null);
    const setText: React.Dispatch<React.SetStateAction<string>> = (update) => setDraft((current) => {
        const value = typeof update === 'function' ? update(current.text) : update;
        return { ...current, text: value, contextItems: reconcileContextItems(value, current.contextItems) };
    });
    const chatWidth = useUiStore((state) => state.chatWidth);

    /** Set while a prompt is waiting on its large-run confirmation. */
    const [largeRun, setLargeRun] = useState<{
        estimate: TabularRunEstimate;
        outgoing: { message: string; promptInfo: Json | null };
        draftKey: string;
    } | null>(null);

    /** Whether the Documents button's picker is open. */
    const [pickerOpen, setPickerOpen] = useState(false);
    const [showPromptWarning, setShowPromptWarning] = useState(false);
    const [promptReview, setPromptReview] = useState({ instance: 0, request: 0 });
    useEffect(() => {
        setShowPromptWarning(false);
        setPromptReview({ instance: 0, request: 0 });
    }, [activeConversationId, shared]);
    /** A prompt being saved from what is currently written, if any. */
    const [savingDraft, setSavingDraft] = useState<PromptDraft | null>(null);
    const [savingPrompt, setSavingPrompt] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);

    const [options, setOptions] = useState<Omit<ComposerOptions, 'contextItems' | 'promptId'>>({
        documentSearch: false,
        webSearch: false,
        imageGeneration: false,
        deepResearch: false,
        urlAccess: false,
        agentSelection: initialAgentSelection,
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
    const [orchestrationOn, setOrchestrationOn] = useState(orchestrationAvailable && !initialAgentSelection);
    // Whether the user has expressed an opinion. The bootstrap resolves after the first
    // render, so the deployment's answer has to be adopted when it lands -- but adopting it
    // unconditionally would switch orchestration back on every time the payload refreshed,
    // overriding somebody who had just turned it off.
    const orchestrationChosen = useRef(Boolean(initialAgentSelection));
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
    const [excludeImageForThisMessage, setExcludeImageForThisMessage] = useState(false);
    const imageSelectionNoticeId = useId();
    const imageSelectionNoticeRef = useRef<HTMLDivElement>(null);
    const imageSelectionBlocked = orchestrating && options.imageGeneration && !excludeImageForThisMessage;
    useEffect(() => {
        setExcludeImageForThisMessage(false);
    }, [orchestrating, activeConversationId]);

    // The disclosure that hides the manual controls while orchestrating. Only reachable when the
    // administrator leaves them reachable; otherwise the planner owns every decision and there is
    // nothing under the disclosure to open.
    const [manualControlsOpen, setManualControlsOpen] = useState(false);
    const manualControlsGovernable = Boolean(orchestrationConfig?.show_manual_controls);
    // Visible inline when not orchestrating (the classic composer), and behind the disclosure
    // when orchestrating with manual controls left reachable.
    const manualControlsVisible =
        !orchestrating || (manualControlsGovernable && manualControlsOpen);

    const approvalPreference = useUserSettingsStore(
        (state) => state.settings.orchestrationApprovalMode,
    );
    const preferencesSaving = useUserSettingsStore((state) => state.saving);
    const preferenceSaveError = useUserSettingsStore((state) => state.saveError);
    const approvalOverridable = Boolean(orchestrationConfig?.allow_user_approval_override);
    const { mode: effectiveApprovalMode, invalidPreference: invalidApprovalPreference } =
        resolveOrchestrationApproval(orchestrationConfig, approvalPreference);
    // Bootstrap may arrive before preferences. Do not run an administrator's automatic mode
    // while the user's saved requirement to review is still unknown.
    const approvalBlocked = approvalOverridable && (!settingsLoaded || invalidApprovalPreference);
    const chooseApprovalMode = (value: string | undefined) => {
        if (!settingsLoaded || !approvalOverridable) {
            toast.error('Your approval preference is not currently editable.');
            return;
        }
        if (!isApprovalMode(value)) {
            toast.error('Choose a valid approval mode.');
            return;
        }
        const preferences = useUserSettingsStore.getState();
        preferences.update({ orchestrationApprovalMode: value });
        void preferences.flush();
    };

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

    // A URL in an attached prompt is just as actionable as one typed underneath it.
    const gatingPrompt = orchestrating
        ? buildComposerDraftSubmission(draft, promptContext()).message
        : text;
    const hasPromptUrls = promptUrls(gatingPrompt).length > 0;
    const gating = useMemo(
        () =>
            resolveGating({
                prompt: gatingPrompt,
                features: features as Record<string, unknown>,
                webSearchActive: options.webSearch,
                urlAccessActive: options.urlAccess,
                imageGenerationActive: options.imageGeneration,
                agentActive,
                orchestrating,
            }),
        [
            gatingPrompt,
            features,
            options.webSearch,
            options.urlAccess,
            options.imageGeneration,
            agentActive,
            orchestrating,
        ],
    );

    // No URLs means the draft no longer has a Read URLs selection. A capability losing
    // authorization is different: keep that requirement visible for server validation.
    useEffect(() => {
        if (orchestrating) {
            if (!hasPromptUrls) {
                setOptions((current) => current.urlAccess ? { ...current, urlAccess: false } : current);
            }
            return;
        }
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
    }, [hasPromptUrls, gating.showUrlAccess, gating.showDeepResearch, orchestrating]);

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
        typingRef.current = false;
        uploadConversationRef.current = null;
        setDraft((current) => current.uploads.length ? { ...current, uploads: [] } : current);
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
     * false in the second invocation's closure, so the prompt would be attached twice.
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
        attachPrompt(prompt);
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

    // Storage identity is deliberately separate from the authorized model's policy.
    const reasoningKey = reasoningModelKey(
        selectedModel,
        options.modelDeployment,
    );
    const reasoningPolicy = selectedModel?.reasoning_capabilities;
    const pendingLevels = useRef<ReasoningEffortSettings>({});
    const [reasoningNotice, setReasoningNotice] = useState<{
        key: string; message: string; effectiveEffort: string | undefined;
    } | null>(null);

    const reasoningLevels: DropdownOption[] = useMemo(() => {
        return getModelSupportedLevels(reasoningPolicy).map((level) => ({
            value: level,
            label: REASONING_LABELS[level],
        }));
    }, [reasoningPolicy]);

    // The level in effect is derived from the model and what has been stored for it, never
    // remembered on its own. A level chosen for one model must not follow the user to
    // another, and a model that offers no choice must not carry one into the request at all.
    //
    // Without a published supported policy, use model default rather than inventing levels.
    //
    // Agent mode is deliberately not a condition here. It hides the control and drops the
    // level from the request in `buildSelectionFields`, which is where that rule lives; the
    // level stays derived from the model underneath, so clearing the agent brings it back.
    const reasoningResolution = resolveReasoningSelection(
        reasoningKey,
        { ...reasoningEffortSettings, ...pendingLevels.current },
        reasoningPolicy,
    );
    const derivedReasoning = reasoningResolution.effective_effort ?? undefined;

    useEffect(() => {
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

    useEffect(() => {
        if (!reasoningKey || !settingsLoaded || !reasoningResolution.adjustment_reason) {
            return;
        }
        const message = reasoningAdjustmentMessage(
            reasoningResolution, selectedModel?.model_name || selectedModel?.display_name,
        );
        setReasoningNotice((current) =>
            current?.key === reasoningKey && current.message === message
                ? current : { key: reasoningKey, message, effectiveEffort: derivedReasoning },
        );
        // Only correct entries with a known supported replacement. Unknown policies must not
        // erase a saved preference, especially while a refreshed catalog is still arriving.
        if (derivedReasoning && !pendingLevels.current[reasoningKey]) {
            storeReasoningLevels({ [reasoningKey]: derivedReasoning });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reasoningKey, reasoningResolution.requested_effort, derivedReasoning, settingsLoaded, reasoningPolicy]);

    /** Store a chosen level against the current model, for both interfaces to read back. */
    const chooseReasoningLevel = (level: string | undefined) => {
        setReasoningNotice(null);
        if (!level) {
            // Only reachable where the control is clearable, which is where no level is
            // stored, so there is nothing to clear but the session's own choice.
            setOptions((current) => ({ ...current, reasoningEffort: undefined }));
            return;
        }

        setOptions((current) => ({ ...current, reasoningEffort: level }));

        // A catalog-less selection has no persistent identity to store against.
        if (!reasoningKey) {
            return;
        }

        if (settingsLoaded) {
            storeReasoningLevels({ [reasoningKey]: level });
            return;
        }

        pendingLevels.current = { ...pendingLevels.current, [reasoningKey]: level };
        if (settingsFailed) {
            // The map was never read, so writing would replace it. Saying so is better than
            // a control that appears to save and does not.
            toast.error(
                'Your preferences could not be loaded, so this reasoning level applies to this conversation only.',
            );
            return;
        }
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
     * The message this turn will send, plus what to tell the server about the prompt behind it.
     *
     * Built at send rather than when the prompt was picked. That is what makes `{{composer}}`
     * mean the message written underneath the card, and it is why editing a variable after
     * typing changes what is actually sent instead of only what the preview shows.
     */
    const buildOutgoing = () => buildComposerDraftSubmission(draft, promptContext());

    /**
     * Send, unless the prompt is about to start a long row-level export.
     *
     * The confirmation is raised before anything is sent and before the composer is cleared,
     * so declining leaves the typed prompt exactly where it was to be edited.
     */
    const outgoingDraftKey = () =>
        JSON.stringify([
            activeConversationId, draft,
            promptContext(), options, orchestrating,
        ]);

    const submit = (allowUnfilled = false) => {
        if (streaming || !canPost || uploadsBlocked) {
            return;
        }
        if (imageSelectionBlocked) {
            imageSelectionNoticeRef.current?.focus();
            return;
        }
        if (orchestrating && approvalBlocked) {
            toast.error(
                settingsFailed
                    ? 'Retry loading your approval preference before sending.'
                    : invalidApprovalPreference && settingsLoaded
                      ? 'Choose a valid approval mode before sending.'
                      : 'Your approval preference is still loading.',
            );
            return;
        }
        // An attached prompt is a complete message on its own, so a turn carrying one may be
        // sent without anything typed under it.
        if (!text.trim() && !attachedPrompt) {
            return;
        }
        if (attachedPrompt && !allowUnfilled && composerDraftUnfilledVariables(draft, promptContext()).length > 0) {
            setShowPromptWarning(true);
            setPromptReview((current) => ({ instance: promptInstance, request: current.request + 1 }));
            return;
        }

        const outgoing = buildOutgoing();
        if (!outgoing.message) {
            return;
        }
        editorActionsRef.current?.cancelKnowledge();
        setShowPromptWarning(false);

        // Orchestration takes a different road entirely: the server plans the work rather than
        // running a chat stream, so the large-run confirmation — a manual-flow concern about a
        // tabular export the planner has not chosen — does not apply.
        if (orchestrating) {
            dispatchOrchestration(outgoing.message, outgoing.promptInfo);
            return;
        }

        // Estimated against the whole message: a prompt that asks for every row is a long run
        // whether the request came from the card or from the box.
        const estimate = estimateLargeTabularRun(outgoing.message, tabularRunSettings);
        if (estimate.shouldConfirm) {
            setLargeRun({ estimate, outgoing, draftKey: outgoingDraftKey() });
            return;
        }

        dispatch(outgoing);
    };

    /**
     * Clear the draft once it has been sent.
     *
     * Context belongs to this turn, whether selected independently or mentioned inline.
     * The request carries it before clearing, so an empty next draft inherits no selections.
     *
     * The attached prompt goes with them, for the same reason: it belongs to the turn that was
     * just sent, and leaving it attached would silently prepend it to the next message too.
     */
    const clearDraft = () => {
        editorActionsRef.current?.cancelKnowledge();
        setDraft(createComposerDraft());
        setPickerOpen(false);
        uploadConversationRef.current = null;
        setShowPromptWarning(false);
        setPromptReview({ instance: 0, request: 0 });
        setExcludeImageForThisMessage(false);
    };

    const dispatch = (outgoing: { message: string; promptInfo: Json | null }) => {
        // Remembered only once the message is actually on its way, so a prompt that was
        // filled in and then abandoned leaves nothing behind.
        if (attachedPrompt && outgoing.promptInfo) {
            rememberPromptValues(attachedPrompt.id, composerDraftUserPromptValues(draft));
        }
        if (!activeConversationId && uploadConversationRef.current) {
            useChatStore.setState({
                activeConversationId: uploadConversationRef.current,
                activeConversationKind: 'personal',
            });
        }
        // `options` is read before the clear below replaces it, so the request carries the
        // references this message was written with.
        void sendMessage(outgoing.message, {
            ...options,
            contextItems,
            promptInfo: outgoing.promptInfo,
        });
        clearDraft();
        // Sent, so the indicator other people can see must stop now rather than when the
        // idle timer happens to fire.
        stopTyping();
    };

    /**
     * Assemble the seeds a plan request carries from the manual controls.
     *
     * These do not replace the planner's judgement, they constrain it: a document the user
     * pinned, an agent or model they chose, a saved prompt, a supported capability.
     * Unchecked controls are neutral, not permission denials. `buildSelectionFields`
     * keeps the agent-XOR-model exclusivity the chat request already relies on.
     */
    const buildOrchestrationSeeds = (message: string, promptInfo: Json | null = null): Record<string, unknown> => {
        const workspaces = contextScopes(contextItems);
        const scope = resolveDocumentScope({
            activeGroupId: bootstrap?.scope?.active_group_id,
            activePublicWorkspaceId: bootstrap?.scope?.active_public_workspace_id,
            contextGroupIds: workspaces.groupIds,
            contextPublicWorkspaceIds: workspaces.publicWorkspaceIds,
        });

        const seeds: Record<string, unknown> = {
            web_search_enabled: options.webSearch,
            required_capabilities: [
                ...(options.documentSearch || contextItems.length > 0 ? ['document_search'] : []),
                ...(options.webSearch ? ['web_search'] : []),
                ...(options.deepResearch ? ['deep_research'] : []),
                ...(options.urlAccess && promptUrls(message).length > 0 ? ['url_fetch'] : []),
            ],
            selected_document_ids: contextDocumentIds(contextItems),
            // Names for those ids, so the planner can reason about "the Q3 contract" and the
            // approval card can be read. Display only -- the server authorizes from the ids.
            context_documents: contextDocumentDescriptors(contextItems),
            // `resolve_seeds` reads doc_scope and the workspace ids alongside the document
            // ids, and `seeds_are_explicit` turns the planner's candidate probe off once
            // documents are named. Sending the ids without the scope that reaches them would
            // suppress the probe and then find nothing.
            ...scope,
        };
        const tags = contextTags(contextItems);
        if (tags.length > 0) {
            seeds.tags = tags;
        }
        // Without this a picked document beside an unrelated tag chip intersects to nothing,
        // exactly as it did on the chat path before the same field was sent there.
        const filterMode = contextFilterMode(contextItems);
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
        if (promptInfo) {
            // Resolved by the composer rather than re-read from the catalog here: the text the
            // planner is told about must be the text that was actually sent, variables filled
            // and any edit for this turn included.
            seeds.prompt_info = promptInfo;
        }
        return seeds;
    };

    const dispatchOrchestration = (message: string, promptInfo: Json | null = null) => {
        if (attachedPrompt && promptInfo) {
            rememberPromptValues(attachedPrompt.id, composerDraftUserPromptValues(draft));
        }
        const conversationId = activeConversationId ?? uploadConversationRef.current;
        if (!activeConversationId && conversationId) {
            useChatStore.setState({ activeConversationId: conversationId, activeConversationKind: 'personal' });
        }
        void startOrchestrationPlan({
            conversationId,
            message,
            approvalMode: effectiveApprovalMode,
            seeds: buildOrchestrationSeeds(message, promptInfo),
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
     * Adopt a selection handed over from the workspace.
     *
     * The hand-off is captured during the first render rather than read inside the effect, for
     * the same reason the prompt link above is: effects that rewrite the query string also run
     * on mount, and whichever ran first would decide whether the selection survived.
     *
     * Mark it applied only after resolution, so effect cleanup or StrictMode cannot consume
     * the handoff before its items arrive.
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
        const controller = new AbortController();
        void resolveContextHandoff(linkedHandoff, {
            groups: (bootstrap?.scope?.groups ?? []) as WorkspaceRef[],
            publicWorkspaces: (bootstrap?.scope?.public_workspaces ?? []) as WorkspaceRef[],
            state: linkedHandoffState,
            signal: controller.signal,
        })
            .then((items) => {
                if (controller.signal.aborted) {
                    return;
                }
                handoffApplied.current = true;
                setOptions((current) => ({
                    ...current,
                    documentSearch: items.length > 0 || current.documentSearch,
                }));
                setDraft((current) => ({
                    ...current,
                    contextItems: items.reduce(
                        (carry, item) => addContextItem(carry, item),
                        current.contextItems,
                    ),
                }));
                // Clean up only after adoption; navigation can restart this effect.
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
                if (items.length > 0) {
                    textareaRef.current?.focus();
                }
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    toast.error('Could not load the selected context. Choose it again from Documents.');
                }
            });

        return () => controller.abort();
    }, [canPost, linkedHandoff, linkedHandoffState, setSearchParams, bootstrap?.scope]);

    const applySuggestion = (suggestion: MentionSuggestion) => {
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
    };

    /* ---------------------------------------------------------------- Saved prompts */

    /**
     * The conversation facts the built-in variables resolve from.
     *
     * Assembled here rather than inside the dialog because only the composer knows what has
     * been typed but not yet sent. Nothing in this object is applied on its own: the last
     * assistant reply is offered as a chip the reader has to click, because that reply can be
     * quoting an uploaded document and text from a document should not become part of the next
     * instruction without a deliberate act.
     */
    function promptContext() {
        const ownMessages = messages.filter((message) => message.conversation_id === activeConversationId);
        const lastOfRole = (role: string) =>
            [...ownMessages].reverse().find((message) => message.role === role);
        const assistant = lastOfRole('assistant');
        const user = lastOfRole('user');
        const conversation = conversations.find((item) => item.id === activeConversationId);

        return {
            userName: String(bootstrap?.user?.display_name ?? ''),
            conversationTitle: String(conversation?.title ?? ''),
            lastAssistantMessage: assistant ? messageToPlainText(assistant) : '',
            lastUserMessage: user ? messageToPlainText(user) : '',
            composerText: text,
            selectedDocuments: contextItems.filter((item) => item.kind === 'document').map((item) => item.label),
        }
    };

    const attachPrompt = (prompt: PromptOption) => {
        editorActionsRef.current?.cancelKnowledge();
        setShowPromptWarning(false);
        setPromptReview({ instance: 0, request: 0 });
        setDraft((current) => attachPromptToDraft(current, prompt));
        window.requestAnimationFrame(() => textareaRef.current?.focus());
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

    const onPickPrompt = (promptId: string | undefined) => {
        const prompt = bootstrap?.catalogs?.prompts?.find((item) => item.id === promptId);
        if (prompt) {
            attachPrompt(prompt as PromptOption);
        } else if (promptId === undefined) {
            editorActionsRef.current?.cancelKnowledge();
            setDraft((current) => ({
                ...current, attachedPrompt: null, promptValues: {}, promptAiValues: {},
                promptInstance: (current.promptInstance ?? 0) + 1,
            }));
            setShowPromptWarning(false);
            setPromptReview({ instance: 0, request: 0 });
        } else {
            toast.error('That prompt is no longer available.');
        }
    };

    return (
        <div className="shrink-0 px-4 pb-4">
            {largeRun && (
                <LargeRunDialog
                    estimate={largeRun.estimate}
                    onContinue={() => {
                        setLargeRun(null);
                        if (streaming || !canPost || uploadsBlocked) {
                            return;
                        }
                        if (outgoingDraftKey() !== largeRun.draftKey) {
                            submit();
                            return;
                        }
                        dispatch(largeRun.outgoing);
                    }}
                    onCancel={() => setLargeRun(null)}
                />
            )}
            <div className={clsx('mx-auto w-full', chatWidthClass(chatWidth))}>
                {/* Above the input, matching the classic interface: the warning belongs
                    next to the message it is about, not below the send button. */}
                <WebSearchNotice active={options.webSearch} />
                {!agentActive && reasoningNotice?.key === reasoningKey &&
                    reasoningNotice.effectiveEffort === derivedReasoning && (
                    <p role="status" className="mb-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
                        {reasoningNotice.message}
                    </p>
                )}
                {imageSelectionBlocked && (
                    <div
                        id={imageSelectionNoticeId}
                        ref={imageSelectionNoticeRef}
                        role="alert"
                        tabIndex={-1}
                        className="mb-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn"
                    >
                        Image is selected, but Orchestrate cannot generate images.
                        Choose how to send before continuing. Your regular Chat image preference is unchanged.
                        <div className="mt-2 flex flex-wrap gap-3">
                            <button
                                type="button"
                                className="font-medium underline"
                                onClick={() => {
                                    toggleOrchestration();
                                    textareaRef.current?.focus();
                                }}
                            >
                                Use regular Chat with Image
                            </button>
                            <button
                                type="button"
                                className="font-medium underline"
                                onClick={() => {
                                    setExcludeImageForThisMessage(true);
                                    textareaRef.current?.focus();
                                }}
                            >
                                Use Orchestrate without Image for this message
                            </button>
                        </div>
                    </div>
                )}
                {orchestrating && options.imageGeneration && excludeImageForThisMessage && (
                    <p role="status" className="mb-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
                        This orchestration message will not generate images. Image remains selected for regular Chat.
                    </p>
                )}
                {orchestrating && (
                    (options.deepResearch && !gating.showDeepResearch) ||
                    (options.webSearch && !gating.showWeb) ||
                    (options.urlAccess && !gating.showUrlAccess)
                ) && (
                    <p role="status" className="mb-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
                        A selected retrieval requirement is no longer available in the current controls.
                        It will still be sent for server validation, not silently removed.
                        <button
                            type="button"
                            className="ml-2 underline"
                            onClick={() => setOptions((current) => ({
                                ...current,
                                deepResearch: gating.showDeepResearch && current.deepResearch,
                                webSearch: gating.showWeb && current.webSearch,
                                urlAccess: gating.showUrlAccess && current.urlAccess,
                            }))}
                        >
                            Clear unavailable selections
                        </button>
                    </p>
                )}

                {orchestrating && approvalOverridable && (
                    <div className="space-y-1 text-xs">
                        {settingsLoading ? (
                            <p role="status" className="mb-2 text-text-3">
                                Loading your approval preference before orchestration can start...
                            </p>
                        ) : settingsFailed ? (
                            <div role="alert" className="mb-2 rounded-xl bg-danger-soft px-3 py-2 text-danger">
                                Your approval preference could not be loaded. Your draft is unchanged.
                                <button
                                    type="button"
                                    onClick={() => void useUserSettingsStore.getState().load()}
                                    className="ml-2 font-medium underline"
                                >
                                    Retry loading approval preference
                                </button>
                            </div>
                        ) : invalidApprovalPreference ? (
                            <p role="alert" className="mb-2 rounded-xl bg-warn-soft px-3 py-2 text-warn">
                                Your saved approval preference is invalid. Choose an approval mode before sending.
                            </p>
                        ) : null}
                        {preferencesSaving && (
                            <p role="status" className="mb-2 text-text-3">Saving preferences...</p>
                        )}
                        {preferenceSaveError && (
                            <p role="alert" className="mb-2 rounded-xl bg-danger-soft px-3 py-2 text-danger">
                                {preferenceSaveError} Try changing the preference again.
                            </p>
                        )}
                    </div>
                )}

                <div className="glass glass-edge relative rounded-2xl p-2">
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

                    <ComposerEditor
                        id="composer-input"
                        label="Message"
                        draft={draft}
                        onChange={setDraft}
                        conversationId={activeConversationId}
                        disabled={!canPost}
                        rows={1}
                        promptContext={promptContext()}
                        actionsRef={editorActionsRef}
                        showPromptWarning={showPromptWarning && promptReview.instance === promptInstance}
                        submitDisabled={streaming || uploadsBlocked || imageSelectionBlocked || (orchestrating && approvalBlocked)}
                        promptReviewRequest={promptReview.instance === promptInstance ? promptReview.request : 0}
                        onSendWithUnfilled={() => submit(true)}
                        knowledgeAgent={buildSelectionFields({
                            agents: bootstrap?.catalogs?.agents as Record<string, unknown>[] | undefined,
                            models: bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
                            agentSelection: options.agentSelection,
                        }).agent_info}
                        shared={shared}
                        textareaRef={textareaRef}
                        fileInputRef={fileInputRef}
                        showTools={false}
                        uploadsDisabled={gating.disabledByImageGeneration}
                        pickerOpen={pickerOpen}
                        onPickerOpenChange={setPickerOpen}
                        searchAll={options.documentSearch}
                        onToggleSearchAll={() => setOptions((current) => ({
                            ...current,
                            documentSearch: !current.documentSearch,
                        }))}
                        mentionsEnabled={shared && canPost}
                        onMentionSelected={applySuggestion}
                        onTyping={noteTyping}
                        onBlur={stopTyping}
                        onEscape={() => {
                            if (!replyTo) {
                                return false;
                            }
                            setReplyTo(null);
                            return true;
                        }}
                        onSubmit={() => submit()}
                        onUploadComplete={(response, ownerConversationId) => {
                            if (useChatStore.getState().activeConversationId !== ownerConversationId) {
                                return;
                            }
                            if (!ownerConversationId && response.conversation_id) {
                                uploadConversationRef.current = response.conversation_id;
                            } else if (ownerConversationId) {
                                void useChatStore.getState().reloadMessages();
                            }
                        }}
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
                    />

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
                                value={settingsLoaded && !invalidApprovalPreference ? effectiveApprovalMode : undefined}
                                placeholder="Approval"
                                icon={<ShieldCheck size={15} />}
                                title="Approval mode"
                                disabled={!settingsLoaded}
                                onChange={chooseApprovalMode}
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
                                        value={attachedPrompt?.id}
                                        placeholder="Prompt"
                                        clearable
                                        icon={<FileText size={15} />}
                                        onChange={onPickPrompt}
                                        hint={<>Tip: type <strong>/</strong> in your message to choose a prompt.</>}
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
                                        active={options.imageGeneration && !orchestrating}
                                        disabled={orchestrating}
                                        onClick={() =>
                                            setOptions((current) => ({
                                                ...current,
                                                imageGeneration: !current.imageGeneration,
                                            }))
                                        }
                                        icon={<ImageIcon size={15} />}
                                        label={orchestrating ? 'Image unavailable in Orchestrate' : 'Image'}
                                    />
                                )}

                                {/* In Orchestrate this is a positive requirement, independent of Web. */}
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
                                    !canPost ||
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
                                    onClick={() => submit()}
                                    disabled={(!text.trim() && !attachedPrompt) || !canPost || uploadsBlocked || imageSelectionBlocked || (orchestrating && approvalBlocked)}
                                    aria-describedby={imageSelectionBlocked ? imageSelectionNoticeId : undefined}
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
