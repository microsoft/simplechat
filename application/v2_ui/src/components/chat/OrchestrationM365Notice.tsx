// OrchestrationM365Notice.tsx
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { GlassButton } from '../ui/primitives';
import { connectMicrosoft365, m365Sources } from '../../lib/m365Connect';
import { M365_APPROVALS_HREF, M365_CHAT_CONNECTION_HREF } from '../../lib/m365Links';
import type { OrchestrationFailure } from '../../lib/orchestration';

const SOURCE_LABELS: Record<string, string> = {
    calendar: 'Calendar',
    email: 'Email',
    onedrive: 'OneDrive',
    spo: 'SharePoint',
};

/**
 * What to do next when an attempt stopped at a Microsoft 365 step: connect the sources that
 * step needs, or review its approval. Nothing reruns here; the user retries afterward.
 */
export function OrchestrationM365Notice({ failures }: { failures: OrchestrationFailure[] }) {
    const [state, setState] = useState<'idle' | 'connecting' | 'connected'>('idle');
    const [error, setError] = useState<string | null>(null);
    const signIn = failures.find((failure) => failure.code === 'm365_sign_in_required');
    const approval = failures.some((failure) => failure.code === 'm365_approval_required');
    if (!signIn && !approval) return null;
    const sources = m365Sources(signIn?.m365_sources);

    const connect = () => {
        setError(null);
        setState('connecting');
        connectMicrosoft365(sources).then(
            () => setState('connected'),
            (reason: unknown) => {
                setState('idle');
                setError(reason instanceof Error ? reason.message : 'Microsoft 365 sign-in could not be completed.');
            },
        );
    };

    return (
        <div aria-label="Microsoft 365 follow-up" className="space-y-2">
            {signIn && state === 'connected' ? (
                <p role="status" className="rounded-lg bg-ok-soft p-2 text-ok">
                    Microsoft 365 is connected. Select Retry from failed step to continue.
                </p>
            ) : null}
            {signIn && state !== 'connected' && sources.length ? (
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton size="sm" variant="primary" disabled={state === 'connecting'} onClick={connect}>
                        {state === 'connecting' ? 'Waiting for Microsoft 365 sign-in...' : 'Connect Microsoft 365'}
                    </GlassButton>
                    <span>For {sources.map((source) => SOURCE_LABELS[source] ?? source).join(', ')}.</span>
                </div>
            ) : null}
            {signIn && !sources.length ? (
                <p>
                    <Link to={M365_CHAT_CONNECTION_HREF} className="font-medium text-accent underline underline-offset-2">
                        Connect Microsoft 365 in Settings
                    </Link>
                    , then select Retry from failed step.
                </p>
            ) : null}
            {error ? <p role="alert" className="text-danger">{error}</p> : null}
            {approval ? (
                <p>
                    <Link to={M365_APPROVALS_HREF} className="font-medium text-accent underline underline-offset-2">
                        Review the Microsoft 365 approval
                    </Link>
                    , then select Retry from failed step.
                </p>
            ) : null}
        </div>
    );
}
