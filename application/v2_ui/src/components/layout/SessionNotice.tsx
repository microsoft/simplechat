// SessionNotice.tsx

import { useCallback, useEffect, useState } from 'react';
import { apiUrl, verifyAppSession } from '../../lib/apiClient';
import { SESSION_REQUIRED_MESSAGE, useAppSessionStore } from '../../stores/appSessionStore';
import { GlassButton } from '../ui/primitives';

export function SessionNotice() {
    const status = useAppSessionStore((state) => state.status);
    const [checking, setChecking] = useState(false);
    const [checkFailed, setCheckFailed] = useState(false);

    const checkAgain = useCallback(async (force = false) => {
        setChecking(true);
        setCheckFailed(false);
        try {
            const confirmed = await verifyAppSession(force);
            setCheckFailed(!confirmed);
        } catch (error) {
            setCheckFailed(true);
            reportError(error);
        } finally {
            setChecking(false);
        }
    }, []);

    useEffect(() => {
        setCheckFailed(false);
        if (status !== 'required') return undefined;
        const check = () => {
            if (document.visibilityState === 'visible') void checkAgain();
        };
        window.addEventListener('focus', check);
        window.addEventListener('online', check);
        document.addEventListener('visibilitychange', check);
        return () => {
            window.removeEventListener('focus', check);
            window.removeEventListener('online', check);
            document.removeEventListener('visibilitychange', check);
        };
    }, [status, checkAgain]);

    if (status === 'ready') return null;

    return (
        <div role="alert" data-testid="v2-session-notice"
            className="shrink-0 space-y-2 border-b border-edge bg-warn-soft px-4 py-3 text-sm text-text-1">
            <p className="font-medium">
                {status === 'changed'
                    ? 'Your signed-in account changed. Copy any unsaved text, then reload SimpleChat before continuing.'
                    : SESSION_REQUIRED_MESSAGE}
            </p>
            <p>Your current page and unsaved draft have been kept. No failed action will be repeated automatically.</p>
            <div className="flex flex-wrap items-center gap-2">
                {status === 'changed' ? (
                    <GlassButton size="sm" onClick={() => window.location.reload()}>Reload SimpleChat</GlassButton>
                ) : (
                    <>
                        <a href={apiUrl('/login')} target="_blank" rel="noopener noreferrer"
                            className="rounded-lg px-3 py-2 font-medium text-accent underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                            Sign in again (opens a new tab)
                        </a>
                        <GlassButton size="sm" variant="ghost" disabled={checking} onClick={() => void checkAgain(true)}>
                            {checking ? 'Checking session…' : 'Check sign-in'}
                        </GlassButton>
                    </>
                )}
            </div>
            {checkFailed && status === 'required' ? (
                <p role="status">Your sign-in could not be confirmed. Finish signing in, then check again.</p>
            ) : null}
        </div>
    );
}
