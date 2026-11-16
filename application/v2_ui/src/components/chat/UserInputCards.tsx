// UserInputCards.tsx

import { useEffect, useRef, useState } from 'react';
import { ElicitationForm } from './ElicitationCard';
import { GlassButton } from '../ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useAppSessionStore } from '../../stores/appSessionStore';
import { continueInteractionChat, useChatStore } from '../../stores/chatStore';
import { useUserInputStore, type UserInputRequest } from '../../stores/userInputStore';
import { fetchUserInput, openUserInputContinuation, saveUserInput, stopUserInput } from '../../lib/userInput';
import { continueSavedInteraction } from '../../lib/orchestrationController';
import type { ElicitationContext, ElicitationResponse } from '../../lib/orchestration';
import type { ConversationKind } from '../../lib/endpoints';

export function UserInputCards({ conversationId, conversationKind }: {
    conversationId: string; conversationKind: ConversationKind | null;
}) {
    const actorId = useBootstrapStore((state) => state.data?.user?.id ?? null);
    const sessionStatus = useAppSessionStore((state) => state.status);
    const storeActor = useUserInputStore((state) => state.actorId);
    const records = useUserInputStore((state) => state.records);
    const [csrf, setCsrf] = useState('');
    const [error, setError] = useState('');
    const [refresh, setRefresh] = useState(0);
    useEffect(() => {
        useUserInputStore.getState().setActor(sessionStatus === 'changed' ? null : actorId);
        if (sessionStatus === 'changed') return;
        if (!actorId || !conversationKind) return;
        const controller = new AbortController();
        const before = useUserInputStore.getState().records;
        setCsrf('');
        void fetchUserInput(conversationId, controller.signal).then((result) => {
            if (controller.signal.aborted) return;
            const ids = new Set(result.requests.map((item) => item.id));
            for (const [id, record] of Object.entries(before)) {
                if (record.request.conversation_id === conversationId && !ids.has(id)
                    && useUserInputStore.getState().records[id] === record) useUserInputStore.getState().remove(id);
            }
            result.requests.filter((item) => item.conversation_id === conversationId
                && item.conversation_kind === conversationKind).forEach(useUserInputStore.getState().accept);
            setCsrf(result.csrf_token);
            setError('');
        }).catch(() => {
            if (!controller.signal.aborted) setError('Pending questions could not be checked. Reload requests to try again.');
        });
        return () => controller.abort();
    }, [actorId, sessionStatus, conversationId, conversationKind, refresh]);
    if (sessionStatus === 'changed' || !actorId || !conversationKind || actorId !== storeActor) return null;
    return (
        <div className="space-y-3">
            {error ? <div role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
                {error} <GlassButton size="sm" onClick={() => setRefresh((value) => value + 1)}>Reload requests</GlassButton>
            </div> : null}
            {Object.values(records).filter(({ request }) => request.conversation_id === conversationId
                && request.conversation_kind === conversationKind
                && ['pending', 'answered', 'continuing'].includes(request.status)).map(({ request }) => (
                <UserInputCard key={`${actorId}:${request.id}:${request.revision}`} input={request} csrf={csrf}
                    onRefresh={() => setRefresh((value) => value + 1)} />
            ))}
        </div>
    );
}

