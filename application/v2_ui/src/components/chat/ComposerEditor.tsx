// ComposerEditor.tsx

import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, FileText, Loader2, Paperclip, RotateCcw, Search, X } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import {
    addContextItem,
    contextDocumentIds,
    contextFilterMode,
    contextScopes,
    contextTags,
    removeContextItem,
    type ContextItem,
} from '../../lib/chatContext';
import {
    hasContextMention,
    insertContextToken,
    readContextQuery,
    reconcileContextItems,
    removeContextToken,
    type ContextQuery,
} from '../../lib/chatContextTokens';
import { candidateToContextItem, type ContextCandidate } from '../../lib/contextMentions';
import {
    attachPromptToDraft,
    composerDraftKnowledgeContext,
    composerDraftReferences,
    composerReferenceKey,
    interruptComposerDraftUploads,
    type ComposerDraft,
    type ComposerReference,
    type ComposerUpload,
} from '../../lib/composerDraft';
import {
    CHAT_UPLOAD_ACCEPT,
    cancelRetainedComposerUpload,
    chatUploadTargets,
    chatUploadValidationError,
    conversationAttachmentReferences,
    hasRetainedComposerUpload,
    normalizeChatUpload,
    pollChatUpload,
    retainComposerUploadProcessing,
} from '../../lib/chatUploads';
import { uploadDocument, type ChatUploadResponse } from '../../lib/endpoints';
import { findMentionAtCaret, replaceMention, type MentionMatch, type MentionSuggestion } from '../../lib/mentions';
import { attachedPromptContent, attachedPromptIsEdited } from '../../lib/promptRequest';
import { filterPromptsForSlash, readSlashQuery, type SlashQuery } from '../../lib/promptSlash';
import type { PromptResolutionContext } from '../../lib/promptVariables';
import { usePromptVariableValues, type PromptAiValue } from '../../lib/usePromptVariableValues';
import { usePromptKnowledgeFill } from '../../lib/usePromptKnowledgeFill';
import type { PromptKnowledgeRequest } from '../../lib/promptKnowledge';
import type { Json, PromptOption, WorkspaceRef } from '../../lib/types';
import { AttachedPromptCard } from './AttachedPromptCard';
import {
    COMPOSER_TEXT_CLASS,
    COMPOSER_TRANSPARENT_TEXT_STYLE,
    ComposerHighlight,
    useHighlightScrollSync,
} from './ComposerHighlight';
import { ContextChips } from './ContextChips';
import { ContextMenu, useContextSuggestions, type ContextSearchScope } from './ContextMenu';
import { DocumentPickerPopover } from './DocumentPickerPopover';
import { MentionMenu, useMentionSuggestions } from './MentionMenu';
import { PromptSlashMenu } from './PromptSlashMenu';

export interface ComposerEditorProps {
    id: string;
    label: string;
    draft: ComposerDraft;
    onChange: React.Dispatch<React.SetStateAction<ComposerDraft>>;
    conversationId: string | null;
    disabled?: boolean;
    placeholder?: string;
    rows?: number;
    onSubmit?: () => void;
    multipleFiles?: boolean;
    promptContext?: PromptResolutionContext;
    knowledgeReferences?: readonly ComposerReference[];
    knowledgeAgent?: Json;
    actionsRef?: React.Ref<ComposerEditorActions>;
    showPromptWarning?: boolean;
    submitDisabled?: boolean;
    promptReviewRequest?: number;
    onSendWithUnfilled?: () => void;
    shared?: boolean;
    textareaRef?: React.RefObject<HTMLTextAreaElement>;
    fileInputRef?: React.RefObject<HTMLInputElement>;
    showTools?: boolean;
    uploadsDisabled?: boolean;
    pickerOpen?: boolean;
    onPickerOpenChange?: (open: boolean) => void;
    searchAll?: boolean;
    onToggleSearchAll?: () => void;
    mentionsEnabled?: boolean;
    onMentionSelected?: (suggestion: MentionSuggestion) => void;
    onTyping?: (text: string) => void;
    onBlur?: () => void;
    onEscape?: () => boolean;
    onUploadComplete?: (response: ChatUploadResponse, ownerConversationId: string | null) => void;
}

export interface ComposerEditorActions {
    cancelKnowledge: () => void;
}

let uploadSequence = 0;

