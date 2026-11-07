// test_v2_agents_catalog_logic.ts
// Version: 0.261.305
// Implemented in: 0.261.305
// Executes the catalogue's real filtering, promotion, parsing and scope-aware Chat rules.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { AgentCatalogBadges, AgentChatLink } from '../application/v2_ui/src/components/agentsCatalog/AgentCatalogParts';
import {
    CATALOG_VIEW_STORAGE_KEY, DEFAULT_CATALOG_PAGE, agentLinkScope, catalogAgentKey, catalogAgentTypeLabel,
    catalogDisplayName, catalogHeroColor, catalogScopeLabel, catalogUsageCount, normalizePromotionWindow,
    parseCatalogViewMode, popularAgents, promotedBadgeLabel, readAgentsCatalog, tagsFor, visibleAgents,
    type CatalogAgent, type CatalogTab, type CatalogUsageWindow,
} from '../application/v2_ui/src/lib/agentCatalog';
import { chatHrefForAgent } from '../application/v2_ui/src/lib/conversationUrl';

const checks: [string, () => void][] = [];
function check(name: string, run: () => void) {
    checks.push([name, run]);
}

function agent(id: string, extra: Partial<CatalogAgent> = {}): CatalogAgent {
    return {
        id, name: id, display_name: id, scope_type: 'personal', catalog_key: `personal:${id}`,
        usage_count_all_time: 0, usage_count_30_days: 0, ...extra,
    };
}

function ids(agents: CatalogAgent[]): string[] {
    return agents.map((item) => item.id ?? '');
}

function visible(agents: CatalogAgent[], extra: {
    tab?: CatalogTab; window?: CatalogUsageWindow; query?: string; tags?: string[];
} = {}): CatalogAgent[] {
    return visibleAgents({ agents, tab: 'popular', window: 'all_time', query: '', tags: [], ...extra });
}

check('payload parsing normalizes display config and skips non-records', () => {
    const parsed = readAgentsCatalog({
        page: { title: '  Find   partners ', hero_color_mode: 'bad', hero_primary_color: 'url(evil)' },
        agents: [null, 42, [], { id: 'real', tags: ['Finance', 42], icon: { kind: 'html', value: '<script>' } }],
    });
    assert.equal(parsed.page.title, 'Find partners');
    assert.equal(parsed.page.subtitle, DEFAULT_CATALOG_PAGE.subtitle);
    assert.equal(parsed.page.hero_color_mode, 'single');
    assert.equal(parsed.page.hero_primary_color, DEFAULT_CATALOG_PAGE.hero_primary_color);
    assert.deepEqual(ids(parsed.agents), ['real']);
    assert.deepEqual(parsed.agents[0].tags, ['Finance']);
    assert.equal(parsed.agents[0].icon, undefined);
});

check('a malformed response fails instead of looking like an empty catalogue', () => {
    for (const payload of [null, [], {}, { page: {}, agents: {} }, { agents: [] }]) {
        assert.throws(() => readAgentsCatalog(payload), /Invalid agent catalogue response/);
    }
    assert.deepEqual(readAgentsCatalog({ page: {}, agents: [] }).agents, []);
});

check('instructions are suppressed when the details setting is off', () => {
    const record = { id: 'real', instructions: 'Do not publish this.', model_id: 'internal', secret: 'private' };
    const hidden = readAgentsCatalog({ page: { show_instructions_in_details: false }, agents: [record] });
    assert.equal(hidden.agents[0].instructions, undefined);
    assert.equal(hidden.page.show_instructions_in_details, false);
    assert.ok(!JSON.stringify(hidden).includes('Do not publish'));
    assert.ok(!JSON.stringify(hidden).includes('internal'));
    assert.ok(!JSON.stringify(hidden).includes('private'));
    const shown = readAgentsCatalog({ page: {}, agents: [record] });
    assert.equal(shown.agents[0].instructions, record.instructions);
});

check('an empty action-label list does not fall back to internal action names', () => {
    const parsed = readAgentsCatalog({
        page: {}, agents: [{ action_labels: [], actions_to_load: ['internal-name'] }, { actions_to_load: ['visible-name'] }],
    });
    assert.deepEqual(parsed.agents[0].action_labels ?? parsed.agents[0].actions_to_load, []);
    assert.deepEqual(parsed.agents[1].action_labels ?? parsed.agents[1].actions_to_load, ['visible-name']);
});

