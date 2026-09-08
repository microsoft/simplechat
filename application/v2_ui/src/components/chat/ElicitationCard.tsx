// ElicitationCard.tsx

import { useEffect, useId, useMemo, useRef } from 'react';
import { HelpCircle, X } from 'lucide-react';
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
    const pageIndex = Math.min(draft?.pageIndex ?? 0, Math.max(0, pages.length - 1));

    useEffect(() => {
        pageRef.current?.querySelector<HTMLElement>(
            'textarea:not([disabled]), input:not([type="file"]):not([disabled])',
        )?.focus();
    }, [pageIndex, elicitation?.elicitation_id, elicitation?.revision]);

    if (!elicitation || !draft || !answer) {
        return null;
    }
    const isLastPage = pageIndex === pages.length - 1;
    const canFinish = Object.keys(answer.errors).length === 0 && !answer.pendingUploads;
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
        if (isLastPage) {
            send('accept');
        } else {
            changePage(pageIndex + 1);
        }
    };

    return (
        <section
            aria-label={ariaLabel}
            className="my-3 rounded-2xl border border-edge-strong bg-surface-sunken p-3"
        >
            <div className="flex items-start gap-2">
                <HelpCircle size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                <p className="min-w-0 flex-1 text-sm text-text-1">{elicitation.message}</p>
                <span className="shrink-0 text-xs text-text-3" aria-label={`Question page ${pageIndex + 1} of ${pages.length}`}>
                    {pageIndex + 1}/{pages.length}
                </span>
            </div>
            <form
                className="mt-3"
                aria-busy={draft.submitting}
                onSubmit={(event) => {
                    event.preventDefault();
                    advance();
                }}
            >
                <div ref={pageRef} className="space-y-4">
                    {(pages[pageIndex] ?? []).map((name) => (
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
                <div className="mt-4 flex flex-wrap items-center gap-2">
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
                        Decline
                    </GlassButton>
                    <div className="ml-auto flex items-center gap-2">
                        {pageIndex > 0 ? (
                            <GlassButton type="button" size="sm" variant="subtle"
                                onClick={() => changePage(pageIndex - 1)} disabled={draft.submitting}>
                                Back
                            </GlassButton>
                        ) : null}
                        <GlassButton type="submit" size="sm" variant="primary"
                            disabled={draft.submitting || (isLastPage && !canFinish)}>
                            {draft.submitting ? 'Submitting...' : isLastPage ? 'Finish' : 'Next'}
                        </GlassButton>
                    </div>
                </div>
                {isLastPage && !canFinish ? (
                    <div className="mt-2 text-right text-xs text-text-3" aria-live="polite">
                        <p>{answer.pendingUploads
                            ? 'Wait for the attached files to finish processing.'
                            : 'Answer the required fields to finish.'}</p>
                        {Object.keys(answer.errors).filter((name) => !pages[pageIndex]?.includes(name)).map((name) => (
                            <button key={name} type="button" className="ml-3 text-accent underline"
                                onClick={() => changePage(pages.findIndex((page) => page.includes(name)))}>
                                Review {elicitationFieldLabel(name, elicitation.requested_schema.properties[name])}
                            </button>
                        ))}
                    </div>
                ) : null}
            </form>
        </section>
    );
}

function QuestionField({
    name, id, elicitation, draft, conversationId, promptContext, error,
    onValue, onEditor, onSubmit,
}: {
    name: string;
    id: string;
    elicitation: Elicitation;
    draft: ElicitationDraft;
    conversationId: string;
    promptContext: PromptResolutionContext;
    error?: string;
    onValue: (value: unknown) => void;
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
    const options = files
        ? (elicitation.ui_hints.fields?.[name]?.candidates ?? []).filter(isFileReference)
            .map((candidate) => ({
                value: candidate.id,
                label: candidate.label || candidate.id,
                detail: candidate.scope.name || candidate.scope.kind,
            }))
        : (kind === 'radio' ? field.enum ?? [] : kind === 'checkboxes' ? field.items?.enum ?? [] : [])
            .filter((option) => ['string', 'number', 'boolean'].includes(typeof option))
            .map((option) => ({ value: option, label: String(option), detail: '' }));
    const multiple = kind === 'checkboxes' || (files && field.type === 'array');
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
            {options.length > 0 ? (
                <div className="space-y-1.5">
                    {options.map((option, index) => (
                        <label key={index} className="flex items-start gap-2 text-sm text-text-2">
                            <input
                                type={multiple ? 'checkbox' : 'radio'}
                                name={`${id}-choice`}
                                className="mt-1 accent-accent"
                                checked={selected.includes(option.value)}
                                disabled={draft.submitting}
                                onChange={(event) => onValue(multiple
                                    ? event.target.checked
                                        ? [...selected, option.value]
                                        : selected.filter((item) => item !== option.value)
                                    : option.value)}
                            />
                            <span className="min-w-0 break-words">
                                {option.label}
                                {option.detail ? <span className="ml-2 text-xs text-text-3"> {option.detail}</span> : null}
                            </span>
                        </label>
                    ))}
                    {files && selected.length > 0 ? (
                        <button type="button" className="text-xs text-accent underline" disabled={draft.submitting}
                            onClick={() => onValue(multiple ? [] : undefined)}>
                            Clear suggested selections
                        </button>
                    ) : null}
                </div>
            ) : null}
            {kind === 'boolean' ? (
                <label className="flex items-center gap-2 text-sm text-text-2">
                    <input id={`${id}-value`} type="checkbox" checked={value === true}
                        disabled={draft.submitting} aria-required={required}
                        onChange={(event) => onValue(event.target.checked)} />
                    {label}
                </label>
            ) : kind === 'number' ? (
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
            <ComposerEditor
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
            />
            {error ? <p id={`${id}-error`} className="text-xs text-text-3">{error}</p> : null}
        </fieldset>
    );
}
