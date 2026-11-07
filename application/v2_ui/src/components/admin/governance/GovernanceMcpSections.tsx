// GovernanceMcpSections.tsx
// The policy halves of the two MCP governance cards.
//
// MCP Action Destination Governance: the switches above decide whether destinations are
// enforced; this lists the destination policies that decide which servers each scope may
// reach, and for whom. It says plainly when policies are saved but not enforced, and when
// enforcement is on with nothing allowed, which is the state that silently breaks every
// remote MCP action.
//
// Inbound MCP Source Governance: inbound MCP is deny-by-default, so a request that passes
// every check in the Inbound MCP settings still gets no tools until a source policy allows
// the person. New policies start restricted to named people, as the classic page did.

import { useState } from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, ChevronRight, Globe, Info, UserRound, UsersRound } from 'lucide-react';
import {
    INBOUND_MCP_SOURCE_ENTITY_TYPE,
    MCP_DESTINATION_ENTITY_TYPES,
    newItemPolicyDraft,
    readDraftAware,
    type GovernanceEntityType,
} from '../../../lib/governance';
import { asBoolean } from '../../../lib/adminFields';
import type { Json } from '../../../lib/types';
import { openGovernanceEditor } from '../../../stores/governanceStore';
import { GlassButton } from '../../ui/primitives';
import { GovernanceItemPolicyManager } from './GovernanceItemPolicyManager';

function Notice({ tone, children }: { tone: 'info' | 'warn'; children: React.ReactNode }) {
    const Icon = tone === 'warn' ? AlertTriangle : Info;
    return (
        <p
            role="status"
            className={clsx(
                'flex items-start gap-2 rounded-lg border px-3 py-2 text-xs text-text-2',
                tone === 'warn' ? 'border-warn/40 bg-warn/5' : 'border-edge-strong bg-surface-2',
            )}
        >
            <Icon size={13} aria-hidden="true" className={clsx('mt-0.5 shrink-0', tone === 'warn' ? 'text-warn' : 'text-accent')} />
            <span>{children}</span>
        </p>
    );
}

const PATTERNS: { pattern: string; meaning: string }[] = [
    { pattern: 'preconfiguration:github', meaning: 'One template from the MCP catalog. Enterprise templates only appear in the action editor when a policy names them this way.' },
    { pattern: '*.contoso.com', meaning: 'Every endpoint on a matching host.' },
    { pattern: 'https://mcp.contoso.com/mcp*', meaning: 'One endpoint, or every path under it when the URL ends in *.' },
    { pattern: 'preset:generic', meaning: 'Every server built from one preset.' },
    { pattern: 'transport:streamable_http', meaning: 'Every server on one transport. Use the underscore: streamable-http never matches.' },
    { pattern: '*', meaning: 'Any remote server in the scope, after identity and authentication checks.' },
    { pattern: 'group:<group-id>::<pattern>', meaning: 'Group scope only: the pattern applies to one group instead of every group.' },
];

function PatternReference() {
    const [open, setOpen] = useState(false);
    return (
        <div className="rounded-xl border border-edge-strong bg-surface-solid">
            <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen((current) => !current)}
                className={clsx(
                    'flex min-h-10 w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-medium text-text-1 hover:bg-surface-sunken',
                    open && 'rounded-b-none bg-surface-sunken',
                )}
            >
                <ChevronRight size={14} aria-hidden="true" className={clsx('shrink-0 text-text-2 transition-transform', open && 'rotate-90')} />
                Destination patterns
            </button>
            {open ? (
                <dl className="divide-y divide-edge border-t border-edge-strong px-3 text-xs">
                    {PATTERNS.map((entry) => (
                        <div key={entry.pattern} className="grid gap-1 py-2 @min-[44rem]:grid-cols-[minmax(12rem,18rem)_1fr] @min-[44rem]:gap-4">
                            <dt>
                                <code className="font-mono text-[11px] text-text-1 break-all">{entry.pattern}</code>
                            </dt>
                            <dd className="text-text-3">{entry.meaning}</dd>
                        </div>
                    ))}
                </dl>
            ) : null}
        </div>
    );
}

const SCOPE_SHORTCUTS: { entityType: GovernanceEntityType; label: string; Icon: typeof UserRound }[] = [
    { entityType: 'mcp_personal_destination', label: 'Personal', Icon: UserRound },
    { entityType: 'mcp_group_destination', label: 'Group', Icon: UsersRound },
    { entityType: 'mcp_global_destination', label: 'Global', Icon: Globe },
];