check('scope labels follow the catalogue and shared scope classifier', () => {
    assert.equal(catalogScopeLabel(agent('p')), 'Personal');
    assert.equal(catalogScopeLabel(agent('g', { scope_type: ' ENTERPRISE ' })), 'Enterprise');
    assert.equal(catalogScopeLabel(agent('g', { is_global: true })), 'Enterprise');
    assert.equal(catalogScopeLabel(agent('g', { is_group: true, group_name: ' Research ', scope_name: 'Old' })), 'Research');
    assert.equal(catalogScopeLabel(agent('g', { scope_type: 'group', scope_name: 'Fallback' })), 'Fallback');
    assert.equal(catalogScopeLabel(agent('g', { scope_type: 'group' })), 'Group');
});

check('names and agent types have usable fallbacks', () => {
    assert.equal(catalogDisplayName({ name: '  Generated   name ' }), 'Generated name');
    assert.equal(catalogDisplayName({ display_name: ' ', name: '' }), 'Unnamed Agent');
    assert.equal(catalogAgentTypeLabel({ agent_type: 'aifoundry' }), 'Azure AI Foundry');
    assert.equal(catalogAgentTypeLabel({ agent_type: 'foundry_workflow' }), 'Foundry Workflow');
    assert.equal(catalogAgentTypeLabel({}), 'Local');
    assert.equal(catalogAgentTypeLabel({ agent_type: 'Future type' }), 'Future type');
});

check('usage selects the requested window, with finite fallback counts', () => {
    const item = agent('p', { usage_count: 8, usage_count_all_time: 20, usage_count_30_days: '3' });
    assert.equal(catalogUsageCount(item, 'all_time'), 20);
    assert.equal(catalogUsageCount(item, '30_days'), 3);
    assert.equal(catalogUsageCount({ usage_count: 8 }, '30_days'), 8);
    assert.equal(catalogUsageCount({ usage_count_30_days: null, usage_count: 8 }, '30_days'), 8);
    for (const count of [Infinity, NaN, 'not a number']) {
        assert.equal(catalogUsageCount({ usage_count_all_time: count }, 'all_time'), 0);
    }
});

check('promotion-window aliases match classic behavior', () => {
    for (const value of ['all', 'alltime', 'ALL-TIME', 'all_time']) assert.equal(normalizePromotionWindow(value), 'all_time');
    for (const value of ['30', 'last30', 'last_30_days', '30-DAYS']) assert.equal(normalizePromotionWindow(value), '30_days');
    for (const value of ['both', '', 'invalid', null]) assert.equal(normalizePromotionWindow(value), 'both');
});

check('promotion badges respect the display flag and forty-character limit', () => {
    assert.equal(promotedBadgeLabel(agent('p')), '');
    assert.equal(promotedBadgeLabel(agent('p', { is_promoted_popular: true })), 'Promoted');
    assert.equal(promotedBadgeLabel(agent('p', { is_promoted_popular: true, promoted_popular_tag_enabled: false })), '');
    assert.equal(promotedBadgeLabel(agent('p', { is_promoted_popular: true, promoted_popular_tag_label: '  Featured  agent ' })), 'Featured agent');
    assert.equal(promotedBadgeLabel(agent('p', { is_promoted_popular: true, promoted_popular_tag_label: 'A'.repeat(100) })).length, 40);
});

check('Popular keeps all promotions plus twelve usage-ranked agents', () => {
    const promoted = [
        agent('Zulu', { is_promoted_popular: true, promoted_popular_rank: 1 }),
        agent('alpha', { is_promoted_popular: true, promoted_popular_rank: 1 }),
        agent('first', { is_promoted_popular: true, promoted_popular_rank: 0 }),
    ];
    const used = Array.from({ length: 15 }, (_, i) => agent(`used-${i}`, { usage_count_all_time: 100 - i }));
    const result = popularAgents([...used, ...promoted], 'all_time');
    assert.equal(result.length, 15);
    assert.deepEqual(ids(result).slice(0, 3), ['first', 'alpha', 'Zulu']);
    assert.deepEqual(ids(result).slice(3), ids(used).slice(0, 12));
});

check('after placement moves promotions behind usage-ranked agents', () => {
    const promoted = agent('featured', { is_promoted_popular: true, promoted_popular_rank: 0, promoted_popular_order: 'after' });
    const used = agent('used', { usage_count_all_time: 5 });
    assert.deepEqual(ids(popularAgents([promoted, used], 'all_time')), ['used', 'featured']);
});

