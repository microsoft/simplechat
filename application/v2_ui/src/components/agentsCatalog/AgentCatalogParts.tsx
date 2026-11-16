// AgentCatalogParts.tsx

import { MessageSquare } from 'lucide-react';
import { Link } from 'react-router-dom';
import { agentScopeType } from '../../lib/adminAgents';
import {
    agentLinkScope, catalogDisplayName, catalogScopeLabel, promotedBadgeLabel, type CatalogAgent,
} from '../../lib/agentCatalog';
import { chatHrefForAgent } from '../../lib/conversationUrl';
import { GlassButton } from '../ui/primitives';
import { Pill } from '../workspace/primitives';

export function AgentCatalogBadges({ agent }: { agent: CatalogAgent }) {
    const promoted = promotedBadgeLabel(agent);
    return (
        <div className="flex min-w-0 flex-wrap gap-1.5 [&>span]:max-w-full [&>span]:break-words [&>span]:whitespace-normal">
            <Pill tone={agentScopeType(agent) === 'personal' ? 'neutral' : 'accent'}>
                {catalogScopeLabel(agent)}
            </Pill>
            {promoted ? <Pill tone="ok">{promoted}</Pill> : null}
        </div>
    );
}

export function AgentChatLink({ agent }: { agent: CatalogAgent }) {
    const scope = agentLinkScope(agent);
    const label = `Chat with ${catalogDisplayName(agent)}`;
    if (!scope || !agent.id) {
        return (
            <GlassButton size="sm" variant="primary" disabled aria-label={label}
                title="This agent is missing its identifier or group.">
                <MessageSquare size={14} aria-hidden="true" />
                Chat
            </GlassButton>
        );
    }
    return (
        <Link to={chatHrefForAgent(agent.id, scope)} aria-label={label}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-xl bg-accent px-3 text-sm font-medium text-on-accent transition-colors hover:bg-accent-hover">
            <MessageSquare size={14} aria-hidden="true" />
            Chat
        </Link>
    );
}
