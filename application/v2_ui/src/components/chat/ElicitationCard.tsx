// ElicitationCard.tsx

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Check, ChevronRight, HelpCircle, X } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { ComposerEditor } from './ComposerEditor';
import {
    selectElicitation,
    selectElicitationDraft,
    useOrchestrationStore,
} from '../../stores/orchestrationStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { answerElicitation } from '../../lib/orchestrationController';
import {
    buildElicitationAnswer,
    elicitationFieldKind,
    elicitationFieldLabel,
    elicitationFieldReferences,
    elicitationPages,
    isFileReference,
    type ElicitationDraft,
} from '../../lib/elicitationAnswers';
import { messageToPlainText } from '../../lib/messageText';
import type { ComposerDraft } from '../../lib/composerDraft';
import type { Elicitation, ElicitationAction, ElicitationContext, ElicitationResponse } from '../../lib/orchestration';
import type { PromptResolutionContext } from '../../lib/promptVariables';

export function ElicitationCard({
    conversationId,
    turnId,
}: {
    conversationId: string;
    turnId: string;
}) {
    const elicitation = useOrchestrationStore((state) =>
        selectElicitation(state, conversationId, turnId));
    const draft = useOrchestrationStore((state) =>
        selectElicitationDraft(state, conversationId, turnId));
    if (!elicitation || !draft) {
        return null;
    }
    return (
        <ElicitationForm
            conversationId={conversationId}
            elicitation={elicitation}
            draft={draft}
            onDraftChange={(update) => useOrchestrationStore.getState().updateElicitationDraft(
                conversationId, turnId, elicitation.elicitation_id, elicitation.revision ?? 0, update,
            )}
            onAnswer={(response, context) => void answerElicitation({
                conversationId, turnId, response, context,
                elicitationId: elicitation.elicitation_id,
                elicitationRevision: elicitation.revision ?? 0,
            })}
        />
    );
}

