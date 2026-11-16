// usePendingActionReview.ts

import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from 'zustand';
import { ApiError } from '../../lib/apiClient';
import { errorMessage, m365Request, type PendingAction } from '../../lib/approvalsApi';
import { cancelAssistExchange, useAssistThread, type AssistSendRequest, type AssistSendResult } from '../../lib/assistThread';
import {
    describeEditorAssistError, EDITOR_ASSIST_DEADLINE_MS, EDITOR_ASSIST_INSTRUCTION_LIMIT,
    EDITOR_ASSIST_STALE_MESSAGE, editorAssistKey, editorAssistUndoPlan, parseEditorAssistResponse,
    sameEditorAssistValue,
} from '../../lib/editorAssist';
import {
    applyPendingReviewValues, canEditPendingAction, fetchPendingReview, fetchPendingReviewHistory, pendingReviewApplySuggestion, pendingReviewView,
    pendingReviewHistoryFromWire, savePendingReview, type PendingReviewHistory, type PendingReviewWireResponse,
} from '../../lib/pendingActionReview';
import { selectAssistThread, useAssistThreadStore } from '../../stores/assistThreadStore';
import { createPendingReviewStore, pendingReviewDirty } from '../../stores/pendingActionReviewStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';

function cancelLocalThread(key: string) {
    const pending = selectAssistThread(useAssistThreadStore.getState(), key)?.exchanges.find((item) => item.status === 'pending');
    if (pending) cancelAssistExchange(key, pending.id);
}

export function clearPendingReviewThread(id: string) {
    const key = `pending-review:${id}`;
    cancelLocalThread(key);
    useAssistThreadStore.setState((state) => {
        if (!state.threads[key]) return state;
        const threads = { ...state.threads };
        delete threads[key];
        return { threads };
    });
}

