// workspaceAgentReferences.ts
// Literal mention grammar shared with V1: quoted whitespace/colons, bounded trigger scanning.

import type { ActionConfiguration, AgentConfiguration } from './workspaceAuthoring';
import { agentSelectedActionsContext } from './workspaceAgentActions';
import { agentKnowledgeReference, type AgentKnowledgeCatalog } from './workspaceAgentKnowledge';

export interface AgentMention {
    token: string;
    label: string;
    description: string;
}

export function agentMentionValue(value: string): string {
    const text = value.trim();
    return /[\s:"]/.test(text) ? `"${text.replaceAll('"', "'")}"` : text;
}

export function agentActionToken(label: string, capability = ''): string {
    if (!label.trim()) return '';
    return `#action:${agentMentionValue(label)}${capability ? `:${agentMentionValue(capability)}` : ''}`;
}

export function agentKnowledgeToken(type: string, value: string): string {
    return value.trim() && type.trim() ? `#knowledge:${type}:${agentMentionValue(value)}` : '';
}

export function agentMentionTrigger(text: string, cursor: number): { start: number; query: string } | null {
    const windowStart = Math.max(0, cursor - 501);
    for (let index = cursor - 1; index >= windowStart; index -= 1) {
        const character = text[index];
        if (character === '\n' || character === '\r') return null;
        if (character !== '#') continue;
        if (index && !/[\s([{>"'`]/.test(text[index - 1])) return null;
        return { start: index, query: text.slice(index + 1, cursor) };
    }
    return null;
}

export function agentMentions(
    draft: AgentConfiguration, actions: ActionConfiguration[], catalog: AgentKnowledgeCatalog | null,
): AgentMention[] {
    const mentions: AgentMention[] = [];
    for (const action of agentSelectedActionsContext(draft, actions)) {
        mentions.push({ token: agentActionToken(action.display_name), label: action.display_name, description: `Action · ${action.type}` });
        for (const capability of action.capabilities) {
            mentions.push({
                token: agentActionToken(action.display_name, capability.key),
                label: `${action.display_name} · ${capability.label}`, description: 'Action capability',
            });
        }
    }
    const knowledge = agentKnowledgeReference(draft, catalog);
    for (const document of knowledge.documents) mentions.push({ token: agentKnowledgeToken('doc', document.title), label: document.title, description: 'Assigned document' });
    for (const source of knowledge.sources) mentions.push({ token: agentKnowledgeToken('workspace', source.name), label: source.name, description: 'Assigned workspace' });
    for (const tag of knowledge.tags) mentions.push({ token: agentKnowledgeToken('tag', tag), label: tag, description: 'Assigned tag' });
    for (const source of knowledge.web_sources) mentions.push({ token: agentKnowledgeToken('web', source.url), label: source.url, description: 'Assigned URL' });
    return mentions;
}

export function filterAgentMentions(mentions: AgentMention[], query: string): AgentMention[] {
    const normalized = query.replaceAll('"', '').toLowerCase();
    return mentions.filter((mention) => !normalized ||
        mention.token.slice(1).replaceAll('"', '').toLowerCase().includes(normalized) ||
        mention.label.toLowerCase().includes(normalized)).slice(0, 10);
}