/** Shared question inputs; the caller owns either the main-turn or editor-scoped continuation. */
export function ElicitationForm({
    conversationId,
    elicitation,
    draft,
    onDraftChange,
    onAnswer,
    onCancel,
    cancelLabel = 'Cancel and abandon this request',
    ariaLabel = 'Follow-up questions',
}: {
    conversationId: string;
    elicitation: Elicitation;
    draft: ElicitationDraft;
    onDraftChange: (update: (current: ElicitationDraft) => ElicitationDraft) => void;
    onAnswer: (response: ElicitationResponse, context?: ElicitationContext) => void;
    onCancel?: () => void;
    cancelLabel?: string;
    ariaLabel?: string;
}) {
    const bootstrap = useBootstrapStore((state) => state.data);
    const messages = useChatStore((state) => state.messages);
    const conversations = useChatStore((state) => state.conversations);
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const instanceId = useId().replace(/:/g, '');
    const pageRef = useRef<HTMLDivElement>(null);

    const promptContext: PromptResolutionContext = useMemo(() => {
        const ownMessages = activeConversationId === conversationId ? messages : [];
        const lastUser = [...ownMessages].reverse().find((message) => message.role === 'user');
        const lastAssistant = [...ownMessages].reverse().find((message) => message.role === 'assistant');
        return {
            userName: String(bootstrap?.user?.display_name ?? ''),
            conversationTitle: conversations.find((conversation) => conversation.id === conversationId)?.title ?? '',
            lastUserMessage: lastUser ? messageToPlainText(lastUser) : '',
            lastAssistantMessage: lastAssistant ? messageToPlainText(lastAssistant) : '',
        };
    }, [activeConversationId, conversationId, messages, conversations, bootstrap?.user?.display_name]);
    const pages = useMemo(() => elicitation ? elicitationPages(elicitation) : [], [elicitation]);
    const answer = useMemo(() => elicitation && draft
        ? buildElicitationAnswer(elicitation, draft, promptContext)
        : null, [elicitation, draft, promptContext]);
    const pageIndex = Math.min(draft?.pageIndex ?? 0, pages.length);

    useEffect(() => {
        const target = pageRef.current?.querySelector<HTMLElement>(
            'input:not([type="file"]):not([disabled]), textarea:not([disabled]), button:not([disabled])',
        );
        (target ?? pageRef.current)?.focus();
    }, [pageIndex, elicitation?.elicitation_id, elicitation?.revision]);

    if (!elicitation || !draft || !answer) {
        return null;
    }
    const isReview = pageIndex === pages.length;
    const canFinish = Object.keys(answer.errors).length === 0 && !answer.pendingUploads;
    const currentErrors = (pages[pageIndex] ?? []).filter((name) => answer.errors[name]);
    const canAdvance = isReview ? canFinish : currentErrors.length === 0;
    const updateDraft = onDraftChange;
    const changePage = (index: number) =>
        updateDraft((current) => ({ ...current, pageIndex: index }));
    const send = (action: ElicitationAction) => {
        if (draft.submitting || (action === 'accept' && !canFinish)) {
            return;
        }
        if (action === 'cancel' && onCancel) {
            onCancel();
        } else {
            onAnswer(
                action === 'accept' ? answer.response : { action, content: {} },
                action === 'accept' ? answer.context : undefined,
            );
        }
    };
    const advance = () => {
        if (draft.submitting) {
            return;
        }
        if (!canAdvance) {
            return;
        }
        if (isReview) {
            send('accept');
        } else {
            changePage(pageIndex + 1);
        }
    };

    return (
        <section
            aria-label={ariaLabel}
            className="my-4 min-w-0 rounded-2xl border border-edge-strong bg-surface-3 p-4 shadow-glass sm:p-5"
        >
            <div className="flex items-start gap-3">
                <HelpCircle size={20} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                    <h3 className="text-base font-semibold text-text-1">{isReview ? 'Review your answers' : 'A few details before I continue'}</h3>
                    <p className="mt-1 break-words text-sm text-text-2">{elicitation.message}</p>
                </div>
                <span className="shrink-0 text-xs text-text-3" aria-label={`Question page ${Math.min(pageIndex + 1, pages.length)} of ${pages.length}`}>
                    {isReview ? 'Review' : `${pageIndex + 1}/${pages.length}`}
                </span>
            </div>
            <nav aria-label="Question steps" className="mt-4 flex flex-wrap gap-2 border-b border-edge-strong pb-4">
                {pages.map((names, index) => {
                    const complete = names.every((name) => !answer.errors[name] && name in answer.response.content);
                    return (
                        <button key={index} type="button" disabled={draft.submitting}
                            aria-current={!isReview && pageIndex === index ? 'step' : undefined}
                            onClick={() => changePage(index)}
                            className={`flex min-h-11 min-w-11 items-center gap-2 rounded-xl px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${pageIndex === index ? 'bg-accent-soft font-medium text-accent' : 'text-text-2 hover:bg-surface-sunken'}`}>
                            {complete ? <Check size={16} aria-hidden="true" /> : <span aria-hidden="true">{index + 1}</span>}
                            <span className="max-w-40 truncate">{names.length === 1
                                ? elicitationFieldLabel(names[0], elicitation.requested_schema.properties[names[0]])
                                : `Questions ${index + 1}`}</span>
                        </button>
                    );
                })}
            </nav>
            <form
                className="mt-5"
                aria-busy={draft.submitting}
                onSubmit={(event) => {
                    event.preventDefault();
                    advance();
                }}
            >
                <div ref={pageRef} tabIndex={-1} className="space-y-5 outline-none">
                    {isReview ? Object.entries(elicitation.requested_schema.properties).map(([name, field]) => (
                        <div key={name} className="flex min-w-0 items-start gap-3 border-b border-edge-strong pb-3">
                            <div className="min-w-0 flex-1">
                                <p className="text-sm font-medium text-text-1">{elicitationFieldLabel(name, field)}</p>
                                <p className="mt-1 whitespace-pre-wrap break-words text-sm text-text-2">
                                    {name in answer.response.content
                                        ? elicitationFieldKind(elicitation, name) === 'files'
                                            ? elicitationFieldReferences(elicitation, name, draft).map((reference) => reference.label || reference.id).join(', ')
                                            : Array.isArray(answer.response.content[name])
                                                ? (answer.response.content[name] as unknown[]).map(String).join(', ')
                                                : typeof answer.response.content[name] === 'boolean'
                                                    ? answer.response.content[name] ? 'Yes' : 'No'
                                                : String(answer.response.content[name])
                                        : answer.errors[name] ?? 'Skipped (optional)'}
                                </p>
                                {answer.context[name]?.text ? <p className="mt-1 break-words text-xs text-text-3">{answer.context[name].text}</p> : null}
                            </div>
                            <GlassButton type="button" size="sm" variant="ghost" disabled={draft.submitting}
                                aria-label={`Edit ${elicitationFieldLabel(name, field)}`}
                                onClick={() => changePage(pages.findIndex((page) => page.includes(name)))}>Edit</GlassButton>
                        </div>
                    )) : (pages[pageIndex] ?? []).map((name) => (
                        <QuestionField
                            key={`${elicitation.elicitation_id}:${elicitation.revision ?? 0}:${name}`}
                            name={name}
                            id={`elicitation-${instanceId}-${encodeURIComponent(elicitation.elicitation_id)}-${elicitation.revision ?? 0}-${encodeURIComponent(name)}`}
                            elicitation={elicitation}
                            draft={draft}
                            conversationId={conversationId}
                            promptContext={promptContext}
                            error={answer.errors[name]}
                            onValue={(value) => updateDraft((current) => ({
                                ...current,
                                values: { ...current.values, [name]: value },
                                error: null,
                            }))}
                            onCustom={(enabled) => updateDraft((current) => ({
                                ...current, customFields: { ...current.customFields, [name]: enabled }, error: null,
                            }))}
                            onCustomText={(text) => updateDraft((current) => ({
                                ...current, customValues: { ...current.customValues, [name]: text }, error: null,
                            }))}
                            onEditor={(update) => updateDraft((current) => ({
                                ...current,
                                editors: {
                                    ...current.editors,
                                    [name]: typeof update === 'function' ? update(current.editors[name]) : update,
                                },
                                error: null,
                            }))}
                            onSubmit={advance}
                        />
                    ))}
                </div>
                {draft.error ? (
                    <p role="alert" className="mt-3 rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
                        {draft.error}
                    </p>
                ) : null}
                <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-edge-strong pt-4">
                    <GlassButton
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => send('cancel')}
                        disabled={draft.submitting}
                        aria-label={cancelLabel}
                    >
                        <X size={14} aria-hidden="true" />
                        Cancel
                    </GlassButton>
                    <GlassButton
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => send('decline')}
                        disabled={draft.submitting}
                        aria-label="Decline to answer"
                    >
                        Continue without answers
                    </GlassButton>
                    <div className="ml-auto flex items-center gap-2">
                        {pageIndex > 0 ? (
                            <GlassButton type="button" size="sm" variant="subtle"
                                onClick={() => changePage(pageIndex - 1)} disabled={draft.submitting}>
                                Back
                            </GlassButton>
                        ) : null}
                        <GlassButton type="submit" size="sm" variant="primary"
                            disabled={draft.submitting || !canAdvance}>
                            {draft.submitting ? 'Submitting...' : isReview ? 'Use these answers' : pageIndex === pages.length - 1 ? 'Review answers' : 'Next'}
                            {!draft.submitting ? <ChevronRight size={14} aria-hidden="true" /> : null}
                        </GlassButton>
                    </div>
                </div>
                {(isReview ? !canFinish : !canAdvance) ? (
                    <div className="mt-2 text-right text-xs text-text-3" aria-live="polite">
                        <p>{answer.pendingUploads
                            ? 'Wait for the attached files to finish processing.'
                            : 'Complete this answer before continuing.'}</p>
                        {Object.keys(answer.errors).filter((name) => !pages[pageIndex]?.includes(name)).map((name) => (
                            <button key={name} type="button" className="ml-3 text-accent underline"
                                onClick={() => changePage(pages.findIndex((page) => page.includes(name)))}>
                                Review {elicitationFieldLabel(name, elicitation.requested_schema.properties[name])}
                            </button>
                        ))}
                    </div>
                ) : null}
                {!isReview ? <p className="mt-3 text-xs text-text-3">Nothing is sent until you review and submit all answers.</p> : null}
            </form>
        </section>
    );
}