export function usePendingActionReview(id: string, calendar: boolean, editable: boolean, observedVersion: string | undefined,
    clearMaterial: boolean, onSaved: (action?: PendingAction) => void) {
    const [store] = useState(createPendingReviewStore);
    const state = useStore(store);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [paging, setPaging] = useState(false);
    const [error, setError] = useState('');
    const [retryUntil, setRetryUntil] = useState(0);
    const [waitSeconds, setWaitSeconds] = useState(0);
    const assistEnabled = useBootstrapStore((state) => state.data?.features?.enable_action_ai_assistant === true);
    const active = useRef(true);
    const loadSequence = useRef(0);
    const current = useRef({ editable, calendar, onSaved, assistEnabled, observedVersion, clearMaterial });
    current.current = { editable, calendar, onSaved, assistEnabled, observedVersion, clearMaterial };
    const key = `pending-review:${id}`;

    const reload = useCallback(async () => {
        const sequence = ++loadSequence.current;
        cancelLocalThread(key);
        setLoading(true);
        setError('');
        try {
            const result = await fetchPendingReview(id);
            if (active.current && !current.current.clearMaterial && sequence === loadSequence.current) {
                store.getState().load(result);
                current.current.onSaved(result.pending_action);
            }
        } catch (problem) {
            if (active.current && sequence === loadSequence.current) setError(errorMessage(problem, 'The saved draft could not be loaded. Try again.'));
        } finally {
            if (active.current && sequence === loadSequence.current) setLoading(false);
        }
    }, [id, key, store]);

    useEffect(() => {
        active.current = true;
        void reload();
        return () => {
            active.current = false;
            loadSequence.current += 1;
            if (current.current.clearMaterial || !current.current.editable) clearPendingReviewThread(id);
            else cancelLocalThread(key);
            store.getState().clear();
        };
    }, [key, reload, store]);

    useEffect(() => {
        if (editable && !clearMaterial) return;
        clearPendingReviewThread(id);
        if (clearMaterial) store.getState().clear();
    }, [editable, clearMaterial, id, store]);

    useEffect(() => {
        const tick = () => setWaitSeconds(Math.max(0, Math.ceil((retryUntil - Date.now()) / 1000)));
        tick();
        const timer = window.setInterval(tick, 1000);
        return () => window.clearInterval(timer);
    }, [retryUntil]);

    const loadHistory = useCallback(async (more = false) => {
        const base = store.getState().review;
        const observed = current.current.observedVersion;
        if (!base) return;
        setPaging(true);
        try {
            const result = await fetchPendingReviewHistory(id, more ? store.getState().continuationToken : '');
            if (active.current && current.current.editable && store.getState().review?.version === base.version
                && (current.current.observedVersion === observed || current.current.observedVersion === result.version)) {
                store.getState().appendHistory(result.history ?? [], result.continuation_token ?? '', more);
                if (!pendingReviewDirty(base.draft, result.draft)) {
                    store.getState().acceptAssist(result.pending_action, result.version, store.getState().assistTurnId);
                } else {
                    setError('The saved draft changed. Your working copy has been kept. Reload the saved draft before saving.');
                }
                current.current.onSaved(result.pending_action);
            }
        } catch (problem) {
            if (active.current) setError(errorMessage(problem, 'History could not be loaded. Try again.'));
        } finally {
            if (active.current) setPaging(false);
        }
    }, [id, store]);

    const send = useCallback(async (request: AssistSendRequest): Promise<AssistSendResult> => {
        const snapshot = store.getState();
        if (!current.current.editable || !current.current.assistEnabled || !snapshot.review?.assist_enabled || !snapshot.draft) {
            return { ok: false, error: 'Ask AI is not available for this draft.' };
        }
        if (current.current.observedVersion && current.current.observedVersion !== snapshot.review.version) {
            return { ok: false, error: EDITOR_ASSIST_STALE_MESSAGE };
        }
        const draft = snapshot.draft;
        setError('');
        const version = snapshot.review.version;
        const sentObservedVersion = current.current.observedVersion;
        const controller = new AbortController();
        const abort = () => controller.abort();
        request.signal.addEventListener('abort', abort, { once: true });
        const deadline = window.setTimeout(abort, EDITOR_ASSIST_DEADLINE_MS);
        try {
            const payload = await m365Request<PendingReviewWireResponse>(`/api/msgraph/pending-actions/${encodeURIComponent(id)}/assist`, {
                method: 'POST',
                body: { expected_version: version, fields: draft, instruction: request.text, submission_id: request.submissionId },
                signal: controller.signal,
            });
            if (request.signal.aborted || !active.current) return { ok: false, aborted: true, error: '' };
            const response = parseEditorAssistResponse(payload, request.submissionId);
            if (!response) return { ok: false, error: "The assistant's answer couldn't be read. Nothing was changed." };
            const now = store.getState();
            if (!current.current.editable || now.review?.version !== version
                || current.current.observedVersion !== sentObservedVersion
                || editorAssistKey(now.draft) !== editorAssistKey(draft)) {
                setError(EDITOR_ASSIST_STALE_MESSAGE);
                await loadHistory();
                return { ok: false, error: EDITOR_ASSIST_STALE_MESSAGE };
            }
            if (payload.pending_action?.id !== id || !canEditPendingAction(payload.pending_action)
                || !payload.expected_version || payload.pending_action.version !== payload.expected_version) {
                return { ok: false, error: 'The saved assistant turn could not be verified. Reload the draft before saving.' };
            }
            if (response.candidate) store.getState().edit(applyPendingReviewValues(draft, response.candidate.values, current.current.calendar), 'ai');
            store.getState().acceptAssist(payload.pending_action, payload.expected_version, payload.assist_turn_id ?? '');
            const history = pendingReviewHistoryFromWire(payload);
            store.getState().appendHistory(history.history.map((record) => record.id === payload.assist_turn_id
                ? { ...record, before: record.before ?? draft, warnings: record.warnings ?? response.warnings } : record), history.continuation_token);
            current.current.onSaved(payload.pending_action);
            return { ok: true, reply: response.reply };
        } catch (problem) {
            if (request.signal.aborted || !active.current) return { ok: false, aborted: true, error: '' };
            const failure = describeEditorAssistError(problem instanceof ApiError ? problem.status : 0,
                problem instanceof ApiError ? problem.payload : { message: errorMessage(problem, 'Ask AI did not finish. Try again.') });
            if (failure.retryAfterSeconds) setRetryUntil(Date.now() + failure.retryAfterSeconds * 1000);
            const message = controller.signal.aborted ? 'Ask AI timed out. Try again; nothing was saved or sent.' : failure.message;
            setError(message);
            if (problem instanceof ApiError && [401, 403, 409, 412].includes(problem.status)) current.current.onSaved();
            return { ok: false, error: message };
        } finally {
            window.clearTimeout(deadline);
            request.signal.removeEventListener('abort', abort);
        }
    }, [id, loadHistory, store]);

    const thread = useAssistThread({
        key: editable && assistEnabled && state.review?.assist_enabled ? key : null,
        conversationId: null, mode: 'stored', maxLength: EDITOR_ASSIST_INSTRUCTION_LIMIT,
        send, storedTurns: state.history, countCodePoints: true, retain: true,
    });

    const save = async () => {
        const snapshot = store.getState();
        if (!snapshot.review || !snapshot.draft || !editable || thread.pending || saving) return;
        if (current.current.observedVersion && current.current.observedVersion !== snapshot.review.version) return;
        setSaving(true);
        setError('');
        try {
            const result = await savePendingReview(id, snapshot.review.version, snapshot.draft, snapshot.attribution,
                snapshot.attribution === 'ai' ? snapshot.assistTurnId : undefined);
            if (!active.current || current.current.clearMaterial) return;
            store.getState().load(result);
            current.current.onSaved(result.pending_action);
        } catch (problem) {
            if (active.current) {
                setError(errorMessage(problem, 'The draft could not be saved. Your working copy has been kept.'));
                current.current.onSaved();
            }
        } finally {
            if (active.current) setSaving(false);
        }
    };

    const applySuggestion = (record: PendingReviewHistory) => {
        const snapshot = store.getState();
        if (!snapshot.review || !snapshot.draft || !record.before || !record.after || saving || thread.pending || !editable
            || (observedVersion && snapshot.review.version !== observedVersion)) return;
        const proposal = pendingReviewApplySuggestion(record.before, record.after, snapshot.draft, calendar);
        if (proposal.applied.length) {
            store.getState().edit(proposal.draft, 'ai');
            store.getState().acceptAssist(snapshot.review.pending_action, snapshot.review.version, record.id);
        }
        setError(proposal.skipped.length
            ? 'Some suggested changes were not applied because those fields changed later. Your newer edits have been kept.'
            : '');
    };

    const undo = (record: PendingReviewHistory) => {
        const draft = store.getState().draft;
        if (!draft || !record.before || !record.after || saving || thread.pending || !editable) return;
        const before = pendingReviewView(record.before, calendar).values;
        const after = pendingReviewView(record.after, calendar).values;
        const view = pendingReviewView(draft, calendar);
        const entries = Object.keys(after).map((path) => ({ path, before: before[path], after: after[path] }))
            .filter((entry) => !sameEditorAssistValue(entry.before, entry.after));
        const plan = editorAssistUndoPlan(entries, before, view.values);
        store.getState().edit(applyPendingReviewValues(draft, { ...view.values, ...plan.patch }, calendar));
        setError(plan.skipped.length ? 'Some changes were kept because those fields changed later. Review the working copy before saving.' : '');
    };

    return { ...state, store, thread, loading, saving, paging, error, waitSeconds, reload, loadHistory, save, undo, applySuggestion,
        assistAvailable: assistEnabled && state.review?.assist_enabled === true,
        dirty: pendingReviewDirty(state.review?.draft ?? null, state.draft),
        locked: loading || saving || Boolean(thread.pending) || !editable
            || Boolean(state.review && observedVersion && state.review.version !== observedVersion) };
}