check('mixed placement ranks by usage, promotion rank, then name', () => {
    const items = [
        agent('featured', { is_promoted_popular: true, promoted_popular_order: 'mixed', promoted_popular_rank: 0, usage_count_all_time: 4 }),
        agent('Zulu', { usage_count_all_time: 4 }),
        agent('alpha', { usage_count_all_time: 4 }),
        agent('most-used', { usage_count_all_time: 20 }),
    ];
    assert.deepEqual(ids(popularAgents(items, 'all_time')), ['most-used', 'featured', 'alpha', 'Zulu']);
});

check('Popular switches usage and window-specific promotions together', () => {
    const items = [
        agent('all-featured', { is_promoted_popular: true, promoted_popular_window: 'all_time', promoted_popular_rank: 0 }),
        agent('recent-featured', { is_promoted_popular: true, promoted_popular_window: '30_days', promoted_popular_rank: 0 }),
        agent('all-used', { usage_count_all_time: 20, usage_count_30_days: 1 }),
        agent('recent-used', { usage_count_all_time: 10, usage_count_30_days: 5 }),
    ];
    assert.deepEqual(ids(popularAgents(items, 'all_time')), ['all-featured', 'all-used', 'recent-used']);
    assert.deepEqual(ids(popularAgents(items, '30_days')), ['recent-featured', 'recent-used', 'all-used']);
});

check('deduplication uses the catalogue key without merging agents in different groups', () => {
    const first = agent('shared', { scope_type: 'group', catalog_key: 'group:g1:shared', usage_count_all_time: 2 });
    const second = agent('shared', { scope_type: 'group', catalog_key: 'group:g2:shared', usage_count_all_time: 1 });
    assert.equal(popularAgents([first, first, second], 'all_time').length, 2);
    assert.equal(catalogAgentKey({ id: 'id' }), 'id');
    assert.equal(catalogAgentKey({ display_name: 'Name' }), 'Name');
});

check('unused unpromoted agents are absent from Popular, but still in their scope', () => {
    const items = [agent('unused'), agent('featured', { is_promoted_popular: true })];
    assert.deepEqual(ids(visible(items)), ['featured']);
    assert.deepEqual(ids(visible(items, { tab: 'personal' })), ['featured', 'unused']);
});

check('search spans every scope and every catalogue search field', () => {
    const item = agent('g', {
        scope_type: 'group', display_name: 'Research helper', name: 'generated-research', description: 'Compliance    review',
        group_name: 'Product Research', model_label: 'Special GPT', tags: ['Finance'],
    });
    for (const query of ['RESEARCH helper', 'generated-research', ' compliance   review ', 'product research', 'special GPT', 'finance']) {
        assert.deepEqual(ids(visible([item], { tab: 'personal', query })), ['g'], query);
    }
});

check('search does not disclose instructions or internal action identifiers', () => {
    const item = agent('g', { instructions: 'private-instructions', actions_to_load: ['internal-action'] });
    assert.deepEqual(visible([item], { query: 'private-instructions' }), []);
    assert.deepEqual(visible([item], { query: 'internal-action' }), []);
});

check('scope results sort alphabetically and treat whitespace-only search as cleared', () => {
    const items = [
        agent('Zulu'), agent('alpha'), agent('group', { scope_type: 'group' }), agent('enterprise', { is_global: true }),
    ];
    assert.deepEqual(ids(visible(items, { tab: 'personal', query: '   ' })), ['alpha', 'Zulu']);
    assert.deepEqual(ids(visible(items, { tab: 'enterprise' })), ['enterprise']);
    assert.deepEqual(ids(visible(items, { tab: 'group' })), ['group']);
});

check('tags are case-insensitive AND filters, including during cross-scope search', () => {
    const items = [
        agent('both', { tags: [' Finance ', 'Review'], usage_count_all_time: 3 }),
        agent('one', { tags: ['Finance'], usage_count_all_time: 4 }),
        agent('group', { scope_type: 'group', tags: ['FINANCE', 'review'], usage_count_all_time: 1 }),
    ];
    assert.deepEqual(ids(visible(items, { tags: ['finance', 'REVIEW'] })), ['both', 'group']);
    assert.deepEqual(ids(visible(items, { tab: 'personal', query: 'finance', tags: ['review'] })), ['both', 'group']);
});

