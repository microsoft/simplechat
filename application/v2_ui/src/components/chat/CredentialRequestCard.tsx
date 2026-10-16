// CredentialRequestCard.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { continueCredentialChat } from '../../stores/chatStore';
import { continueCredentialOrchestration } from '../../lib/orchestrationController';
import { ACTION_CREDENTIAL_EVENT, readCredentialRequest } from '../../lib/actionCredentialEvents';
import { cancelActionCredentials, clearCredentialSession, fetchActionCredentialRequest, fetchCredentialRequests, saveActionCredentials } from '../../lib/actionCredentials';
import { fetchOrchestrationRun, isOrchestrationRunWaiting } from '../../lib/orchestration';
import type { CredentialRequest, CredentialSlot, CredentialSubmission } from '../../lib/actionCredentialTypes';
import { ApiError } from '../../lib/apiClient';

const inputClass = 'w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20';
const reasonMessages: Record<string, string> = {
    rejected: 'The service rejected your saved credentials. Choose another identity or replace its credentials.',
    credentials_rejected: 'The service rejected your saved credentials. Choose another identity or replace its credentials.',
    credentials_expired: 'Your saved credentials have expired. Choose another identity or replace its credentials.',
    binding_changed: 'The action connection changed. Review the destination before choosing your personal identity.',
    identity_removed: 'The previously selected identity is no longer available. Choose another identity or save a new one.',
};

export function CredentialRequestCards({ conversationId }: { conversationId: string }) {
    const userId = useBootstrapStore((state) => state.data?.user?.id);
    return <CredentialRequestList key={`${userId}:${conversationId}`} conversationId={conversationId} />;
}

function CredentialRequestList({ conversationId }: { conversationId: string }) {
    const [requests, setRequests] = useState<CredentialRequest[]>([]);
    const [error, setError] = useState('');
    const refresh = useRef<() => void>(() => {});
    useEffect(() => {
        clearCredentialSession();
        const controller = new AbortController();
        let eventSeen = false;
        const accept = (credentialRequest: CredentialRequest) => {
            if (credentialRequest.conversation_id !== conversationId) return;
            setRequests((current) => [...current.filter((item) => item.id !== credentialRequest.id), credentialRequest]);
        };
        const onEvent = (event: Event) => {
            if (!(event instanceof CustomEvent)) return;
            try {
                const credentialRequest = readCredentialRequest(event.detail);
                if (credentialRequest.conversation_id !== conversationId) return;
                eventSeen = true;
                accept(credentialRequest);
            } catch {
                setError('The credential request could not be read. Reload this conversation.');
            }
        };
        const load = () => {
            eventSeen = false;
            void fetchCredentialRequests(conversationId, controller.signal).then((pending) => {
                if (controller.signal.aborted) return;
                if (eventSeen) {
                    pending.filter((item) => item.conversation_id === conversationId).forEach((item) => setRequests((current) => current.some((existing) => existing.id === item.id)
                        ? current : [...current, item]));
                } else {
                    setRequests(pending.filter((item) => item.conversation_id === conversationId));
                }
                setError('');
            }).catch((failure: unknown) => {
                if (controller.signal.aborted) return;
                if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) setRequests([]);
                setError('Pending action credentials could not be loaded.');
            });
        };
        refresh.current = load;
        window.addEventListener(ACTION_CREDENTIAL_EVENT, onEvent);
        load();
        return () => {
            controller.abort();
            window.removeEventListener(ACTION_CREDENTIAL_EVENT, onEvent);
            clearCredentialSession();
        };
    }, [conversationId]);
    return <div className="space-y-3">
        {error ? <div role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
            {error} <GlassButton size="sm" onClick={() => refresh.current()}>Reload requests</GlassButton>
        </div> : null}
        {requests.filter((item) => item.status === 'pending' || item.status === 'ready').map((item) =>
            <CredentialRequestCard key={`${item.id}:${item.etag}`} credentialRequest={item}
                onUpdate={(updated) => setRequests((current) => current.map((existing) => existing.id === updated.id ? updated : existing))}
                onRemove={() => setRequests((current) => current.filter((existing) => existing.id !== item.id || existing.etag !== item.etag))} />)}
    </div>;
}