export function GovernanceMcpDestinationPolicies({
    help,
    settings,
    draft,
}: {
    help?: string;
    settings: Json;
    draft: Json;
}) {
    const [total, setTotal] = useState<number | null>(null);
    const enforced = asBoolean(readDraftAware(settings, draft, 'enable_mcp_destination_governance'));

    const create = (entityType: GovernanceEntityType) =>
        openGovernanceEditor({
            draft: newItemPolicyDraft({ entity_type: entityType }),
            entityTypes: MCP_DESTINATION_ENTITY_TYPES,
        });

    return (
        <div className="space-y-3 py-3">
            {help ? <p className="max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{help}</p> : null}

            {!enforced ? (
                <Notice tone="info">
                    These policies are saved but not enforced while the allowlist is off. Prepare them for the
                    servers people already use, then turn on Enforce MCP Destination Allowlist.
                </Notice>
            ) : total === 0 ? (
                <Notice tone="warn">
                    The allowlist is on and no destination policy exists, so no remote MCP server is reachable
                    from any scope unless the deployment environment allows it.
                </Notice>
            ) : null}

            <PatternReference />

            <GovernanceItemPolicyManager
                entityTypes={MCP_DESTINATION_ENTITY_TYPES}
                newPolicy={() => newItemPolicyDraft({ entity_type: 'mcp_personal_destination' })}
                hideNewButton
                actions={(
                    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="New destination policy">
                        <span className="text-xs text-text-3">New policy for</span>
                        {SCOPE_SHORTCUTS.map(({ entityType, label, Icon }) => (
                            <GlassButton
                                key={entityType}
                                type="button"
                                size="md"
                                variant="subtle"
                                aria-label={`New ${label.toLowerCase()} destination policy`}
                                onClick={() => create(entityType)}
                            >
                                <Icon size={15} aria-hidden="true" />
                                {label}
                            </GlassButton>
                        ))}
                    </div>
                )}
                emptyText="No destination policies yet. Start with a specific preconfigured server or host for each scope people build MCP actions in, rather than *."
                label="MCP destination policies"
                onTotalChange={setTotal}
            />
        </div>
    );
}

export function GovernanceInboundMcpPolicies({
    help,
    settings,
    draft,
    mcpUiEnabled,
}: {
    help?: string;
    settings: Json;
    draft: Json;
    mcpUiEnabled: boolean;
}) {
    const [total, setTotal] = useState<number | null>(null);
    const serverOn = asBoolean(readDraftAware(settings, draft, 'enable_inbound_mcp_server'));
    const allowAllSourcesValue = readDraftAware(settings, draft, 'inbound_mcp_allow_all_source_ids');
    const allowAllSources = allowAllSourcesValue === undefined ? true : asBoolean(allowAllSourcesValue);

    const create = (anySource: boolean) =>
        openGovernanceEditor({
            draft: newItemPolicyDraft({
                entity_type: INBOUND_MCP_SOURCE_ENTITY_TYPE,
                item_id: anySource ? '*' : '',
                resource_label: anySource ? 'All accepted source IDs (*)' : '',
                policy_name: anySource ? 'Inbound MCP all source access' : 'Inbound MCP source access',
                // Restricted by default, as on the classic page: allowing everyone with the
                // Entra role and delegated scope is a deliberate choice, not a default.
                allow_all: false,
            }),
            entityTypes: [INBOUND_MCP_SOURCE_ENTITY_TYPE],
        });

    return (
        <div className="space-y-3 py-3">
            {help ? <p className="max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{help}</p> : null}

            <dl className="grid gap-x-6 gap-y-1 text-xs @min-[44rem]:grid-cols-3">
                <div className="flex gap-1.5">
                    <dt className="text-text-3">Inbound MCP</dt>
                    <dd className="text-text-1">{mcpUiEnabled ? 'Available' : 'Not enabled for this deployment'}</dd>
                </div>
                <div className="flex gap-1.5">
                    <dt className="text-text-3">Server</dt>
                    <dd className="text-text-1">{serverOn ? 'On' : 'Off'}</dd>
                </div>
                <div className="flex gap-1.5">
                    <dt className="text-text-3">Accepted sources</dt>
                    <dd className="text-text-1">{allowAllSources ? 'Any source ID' : 'Listed source IDs only'}</dd>
                </div>
            </dl>

            {!mcpUiEnabled ? (
                <Notice tone="info">
                    The App Service setting that enables inbound MCP is off, so these policies have no effect yet.
                    They apply as soon as it is turned on.
                </Notice>
            ) : serverOn && total === 0 ? (
                <Notice tone="warn">
                    The inbound MCP server is on, but no source policy allows anyone, so every request is refused.
                </Notice>
            ) : null}

            <p className="flex items-start gap-2 text-xs text-text-3">
                <AlertTriangle size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-warn" />
                The source ID comes from a request header the client sends. Treat it as advisory unless a trusted
                gateway sets or validates it; the Entra role and delegated scope are what authenticate the caller.
            </p>

            <GovernanceItemPolicyManager
                entityTypes={[INBOUND_MCP_SOURCE_ENTITY_TYPE]}
                newPolicy={() => newItemPolicyDraft({ entity_type: INBOUND_MCP_SOURCE_ENTITY_TYPE, allow_all: false })}
                hideNewButton
                actions={(
                    <div className="flex flex-wrap gap-1.5">
                        <GlassButton type="button" size="md" variant="primary" onClick={() => create(true)}>
                            Allow from any source
                        </GlassButton>
                        {/* With every source ID accepted, * is the only source a policy can name. */}
                        {!allowAllSources ? (
                            <GlassButton type="button" size="md" variant="subtle" onClick={() => create(false)}>
                                Allow from one source
                            </GlassButton>
                        ) : null}
                    </div>
                )}
                emptyText="No source policy yet, so inbound MCP returns no tools to anyone. Start with a policy for * that names the people or groups who should connect."
                label="Inbound MCP source policies"
                onTotalChange={setTotal}
            />
        </div>
    );
}