function QuestionField({
    name, id, elicitation, draft, conversationId, promptContext, error,
    onValue, onCustom, onCustomText, onEditor, onSubmit,
}: {
    name: string;
    id: string;
    elicitation: Elicitation;
    draft: ElicitationDraft;
    conversationId: string;
    promptContext: PromptResolutionContext;
    error?: string;
    onValue: (value: unknown) => void;
    onCustom: (enabled: boolean) => void;
    onCustomText: (text: string) => void;
    onEditor: React.Dispatch<React.SetStateAction<ComposerDraft>>;
    onSubmit: () => void;
}) {
    const field = elicitation.requested_schema.properties[name];
    const kind = elicitationFieldKind(elicitation, name);
    const label = elicitationFieldLabel(name, field);
    const required = elicitation.requested_schema.required.includes(name);
    const value = draft.values[name];
    const selected = Array.isArray(value) ? value : value === undefined ? [] : [value];
    const files = kind === 'files';
    const suggestions = kind === 'suggestedSingle' || kind === 'suggestedMultiple';
    const choiceHint = elicitation.ui_hints.fields?.[name];
    const custom = Boolean(draft.customFields?.[name]);
    const [contextOpen, setContextOpen] = useState(Boolean(
        draft.editors[name]?.text || draft.editors[name]?.contextItems?.length || draft.editors[name]?.uploads?.length,
    ));
    const options = files
        ? (elicitation.ui_hints.fields?.[name]?.candidates ?? []).filter(isFileReference)
            .map((candidate) => ({
                value: candidate.id,
                label: candidate.label || candidate.id,
                detail: candidate.scope.name || candidate.scope.kind,
            }))
        : kind === 'boolean' ? [{ value: true, label: 'Yes', detail: '' }, { value: false, label: 'No', detail: '' }]
        : suggestions ? (choiceHint?.choices ?? []).map((choice) => ({
            value: choice.value, label: choice.label, detail: choice.description ?? '',
        })) : (kind === 'radio' ? field.enum ?? [] : kind === 'checkboxes' ? field.items?.enum ?? [] : [])
            .filter((option) => ['string', 'number', 'boolean'].includes(typeof option))
            .map((option) => ({ value: option, label: String(option), detail: '' }));
    const multiple = kind === 'checkboxes' || kind === 'suggestedMultiple' || (files && field.type === 'array');
    const primaryEditor = kind === 'text' || (kind === 'arrayText' && field.items?.type === 'string');
    const nativeArray = kind === 'arrayText' && !primaryEditor;
    const inputClass = 'mt-1 w-full rounded-xl border border-edge bg-surface-2 px-3 py-2 text-sm text-text-1 focus:outline-none focus:ring-2 focus:ring-accent-ring';
    const describedBy = [field.description ? `${id}-description` : '', error ? `${id}-error` : '']
        .filter(Boolean).join(' ') || undefined;

    return (
        <fieldset className="min-w-0 space-y-2" aria-required={required} aria-describedby={describedBy}>
            <legend className="text-sm font-medium text-text-1">
                {label}{required ? <span className="text-danger" aria-hidden="true"> *</span> : null}
            </legend>
            {field.description ? <p id={`${id}-description`} className="text-xs text-text-3">{field.description}</p> : null}
            {multiple && !files ? <p className="text-xs text-text-3">Choose any that apply.</p> : null}
            {options.length > 0 ? (
                <div className="max-h-96 space-y-2 overflow-y-auto p-0.5">
                    {options.map((option, index) => (
                        <label key={index} className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm text-text-2 motion-safe:transition-colors ${selected.includes(option.value) && (multiple || !custom) ? 'border-accent bg-accent-soft' : 'border-edge-strong bg-surface-2 hover:bg-surface-sunken'}`}>
                            <input
                                type={multiple ? 'checkbox' : 'radio'}
                                name={`${id}-choice`}
                                className="mt-1 accent-accent"
                                checked={selected.includes(option.value) && (multiple || !custom)}
                                disabled={draft.submitting}
                                onChange={(event) => {
                                    if (!multiple) onCustom(false);
                                    onValue(multiple
                                    ? event.target.checked
                                        ? [...selected, option.value]
                                        : selected.filter((item) => item !== option.value)
                                    : option.value);
                                }}
                            />
                            <span className="min-w-0 break-words">
                                {option.label}
                                {option.detail ? <span className="mt-1 block text-xs text-text-3">{option.detail}</span> : null}
                            </span>
                        </label>
                    ))}
                    {suggestions && choiceHint?.allow_custom ? (
                        <label className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm text-text-2 ${custom ? 'border-accent bg-accent-soft' : 'border-edge-strong bg-surface-2'}`}>
                            <input type={multiple ? 'checkbox' : 'radio'} name={`${id}-choice`}
                                checked={custom} disabled={draft.submitting} className="accent-accent"
                                onChange={(event) => onCustom(event.target.checked)} />
                            Write my own
                        </label>
                    ) : null}
                    {files && selected.length > 0 ? (
                        <button type="button" className="text-xs text-accent underline" disabled={draft.submitting}
                            onClick={() => onValue(multiple ? [] : undefined)}>
                            Clear suggested selections
                        </button>
                    ) : null}
                    {suggestions && custom ? (
                        <label className="block text-sm text-text-2">
                            Your answer for {label}
                            <textarea rows={2} maxLength={4000} className={inputClass}
                                value={draft.customValues?.[name] ?? ''} disabled={draft.submitting}
                                onChange={(event) => onCustomText(event.target.value)}
                                aria-describedby={describedBy} placeholder="Write the answer that fits your task" />
                        </label>
                    ) : null}
                </div>
            ) : null}
            {kind === 'number' ? (
                <input id={`${id}-value`} type="number" aria-label={label}
                    aria-required={required} aria-describedby={describedBy}
                    step={field.type === 'integer' ? 1 : 'any'} className={inputClass}
                    value={typeof value === 'string' || typeof value === 'number' ? value : ''}
                    disabled={draft.submitting} onChange={(event) => onValue(event.target.value)} />
            ) : nativeArray ? (
                <textarea id={`${id}-value`} rows={3} aria-label={label}
                    aria-required={required} aria-describedby={describedBy}
                    className={inputClass} placeholder="One value per line"
                    value={typeof value === 'string' ? value : ''} disabled={draft.submitting}
                    onChange={(event) => onValue(event.target.value)} />
            ) : null}
            {!primaryEditor && !files ? <button type="button" disabled={draft.submitting}
                className="min-h-11 rounded-lg text-sm text-accent underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                aria-expanded={contextOpen} onClick={() => setContextOpen((open) => !open)}>
                {contextOpen ? 'Hide additional context' : 'Add context or a file (optional)'}
            </button> : null}
            {primaryEditor || files || contextOpen ? <ComposerEditor
                id={`${id}-editor`}
                label={primaryEditor ? label : `Additional details for ${label} (optional)`}
                draft={draft.editors[name]}
                onChange={onEditor}
                conversationId={conversationId}
                disabled={draft.submitting}
                rows={kind === 'arrayText' ? 3 : 2}
                multipleFiles={!files || field.type === 'array'}
                knowledgeReferences={elicitationFieldReferences(elicitation, name, draft)}
                placeholder={kind === 'arrayText' && primaryEditor
                    ? 'One value per line, # references, or / prompts'
                    : files
                        ? 'Reference a file with #, upload one, or add details'
                        : 'Write an answer, # reference a file, or / use a prompt'}
                promptContext={{
                    ...promptContext,
                    composerText: draft.editors[name].text,
                    selectedDocuments: elicitationFieldReferences(elicitation, name, draft)
                        .filter(isFileReference).map((reference) => reference.label || reference.id),
                }}
                onSubmit={onSubmit}
            /> : null}
            {error ? <p id={`${id}-error`} role="status" className="text-xs text-danger">{error}</p> : null}
        </fieldset>
    );
}