export function CredentialRequestCard({ credentialRequest, onUpdate, onRemove }: {
    credentialRequest: CredentialRequest;
    onUpdate: (request: CredentialRequest) => void;
    onRemove: () => void;
}) {
    const id = useId();
    const formRef = useRef<HTMLFormElement>(null);
    const controller = useRef<AbortController | null>(null);
    const [identities, setIdentities] = useState<Partial<Record<CredentialSlot, string>>>({});
    const [rotations, setRotations] = useState<Partial<Record<CredentialSlot, boolean>>>({});
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [saved, setSaved] = useState<CredentialRequest | null>(null);
    const [needsRefresh, setNeedsRefresh] = useState(false);
    const [closed, setClosed] = useState(false);
    const working = useRef(false);
    useEffect(() => () => {
        controller.current?.abort();
        formRef.current?.reset();
    }, []);
    const ready = saved || (credentialRequest.status === 'ready' ? credentialRequest : null);
    const reasonMessage = Object.hasOwn(reasonMessages, credentialRequest.reason) ? reasonMessages[credentialRequest.reason] : '';
    const continueWork = async (request: CredentialRequest) => {
        if (request.run_id) await continueCredentialOrchestration(request);
        else await continueCredentialChat(request);
        if (!controller.current?.signal.aborted) onRemove();
    };
    const submit = async () => {
        if (working.current || needsRefresh || closed) return;
        working.current = true;
        setBusy(true);
        setError('');
        controller.current = new AbortController();
        let confirmedSave = ready;
        try {
            if (ready) {
                await continueWork(ready);
                return;
            }
            const form = formRef.current;
            if (!form) throw new Error('The credential form is unavailable.');
            const data = new FormData(form);
            const slots: CredentialSubmission[] = credentialRequest.requirements.map((requirement) => {
                const identityId = identities[requirement.slot];
                if (identityId && !rotations[requirement.slot]) return { slot: requirement.slot, identity_id: identityId };
                const credentials = requirement.auth_type === 'username_password'
                        ? { auth_type: requirement.auth_type, username: String(data.get(`${requirement.slot}-username`) || ''),
                            password: String(data.get(`${requirement.slot}-secret`) || '') }
                        : { auth_type: requirement.auth_type, secret: String(data.get(`${requirement.slot}-secret`) || '') };
                if (identityId) {
                    const identity = credentialRequest.identities.find((item) => item.id === identityId);
                    if (!identity?.etag) throw new Error('Reload this identity before replacing its credentials.');
                    return { slot: requirement.slot, identity_id: identityId, expected_identity_etag: identity.etag, credentials };
                }
                return { slot: requirement.slot, name: String(data.get(`${requirement.slot}-name`) || ''), credentials };
            });
            form.reset();
            for (const key of Array.from(data.keys())) data.delete(key);
            let updated: CredentialRequest;
            try {
                updated = await saveActionCredentials(credentialRequest, slots, controller.current.signal);
            } finally {
                slots.length = 0;
            }
            if (controller.current.signal.aborted) return;
            setSaved(updated);
            confirmedSave = updated;
            await continueWork(updated);
        } catch {
            if (!controller.current?.signal.aborted) {
                setNeedsRefresh(true);
                setError(confirmedSave
                    ? 'Your credentials are saved, but continuation could not be confirmed. Refresh the saved request before trying again.'
                    : 'Saving could not be confirmed. Refresh the saved request before entering credentials again.');
            }
        } finally {
            working.current = false;
            if (!controller.current?.signal.aborted) setBusy(false);
        }
    };
    const refreshSavedRequest = async () => {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        controller.current = new AbortController();
        try {
            const current = await fetchActionCredentialRequest(saved || credentialRequest, controller.current.signal);
            let waiting = true;
            if (['pending', 'ready'].includes(current.status) && current.run_id) {
                const run = await fetchOrchestrationRun(current.run_id, {
                    conversationId: current.conversation_id, signal: controller.current.signal,
                });
                if (!run || run.run_id !== current.run_id || run.conversation_id !== current.conversation_id ||
                    (current.turn_id && current.turn_id !== run.turn_id)) {
                    throw new Error('The saved work could not be confirmed.');
                }
                waiting = isOrchestrationRunWaiting(run);
            }
            if (controller.current.signal.aborted) return;
            if (current.status === 'pending' && waiting) {
                setSaved(null);
                setClosed(false);
                setNeedsRefresh(false);
                setError('');
                onUpdate(current);
            } else {
                setSaved(current.status === 'ready' || ready ? current : null);
                const canContinue = current.status === 'ready' && waiting;
                setClosed(!canContinue);
                setNeedsRefresh(!canContinue);
                setError(canContinue ? ''
                    : current.run_id
                        ? 'This work is no longer waiting for these credentials. Review run details for saved progress and recovery options.'
                        : 'This work is no longer waiting for these credentials. Review the conversation before starting new work.');
            }
        } catch {
            if (!controller.current.signal.aborted) {
                setNeedsRefresh(true);
                setError('The saved request could not be refreshed. Reload this conversation before trying again.');
            }
        } finally {
            working.current = false;
            if (!controller.current.signal.aborted) setBusy(false);
        }
    };
    const cancel = async () => {
        if (working.current || needsRefresh || closed) return;
        working.current = true;
        setBusy(true);
        setError('');
        formRef.current?.reset();
        controller.current = new AbortController();
        try {
            await cancelActionCredentials(ready || credentialRequest, controller.current.signal);
            onRemove();
        } catch {
            if (!controller.current.signal.aborted) setError('The credential request could not be cancelled. Reload requests before trying again.');
        } finally {
            working.current = false;
            if (!controller.current.signal.aborted) setBusy(false);
        }
    };
    return <section aria-label="Personal action credentials" className="rounded-2xl border border-edge-strong bg-surface-sunken p-4">
        <div className="flex items-start gap-3">
            <KeyRound size={18} aria-hidden="true" className="mt-1 shrink-0 text-accent" />
            <div className="min-w-0">
                <h3 className="font-medium text-text-1">{credentialRequest.action_name || 'Action'} needs your credentials</h3>
                {credentialRequest.destination_label ? <p className="mt-1 break-words text-sm text-text-2">{credentialRequest.destination_label}</p> : null}
                <p className="mt-2 text-sm leading-relaxed text-text-2">
                    Credentials are saved to your personal identities, not sent as a chat message. Save and continue resumes the blocked work.
                </p>
                {reasonMessage ? <p className="mt-2 text-sm text-warn">{reasonMessage}</p> : null}
            </div>
        </div>
        <form ref={formRef} className="mt-4 space-y-4" onSubmit={(event) => { event.preventDefault(); void submit(); }}
            aria-busy={busy} autoComplete="off">
            <fieldset disabled={busy} className="space-y-4">
                {!ready && !needsRefresh ? credentialRequest.requirements.map((requirement) => {
                    const prefix = `${id}-${requirement.slot}`;
                    const candidates = credentialRequest.identities.filter((item) => item.auth_type === requirement.auth_type);
                    const selectedIdentity = candidates.find((item) => item.id === identities[requirement.slot]);
                    return <fieldset key={requirement.slot} className="space-y-3">
                        <legend className="mb-2 text-sm font-medium text-text-1">{requirement.label || requirement.slot}</legend>
                        <label htmlFor={`${prefix}-identity`} className="block text-sm text-text-2">Personal identity</label>
                        <select id={`${prefix}-identity`} className={inputClass} value={identities[requirement.slot] || ''}
                            onChange={(event) => {
                                const identityId = event.target.value;
                                formRef.current?.reset();
                                setIdentities((current) => ({ ...current, [requirement.slot]: identityId }));
                                setRotations((current) => ({ ...current, [requirement.slot]: false }));
                            }}>
                            <option value="">Save a new personal identity</option>
                            {candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}
                        </select>
                        {selectedIdentity?.etag ? <label className="flex items-start gap-2 text-sm text-text-2">
                            <input type="checkbox" className="mt-1" checked={rotations[requirement.slot] || false}
                                onChange={(event) => {
                                    const rotate = event.target.checked;
                                    formRef.current?.reset();
                                    setRotations((current) => ({ ...current, [requirement.slot]: rotate }));
                                }} />
                            Replace credentials in this personal identity
                        </label> : null}
                        {!identities[requirement.slot] || rotations[requirement.slot] ? <>
                            {!identities[requirement.slot] ? <>
                            <label htmlFor={`${prefix}-name`} className="block text-sm text-text-2">Identity name</label>
                            <input id={`${prefix}-name`} name={`${requirement.slot}-name`} className={inputClass} required maxLength={200}
                                defaultValue={`${credentialRequest.action_name} ${requirement.slot}`} />
                            </> : null}
                            {requirement.auth_type === 'username_password' ? <>
                                <label htmlFor={`${prefix}-username`} className="block text-sm text-text-2">Username</label>
                                <input id={`${prefix}-username`} name={`${requirement.slot}-username`} className={inputClass}
                                    required autoComplete="off" spellCheck={false} />
                            </> : null}
                            <label htmlFor={`${prefix}-secret`} className="block text-sm text-text-2">
                                {requirement.auth_type === 'username_password' ? 'Password' : requirement.auth_type === 'api_key' ? 'API key' : 'Bearer token'}
                            </label>
                            <input id={`${prefix}-secret`} name={`${requirement.slot}-secret`} className={inputClass} type="password"
                                required autoComplete="new-password" spellCheck={false} />
                        </> : null}
                    </fieldset>;
                }) : ready ? <p role="status" className="text-sm text-ok">
                    {needsRefresh || closed ? 'Your personal identities are saved.'
                        : 'Your personal identities are saved. Continue the blocked action when ready.'}
                </p> : null}
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
                <div className="flex flex-wrap items-center gap-2">
                    {!closed ? <>
                        <GlassButton type="submit" variant="primary" disabled={needsRefresh}>{busy ? 'Working...' : ready ? 'Continue' : 'Save and continue'}</GlassButton>
                        <GlassButton type="button" disabled={needsRefresh} onClick={() => void cancel()}>Cancel blocked work</GlassButton>
                    </> : null}
                    {needsRefresh || saved ? <GlassButton type="button" onClick={() => void refreshSavedRequest()}>
                        Refresh saved request
                    </GlassButton> : null}
                </div>
            </fieldset>
        </form>
    </section>;
}
