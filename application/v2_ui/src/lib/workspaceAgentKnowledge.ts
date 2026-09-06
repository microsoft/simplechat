// workspaceAgentKnowledge.ts

import { api } from './apiClient';
import type { AgentConfiguration } from './workspaceAuthoring';
import { agentObject, agentStrings, agentText, clearAgentDraftFields } from './workspaceAgentAuthoring';

export interface AgentKnowledgeSource {
    scope: string;
    id: string;
    label: string;
}

export interface AgentKnowledgeDocument {
    id: string;
    title: string;
    file_name: string;
    scope: string;
    source_id: string;
    source_name: string;
    tags: string[];
}

export interface AgentKnowledgeCatalog {
    sources: AgentKnowledgeSource[];
    documents: AgentKnowledgeDocument[];
    tags: { name: string; count: number }[];
}

export interface AgentWebSource {
    url: string;
    mode: string;
    [key: string]: unknown;
}

export interface AgentKnowledgeConfiguration {
    enabled: boolean;
    scopes: {
        personal: boolean;
        group_ids: string[];
        public_workspace_ids: string[];
        [key: string]: unknown;
    };
    document_ids: string[];
    tags: string[];
    web_sources: AgentWebSource[];
    allow_user_workspace_context: boolean;
    allowed_user_workspace_actions: string[];
    [key: string]: unknown;
}

export const USER_KNOWLEDGE_ACTIONS = ['search', 'analyze', 'compare'] as const;
export const KNOWLEDGE_LIMITS = { documents: 200, tags: 50, sources: 50, urls: 50 };

export async function fetchAgentKnowledgeCatalog(signal?: AbortSignal): Promise<AgentKnowledgeCatalog> {
    const response = await api.get<AgentKnowledgeCatalog>('/api/agents/assigned-knowledge/catalog?agent_scope=personal', signal);
    if (!response || !Array.isArray(response.sources) || !Array.isArray(response.documents) || !Array.isArray(response.tags)) {
        throw new Error('The assigned knowledge catalogue returned an invalid response.');
    }
    return response;
}

export function normalizeAgentKnowledgeUrl(value: string): string {
    try {
        const url = new URL(value.trim());
        if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return '';
        url.hash = '';
        return url.toString();
    } catch {
        return '';
    }
}

function webMode(mode: unknown): string {
    if (['deep', 'deep-research', 'research'].includes(agentText(mode))) return 'deep_research';
    return agentText(mode) || 'url_review';
}

export function readAgentKnowledge(draft: AgentConfiguration): AgentKnowledgeConfiguration {
    const value = agentObject(draft.other_settings.assigned_knowledge);
    const scopes = agentObject(value.scopes);
    const rawWeb = value.web_sources;
    const webObject = agentObject(rawWeb);
    const rawEntries = typeof rawWeb === 'string' || Array.isArray(rawWeb) ? rawWeb : webObject.sources ?? webObject.urls ?? [];
    const webEntries = typeof rawEntries === 'string' ? rawEntries.split(/[\s,]+/).filter(Boolean) : Array.isArray(rawEntries) ? rawEntries : [];
    const legacySources = (Array.isArray(value.sources) ? value.sources : []).map(agentObject);
    const legacyIds = (scope: string) => legacySources.filter((source) => source.scope === scope)
        .map((source) => agentText(source.id || source.source_id)).filter(Boolean);
    const sourceIds = (field: 'group_ids' | 'public_workspace_ids', scope: string) =>
        [...new Set([...(agentStrings(scopes[field]).length ? agentStrings(scopes[field]) : agentStrings(value[field])), ...legacyIds(scope)])];
    return {
        ...value,
        enabled: value.enabled === true,
        scopes: {
            ...scopes,
            personal: scopes.personal === true || value.personal === true || legacySources.some((source) => source.scope === 'personal'),
            group_ids: sourceIds('group_ids', 'group'),
            public_workspace_ids: sourceIds('public_workspace_ids', 'public'),
        },
        document_ids: agentStrings(value.document_ids).length ? agentStrings(value.document_ids) : agentStrings(value.selected_document_ids),
        tags: agentStrings(value.tags),
        web_sources: webEntries.map((entry) => typeof entry === 'string'
            ? { url: entry, mode: webMode(webObject.mode || (webObject.deep_research === true ? 'deep_research' : undefined)) }
            : {
                ...agentObject(entry),
                url: agentText(agentObject(entry).url || agentObject(entry).href || agentObject(entry).link),
                mode: webMode(agentObject(entry).deep_research === true ? 'deep_research' : agentObject(entry).mode),
            }),
        allow_user_workspace_context: value.allow_user_workspace_context === true,
        allowed_user_workspace_actions: agentStrings(value.allowed_user_workspace_actions ?? value.allowed_user_context_actions ?? USER_KNOWLEDGE_ACTIONS),
    };
}

