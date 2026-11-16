// adminAgents.ts
// Pure helpers behind the two bespoke Agents controls in Admin Settings.
//
// They live here rather than beside their components so they can be executed by a test
// directly. Both encode a server-side rule that is easy to break and impossible to see
// breaking: orchestration hides a control the server would discard, and a promotion has to
// carry the exact fields `normalize_agents_page_promoted_popular_agents` keeps.

/** One orchestration mode offered by `GET /api/orchestration_types`. */
export interface OrchestrationType {
    value: string;
    label: string;
    agent_mode?: string;
    description?: string;
}

/** One promotion, matching the stored entry shape exactly. */
export interface PromotedAgent {
    catalog_key: string;
    display_name: string;
    scope_label: string;
    scope_type: string;
    window: string;
}

/** A catalog entry as it arrives from `GET /api/agents/catalog`. */
export interface CatalogAgent {
    catalog_key?: unknown;
    display_name?: unknown;
    name?: unknown;
    scope_label?: unknown;
    scope_name?: unknown;
    scope_type?: unknown;
    window?: unknown;
    is_global?: unknown;
    is_group?: unknown;
}

/**
 * Which Popular views a promotion applies to.
 *
 * Mirrors `AGENTS_PAGE_PROMOTED_POPULAR_WINDOW_OPTIONS`; the server rewrites anything else
 * to `both`, so offering a value outside this set would silently change on save.
 */
export const PROMOTED_WINDOW_OPTIONS = [
    { value: 'both', label: 'Both windows' },
    { value: '30_days', label: 'Last 30 days' },
    { value: 'all_time', label: 'All time' },
];

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/** Types the server offers, filtered to the ones a select could actually use. */
export function readOrchestrationTypes(payload: unknown): OrchestrationType[] {
    if (!Array.isArray(payload)) {
        return [];
    }
    return payload
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map((item) => ({
            value: String(item.value ?? ''),
            label: String(item.label ?? item.value ?? ''),
            agent_mode: typeof item.agent_mode === 'string' ? item.agent_mode : undefined,
            description: typeof item.description === 'string' ? item.description : undefined,
        }))
        .filter((item) => item.value.length > 0);
}

/**
 * Whether the orchestration control is worth drawing at all.
 *
 * `get_agent_orchestration_types()` returns a single entry today, because the multi-agent
 * modes are commented out. A select with one option is not a choice, so the card stays
 * hidden until a deployment offers a real one -- and reappears by itself if it does.
 */
export function orchestrationIsSelectable(types: OrchestrationType[]): boolean {
    return types.length > 1;
}

/**
 * Whether Max Rounds Per Agent applies to the selected type.
 *
 * The server forces the stored value back to 1 for anything that is not multi-agent, so
 * showing the control otherwise would offer an edit that is discarded on save.
 */
export function roundsApply(types: OrchestrationType[], selected: string): boolean {
    return types.find((type) => type.value === selected)?.agent_mode === 'multi';
}

/** Port of `getAdminAgentScopeType`, so both surfaces classify a scope the same way. */
export function agentScopeType(agent: CatalogAgent): string {
    const declared = text(agent.scope_type).toLowerCase();
    if (agent.is_group || declared === 'group') {
        return 'group';
    }
    if (agent.is_global || declared === 'global' || declared === 'enterprise') {
        return 'global';
    }
    return 'personal';
}

/** Port of `getAdminAgentScopeLabel`. */
export function agentScopeLabel(agent: CatalogAgent): string {
    const scope = agentScopeType(agent);
    if (scope === 'group') {
        return text(agent.scope_name) || 'Group';
    }
    return scope === 'global' ? 'Enterprise' : 'Personal';
}

/** Build a stored promotion from a catalog entry, or null when it has no catalog key. */
export function toPromotedAgent(agent: CatalogAgent): PromotedAgent | null {
    const catalogKey = text(agent.catalog_key);
    if (!catalogKey) {
        return null;
    }
    return {
        catalog_key: catalogKey,
        display_name: text(agent.display_name) || text(agent.name),
        scope_label: text(agent.scope_label) || agentScopeLabel(agent),
        scope_type: agentScopeType(agent),
        window: 'both',
    };
}

/** Read the stored value defensively; it is administrator data from the database. */
export function readPromotedAgents(value: unknown): PromotedAgent[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const seen = new Set<string>();
    const promoted: PromotedAgent[] = [];

    for (const item of value) {
        if (!item || typeof item !== 'object') {
            continue;
        }
        const entry = item as CatalogAgent;
        const catalogKey = text(entry.catalog_key);
        // The server keys the list by catalog key and drops repeats, so a duplicate
        // shown here would disappear on save with no explanation.
        if (!catalogKey || seen.has(catalogKey)) {
            continue;
        }
        seen.add(catalogKey);
        promoted.push({
            catalog_key: catalogKey,
            display_name: text(entry.display_name) || text(entry.name),
            scope_label: text(entry.scope_label) || text(entry.scope_name),
            scope_type: text(entry.scope_type).toLowerCase(),
            window: text(entry.window) || 'both',
        });
    }

    return promoted;
}

/** Catalog agents that may still be promoted, given what is already promoted. */
export function promotableAgents(
    candidates: CatalogAgent[],
    promoted: PromotedAgent[],
): PromotedAgent[] {
    const taken = new Set(promoted.map((agent) => agent.catalog_key));
    return candidates
        .map(toPromotedAgent)
        .filter((agent): agent is PromotedAgent => agent !== null)
        .filter((agent) => !taken.has(agent.catalog_key));
}
