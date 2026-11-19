// AgentCredentialRecoveryNotice.tsx

import { useId } from 'react';
import { Bot, ExternalLink } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import type { AgentCredentialRecovery } from '../../lib/types';
import { normalizeAgentCredentialEditUrl } from '../../lib/agentCredentialRecovery';

export function AgentCredentialRecoveryNotice({ message, recovery }: {
    message: string;
    recovery?: AgentCredentialRecovery | null;
}) {
    const headingId = useId();
    const editorHelpId = useId();
    const retryHelpId = useId();
    const safeAgentUrl = normalizeAgentCredentialEditUrl(recovery);
    const prefix = /^(Agent (?:credentials|connection settings) need updating)\.\s*/.exec(message);
    const heading = prefix?.[1] ?? 'Agent connection needs attention';
    const detail = prefix ? message.slice(prefix[0].length) : message;

    return (
        <div role="alert" aria-labelledby={headingId} data-agent-credential-recovery
            className="w-full space-y-2.5 text-sm text-text-1">
            <div className="flex items-center gap-2.5 text-text-2">
                <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-sunken">
                    <Bot size={17} aria-hidden="true" />
                </span>
                <span className="font-medium">Agent connection</span>
            </div>
            <section className="rounded-xl border border-edge-strong bg-surface-solid p-4 sm:ms-10 sm:p-5">
                <h3 id={headingId} className="text-base font-semibold leading-6">{heading}</h3>
                {safeAgentUrl && detail && <p className="mt-1.5 leading-relaxed text-text-2">{detail}</p>}
                <ol aria-label="Agent credential recovery" role="list"
                    className="mt-5 grid list-none gap-6 sm:grid-cols-2">
                    <li className="flex min-w-0 items-start gap-2.5">
                        <span aria-hidden="true"
                            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-edge-strong bg-surface-sunken text-text-2">1</span>
                        <div className="min-w-0 flex-1">
                            <p className="font-medium leading-6">{safeAgentUrl ? 'Update the connection' : 'Request an update'}</p>
                            {safeAgentUrl ? (
                                <>
                                    <GlassButton type="button" variant="primary"
                                        aria-label="Update agent credentials (opens in a new tab)"
                                        aria-describedby={`${editorHelpId} ${retryHelpId}`}
                                        onClick={() => window.open(safeAgentUrl, '_blank', 'noopener,noreferrer')}
                                        className="mt-2 h-auto min-h-11 w-full justify-center gap-2 bg-accent-hover px-3 py-2.5 text-left hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:w-auto">
                                        <span>Update agent credentials</span>
                                        <ExternalLink size={15} aria-hidden="true" className="shrink-0" />
                                    </GlassButton>
                                    <p id={editorHelpId} className="mt-2 leading-relaxed text-text-2">
                                        The agent editor opens in a new tab.
                                    </p>
                                </>
                            ) : <p className="mt-2 leading-relaxed text-text-2">{detail || message}</p>}
                        </div>
                    </li>
                    <li className="flex min-w-0 items-start gap-2.5">
                        <span aria-hidden="true"
                            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-edge-strong bg-surface-sunken text-text-2">2</span>
                        <div className="min-w-0 flex-1">
                            <p className="font-medium leading-6">Return to this chat</p>
                            <p id={retryHelpId} className="mt-2 leading-relaxed text-text-2">
                                {safeAgentUrl ? 'After saving' : 'After the agent is updated'}, select Retry on your message,
                                {' '}or start a new conversation.
                            </p>
                        </div>
                    </li>
                </ol>
                <p className="mt-5 border-t border-edge-strong pt-3.5 leading-relaxed text-text-2">
                    Nothing retries automatically.
                </p>
            </section>
        </div>
    );
}