check('tag filtering preserves Popular order while search uses alphabetical order', () => {
    const items = [agent('Zulu', { usage_count_all_time: 5, tags: ['same'] }), agent('alpha', { usage_count_all_time: 2, tags: ['same'] })];
    assert.deepEqual(ids(visible(items, { tags: ['same'] })), ['Zulu', 'alpha']);
    assert.deepEqual(ids(visible(items, { tags: ['same'], query: 'same' })), ['alpha', 'Zulu']);
});

check('tag choices normalize whitespace, deduplicate case and sort for scanning', () => {
    assert.deepEqual(tagsFor([
        agent('p', { tags: [' Finance ', 'Review', '', '  '] }), agent('g', { tags: ['finance', 'Analytics'] }),
    ]), ['Analytics', 'Finance', 'Review']);
});

check('Chat links name the agent own scope and group, never an active-group fallback', () => {
    assert.deepEqual(agentLinkScope(agent('p')), { kind: 'personal' });
    assert.deepEqual(agentLinkScope(agent('e', { is_global: true })), { kind: 'global' });
    assert.deepEqual(agentLinkScope(agent('g', { scope_type: 'group', group_id: 'research', scope_id: 'operations' })), { kind: 'group', id: 'research' });
    assert.deepEqual(agentLinkScope(agent('g', { scope_type: 'group', scope_id: 'research' })), { kind: 'group', id: 'research' });
    assert.equal(agentLinkScope({ id: '' }), null);
    assert.equal(agentLinkScope(agent('g', { scope_type: 'group' })), null);
});

check('Chat URL builders encode identifiers and always ask for a new chat', () => {
    const href = chatHrefForAgent('agent & query', { kind: 'group', id: 'group & name' });
    const params = new URL(href, 'http://simplechat.test').searchParams;
    assert.equal(params.get('agent_id'), 'agent & query');
    assert.equal(params.get('agent_scope'), 'group');
    assert.equal(params.get('agent_scope_id'), 'group & name');
    assert.equal(params.get('new'), '1');
});

check('Chat controls are native links or an explicitly disabled malformed record', () => {
    const render = (item: CatalogAgent) => renderToStaticMarkup(createElement(
        MemoryRouter, {}, createElement(AgentChatLink, { agent: item }),
    ));
    assert.match(render(agent('p')), /href="\/chat\?agent_id=p&amp;agent_scope=personal&amp;new=1"/);
    assert.match(render(agent('g', { scope_type: 'group', group_id: 'own-group' })), /agent_scope_id=own-group/);
    assert.match(render(agent('bad', { scope_type: 'group' })), /disabled=""/);
    assert.doesNotMatch(render(agent('bad', { scope_type: 'group' })), /href=/);
});

check('display names and badge labels stay text, not executable markup', () => {
    const html = renderToStaticMarkup(createElement(AgentCatalogBadges, {
        agent: agent('p', { scope_type: 'group', group_name: '<img onerror=evil()>', is_promoted_popular: true, promoted_popular_tag_label: '<script>evil()</script>' }),
    }));
    assert.ok(html.includes('&lt;img'));
    assert.ok(html.includes('&lt;script&gt;'));
    assert.doesNotMatch(html, /<img|<script/);
});

check('hero colours accept only full hexadecimal values', () => {
    assert.equal(catalogHeroColor(' #AAbB22 ', '#0f172a'), '#AAbB22');
    for (const value of ['#fff', 'red', 'url(https://evil.test)', '#000000;display:none', null]) {
        assert.equal(catalogHeroColor(value, '#0f172a'), '#0f172a');
    }
});

check('view parsing uses the classic storage key and only accepts list or card', () => {
    assert.equal(CATALOG_VIEW_STORAGE_KEY, 'simplechat-agents-catalog-view');
    assert.equal(parseCatalogViewMode('card'), 'card');
    for (const value of ['list', '', 'grid', null, 42]) assert.equal(parseCatalogViewMode(value), 'list');
});

check('filtering and ranking never reorder or mutate the API records', () => {
    const items = [agent('Zulu', { usage_count_all_time: 10 }), agent('alpha', { is_promoted_popular: true })];
    const before = JSON.stringify(items);
    popularAgents(items, 'all_time');
    visible(items, { tab: 'personal' });
    tagsFor(items);
    assert.equal(JSON.stringify(items), before);
});

let failed = 0;
for (const [name, run] of checks) {
    try {
        run();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`  FAIL  ${name}`, error);
    }
}
console.log(`Results: ${checks.length - failed}/${checks.length} catalogue checks passed`);
process.exitCode = failed ? 1 : 0;
