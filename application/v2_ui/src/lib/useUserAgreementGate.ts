// useUserAgreementGate.ts
// Settles the User Agreement before an upload starts, and owns the state of its dialog.
//
// Every place that sends a user's file to the server asks this first: the chat composer and the
// workspace documents explorer. A component calls the hook once, awaits `confirm` (or hands
// `withAgreement` the work to do) before it sends anything, and renders <UserAgreementDialog gate={gate} />.
//
// The answer is one of three things. Nothing applies, so the upload goes ahead. An agreement applies,
// so the dialog asks and the upload goes ahead only on Accept. Or the check itself failed, so the
// dialog says so and the upload stays held: unlike classic, which lets the upload through on a failed
// check, a compliance control that cannot tell whether it applies must not assume that it does not.
// Cancel always leaves the caller's selection as it was; the caller simply never starts.
//
// Requests are made one gate at a time, so a second drop while the first is still being settled waits
// its turn instead of stacking a second dialog on the first. Unmounting the owner ends the gate with
// "do not upload", which is what keeps an upload from starting in a component that has gone.
//
// `pending` is how an owner that can send something else in the meantime learns that a file is still
// on its way to the draft. Until the gate settles the file is not in the draft yet, so nothing else
// shows that an upload is coming: a composer that let its message go during that window would send it
// without the file, and the file that arrived afterwards would have nowhere to go. It is true from the
// moment a gate that needs the check is queued until that gate settles, however it settles, and never
// for a gate that is answered at once because the feature is off.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import {
    acceptUserAgreement,
    agreementFailureMessage,
    agreementGateDecision,
    checkUserAgreement,
    type UserAgreementScope,
} from './userAgreement';

/** What the dialog shows. `unavailable` is a check that failed: the upload is held, never waved through. */
export interface UserAgreementPrompt {
    kind: 'agreement' | 'unavailable';
    agreementText: string;
    enableDailyAcceptance: boolean;
    fileCount: number;
    /** A request is in flight: the dialog cannot be dismissed or answered again until it lands. */
    busy: boolean;
    error: string | null;
}

export interface UserAgreementGate {
    /**
     * Resolves true when the upload may start: no agreement applies, or the user accepted it. Resolves
     * false when it must not: there is nothing to upload, the user cancelled, or the owner went away.
     * Never rejects.
     */
    confirm: (scope: UserAgreementScope, files: readonly File[]) => Promise<boolean>;
    /** `confirm`, then `proceed` with the files. Resolves true when `proceed` ran. */
    withAgreement: (
        scope: UserAgreementScope,
        files: readonly File[],
        proceed: (files: File[]) => void | Promise<void>,
    ) => Promise<boolean>;
    /** The dialog's state; null while nothing is waiting on the user. */
    prompt: UserAgreementPrompt | null;
    /**
     * True while any `confirm` that needs the check has not settled: the check is running, the gate is
     * waiting behind another, the dialog is open, or an acceptance is being recorded. False otherwise,
     * and always false when no agreement can apply, which is answered without waiting.
     */
    pending: boolean;
    /** Accept the agreement, or, when the check failed, try the check again. */
    accept: () => void;
    cancel: () => void;
}

interface GateSession {
    scope: UserAgreementScope;
    fileCount: number;
    controller: AbortController;
    settle: (proceed: boolean) => void;
    /** Set once the session is over, so a response that lands late cannot reopen the dialog. */
    ended: boolean;
}

