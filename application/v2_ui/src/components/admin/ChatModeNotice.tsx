// ChatModeNotice.tsx
// Says which of the two chat routes is live.
//
// SimpleChat has two ways to reach a chat model and only one is in force at a time:
// the connections listed above, or a single classic endpoint whose fields exist solely
// on the server-rendered admin page. Nothing on screen used to distinguish them, so an
// administrator could add a connection here, watch it save, and still be served by the
// classic endpoint -- with no error to explain the difference.
//
// V2 deliberately does not carry the classic endpoint's fields. Being explicit about
// which route is live, and pointing at where the other one is configured, is what keeps
// that omission honest rather than hidden.

import { ExternalLink, Info, TriangleAlert } from 'lucide-react';
import { clsx } from 'clsx';

interface ChatModeNoticeProps {
    /** Whether connections are in force, as currently stored. */
    enabled: boolean;
    /**
     * The unsaved value of the same toggle, when it differs from `enabled`. The route
     * does not change until the save lands, and saying so avoids reading the notice as
     * a description of what is already happening.
     */
    pending?: boolean;
    help?: string;
}

export function ChatModeNotice({ enabled, pending, help }: ChatModeNoticeProps) {
    // Switching to connections is one-way: the settings write coerces the flag to
    // "already on or newly on", so an attempt to turn it back off is refused rather
    // than stored. Only the on-switch is worth announcing.
    const switchingOn = !enabled && pending === true;

    return (
        <div className="py-3">
            <div
                role="note"
                className={clsx(
                    'flex items-start gap-2.5 rounded-lg border p-3 text-xs leading-relaxed',
                    enabled
                        ? 'border-edge bg-surface-1 text-text-2'
                        : 'border-warn/40 bg-warn-soft text-text-1',
                )}
            >
                <span className={clsx('mt-0.5 shrink-0', enabled ? 'text-text-3' : 'text-warn')}>
                    {enabled ? <Info size={15} /> : <TriangleAlert size={15} />}
                </span>
                <div>
                    <p className="font-medium text-text-1">
                        {enabled
                            ? 'Chat is using the connections above.'
                            : 'Chat is using the classic single endpoint.'}
                    </p>
                    <p className="mt-1">
                        {enabled ? (
                            <>
                                People can choose any model that is enabled on an enabled
                                connection. The classic single endpoint is not consulted.
                            </>
                        ) : (
                            <>
                                Connections are configured but unused. Chat runs on one Azure
                                OpenAI or API Management endpoint whose address, credentials and
                                deployment are set on the{' '}
                                <a
                                    href="/admin/settings#model-endpoints"
                                    className="inline-flex items-center gap-1 text-accent underline"
                                >
                                    classic admin page
                                    <ExternalLink size={11} />
                                </a>
                                . Turn on <strong>Use connections for chat</strong> to switch.
                            </>
                        )}
                    </p>
                    {switchingOn ? (
                        <p className="mt-1.5 font-medium text-text-1">
                            Saving will switch chat to the connections above, and that cannot
                            be reversed from here.
                        </p>
                    ) : null}
                </div>
            </div>
            {help ? <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p> : null}
        </div>
    );
}