export function ComposerEditor({
    id,
    label,
    draft,
    onChange,
    conversationId,
    disabled = false,
    placeholder = 'Write an answer, # add context, or / choose a prompt…',
    rows = 2,
    onSubmit,
    multipleFiles = true,
    promptContext = {},
    knowledgeReferences = [],
    knowledgeAgent,
    actionsRef,
    showPromptWarning = false,
    submitDisabled = false,
    promptReviewRequest = 0,
    onSendWithUnfilled,
    shared: sharedOverride,
    textareaRef: externalTextareaRef,
    fileInputRef: externalFileInputRef,
    showTools = true,
    uploadsDisabled = false,
    pickerOpen: controlledPickerOpen,
    onPickerOpenChange,
    searchAll = false,
    onToggleSearchAll,
    mentionsEnabled = false,
    onMentionSelected,
    onTyping,
    onBlur,
    onEscape,
    onUploadComplete,
}: ComposerEditorProps) {
    const localTextareaRef = useRef<HTMLTextAreaElement>(null);
    const localFileInputRef = useRef<HTMLInputElement>(null);
    const textareaRef = externalTextareaRef ?? localTextareaRef;
    const fileInputRef = externalFileInputRef ?? localFileInputRef;
    const backdropRef = useRef<HTMLDivElement>(null);
    const holderRef = useRef<HTMLDivElement>(null);
    const bootstrap = useBootstrapStore((state) => state.data);
    const messages = useChatStore((state) => state.messages);
    const sharedConversation = useChatStore((state) =>
        state.activeConversationId === conversationId && state.activeConversationKind === 'collaborative',
    );
    const shared = sharedOverride ?? sharedConversation;
    const features = bootstrap?.features ?? {};
    const uploadsEnabled = features.enable_chat_file_uploads === true && !uploadsDisabled;
    const promptCatalog = (bootstrap?.catalogs?.prompts ?? []) as PromptOption[];
    const [contextQuery, setContextQuery] = useState<ContextQuery | null>(null);
    const [contextIndex, setContextIndex] = useState(0);
    const [slash, setSlash] = useState<SlashQuery | null>(null);
    const [slashIndex, setSlashIndex] = useState(0);
    const [mention, setMention] = useState<MentionMatch | null>(null);
    const [mentionIndex, setMentionIndex] = useState(0);
    const [localPickerOpen, setLocalPickerOpen] = useState(false);
    const pickerOpen = controlledPickerOpen ?? localPickerOpen;
    const setPickerOpen = onPickerOpenChange ?? setLocalPickerOpen;
    const scope: ContextSearchScope = useMemo(() => ({
        groups: (bootstrap?.scope?.groups ?? []) as WorkspaceRef[],
        publicWorkspaces: (bootstrap?.scope?.public_workspaces ?? []) as WorkspaceRef[],
        groupsEnabled: Boolean(features.enable_group_workspaces),
        publicEnabled: Boolean(features.enable_public_workspaces),
    }), [bootstrap?.scope, features.enable_group_workspaces, features.enable_public_workspaces]);
    const { candidates, loading } = useContextSuggestions(disabled ? null : contextQuery?.query ?? null, scope);
    const mentionSuggestions = useMentionSuggestions(
        mentionsEnabled && !disabled ? mention?.query ?? null : null,
    );
    const slashResults = slash && !disabled ? filterPromptsForSlash(promptCatalog, slash.query) : [];
    const [menuPlacement, setMenuPlacement] = useState<'up' | 'down'>('up');
    const menuOpen = Boolean(pickerOpen || contextQuery || slashResults.length || mentionSuggestions.length);
    useLayoutEffect(() => {
        if (!menuOpen) {
            return;
        }
        const measure = () => {
            const rect = holderRef.current?.getBoundingClientRect();
            if (!rect) {
                return;
            }
            const above = rect.top - 20;
            const below = window.innerHeight - rect.bottom - 20;
            setMenuPlacement(above >= 288 || above >= below ? 'up' : 'down');
        };
        measure();
        const observer = new ResizeObserver(measure);
        if (holderRef.current) {
            observer.observe(holderRef.current);
        }
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        return () => {
            observer.disconnect();
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [menuOpen]);
    const contextKeys = useMemo(() => new Set(draft.contextItems.map((item) => item.key)), [draft.contextItems]);
    const contextTokens = useMemo(
        () => new Set(draft.contextItems.filter(hasContextMention).map((item) => item.token)),
        [draft.contextItems],
    );
    const availableAttachments = useMemo(
        () => conversationAttachmentReferences(messages, conversationId),
        [messages, conversationId],
    );

    const attached = draft.attachedPrompt;
    const promptInstance = draft.promptInstance ?? 0;
    const promptKey = JSON.stringify([id, conversationId, promptInstance]);
    const setPromptValues = useCallback<React.Dispatch<React.SetStateAction<Record<string, string>>>>(
        (update) => onChange((current) => {
            if (current.attachedPrompt?.id !== attached?.id || (current.promptInstance ?? 0) !== promptInstance) {
                return current;
            }
            return {
                ...current,
                promptValues: typeof update === 'function' ? update(current.promptValues) : update,
            };
        }),
        [onChange, attached?.id, promptInstance],
    );
    const setPromptAiValues = useCallback<React.Dispatch<React.SetStateAction<Record<string, PromptAiValue>>>>(
        (update) => onChange((current) => {
            if (current.attachedPrompt?.id !== attached?.id || (current.promptInstance ?? 0) !== promptInstance) {
                return current;
            }
            return {
                ...current,
                promptAiValues: typeof update === 'function' ? update(current.promptAiValues ?? {}) : update,
            };
        }),
        [onChange, attached?.id, promptInstance],
    );
    const knowledgeItems = composerDraftKnowledgeContext(draft, knowledgeReferences);
    const selectedFiles = [...composerDraftReferences(draft), ...knowledgeReferences]
        .filter((reference) => reference.kind === 'document' || reference.kind === 'chat_attachment');
    const resolutionContext = {
        ...promptContext,
        selectedDocuments: promptContext.selectedDocuments
            ?? [...new Set(selectedFiles.map((reference) => reference.label || reference.id))],
        composerText: draft.text,
    };
    const promptVariables = usePromptVariableValues({
        promptId: attached?.id ?? '',
        content: attached ? attachedPromptContent(attached) : '',
        context: resolutionContext,
        shared,
        values: draft.promptValues,
        onValuesChange: setPromptValues,
        aiValues: draft.promptAiValues ?? {},
        onAiValuesChange: setPromptAiValues,
        instanceKey: promptKey,
    });
    const [searchAllKnowledge, setSearchAllKnowledge] = useState(false);
    const [localReview, setLocalReview] = useState({ promptKey: '', request: 0 });
    useEffect(() => {
        setSearchAllKnowledge(false);
        setLocalReview({ promptKey, request: 0 });
    }, [promptKey, shared]);
    const knowledgeScopes = contextScopes(knowledgeItems);
    const knowledgeKinds = [...new Set(knowledgeItems.map((item) => item.scope.kind))];
    const knowledgeRequest: PromptKnowledgeRequest = {
        prompt_content: attached ? attachedPromptContent(attached) : '',
        composer_text: draft.text,
        conversation_id: conversationId ?? undefined,
        conversation_kind: shared ? 'collaborative' : 'personal',
        selected_document_ids: searchAllKnowledge ? [] : contextDocumentIds(knowledgeItems),
        tags: searchAllKnowledge ? [] : contextTags(knowledgeItems),
        doc_scope: searchAllKnowledge || knowledgeKinds.length > 1 ? 'all' : knowledgeKinds[0] ?? 'personal',
        active_group_ids: searchAllKnowledge ? [] : knowledgeScopes.groupIds,
        active_public_workspace_ids: searchAllKnowledge ? [] : knowledgeScopes.publicWorkspaceIds,
        document_filter_mode: contextFilterMode(knowledgeItems) ?? 'intersection',
        search_all: searchAllKnowledge,
        scope_selected: !searchAllKnowledge && knowledgeItems.some((item) => item.kind === 'scope'),
        context_items: searchAllKnowledge ? [] : knowledgeItems.map((item) => ({
            kind: item.kind, id: item.id, scope: { kind: item.scope.kind, id: item.scope.id },
        })),
        agent_info: knowledgeAgent,
    };
    const knowledgeEnabled = !disabled && Boolean(attached)
        && (searchAllKnowledge || knowledgeItems.length > 0);
    const promptKnowledge = usePromptKnowledgeFill({
        request: knowledgeRequest,
        variableState: promptVariables,
        enabled: knowledgeEnabled,
        draftKey: JSON.stringify([promptKey, attached?.id, knowledgeItems]),
    });
    useImperativeHandle(actionsRef, () => ({ cancelKnowledge: promptKnowledge.cancel }));
    const reviewRequest = promptReviewRequest + (localReview.promptKey === promptKey ? localReview.request : 0);
    const fillSources = [
        { label: 'Last reply', value: promptContext.lastAssistantMessage ?? '' },
        { label: 'My last message', value: promptContext.lastUserMessage ?? '' },
        { label: 'What I have typed', value: draft.text },
    ].filter((source) => source.value.trim());

    useEffect(() => {
        const element = textareaRef.current;
        if (element) {
            element.style.height = 'auto';
            element.style.height = `${Math.min(element.scrollHeight, 224)}px`;
        }
    }, [draft.text, rows, textareaRef]);
    useHighlightScrollSync(textareaRef, backdropRef, draft.text);

    useEffect(() => {
        setContextQuery(null);
        setSlash(null);
        setMention(null);
        setLocalPickerOpen(false);
    }, [id, conversationId]);
    useEffect(() => {
        if (!draft.text || disabled) {
            setContextQuery(null);
            setSlash(null);
            setMention(null);
        }
    }, [draft.text, disabled]);

    const focusAt = (caret?: number) => window.requestAnimationFrame(() => {
        const element = textareaRef.current;
        element?.focus();
        if (caret !== undefined) {
            element?.setSelectionRange(caret, caret);
        }
    });
    const syncQueries = (element: HTMLTextAreaElement) => {
        if (disabled) {
            return;
        }
        const caret = element.selectionStart ?? 0;
        setContextQuery(readContextQuery(element.value, caret));
        setContextIndex(0);
        setSlash(readSlashQuery(element.value, caret));
        setSlashIndex(0);
        setMention(mentionsEnabled ? findMentionAtCaret(element.value, caret) : null);
        setMentionIndex(0);
    };
    const applyText = (text: string) => onChange((current) => ({
        ...current,
        text,
        contextItems: reconcileContextItems(text, current.contextItems),
    }));
    const removeContextChips = (items: ContextItem[]) => onChange((current) => {
        const dropped = new Set(items.map((item) => item.key));
        const remaining = current.contextItems.filter((entry) => !dropped.has(entry.key));
        const stillReferenced = new Set(remaining.filter(hasContextMention).map((entry) => entry.token));
        const strip = [...new Set(items.filter(hasContextMention).map((item) => item.token))]
            .filter((token) => !stillReferenced.has(token));
        return {
            ...current,
            text: strip.reduce((text, token) => removeContextToken(text, token), current.text),
            contextItems: remaining,
        };
    });
    const removeContextChip = (item: ContextItem) => onChange((current) => {
        const remaining = removeContextItem(current.contextItems, item.key);
        return {
            ...current,
            text: hasContextMention(item)
                && !remaining.some((entry) => hasContextMention(entry) && entry.token === item.token)
                ? removeContextToken(current.text, item.token)
                : current.text,
            contextItems: remaining,
        };
    });
    const toggleContextCandidate = (candidate: ContextCandidate) => {
        const existing = draft.contextItems.find((item) => item.key === candidate.key);
        if (existing) {
            removeContextChip(existing);
        } else {
            onChange((current) => ({
                ...current,
                contextItems: addContextItem(
                    current.contextItems,
                    candidateToContextItem(candidate, current.contextItems),
                ),
            }));
        }
    };
    const applyContextCandidate = (candidate: ContextCandidate) => {
        if (!contextQuery) {
            return;
        }
        const existing = draft.contextItems.find((item) => item.key === candidate.key);
        const item: ContextItem = existing
            ? { ...existing, attachment: 'mention' }
            : candidateToContextItem(candidate, draft.contextItems, 'user', 'mention');
        const next = insertContextToken(draft.text, contextQuery.start, contextQuery.end, item.token);
        onChange((current) => ({
            ...current,
            text: next.text,
            contextItems: addContextItem(current.contextItems, item),
        }));
        setContextQuery(null);
        focusAt(next.caret);
    };
    const pickSlashPrompt = (prompt: PromptOption) => {
        if (!slash) {
            return;
        }
        promptKnowledge.cancel();
        onChange((current) => attachPromptToDraft(current, prompt, slash));
        const caret = slash.start;
        setSlash(null);
        focusAt(caret);
    };
    const applyMention = (suggestion: MentionSuggestion) => {
        if (!mention) {
            return;
        }
        const next = replaceMention(draft.text, mention, suggestion.mention_text);
        applyText(next.value);
        setMention(null);
        onMentionSelected?.(suggestion);
        focusAt(next.caretIndex);
    };
    const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (event.nativeEvent.isComposing) {
            return;
        }
        if (contextQuery && loading && (event.key === 'Enter' || event.key === 'Tab')) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        const count = contextQuery && candidates.length ? candidates.length
            : slashResults.length || (mention ? mentionSuggestions.length : 0);
        if (count) {
            const index = contextQuery && candidates.length ? contextIndex
                : slashResults.length ? slashIndex : mentionIndex;
            const setIndex = contextQuery && candidates.length ? setContextIndex
                : slashResults.length ? setSlashIndex : setMentionIndex;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                setIndex((index + (event.key === 'ArrowDown' ? 1 : -1) + count) % count);
                return;
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                event.stopPropagation();
                if (contextQuery && candidates.length) {
                    applyContextCandidate(candidates[index % count]);
                } else if (slashResults.length) {
                    pickSlashPrompt(slashResults[index % count]);
                } else {
                    applyMention(mentionSuggestions[index % count]);
                }
                return;
            }
        }
        if (event.key === 'Escape') {
            if (contextQuery || slash || mention || pickerOpen) {
                event.preventDefault();
                event.stopPropagation();
                setContextQuery(null);
                setSlash(null);
                setMention(null);
                setPickerOpen(false);
                return;
            }
            if (onEscape?.()) {
                event.preventDefault();
            }
        }
        if (event.key === 'Enter' && !event.shiftKey && onSubmit) {
            event.preventDefault();
            event.stopPropagation();
            onSubmit();
        }
    };

    // Byte transfers belong to this mount. A persisted question can retain processing
    // checks beyond it; all other interruptions are recorded in the controlled draft.
    const owner = useMemo(() => ({
        id, conversationId, active: false,
        uploadIds: new Set<string>(),
        changeDraft: onChange,
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }), [id, conversationId]);
    owner.uploadIds = new Set(draft.uploads.filter((upload) =>
        upload.state === 'uploading' || upload.state === 'processing',
    ).map((upload) => upload.id));
    owner.changeDraft = onChange;
    const currentOwner = useRef(owner);
    currentOwner.current = owner;
    const requests = useRef(new Map<string, AbortController>());
    const files = useRef(new Map<string, File>());
    const uploadQueue = useRef<Promise<void>>(Promise.resolve());
    const uploadConversation = useRef<string | null>(conversationId);
    const retryFileId = useRef<string | null>(null);
    useEffect(() => {
        owner.active = true;
        uploadConversation.current = conversationId;
        uploadQueue.current = Promise.resolve();
        const ownedRequests = requests.current;
        const ownedFiles = files.current;
        return () => {
            owner.active = false;
            const interruptedIds = new Set([...owner.uploadIds, ...ownedRequests.keys()]
                .filter((localId) => !hasRetainedComposerUpload(localId, conversationId)));
            for (const controller of ownedRequests.values()) {
                controller.abort();
            }
            ownedRequests.clear();
            ownedFiles.clear();
            if (interruptedIds.size) {
                owner.changeDraft((current) => interruptComposerDraftUploads(current, interruptedIds));
            }
        };
    }, [owner, conversationId]);

    const updateUpload = (
        localId: string,
        change: Partial<ComposerUpload>,
        capturedOwner = owner,
        changeDraft = onChange,
    ) => {
        if (currentOwner.current !== capturedOwner || !capturedOwner.active) {
            return;
        }
        changeDraft((current) => ({
            ...current,
            uploads: current.uploads.map((upload) => upload.id === localId ? { ...upload, ...change } : upload),
        }));
    };

    useEffect(() => {
        const selected = new Set(draft.uploads.map((upload) => upload.id));
        for (const [localId, controller] of requests.current) {
            if (!selected.has(localId)) {
                controller.abort();
                requests.current.delete(localId);
                files.current.delete(localId);
            }
        }
        for (const upload of draft.uploads) {
            if (requests.current.has(upload.id)) {
                continue;
            }
            if (upload.state === 'failed' && upload.interrupted === 'processing' && upload.reference) {
                updateUpload(upload.id, { state: 'processing', interrupted: undefined, error: undefined });
                continue;
            }
            if (upload.state === 'uploading') {
                updateUpload(upload.id, {
                    state: 'failed',
                    interrupted: 'uploading',
                    error: 'The upload was interrupted. Choose the file again to retry.',
                });
            } else if (upload.state === 'processing' && !upload.reference) {
                updateUpload(upload.id, {
                    state: 'failed',
                    interrupted: undefined,
                    error: 'This file has no processing reference. Retry with the file or remove it.',
                });
            } else if (upload.state === 'processing' && upload.reference) {
                if (retainComposerUploadProcessing(upload, conversationId, onChange)) {
                    continue;
                }
                const controller = new AbortController();
                requests.current.set(upload.id, controller);
                void pollChatUpload(upload.reference, controller.signal, (status) => {
                    if (!controller.signal.aborted) {
                        updateUpload(upload.id, { ...status, interrupted: undefined, error: status.error });
                    }
                }).catch((error: unknown) => {
                    if (!controller.signal.aborted) {
                        updateUpload(upload.id, {
                            state: 'failed',
                            interrupted: undefined,
                            error: error instanceof Error ? error.message : 'Could not check file processing. Retry or remove it.',
                        });
                    }
                }).finally(() => {
                    if (requests.current.get(upload.id) === controller) {
                        requests.current.delete(upload.id);
                    }
                });
            }
        }
        // Each operation captures this editor's setter and identity; keystrokes must not
        // restart active requests or polls.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [draft.uploads, owner]);

    const uploadFile = async (upload: ComposerUpload, file: File, controller: AbortController) => {
        const capturedOwner = owner;
        const changeDraft = onChange;
        if (controller.signal.aborted || currentOwner.current !== capturedOwner || !capturedOwner.active) {
            return;
        }
        try {
            const owningConversationId = upload.conversationId ?? uploadConversation.current;
            updateUpload(upload.id, { conversationId: owningConversationId ?? undefined }, capturedOwner, changeDraft);
            const result = await uploadDocument(
                file,
                owningConversationId,
                controller.signal,
                {
                    groupUploadTargetId: upload.groupUploadTargetId,
                    uploadScopeGroupIds: upload.uploadScopeGroupIds,
                },
            );
            if (controller.signal.aborted || currentOwner.current !== capturedOwner) {
                return;
            }
            const normalized = normalizeChatUpload(result, file.name);
            if (owningConversationId && normalized.conversationId
                && normalized.conversationId !== owningConversationId) {
                throw new Error('The upload returned a different conversation. Remove it and try again.');
            }
            if (!uploadConversation.current && normalized.conversationId) {
                uploadConversation.current = normalized.conversationId;
            }
            updateUpload(upload.id, {
                ...normalized, interrupted: undefined, groupUploadTargets: undefined,
            }, capturedOwner, changeDraft);
            retainComposerUploadProcessing({ ...upload, ...normalized }, conversationId, changeDraft);
            onUploadComplete?.(result, conversationId);
        } catch (error) {
            if (!controller.signal.aborted) {
                const targets = chatUploadTargets(error);
                updateUpload(upload.id, {
                    state: 'failed',
                    error: targets !== null
                        ? 'Choose a group workspace for this upload, then retry.'
                        : error instanceof Error ? error.message : 'Could not upload this file.',
                    groupUploadTargets: targets ?? undefined,
                }, capturedOwner, changeDraft);
            }
        } finally {
            if (requests.current.get(upload.id) === controller) {
                requests.current.delete(upload.id);
            }
        }
    };
    const queueUpload = (upload: ComposerUpload, file: File, controller: AbortController) => {
        const start = () => uploadFile(upload, file, controller);
        const pending = uploadQueue.current.then(start, start);
        uploadQueue.current = pending;
        return pending;
    };
    const onSelectFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const chosen = Array.from(event.target.files ?? []);
        event.target.value = '';
        if (disabled || !uploadsEnabled) {
            return;
        }
        const selectedFiles = multipleFiles ? chosen : chosen.slice(0, 1);
        const replacing = retryFileId.current;
        const replacedUpload = draft.uploads.find((upload) => upload.id === replacing);
        retryFileId.current = null;
        const groupIds = contextScopes(draft.contextItems).groupIds;
        const scopedGroupIds = [...new Set([
            ...(bootstrap?.scope?.active_group_id ? [String(bootstrap.scope.active_group_id)] : []),
            ...groupIds,
        ])];
        const queued = selectedFiles.map((file, index) => {
            const error = chatUploadValidationError(file, uploadsEnabled, bootstrap?.settings?.max_file_size_mb);
            const upload: ComposerUpload = {
                id: replacedUpload && index === 0
                    ? replacedUpload.id
                    : `${id}-upload-${Date.now()}-${++uploadSequence}`,
                fileName: file.name,
                state: error ? 'failed' : 'uploading',
                error: error ?? undefined,
                conversationId: conversationId ?? undefined,
                uploadScopeGroupIds: replacedUpload?.uploadScopeGroupIds ?? scopedGroupIds,
                groupUploadTargetId: replacedUpload?.groupUploadTargetId,
            };
            files.current.set(upload.id, file);
            const controller = new AbortController();
            if (!error) {
                owner.uploadIds.add(upload.id);
                requests.current.set(upload.id, controller);
            }
            return { upload, file, controller };
        });
        onChange((current) => ({
            ...current,
            uploads: [
                ...current.uploads.filter((upload) => !queued.length || upload.id !== replacing),
                ...queued.map((item) => item.upload),
            ],
        }));
        // Serial upload requests let a new chat's first response supply the conversation
        // identity for the rest of the batch. Processing polls still run independently.
        await Promise.all(queued.filter((item) => !item.upload.error)
            .map((item) => queueUpload(item.upload, item.file, item.controller)));
    };
    const retryUpload = (upload: ComposerUpload) => {
        if (upload.reference) {
            updateUpload(upload.id, { state: 'processing', interrupted: undefined, error: undefined });
            return;
        }
        const file = files.current.get(upload.id);
        if (!file) {
            retryFileId.current = upload.id;
            fileInputRef.current?.click();
            return;
        }
        const error = chatUploadValidationError(file, uploadsEnabled, bootstrap?.settings?.max_file_size_mb);
        if (error) {
            updateUpload(upload.id, { state: 'failed', error });
            return;
        }
        const controller = new AbortController();
        requests.current.set(upload.id, controller);
        updateUpload(upload.id, { state: 'uploading', interrupted: undefined, error: undefined });
        void queueUpload(upload, file, controller);
    };
    const removeUpload = (localId: string) => {
        cancelRetainedComposerUpload(localId, conversationId);
        requests.current.get(localId)?.abort();
        requests.current.delete(localId);
        files.current.delete(localId);
        onChange((current) => ({ ...current, uploads: current.uploads.filter((upload) => upload.id !== localId) }));
    };
    const selectAttachment = (reference: ComposerReference) => onChange((current) => {
        const key = composerReferenceKey(reference);
        if (current.uploads.some((upload) => upload.reference && composerReferenceKey(upload.reference) === key)) {
            return current;
        }
        return {
            ...current,
            uploads: [...current.uploads, {
                id: `${id}-attachment-${++uploadSequence}`,
                fileName: reference.label || 'Attached file',
                reference,
                state: 'ready',
            }],
        };
    });

    return (
        <div ref={holderRef} className="relative min-w-0" data-composer-editor={id}>
            {mention && !disabled && (
                <MentionMenu suggestions={mentionSuggestions} activeIndex={mentionIndex} onSelect={applyMention}
                    placement={menuPlacement} />
            )}
            {slashResults.length > 0 && (
                <PromptSlashMenu prompts={slashResults} activeIndex={slashIndex} onSelect={pickSlashPrompt}
                    placement={menuPlacement} />
            )}
            {contextQuery && !pickerOpen && !disabled && (
                <ContextMenu candidates={candidates} loading={loading} activeIndex={contextIndex}
                    selectedKeys={contextKeys} onSelect={applyContextCandidate} placement={menuPlacement} />
            )}
            {pickerOpen && !disabled && (
                <DocumentPickerPopover scope={scope} searchAll={searchAll} selectedKeys={contextKeys}
                    onToggleSearchAll={onToggleSearchAll} onToggle={toggleContextCandidate}
                    onClear={() => removeContextChips(draft.contextItems)}
                    onClose={() => setPickerOpen(false)} placement={menuPlacement} />
            )}
            <ContextChips items={draft.contextItems}
                onRemove={(item) => !disabled && removeContextChip(item)}
                onRemoveAll={(items) => !disabled && removeContextChips(items)}
                onClear={() => !disabled && removeContextChips(draft.contextItems)} />
            {attached && (
                <AttachedPromptCard key={`${attached.id}:${promptInstance}`} id={`${id}-prompt`} name={attached.name}
                    scopeLabel={attached.scopeName} content={attachedPromptContent(attached)}
                    edited={attachedPromptIsEdited(attached)} variableState={promptVariables}
                    sources={fillSources} disabled={disabled}
                    reviewRequest={reviewRequest}
                    knowledge={promptKnowledge}
                    knowledgeEnabled={knowledgeEnabled}
                    knowledgeControls={(
                        <div className="space-y-1 rounded-lg bg-surface-sunken px-2.5 py-2 text-xs text-text-3">
                            <p className="break-words">
                                {searchAllKnowledge
                                    ? 'AI fill searches all knowledge you can access.'
                                    : knowledgeItems.length > 0
                                        ? `AI fill searches: ${knowledgeItems.map((item) => item.label).join(', ')}`
                                        : 'Choose documents, tags or a workspace to find values in knowledge.'}
                            </p>
                            <button type="button" disabled={disabled} onClick={() => setPickerOpen(true)}
                                className="rounded py-1 text-accent disabled:opacity-50">
                                Choose knowledge
                            </button>
                            <label className="flex items-start gap-2">
                                <input type="checkbox" checked={searchAllKnowledge} disabled={disabled}
                                    onChange={(event) => {
                                        promptKnowledge.cancel();
                                        setSearchAllKnowledge(event.target.checked);
                                    }} className="mt-0.5 accent-accent" />
                                Search all accessible knowledge for AI fill
                            </label>
                            {searchAllKnowledge && <p>Only widens AI fill, not your message's document selection.</p>}
                            {shared && <p>Filled values will be visible to participants when you send.</p>}
                        </div>
                    )}
                    onContentChange={(value) => {
                        promptKnowledge.cancel();
                        onChange((current) => ({
                            ...current,
                            attachedPrompt: current.attachedPrompt ? { ...current.attachedPrompt, editedContent: value } : null,
                        }));
                    }}
                    onResetContent={() => {
                        promptKnowledge.cancel();
                        onChange((current) => ({
                            ...current,
                            attachedPrompt: current.attachedPrompt ? { ...current.attachedPrompt, editedContent: null } : null,
                        }));
                    }}
                    onRemove={() => {
                        promptKnowledge.cancel();
                        onChange((current) => ({
                            ...current, attachedPrompt: null, promptValues: {}, promptAiValues: {},
                            promptInstance: (current.promptInstance ?? 0) + 1,
                        }));
                        focusAt();
                    }} />
            )}
            {attached && showPromptWarning && promptVariables.unfilled.length > 0 && (
                <div role="alert" className="mb-2 rounded-xl border border-warn/40 bg-surface-1 px-3 py-2 text-xs text-text-2">
                    <p className="font-medium">Some prompt variables are still unanswered.</p>
                    <p className="mt-1 break-words">
                        {promptVariables.unfilled.map((variable) => `{{${variable.name}}}`).join(', ')}
                        {' '}will be sent as literal placeholders if you send anyway.
                    </p>
                    <div className="mt-2 flex flex-wrap gap-3">
                        <button type="button" onClick={() => setLocalReview((current) => ({
                            promptKey, request: current.request + 1,
                        }))} className="text-accent">Review fields</button>
                        <button type="button" disabled={!knowledgeEnabled || promptKnowledge.pendingKeys.length > 0
                            || !promptVariables.unfilled.some((variable) => !variable.builtIn)}
                            onClick={() => void promptKnowledge.fill()} className="text-accent disabled:opacity-50">
                            Fill missing fields
                        </button>
                        {onSendWithUnfilled && (
                            <button type="button" disabled={disabled || submitDisabled}
                                onClick={onSendWithUnfilled} className="font-medium text-text-1 disabled:opacity-50">
                                Send anyway
                            </button>
                        )}
                    </div>
                </div>
            )}
            <label htmlFor={id} className="sr-only">{label}</label>
            <div className="relative">
                <ComposerHighlight text={draft.text} tokens={contextTokens} backdropRef={backdropRef} />
                <textarea id={id} ref={textareaRef} rows={rows} value={draft.text} disabled={disabled}
                    placeholder={placeholder}
                    onChange={(event) => {
                        applyText(event.target.value);
                        syncQueries(event.target);
                        onTyping?.(event.target.value);
                    }}
                    onSelect={(event) => syncQueries(event.currentTarget)}
                    onBlur={onBlur} onKeyDown={onKeyDown}
                    className={clsx(COMPOSER_TEXT_CLASS, 'relative resize-none bg-transparent',
                        'placeholder:text-text-3 focus:outline-none selection:bg-accent-soft disabled:cursor-not-allowed')}
                    style={COMPOSER_TRANSPARENT_TEXT_STYLE} />
            </div>
            <input ref={fileInputRef} type="file" accept={CHAT_UPLOAD_ACCEPT} multiple={multipleFiles}
                disabled={disabled || !uploadsEnabled} className="hidden" onChange={(event) => void onSelectFiles(event)} />
            {showTools && (
                <div className="flex flex-wrap items-center gap-2 px-1 pb-1">
                    <button type="button" disabled={disabled} onClick={() => setPickerOpen(!pickerOpen)}
                        aria-expanded={pickerOpen} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-text-2 hover:bg-surface-2 disabled:opacity-40">
                        <Search size={13} /> Add context
                    </button>
                    <button type="button" disabled={disabled || !uploadsEnabled}
                        onClick={() => fileInputRef.current?.click()} aria-label="Attach a file"
                        className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-text-2 hover:bg-surface-2 disabled:opacity-40">
                        <Paperclip size={13} /> Attach file
                    </button>
                    <span className="text-[11px] text-text-3"># context · / prompt</span>
                </div>
            )}
            {availableAttachments.length > 0 && (
                <details className="px-2 pb-1 text-xs text-text-2">
                    <summary className="cursor-pointer">Files in this conversation</summary>
                    <div className="mt-1 flex flex-wrap gap-1">
                        {availableAttachments.map((reference) => (
                            <button key={composerReferenceKey(reference)} type="button" disabled={disabled}
                                onClick={() => selectAttachment(reference)}
                                className="inline-flex items-center gap-1 rounded-lg border border-edge px-2 py-1 hover:bg-surface-2 disabled:opacity-40">
                                <FileText size={12} /> {reference.label}
                            </button>
                        ))}
                    </div>
                </details>
            )}
            {draft.uploads.length > 0 && (
                <ul className="space-y-1 px-1 pb-1" aria-label="Attached files" aria-live="polite">
                    {draft.uploads.map((upload) => (
                        <li key={upload.id} className="rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-xs">
                            <div className="flex items-center gap-1.5">
                                {upload.state === 'uploading' || upload.state === 'processing'
                                    ? <Loader2 size={12} className="shrink-0 animate-spin" />
                                    : upload.state === 'ready' ? <Check size={12} className="shrink-0 text-accent" /> : <FileText size={12} />}
                                <span className="min-w-0 flex-1 truncate text-text-1">{upload.fileName}</span>
                                <span className="text-text-3">
                                    {upload.state === 'uploading' ? 'Uploading…'
                                        : upload.state === 'processing' ? `Processing ${Math.round(upload.progress ?? 0)}%`
                                            : upload.state === 'ready' ? 'Ready' : 'Failed'}
                                </span>
                                {upload.state === 'failed' && (
                                    <button type="button" disabled={disabled || !uploadsEnabled
                                        || Boolean(upload.groupUploadTargets && !upload.groupUploadTargetId)}
                                        onClick={() => retryUpload(upload)} aria-label={`Retry ${upload.fileName}`}
                                        className="rounded p-1 text-text-2 hover:bg-surface-2 disabled:opacity-40">
                                        <RotateCcw size={12} />
                                    </button>
                                )}
                                <button type="button" disabled={disabled} onClick={() => removeUpload(upload.id)}
                                    aria-label={`Remove ${upload.fileName}`} className="rounded p-1 text-text-3 hover:bg-surface-2 disabled:opacity-40">
                                    <X size={12} />
                                </button>
                            </div>
                            {upload.error && <p role="alert" className="mt-1 text-danger">{upload.error}</p>}
                            {upload.groupUploadTargets && (
                                <div className="mt-1">
                                    <label htmlFor={`${upload.id}-target`} className="block text-text-2">Upload destination</label>
                                    <select id={`${upload.id}-target`} disabled={disabled}
                                        value={upload.groupUploadTargetId ?? ''}
                                        onChange={(event) => updateUpload(upload.id, { groupUploadTargetId: event.target.value })}
                                        className="mt-1 w-full rounded border border-edge bg-surface-1 px-2 py-1 text-text-1">
                                        <option value="">Choose a group workspace</option>
                                        {upload.groupUploadTargets.map((target) => (
                                            <option key={target.id} value={target.id} disabled={!target.can_upload}>
                                                {target.name}{target.can_upload ? '' : ` — ${target.reason || 'Uploads not allowed'}`}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
