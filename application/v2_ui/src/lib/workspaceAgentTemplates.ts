// workspaceAgentTemplates.ts

import { api } from './apiClient';
import { EDITOR_SECRET_MASK, editorName, isRecord, type ActionConfiguration, type AgentConfiguration } from './workspaceAuthoring';
import { agentObject, agentStrings, newAgentDraft } from './workspaceAgentAuthoring';
import { resolveAgentAction } from './workspaceAgentActions';

export interface AgentTemplate {
    id: string;
    title: string;
    display_name: string;
    description: string;
    helper_text?: string;
    instructions: string;
    additional_settings?: string | Record<string, unknown>;
    actions_to_load?: string[];
    tags?: string[];
    status?: string;
}

const PRIVATE_TEMPLATE_FIELD = /secret|password|credential|connection|endpoint|api[_-]?key|subscription[_-]?key|private[_-]?key|account[_-]?key|access[_-]?token|refresh[_-]?token|bearer[_-]?token|authorization|cookie|^auth$|^key$|^token$|^sas$|sas[_-]?token|keyvault|key_vault/i;
const PRIVATE_TEMPLATE_VALUES = new Set([EDITOR_SECRET_MASK, 'Stored_In_KeyVault', '[REDACTED]', '********', '**********']);

/** Templates are shared recipes, never a mechanism for copying saved connection secrets. */
export function safeAgentTemplateSettings(value: unknown): Record<string, unknown> {
    const clean = (item: unknown): unknown => {
        if (typeof item === 'string' && PRIVATE_TEMPLATE_VALUES.has(item)) return undefined;
        if (typeof item === 'string' && /^https?:\/\//i.test(item)) {
            try {
                const url = new URL(item);
                if (url.username || url.password || /\/secrets\//i.test(url.pathname) ||
                    [...url.searchParams.keys()].some((key) => PRIVATE_TEMPLATE_FIELD.test(key))) return undefined;
            } catch {
                return undefined;
            }
        }
        if (Array.isArray(item)) return item.map(clean).filter((entry) => entry !== undefined);
        if (!isRecord(item)) return item;
        return Object.fromEntries(Object.entries(item)
            .filter(([key]) => !PRIVATE_TEMPLATE_FIELD.test(key))
            .map(([key, entry]) => [key, clean(entry)])
            .filter(([, entry]) => entry !== undefined));
    };
    return agentObject(clean(value));
}

export async function fetchAgentTemplates(signal?: AbortSignal): Promise<AgentTemplate[]> {
    const payload = await api.get<{ templates: AgentTemplate[] }>('/api/agent-templates', signal);
    if (!payload || !Array.isArray(payload.templates)) throw new Error('The template gallery returned an invalid response.');
    return payload.templates;
}

export function agentDraftFromTemplate(template: AgentTemplate, actions: ActionConfiguration[]): AgentConfiguration {
    const settings: unknown = typeof template.additional_settings === 'string'
        ? JSON.parse(template.additional_settings || '{}') : template.additional_settings ?? {};
    if (!isRecord(settings)) throw new Error('This template has invalid additional settings.');
    const name = template.display_name || template.title;
    return {
        ...newAgentDraft(),
        display_name: name,
        name: editorName(name),
        description: template.description || template.helper_text || '',
        instructions: template.instructions || '',
        tags: agentStrings(template.tags),
        other_settings: safeAgentTemplateSettings(settings),
        actions_to_load: [...new Set(agentStrings(template.actions_to_load).map((reference) => resolveAgentAction(reference, actions)?.id || reference))],
    };
}

export function agentTemplateSubmission(draft: AgentConfiguration) {
    return {
        template: {
            title: draft.display_name.trim(),
            display_name: draft.display_name.trim(),
            description: draft.description,
            helper_text: draft.description,
            instructions: draft.instructions,
            additional_settings: JSON.stringify(safeAgentTemplateSettings(draft.other_settings)),
            actions_to_load: draft.actions_to_load,
            tags: draft.tags ?? [],
            ...(draft.id ? { source_agent_id: draft.id } : {}),
            source_scope: 'personal',
        },
    };
}