export function useUserAgreementGate(): UserAgreementGate {
    const [prompt, setPrompt] = useState<UserAgreementPrompt | null>(null);
    const [pending, setPending] = useState(false);
    const promptRef = useRef<UserAgreementPrompt | null>(null);
    const activeSession = useRef<GateSession | null>(null);
    const queue = useRef<Promise<unknown>>(Promise.resolve());
    const mounted = useRef(true);
    // Gates that need the check and have not settled. `pending` mirrors whether this is above zero, so two
    // gates that overlap keep it true until both are done.
    const waiting = useRef(0);

    const show = useCallback((next: UserAgreementPrompt | null) => {
        promptRef.current = next;
        if (mounted.current) {
            setPrompt(next);
        }
    }, []);

    const holdGate = useCallback(() => {
        waiting.current += 1;
        if (mounted.current) {
            setPending(true);
        }
    }, []);

    const releaseGate = useCallback(() => {
        waiting.current = Math.max(0, waiting.current - 1);
        if (waiting.current === 0 && mounted.current) {
            setPending(false);
        }
    }, []);

    const finish = useCallback((session: GateSession, proceed: boolean) => {
        if (session.ended) {
            return;
        }
        session.ended = true;
        if (activeSession.current === session) {
            activeSession.current = null;
            show(null);
        }
        session.settle(proceed);
    }, [show]);

    const evaluate = useCallback(async (session: GateSession) => {
        try {
            const check = await checkUserAgreement(session.scope, session.controller.signal);
            if (session.ended) {
                return;
            }
            if (!check.needsAgreement) {
                finish(session, true);
                return;
            }
            show({
                kind: 'agreement',
                agreementText: check.agreementText,
                enableDailyAcceptance: check.enableDailyAcceptance,
                fileCount: session.fileCount,
                busy: false,
                error: null,
            });
        } catch (error) {
            if (session.ended) {
                return;
            }
            show({
                kind: 'unavailable',
                agreementText: '',
                enableDailyAcceptance: false,
                fileCount: session.fileCount,
                busy: false,
                error: agreementFailureMessage('check', error),
            });
        }
    }, [finish, show]);

    const confirm = useCallback((scope: UserAgreementScope, files: readonly File[]): Promise<boolean> => {
        // Read when the upload is attempted, not when the owner rendered, so a refreshed bootstrap applies.
        const decision = agreementGateDecision(useBootstrapStore.getState().data?.settings, files.length);
        if (decision !== 'check') {
            return Promise.resolve(decision === 'proceed');
        }
        const fileCount = files.length;
        // Held from here, before the gate has even started, so there is no moment in which a file is on
        // its way but nothing says so. Released when the answer settles, on whichever path it takes.
        holdGate();
        const run = () => new Promise<boolean>((resolve) => {
            if (!mounted.current) {
                resolve(false);
                return;
            }
            const session: GateSession = {
                scope, fileCount, controller: new AbortController(), settle: resolve, ended: false,
            };
            activeSession.current = session;
            void evaluate(session);
        });
        // `run` settles with a boolean and never rejects, so the chain cannot break.
        const result = queue.current.then(run);
        queue.current = result;
        // The flag drops in the microtask that follows the answer and the caller acts on the answer in the next
        // one, so a caller that puts its file in a draft straight away has done so before the lowered flag is
        // rendered. The rejection handler is only a guard: the flag cannot stay raised.
        void result.then(releaseGate, releaseGate);
        return result;
    }, [evaluate, holdGate, releaseGate]);

    const withAgreement = useCallback(async (
        scope: UserAgreementScope,
        files: readonly File[],
        proceed: (files: File[]) => void | Promise<void>,
    ): Promise<boolean> => {
        if (!(await confirm(scope, files))) {
            return false;
        }
        await proceed([...files]);
        return true;
    }, [confirm]);

    const accept = useCallback(() => {
        const session = activeSession.current;
        const current = promptRef.current;
        if (!session || session.ended || !current || current.busy) {
            return;
        }
        show({ ...current, busy: true, error: null });
        if (current.kind === 'unavailable') {
            void evaluate(session);
            return;
        }
        void (async () => {
            try {
                await acceptUserAgreement(session.scope, session.controller.signal);
                if (!session.ended) {
                    finish(session, true);
                }
            } catch (error) {
                if (!session.ended) {
                    show({ ...current, busy: false, error: agreementFailureMessage('accept', error) });
                }
            }
        })();
    }, [evaluate, finish, show]);

    const cancel = useCallback(() => {
        const session = activeSession.current;
        // A request in flight settles the gate itself; ignoring Cancel meanwhile keeps an acceptance
        // that is already being recorded from also being reported as declined.
        if (!session || session.ended || promptRef.current?.busy) {
            return;
        }
        finish(session, false);
        session.controller.abort();
    }, [finish]);

    useEffect(() => {
        mounted.current = true;
        // A gate that ended while this was not mounted could not update the dialog or lower the flag, so
        // both are read afresh rather than left showing a gate that is over.
        setPrompt(promptRef.current);
        setPending(waiting.current > 0);
        return () => {
            mounted.current = false;
            const session = activeSession.current;
            if (session) {
                finish(session, false);
                session.controller.abort();
            }
        };
    }, [finish]);

    return useMemo(
        () => ({ confirm, withAgreement, prompt, pending, accept, cancel }),
        [confirm, withAgreement, prompt, pending, accept, cancel],
    );
}