export function updateAgentKnowledge(draft: AgentConfiguration, changes: Partial<AgentKnowledgeConfiguration>): AgentConfiguration {
    const next = { ...readAgentKnowledge(draft), ...changes };
    // Legacy aliases must not resurrect references after the author explicitly removes them.
    if (Object.hasOwn(changes, 'scopes')) {
        for (const field of ['personal', 'group_ids', 'public_workspace_ids']) delete next[field];
        const unknownSources = (Array.isArray(next.sources) ? next.sources : []).filter((source) =>
            !['personal', 'group', 'public'].includes(agentText(agentObject(source).scope)));
        if (unknownSources.length) next.sources = unknownSources;
        else delete next.sources;
    }
    if (Object.hasOwn(changes, 'document_ids')) delete next.selected_document_ids;
    if (Object.hasOwn(changes, 'allowed_user_workspace_actions')) delete next.allowed_user_context_actions;
    if (Object.hasOwn(changes, 'web_sources')) {
        next.web_sources = next.web_sources.map((source) => {
            const updated = { ...source };
            for (const field of ['href', 'link', 'deep_research']) delete updated[field];
            return updated;
        });
    }
    return clearAgentDraftFields({ ...draft, other_settings: { ...draft.other_settings, assigned_knowledge: next } }, '_editor_settings_text');
}

export function knowledgeSourceKey(source: Pick<AgentKnowledgeSource, 'scope' | 'id'>): string {
    return `${source.scope}:${source.id}`;
}

export function selectedKnowledgeSources(config: AgentKnowledgeConfiguration): string[] {
    return [
        ...(config.scopes.personal ? ['personal:personal'] : []),
        ...config.scopes.group_ids.map((id) => `group:${id}`),
        ...config.scopes.public_workspace_ids.map((id) => `public:${id}`),
    ];
}

export function toggleAgentKnowledgeSource(draft: AgentConfiguration, source: AgentKnowledgeSource, enabled: boolean): AgentConfiguration {
    const config = readAgentKnowledge(draft);
    if (!['personal', 'public'].includes(source.scope)) throw new Error('Personal agents can assign only authorized personal and public sources.');
    const scopes = { ...config.scopes };
    if (source.scope === 'personal') scopes.personal = enabled;
    else scopes.public_workspace_ids = toggleString(scopes.public_workspace_ids, source.id, enabled);
    return updateAgentKnowledge(draft, { scopes });
}

export function toggleString(values: string[], value: string, enabled: boolean): string[] {
    return enabled ? [...new Set([...values, value])] : values.filter((item) => item !== value);
}

export function resolvedAgentDocuments(config: AgentKnowledgeConfiguration, catalog: AgentKnowledgeCatalog): AgentKnowledgeDocument[] {
    if (!config.enabled) return [];
    const sources = new Set(selectedKnowledgeSources(config));
    const ids = new Set(config.document_ids);
    const unrestricted = !ids.size && !config.tags.length;
    const seen = new Set<string>();
    return catalog.documents.filter((document) => {
        if (!sources.has(`${document.scope}:${document.source_id}`) || seen.has(document.id)) return false;
        // Explicit documents OR documents with every selected tag, matching the runtime.
        const active = unrestricted || ids.has(document.id) ||
            (config.tags.length > 0 && config.tags.every((tag) => document.tags.includes(tag)));
        if (active) seen.add(document.id);
        return active;
    });
}

export function agentKnowledgeReference(draft: AgentConfiguration, catalog: AgentKnowledgeCatalog | null) {
    const config = readAgentKnowledge(draft);
    if (draft.agent_type !== 'local' || !config.enabled) return { enabled: false, sources: [], documents: [], tags: [], web_sources: [] };
    const selected = new Set(selectedKnowledgeSources(config));
    return {
        enabled: true,
        sources: (catalog?.sources ?? []).filter((source) => selected.has(knowledgeSourceKey(source))).map((source) => ({
            scope: source.scope, id: source.id, name: source.label,
        })),
        documents: (catalog ? resolvedAgentDocuments(config, catalog) : []).map((document) => ({
            ...document, is_explicit: config.document_ids.includes(document.id),
        })),
        tags: config.tags,
        web_sources: config.web_sources.map((source) => ({
            ...source, mode_label: source.mode === 'deep_research' ? 'Deep research' : 'URL review',
        })),
    };
}

export function agentKnowledgeErrors(draft: AgentConfiguration): string[] {
    const config = readAgentKnowledge(draft);
    if (draft.agent_type !== 'local' || !config.enabled) return [];
    const errors: string[] = [];
    if (!selectedKnowledgeSources(config).length && !config.web_sources.length) errors.push('Select a knowledge workspace or assign a URL.');
    if (config.document_ids.length > KNOWLEDGE_LIMITS.documents) errors.push('Assigned knowledge supports at most 200 explicit documents.');
    if (config.tags.length > KNOWLEDGE_LIMITS.tags) errors.push('Assigned knowledge supports at most 50 tags.');
    if (config.scopes.public_workspace_ids.length > KNOWLEDGE_LIMITS.sources) errors.push('Assigned knowledge supports at most 50 public workspaces.');
    if (config.web_sources.length > KNOWLEDGE_LIMITS.urls) errors.push('Assigned knowledge supports at most 50 URLs.');
    if (config.web_sources.some((source) => !normalizeAgentKnowledgeUrl(source.url))) errors.push('Assigned URLs must be valid HTTP or HTTPS URLs without embedded credentials.');
    if (config.web_sources.some((source) => !['url_review', 'deep_research'].includes(source.mode))) errors.push('Review the mode for each assigned URL.');
    return errors;
}
