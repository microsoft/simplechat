// agentCatalog.ts

import { agentScopeType } from './adminAgents';
import type { AgentLinkScope } from './conversationUrl';
import { isRecord, type AgentConfiguration } from './workspaceAuthoring';
import { AGENT_TYPE_LABELS, agentStrings, agentText } from './workspaceAgentAuthoring';

export const AGENTS_CATALOG_ENDPOINT = '/api/v2/agents/catalog';
export const CATALOG_VIEW_STORAGE_KEY = 'simplechat-agents-catalog-view';
export type CatalogTab = 'popular' | 'personal' | 'group' | 'enterprise';
export type CatalogUsageWindow = 'all_time' | '30_days';
export type CatalogViewMode = 'list' | 'card';

export interface CatalogAgent {
    id?: string;
    name?: string;
    display_name?: string;
    description?: string;
    agent_type?: string;
    is_global?: boolean;
    is_group?: boolean;
    scope_type?: string;
    scope_id?: string;
    scope_name?: string;
    group_id?: string;
    group_name?: string;
    tags?: string[];
    icon?: AgentConfiguration['icon'];
    model_label?: string;
    actions_to_load?: string[];
    action_labels?: string[];
    catalog_key?: string;
    usage_count?: number | string | null;
    usage_count_30_days?: number | string | null;
    usage_count_all_time?: number | string | null;
    is_promoted_popular?: boolean;
    promoted_popular_window?: string;
    promoted_popular_rank?: number | string | null;
    promoted_popular_order?: string;
    promoted_popular_tag_enabled?: boolean;
    promoted_popular_tag_label?: string;
    instructions?: string;
}

export interface CatalogPageConfig {
    title: string;
    subtitle: string;
    hero_color_mode: 'single' | 'two_tone';
    hero_primary_color: string;
    hero_secondary_color: string;
    disclaimer_markdown: string;
    show_instructions_in_details: boolean;
}

export interface AgentsCatalog {
    page: CatalogPageConfig;
    agents: CatalogAgent[];
}

export const DEFAULT_CATALOG_PAGE: CatalogPageConfig = {
    title: 'Find your next AI partner',
    subtitle: 'Explore specialized agents built to accelerate how you work.',
    hero_color_mode: 'single',
    hero_primary_color: '#0f172a',
    hero_secondary_color: '#1e293b',
    disclaimer_markdown: '',
    show_instructions_in_details: true,
};

export function normalizeCatalogText(value: unknown): string {
    return agentText(value).replace(/\s+/g, ' ').trim();
}

export function catalogDisplayName(agent: CatalogAgent): string {
    return normalizeCatalogText(agent.display_name) || normalizeCatalogText(agent.name) || 'Unnamed Agent';
}

export function catalogScopeLabel(agent: CatalogAgent): string {
    const scope = agentScopeType(agent);
    if (scope === 'group') {
        return normalizeCatalogText(agent.group_name) || normalizeCatalogText(agent.scope_name) || 'Group';
    }
    return scope === 'global' ? 'Enterprise' : 'Personal';
}

export function catalogAgentTypeLabel(agent: CatalogAgent): string {
    const type = normalizeCatalogText(agent.agent_type).toLowerCase();
    if (type === 'local' || type === 'aifoundry' || type === 'new_foundry' || type === 'foundry_workflow') {
        return AGENT_TYPE_LABELS[type];
    }
    return normalizeCatalogText(agent.agent_type) || AGENT_TYPE_LABELS.local;
}

export function catalogAgentKey(agent: CatalogAgent): string {
    return normalizeCatalogText(agent.catalog_key) || normalizeCatalogText(agent.id) || catalogDisplayName(agent);
}

export function promotedBadgeLabel(agent: CatalogAgent): string {
    if (!agent.is_promoted_popular || agent.promoted_popular_tag_enabled === false) {
        return '';
    }
    return (normalizeCatalogText(agent.promoted_popular_tag_label) || 'Promoted').slice(0, 40);
}

export function normalizePromotionWindow(value: unknown): CatalogUsageWindow | 'both' {
    const window = normalizeCatalogText(value).toLowerCase().replace(/-/g, '_');
    if (['all', 'alltime', 'all_time'].includes(window)) {
        return 'all_time';
    }
    if (['30', 'last30', 'last_30_days', '30_days'].includes(window)) {
        return '30_days';
    }
    return 'both';
}

