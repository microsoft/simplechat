// EndpointLinks.tsx
// The addresses a section exposes, ready to copy into the tool that will call them.
//
// Health checks are pasted into App Service, Azure Monitor or a load balancer probe, and the
// Swagger links are handed to developers. In each case the full address -- this
// deployment's origin plus the path -- is what is needed, and typing it by hand is where it
// goes wrong. Each row also says who the endpoint answers and whether it is live right now:
// a health check is live once its switch is saved on, while Swagger is live only once the
// running app has registered it, which a save alone does not do.

import { clsx } from 'clsx';
import { ArrowUpRight } from 'lucide-react';
import type { AdminEndpointAccess, AdminEndpointLink } from '../../lib/adminFields';
import { safeSameOriginUrl } from '../../lib/adminOperations';
import { apiUrl } from '../../lib/apiClient';
import { CopyButton } from './CopyValue';
import { ReadoutRow } from './ReadoutRow';

const ACCESS_LABEL: Record<AdminEndpointAccess, string> = {
    protected: 'Protected',
    public: 'No sign-in',
    signed_in: 'Sign-in required',
};

type EndpointState =
    | { kind: 'on' }
    | { kind: 'off' }
    | { kind: 'turns-on' }
    | { kind: 'turns-off' }
    | { kind: 'running' }
    | { kind: 'not-running' };

const STATE_LABEL: Record<EndpointState['kind'], string> = {
    on: 'On',
    off: 'Off',
    'turns-on': 'On after you save',
    'turns-off': 'Off after you save',
    running: 'Running',
    'not-running': 'Not running',
};

function stateOf(
    endpoint: AdminEndpointLink,
    isSavedOn: (key: string) => boolean,
    isDraftOn: (key: string) => boolean,
    runtimeFlags: Record<string, boolean>,
): EndpointState {
    if (endpoint.runtime_flag) {
        return runtimeFlags[endpoint.runtime_flag] ? { kind: 'running' } : { kind: 'not-running' };
    }
    if (!endpoint.gate_key) {
        return { kind: 'on' };
    }
    const saved = isSavedOn(endpoint.gate_key);
    const draft = isDraftOn(endpoint.gate_key);
    if (saved === draft) {
        return saved ? { kind: 'on' } : { kind: 'off' };
    }
    return draft ? { kind: 'turns-on' } : { kind: 'turns-off' };
}

/** Whether the address answers right now, which is what decides if Open is offered. */
function isLive(state: EndpointState): boolean {
    return state.kind === 'on' || state.kind === 'running' || state.kind === 'turns-off';
}

function Chip({ children, tone }: { children: string; tone: 'ok' | 'warn' | 'muted' | 'info' }) {
    return (
        <span
            className={clsx(
                'inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium',
                tone === 'ok' && 'bg-ok-soft text-ok',
                tone === 'warn' && 'bg-warn-soft text-warn',
                tone === 'info' && 'bg-accent-soft text-accent',
                tone === 'muted' && 'bg-surface-2 text-text-3',
            )}
        >
            {children}
        </span>
    );
}

function stateTone(state: EndpointState): 'ok' | 'warn' | 'muted' | 'info' {
    if (state.kind === 'on' || state.kind === 'running') {
        return 'ok';
    }
    if (state.kind === 'not-running') {
        return 'warn';
    }
    if (state.kind === 'turns-on' || state.kind === 'turns-off') {
        return 'info';
    }
    return 'muted';
}

export function EndpointLinks({
    label,
    help,
    endpoints,
    isSavedOn,
    isDraftOn,
    runtimeFlags,
}: {
    label: string;
    help?: string;
    endpoints: AdminEndpointLink[];
    isSavedOn: (key: string) => boolean;
    isDraftOn: (key: string) => boolean;
    runtimeFlags: Record<string, boolean>;
}) {
    const origin = window.location.origin;

    return (
        <ReadoutRow label={label} help={help} width="full">
            <ul className="divide-y divide-edge rounded-lg border border-edge">
                {endpoints.map((endpoint) => {
                    const state = stateOf(endpoint, isSavedOn, isDraftOn, runtimeFlags);
                    const href = safeSameOriginUrl(apiUrl(endpoint.path), origin);
                    const address = href ?? endpoint.path;
                    return (
                        <li key={endpoint.path} className="px-3 py-2.5">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                <span className="text-[0.8125rem] font-semibold text-text-1">
                                    {endpoint.label}
                                </span>
                                <Chip tone={endpoint.access === 'public' ? 'warn' : 'muted'}>
                                    {ACCESS_LABEL[endpoint.access]}
                                </Chip>
                                <Chip tone={stateTone(state)}>{STATE_LABEL[state.kind]}</Chip>
                                {isLive(state) && href ? (
                                    <a
                                        href={href}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
                                    >
                                        Open
                                        <ArrowUpRight size={13} aria-hidden="true" />
                                        <span className="sr-only">
                                            {endpoint.label} (opens in a new tab)
                                        </span>
                                    </a>
                                ) : null}
                            </div>
                            <div className="mt-1.5 flex min-w-0 items-center gap-1">
                                <code className="min-w-0 flex-1 truncate rounded-md bg-surface-2 px-2 py-1 font-mono text-xs text-text-1">
                                    {address}
                                </code>
                                <CopyButton value={address} label={`the ${endpoint.label.toLowerCase()} address`} />
                            </div>
                            {endpoint.returns ? (
                                <p className="mt-1 text-xs leading-relaxed text-text-3">{endpoint.returns}</p>
                            ) : null}
                        </li>
                    );
                })}
            </ul>
        </ReadoutRow>
    );
}