export function UserInputCard({ input, csrf, onRefresh }: {
    input: UserInputRequest; csrf: string; onRefresh: () => void;
}) {
    const record = useUserInputStore((state) => state.records[input.id]);
    const streaming = useChatStore((state) => state.streaming);
    const working = useRef(false);
    const [collapsed, setCollapsed] = useState(false);
    if (!record) return null;
    const draft = record.draft;
    const ownsRequest = () => {
        const state = useUserInputStore.getState();
        return useAppSessionStore.getState().status !== 'changed'
            && state.actorId === input.actor_id && state.records[input.id]?.request.revision === input.revision;
    };
    const update = (change: (current: typeof draft) => typeof draft) => {
        if (ownsRequest()) useUserInputStore.getState().update(input.id, change);
    };

    const continueWork = async (saved: UserInputRequest, submissionId: string) => {
        const open = (signal?: AbortSignal) => openUserInputContinuation(saved, submissionId, csrf, signal);
        if (saved.run_id) await continueSavedInteraction(saved, undefined, open);
        else await continueInteractionChat(saved.conversation_id, saved.conversation_kind, open, async () => {
            if (ownsRequest()) await stopUserInput(saved, submissionId, csrf);
        });
        if (ownsRequest()) useUserInputStore.getState().remove(input.id);
    };
    const stopSavedWork = async () => {
        if (!ownsRequest() || !input.submission_id || !csrf) return;
        update((current) => ({ ...current, submitting: true, error: null }));
        try {
            await stopUserInput(input, input.submission_id, csrf);
            onRefresh();
        } catch {
            update((current) => ({ ...current, error: 'Stopping could not be confirmed. Refresh the saved status.' }));
        } finally {
            update((current) => ({ ...current, submitting: false }));
        }
    };
    const send = async (response?: ElicitationResponse, context?: ElicitationContext) => {
        if (working.current || streaming || !ownsRequest()) return;
        if (!csrf) {
            update((current) => ({ ...current, error: 'Reload requests before sending your answers.' }));
            return;
        }
        working.current = true;
        const fingerprint = JSON.stringify({ response, context });
        const submissionId = input.submission_id
            ?? (draft.submissionFingerprint === fingerprint ? draft.submissionId : null) ?? crypto.randomUUID();
        update((current) => ({
            ...current, submitting: true, error: null, submissionId, submissionFingerprint: fingerprint,
        }));
        try {
            const saved = response
                ? await saveUserInput(input, submissionId, response, context, csrf)
                : input;
            if (!ownsRequest()) return;
            useUserInputStore.getState().accept(saved);
            if (saved.status === 'cancelled' || saved.status === 'completed') {
                useUserInputStore.getState().remove(input.id);
                await useChatStore.getState().reloadMessages();
            } else {
                await continueWork(saved, submissionId);
            }
        } catch (failure) {
            update((current) => ({ ...current,
                error: failure instanceof Error ? failure.message : 'The answers could not be submitted. Reload requests.' }));
        } finally {
            working.current = false;
            update((current) => ({ ...current, submitting: false }));
        }
    };
    return (
        <div>
            <div className="flex items-center justify-between gap-3 text-sm text-text-2">
                <span>{input.status === 'pending' ? `${input.agent_name} needs your input` : `Your answers for ${input.agent_name}`}</span>
                <GlassButton size="sm" variant="ghost" aria-expanded={!collapsed}
                    onClick={() => setCollapsed((value) => !value)}>{collapsed ? 'Show questions' : 'Minimize'}</GlassButton>
            </div>
            {collapsed ? null : input.status === 'pending' ? (
                <ElicitationForm conversationId={input.conversation_id} elicitation={input.question}
                    draft={{ ...draft, submitting: draft.submitting || streaming }} onDraftChange={update}
                    onAnswer={(response, context) => void send(response, context)} />
            ) : (
                <section aria-label="Saved answers" className="space-y-3 rounded-2xl border border-edge-strong bg-surface-3 p-4">
                    <p className="text-sm text-text-1">{input.cancel_requested ? 'Stop requested. Refresh the saved status to confirm the outcome.'
                        : input.status === 'continuing'
                        ? 'Your answers are saved. The work is continuing or needs its saved status checked.'
                        : 'Your answers are saved. Continue the paused work when you are ready.'}</p>
                    {draft.error ? <p role="alert" className="text-sm text-danger">{draft.error}</p> : null}
                    {input.status === 'answered' ? <GlassButton disabled={draft.submitting || streaming}
                        onClick={() => void send()}>Continue saved work</GlassButton> : null}
                    {input.status === 'continuing' && !input.run_id && !input.cancel_requested ? (
                        <GlassButton disabled={draft.submitting} variant="ghost"
                            onClick={() => void stopSavedWork()}>Stop saved work</GlassButton>
                    ) : null}
                    <GlassButton variant="ghost" onClick={onRefresh}>Refresh saved status</GlassButton>
                </section>
            )}
        </div>
    );
}