export function catalogUsageCount(agent: CatalogAgent, window: CatalogUsageWindow): number {
    const selected = window === '30_days' ? agent.usage_count_30_days : agent.usage_count_all_time;
    const count = Number(selected ?? agent.usage_count ?? 0);
    return Number.isFinite(count) ? count : 0;
}

function promotionRank(agent: CatalogAgent): number {
    const rank = Number(agent.promoted_popular_rank);
    return Number.isFinite(rank) ? rank : 1000000;
}

function byName(left: CatalogAgent, right: CatalogAgent): number {
    return catalogDisplayName(left).localeCompare(catalogDisplayName(right), undefined, { sensitivity: 'base' });
}

function dedupeAgents(agents: CatalogAgent[]): CatalogAgent[] {
    const seen = new Set<string>();
    return agents.filter((agent) => {
        const key = catalogAgentKey(agent);
        if (seen.has(key)) {
            return false;
        }
        seen.add(key);
        return true;
    });
}

/** Promotions are additional to, not part of, the twelve usage-ranked agents. */
export function popularAgents(agents: CatalogAgent[], window: CatalogUsageWindow): CatalogAgent[] {
    const promoted = agents.filter((agent) => {
        const promotionWindow = normalizePromotionWindow(agent.promoted_popular_window);
        return agent.is_promoted_popular && (promotionWindow === 'both' || promotionWindow === window);
    }).sort((left, right) => promotionRank(left) - promotionRank(right) || byName(left, right));
    const promotedKeys = new Set(promoted.map(catalogAgentKey));
    const used = agents.filter((agent) => (
        catalogUsageCount(agent, window) > 0 && !promotedKeys.has(catalogAgentKey(agent))
    )).sort((left, right) => (
        catalogUsageCount(right, window) - catalogUsageCount(left, window) || byName(left, right)
    )).slice(0, 12);

    const order = normalizeCatalogText(promoted[0]?.promoted_popular_order).toLowerCase();
    if (promoted.length && order !== 'mixed' && order !== 'after') {
        return dedupeAgents([...promoted, ...used]);
    }
    if (order === 'after') {
        return dedupeAgents([...used, ...promoted]);
    }
    return dedupeAgents([...used, ...promoted]).sort((left, right) => (
        catalogUsageCount(right, window) - catalogUsageCount(left, window)
        || promotionRank(left) - promotionRank(right)
        || byName(left, right)
    ));
}

export function visibleAgents({
    agents, tab, window, query, tags,
}: {
    agents: CatalogAgent[];
    tab: CatalogTab;
    window: CatalogUsageWindow;
    query: string;
    tags: string[];
}): CatalogAgent[] {
    const search = normalizeCatalogText(query).toLowerCase();
    const base = search ? agents : tab === 'popular' ? popularAgents(agents, window) : agents.filter((agent) => {
        const scope = agentScopeType(agent);
        return scope === (tab === 'enterprise' ? 'global' : tab);
    });
    const tagKeys = tags.map((tag) => normalizeCatalogText(tag).toLowerCase());
    const result = base.filter((agent) => {
        const agentTags = new Set(agentStrings(agent.tags).map((tag) => normalizeCatalogText(tag).toLowerCase()));
        if (!tagKeys.every((tag) => agentTags.has(tag))) {
            return false;
        }
        const searchable = [
            catalogDisplayName(agent), agent.name, agent.description, catalogScopeLabel(agent),
            agent.model_label, ...agentStrings(agent.tags),
        ].map(normalizeCatalogText).join(' ').toLowerCase();
        return !search || searchable.includes(search);
    });
    return search || tab !== 'popular' ? result.sort(byName) : result;
}

export function tagsFor(agents: CatalogAgent[]): string[] {
    const tags = new Map<string, string>();
    for (const agent of agents) {
        for (const raw of agentStrings(agent.tags)) {
            const tag = normalizeCatalogText(raw);
            if (tag && !tags.has(tag.toLowerCase())) {
                tags.set(tag.toLowerCase(), tag);
            }
        }
    }
    return [...tags.values()].sort((left, right) => left.localeCompare(right, undefined, { sensitivity: 'base' }));
}

export function agentLinkScope(agent: CatalogAgent): AgentLinkScope | null {
    if (!normalizeCatalogText(agent.id)) {
        return null;
    }
    const scope = agentScopeType(agent);
    if (scope === 'group') {
        const id = normalizeCatalogText(agent.group_id) || normalizeCatalogText(agent.scope_id);
        return id ? { kind: 'group', id } : null;
    }
    return scope === 'global' ? { kind: 'global' } : { kind: 'personal' };
}

export function catalogHeroColor(value: unknown, fallback: string): string {
    const color = agentText(value).trim();
    return /^#[0-9a-fA-F]{6}$/.test(color) ? color : fallback;
}

export function parseCatalogViewMode(value: unknown): CatalogViewMode {
    return value === 'card' ? 'card' : 'list';
}

function numericField(value: unknown): number | string | null | undefined {
    return typeof value === 'number' || typeof value === 'string' || value === null ? value : undefined;
}

function readCatalogAgent(record: Record<string, unknown>, showInstructions: boolean): CatalogAgent {
    const icon = record.icon;
    return {
        id: agentText(record.id).trim(),
        name: agentText(record.name),
        display_name: agentText(record.display_name),
        description: agentText(record.description),
        agent_type: agentText(record.agent_type),
        is_global: record.is_global === true,
        is_group: record.is_group === true,
        scope_type: agentText(record.scope_type),
        scope_id: agentText(record.scope_id).trim(),
        scope_name: agentText(record.scope_name),
        group_id: agentText(record.group_id).trim(),
        group_name: agentText(record.group_name),
        tags: agentStrings(record.tags),
        icon: isRecord(icon) && (icon.kind === 'image' || icon.kind === 'bootstrap') && typeof icon.value === 'string'
            ? { kind: icon.kind, value: icon.value, mime_type: typeof icon.mime_type === 'string' ? icon.mime_type : undefined }
            : undefined,
        model_label: agentText(record.model_label),
        actions_to_load: agentStrings(record.actions_to_load),
        // An explicitly empty display-label list is authoritative, as in classic details.
        action_labels: Array.isArray(record.action_labels) ? agentStrings(record.action_labels) : undefined,
        catalog_key: agentText(record.catalog_key),
        usage_count: numericField(record.usage_count),
        usage_count_30_days: numericField(record.usage_count_30_days),
        usage_count_all_time: numericField(record.usage_count_all_time),
        is_promoted_popular: record.is_promoted_popular === true,
        promoted_popular_window: agentText(record.promoted_popular_window),
        promoted_popular_rank: numericField(record.promoted_popular_rank),
        promoted_popular_order: agentText(record.promoted_popular_order),
        promoted_popular_tag_enabled: record.promoted_popular_tag_enabled !== false,
        promoted_popular_tag_label: agentText(record.promoted_popular_tag_label),
        instructions: showInstructions ? agentText(record.instructions) : undefined,
    };
}

export function readAgentsCatalog(payload: unknown): AgentsCatalog {
    if (!isRecord(payload) || !isRecord(payload.page) || !Array.isArray(payload.agents)) {
        throw new Error('Invalid agent catalogue response.');
    }
    const page = payload.page;
    const showInstructions = page.show_instructions_in_details !== false;
    return {
        page: {
            title: (normalizeCatalogText(page.title) || DEFAULT_CATALOG_PAGE.title).slice(0, 120),
            subtitle: (normalizeCatalogText(page.subtitle) || DEFAULT_CATALOG_PAGE.subtitle).slice(0, 240),
            hero_color_mode: page.hero_color_mode === 'two_tone' ? 'two_tone' : 'single',
            hero_primary_color: catalogHeroColor(page.hero_primary_color, DEFAULT_CATALOG_PAGE.hero_primary_color),
            hero_secondary_color: catalogHeroColor(page.hero_secondary_color, DEFAULT_CATALOG_PAGE.hero_secondary_color),
            disclaimer_markdown: agentText(page.disclaimer_markdown).slice(0, 3000),
            show_instructions_in_details: showInstructions,
        },
        agents: payload.agents.filter(isRecord).map((agent) => readCatalogAgent(agent, showInstructions)),
    };
}
