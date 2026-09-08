// test_v2_workspace_agent_authoring_logic.mjs
// Version: 0.261.102
// Implemented in: 0.261.096
// Executes native agent draft, model, action, knowledge, template, and command behavior.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    newAgentDraft, renameAgentDraft, updateAgentSetting, parseAgentSettings, changeAgentType, clearAgentDraftFields,
    agentModelChoices, selectedAgentModel, selectAgentModel, foundryEndpointMatches,
    selectFoundryEndpoint, applyFoundryDiscovery, agentValidationErrors, agentForSave,
    secretValueAt, setAgentSecret, secretIntent, isAgentIconImage, isAgentEditorEnvelope,
    agentStoredArrayEditError, applySafeAgentDraft,
} = await import('../application/v2_ui/src/lib/workspaceAgentAuthoring.ts');
const {
    readAgentKnowledge, updateAgentKnowledge, toggleAgentKnowledgeSource, selectedKnowledgeSources,
    resolvedAgentDocuments, agentKnowledgeReference, normalizeAgentKnowledgeUrl, agentKnowledgeErrors,
    fetchAgentKnowledgeCatalog,
} = await import('../application/v2_ui/src/lib/workspaceAgentKnowledge.ts');
const {
    AGENT_ACTION_CAPABILITIES, resolveAgentAction, toggleAgentAction, agentHasAction,
    agentActionUnavailableReason, agentActionCapabilities, updateAgentCapability, agentSelectedActionsContext, newAgentActionErrors,
} = await import('../application/v2_ui/src/lib/workspaceAgentActions.ts');
const {
    agentActionToken, agentKnowledgeToken, agentMentionTrigger, agentMentions, filterAgentMentions,
} = await import('../application/v2_ui/src/lib/workspaceAgentReferences.ts');
const {
    safeAgentTemplateSettings, agentDraftFromTemplate, agentTemplateSubmission, fetchAgentTemplates,
} = await import('../application/v2_ui/src/lib/workspaceAgentTemplates.ts');
const {
    agentInstructionRequest, draftAgentInstructions, withAgentInstructionProposal, discoverAgentFoundryResources,
} = await import('../application/v2_ui/src/lib/workspaceAgentCommands.ts');
const { buildEditorWrite, EDITOR_SECRET_MASK, sameEditorValue } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const { saveAgentConfiguration } = await import('../application/v2_ui/src/lib/workspaceAuthoringApi.ts');

const options = {
    agent_types: ['local', 'aifoundry', 'new_foundry', 'foundry_workflow'].map((value) => ({ value, label: value, enabled: true })),
    settings: { allow_user_custom_endpoints: true },
    model_endpoints: [], builtin_actions: [],
};
const originalDraft = {
    ...newAgentDraft(),
    id: 'agent-one', user_id: 'owner', name: 'unchanged-name', display_name: 'Reviewer',
    description: 'Reviews documents.', instructions: 'Quote the evidence.',
    azure_openai_gpt_key: EDITOR_SECRET_MASK,
    actions_to_load: ['ordinary', 'call-agent', 'legacy-action'],
    other_settings: {
        custom: { retained: 42 }, action_capabilities: { ordinary: { read: true, unknown: false } },
        assigned_knowledge: {
            enabled: true, scopes: { personal: true, group_ids: [], public_workspace_ids: ['public-one', 'unavailable-public'] },
            document_ids: ['explicit', 'unavailable-document'], tags: ['policy', 'approved'],
            web_sources: [{ url: 'https://example.org/source', mode: 'url_review' }],
            allow_user_workspace_context: true, allowed_user_workspace_actions: [],
            future_option: { keep: false },
        },
    },
};
const original = { record: originalDraft, revision: 'one', secret_paths: ['/azure_openai_gpt_key'], read_only: false };
const action = (id, type, extra = {}) => ({
    id, type, name: id, displayName: id, description: '', endpoint: '', auth: { type: 'user' },
    additionalFields: {}, metadata: {}, ...extra,
});
const ordinary = action('ordinary', 'http');
const call = action('call-agent', 'agent', {
    additionalFields: { target_agent: { id: 'target', scope_type: 'personal', scope_id: 'owner' } },
});
const actions = [ordinary, call];
const catalog = {
    sources: [
        { scope: 'personal', id: 'personal', label: 'Personal workspace' },
        { scope: 'public', id: 'public-one', label: 'Policies' },
    ],
    documents: [
        { id: 'explicit', title: 'Explicit.pdf', file_name: 'Explicit.pdf', scope: 'personal', source_id: 'personal', source_name: 'Personal workspace', tags: [] },
        { id: 'all-tags', title: 'Handbook.pdf', file_name: 'Handbook.pdf', scope: 'public', source_id: 'public-one', source_name: 'Policies', tags: ['policy', 'approved'] },
        { id: 'one-tag', title: 'Draft.pdf', file_name: 'Draft.pdf', scope: 'public', source_id: 'public-one', source_name: 'Policies', tags: ['policy'] },
        { id: 'other-source', title: 'Other.pdf', file_name: 'Other.pdf', scope: 'public', source_id: 'unselected', source_name: 'Other', tags: ['policy', 'approved'] },
    ],
    tags: [{ name: 'policy', count: 3 }, { name: 'approved', count: 2 }],
};

let checks = 0;
async function check(label, run) {
    await run();
    checks += 1;
    console.log(`ok ${label}`);
}

await check('read-only detail envelopes need no revision while writable records require one', () => {
    assert.ok(isAgentEditorEnvelope({ ...original, read_only: true, revision: '' }));
    assert.ok(isAgentEditorEnvelope({ record: originalDraft, read_only: true, secret_paths: [] }));
    assert.ok(isAgentEditorEnvelope(original));
    for (const revision of ['', ' ', undefined, null, 0]) {
        assert.equal(isAgentEditorEnvelope({ ...original, revision }), false);
    }
    assert.equal(isAgentEditorEnvelope({ ...original, read_only: 'true', revision: '' }), false);
});
await check('read-only permission does not bypass record and secret-path shape checks', () => {
    const resource = { ...original, read_only: true, revision: '' };
    for (const record of [null, undefined, [], 'invalid']) assert.equal(isAgentEditorEnvelope({ ...resource, record }), false);
    for (const secret_paths of [null, undefined, {}, 'invalid', [42]]) assert.equal(isAgentEditorEnvelope({ ...resource, secret_paths }), false);
});

await check('new drafts use the schema sentinel and existing internal names do not change with display names', () => {
    assert.equal(newAgentDraft().max_completion_tokens, -1);
    const created = renameAgentDraft(newAgentDraft(), 'Contract reviewer', true);
    assert.equal(created.name, 'Contract-reviewer');
    assert.equal(renameAgentDraft(originalDraft, 'Renamed', false).name, 'unchanged-name');
    assert.equal(renameAgentDraft({ ...created, name: 'explicit-name' }, 'Other', true).name, 'explicit-name');
});
await check('all four types preserve incompatible settings until an explicit action', () => {
    for (const type of options.agent_types.map((item) => item.value)) {
        const changed = changeAgentType(originalDraft, type);
        assert.equal(changed.agent_type, type);
        assert.deepEqual(changed.other_settings, originalDraft.other_settings);
        assert.deepEqual(changed.actions_to_load, originalDraft.actions_to_load);
        assert.equal(changed.azure_openai_gpt_key, EDITOR_SECRET_MASK);
        if (type !== 'local') assert.match(agentValidationErrors(changed, options).join(' '), /Explicitly detach local actions/);
    }
});
await check('structured edits and pasted JSON retain managed sibling settings, false and empty arrays', () => {
    const next = updateAgentSetting(originalDraft, 'custom', { added: 0 });
    assert.deepEqual(next.other_settings.custom, { retained: 42, added: 0 });
    const parsed = parseAgentSettings('{"custom":{"replacement":true},"assigned_knowledge":{"enabled":false,"scopes":{"personal":false},"allowed_user_workspace_actions":[]}}', originalDraft.other_settings);
    assert.equal(parsed.assigned_knowledge.scopes.personal, false);
    assert.deepEqual(parsed.assigned_knowledge.scopes.public_workspace_ids, ['public-one', 'unavailable-public']);
    assert.deepEqual(parsed.assigned_knowledge.allowed_user_workspace_actions, []);
    assert.deepEqual(parsed.action_capabilities, originalDraft.other_settings.action_capabilities);
    assert.equal(parsed.assigned_knowledge.future_option.keep, false);
    assert.throws(() => parseAgentSettings('[]', originalDraft.other_settings), /JSON object/);
    assert.throws(() => parseAgentSettings('{', originalDraft.other_settings), SyntaxError);
});
await check('ending an untouched advanced edit does not create phantom dirty metadata', () => {
    assert.ok(sameEditorValue(clearAgentDraftFields(originalDraft, '_editor_settings_text'), originalDraft));
    assert.ok(sameEditorValue(updateAgentSetting(originalDraft, 'custom', { retained: 42 }), originalDraft));
    const raw = { ...originalDraft, _editor_settings_text: JSON.stringify(originalDraft.other_settings) };
    assert.ok(sameEditorValue(clearAgentDraftFields(raw, '_editor_settings_text'), originalDraft));
});
await check('duplicate model IDs remain bound to their endpoint identity and preserve credentials', () => {
    const endpoints = ['east', 'west'].map((id) => ({
        id, provider: 'aoai', name: id, models: [{ id: 'same-model', deploymentName: `${id}-deployment`, modelName: 'gpt-5' }],
    }));
    const choices = agentModelChoices({ ...options, model_endpoints: endpoints });
    assert.notEqual(choices[0].key, choices[1].key);
    const next = selectAgentModel(originalDraft, choices[1]);
    assert.equal(next.model_endpoint_id, 'west');
    assert.equal(next.model_id, 'same-model');
    assert.equal(next.model_provider, 'aoai');
    assert.equal(next.azure_openai_gpt_deployment, 'west-deployment');
    assert.equal(next.azure_openai_gpt_key, EDITOR_SECRET_MASK);
    assert.equal(selectedAgentModel(next, choices).endpointId, 'west');
});
await check('disabled model choices are excluded and legacy APIM fields stay separate', () => {
    const disabled = agentModelChoices({ ...options, model_endpoints: [{ id: 'off', enabled: false, models: [{ id: 'hidden' }] }] });
    assert.deepEqual(disabled, []);
    const choices = agentModelChoices({ ...options, settings: { enable_gpt_apim: true, azure_apim_gpt_deployment: 'one, two' } });
    const next = selectAgentModel(originalDraft, choices[1]);
    assert.equal(next.azure_agent_apim_gpt_deployment, 'two');
    assert.equal(next.enable_agent_gpt_apim, true);
    const legacy = agentModelChoices({ ...options, settings: { gpt_model: { selected: [{ deploymentName: 'chat', modelName: 'gpt-4o' }] } } });
    assert.equal(legacy[0].deployment, 'chat');
});
await check('chat model choices use server capability availability without mutating connections', () => {
    const endpoints = [{
        id: 'mixed', provider: 'new_foundry', models: [
            { id: 'chat', capability_status: { chat: { available: true } } },
            { id: 'unknown-legacy-chat' },
            { id: 'image', capability_status: { chat: { available: false } } },
            { id: 'imported', enabled_capabilities: ['image_generation'] },
            { id: 'disabled', enabled: false },
            { id: 'text-disabled', supportsChat: false },
        ],
    }];
    const original = structuredClone(endpoints);
    assert.deepEqual(agentModelChoices({ ...options, model_endpoints: endpoints }).map((choice) => choice.id),
        ['chat', 'unknown-legacy-chat']);
    assert.deepEqual(endpoints, original);
});
await check('Foundry project choices do not force legacy chat into multi-endpoint mode', () => {
    const project = { id: 'project', provider: 'new_foundry', models: [] };
    const legacySettings = { gpt_model: { selected: [{ deploymentName: 'legacy-chat' }] } };
    const source = { ...options, model_endpoints: [project], settings: legacySettings };
    assert.ok(foundryEndpointMatches('new_foundry', project));
    assert.equal(agentModelChoices(source)[0].deployment, 'legacy-chat');
    assert.deepEqual(agentModelChoices({
        ...source, settings: { ...legacySettings, enable_multi_model_endpoints: true },
    }), []);
});
await check('Foundry types accept their scoped providers and synchronize endpoint fields without dropping siblings', () => {
    const endpoint = { id: 'foundry', provider: 'new_foundry', scope: 'personal', connection: {
        endpoint: 'https://example.org/api/projects/review', project_name: 'review', openai_api_version: '2025-01-01-preview',
    } };
    assert.ok(foundryEndpointMatches('foundry_workflow', endpoint));
    assert.ok(!foundryEndpointMatches('aifoundry', endpoint));
    const start = {
        ...originalDraft, agent_type: 'new_foundry',
        other_settings: { ...originalDraft.other_settings, new_foundry: { endpoint: 'old', notes: 'keep', application_id: 'saved-app' } },
    };
    const next = selectFoundryEndpoint(start, endpoint);
    assert.equal(next.other_settings.new_foundry.endpoint, endpoint.connection.endpoint);
    assert.equal(next.other_settings.new_foundry.responses_api_version, '2025-01-01-preview');
    assert.equal(next.other_settings.new_foundry.notes, 'keep');
    assert.equal(next.other_settings.new_foundry.application_id, 'saved-app');
    assert.equal(next.other_settings.new_foundry.authentication_type, 'delegated_user');
    assert.deepEqual(next.actions_to_load, start.actions_to_load);
});
await check('discovered workflow reference retains full identity and additional reference attributes', () => {
    const next = applyFoundryDiscovery({ ...originalDraft, agent_type: 'foundry_workflow' }, {
        workflow_name: 'Review workflow', workflow_agent_id: 'workflow-id',
        application_id: 'review:1', application_version: '1',
        agent_reference: { type: 'agent_reference', future_attribute: 'keep' },
        responses_api_version: 'v1',
    });
    assert.deepEqual(next.other_settings.foundry_workflow.agent_reference, {
        type: 'agent_reference', future_attribute: 'keep', name: 'Review workflow', id: 'workflow-id',
        application_id: 'review:1', application_version: '1',
    });
    assert.equal(next.azure_openai_gpt_api_version, 'v1');
    assert.deepEqual(next.other_settings.custom, originalDraft.other_settings.custom);
});
await check('all four type drafts validate with canonical required fields and gates remain authoritative', () => {
    for (const type of options.agent_types.map((item) => item.value)) {
        const key = type === 'aifoundry' ? 'azure_ai_foundry' : type;
        const settings = type === 'aifoundry' ? { agent_id: 'remote' }
            : type === 'new_foundry' ? { application_id: 'app:1', responses_api_version: 'v1' }
            : { workflow_name: 'workflow', responses_api_version: 'v1' };
        const next = {
            ...originalDraft, agent_type: type, actions_to_load: [],
            azure_openai_gpt_endpoint: 'https://example.org/project', azure_openai_gpt_api_version: 'v1',
            other_settings: type === 'local' ? {} : { [key]: settings },
        };
        assert.deepEqual(agentValidationErrors(next, options), [], type);
        const gated = { ...options, agent_types: options.agent_types.map((item) => ({ ...item, enabled: false })) };
        assert.match(agentValidationErrors(next, gated).join(' '), /not available/);
    }
    assert.equal(agentForSave({ ...originalDraft, agent_type: 'new_foundry', instructions: '' }).instructions,
        'Placeholder instructions: Azure AI Foundry agent manages its own prompt.');
    assert.equal(agentForSave({ ...originalDraft, agent_type: 'new_foundry' }).instructions, originalDraft.instructions);
});
await check('completion token zero is intentional and limits are validated', () => {
    assert.deepEqual(agentValidationErrors({ ...originalDraft, max_completion_tokens: 0 }, options), []);
    assert.match(agentValidationErrors({ ...originalDraft, max_completion_tokens: -2 }, options).join(' '), /Completion token limit/);
    assert.equal(buildEditorWrite({ ...originalDraft, max_completion_tokens: 0 }, original).updates.max_completion_tokens, 0);
});
await check('ordinary and Call agent actions share assignment logic without dropping legacy references', () => {
    const removed = toggleAgentAction(originalDraft, call, false, actions);
    assert.deepEqual(removed.actions_to_load, ['ordinary', 'legacy-action']);
    const readded = toggleAgentAction(removed, call, true, actions);
    assert.ok(agentHasAction(readded, call, actions));
    assert.deepEqual(readded.actions_to_load, ['ordinary', 'legacy-action', 'call-agent']);
    assert.equal(resolveAgentAction('duplicate', [action('one', 'http', { name: 'duplicate' }), action('two', 'agent', { name: 'duplicate' })]), undefined);
    assert.deepEqual(removed.other_settings, originalDraft.other_settings);
});
await check('self-calls compare the full scope identity and unavailable targets remain explicit', () => {
    const self = action('self', 'agent', { additionalFields: { target_agent: { id: originalDraft.id, scope_type: 'personal', scope_id: 'owner' } } });
    const targets = { targets: [{ id: 'target', scope_type: 'personal', scope_id: 'owner' }], scope_type: 'personal', scope_id: 'owner', can_manage: true };
    assert.match(agentActionUnavailableReason(originalDraft, self, targets, 'owner'), /self-calls/);
    assert.equal(agentActionUnavailableReason(originalDraft, call, targets, 'owner'), null);
    assert.match(agentActionUnavailableReason(originalDraft, call, { ...targets, targets: [] }, 'owner'), /no longer available/);
    assert.equal(agentActionUnavailableReason(originalDraft, ordinary, null, 'owner'), null);
    const globalTarget = { ...self, additionalFields: { target_agent: { id: originalDraft.id, scope_type: 'global', scope_id: 'global' } } };
    assert.equal(agentActionUnavailableReason(originalDraft, globalTarget, { ...targets, targets: [globalTarget.additionalFields.target_agent] }, 'owner'), null);
});
await check('new action handoffs cannot save a self-call while unrelated unavailable references are retained', () => {
    const self = action('self', 'agent', { additionalFields: { target_agent: { id: originalDraft.id, scope_type: 'personal', scope_id: 'owner' } } });
    const draft = { ...originalDraft, actions_to_load: [...originalDraft.actions_to_load, 'self'] };
    assert.match(newAgentActionErrors(draft, originalDraft, [...actions, self], null, 'owner').join(' '), /self-calls/);
    assert.deepEqual(newAgentActionErrors(draft, draft, [...actions, self], null, 'owner'), []);
    assert.deepEqual(newAgentActionErrors({ ...newAgentDraft(), actions_to_load: ['template-reference'] }, null, [], null, 'owner'), []);
});
await check('server-disabled personal Call agent attachment does not block provided calls or unchanged bindings', () => {
    const globalTarget = { id: 'global-target', scope_type: 'global', scope_id: 'global' };
    const providedCall = {
        ...call, id: 'provided-call', name: 'provided-call', is_global: true,
        additionalFields: { target_agent: globalTarget },
    };
    const targets = {
        targets: [call.additionalFields.target_agent, globalTarget],
        scope_type: 'personal', scope_id: 'owner', can_manage: false,
    };
    assert.match(agentActionUnavailableReason(originalDraft, call, targets, 'owner'), /New personal Call agent attachments/);
    assert.equal(agentActionUnavailableReason(originalDraft, providedCall, targets, 'owner'), null);
    assert.equal(agentActionUnavailableReason(originalDraft, ordinary, targets, 'owner'), null);
    assert.deepEqual(newAgentActionErrors(originalDraft, originalDraft, actions, targets, 'owner'), []);
    assert.match(newAgentActionErrors(originalDraft, { ...originalDraft, actions_to_load: [] }, actions, targets, 'owner').join(' '), /New personal Call agent attachments/);
    assert.equal(agentActionUnavailableReason(originalDraft, call, { ...targets, can_manage: true }, 'owner'), null);
});
await check('all capability families preserve inherited upload behavior and unknown overrides', () => {
    assert.equal(AGENT_ACTION_CAPABILITIES.simplechat.length, 13);
    assert.equal(AGENT_ACTION_CAPABILITIES.msgraph.length, 11);
    assert.equal(AGENT_ACTION_CAPABILITIES.chart.length, 10);
    const simplechat = action('simple', 'simplechat', { additionalFields: { simplechat_capabilities: { upload_markdown_document: false } } });
    const values = agentActionCapabilities(originalDraft, simplechat);
    assert.equal(values.upload_word_document, false);
    assert.equal(values.upload_powerpoint_document, false);
    assert.equal(values.raise_workflow_alert, false);
    const start = { ...originalDraft, other_settings: { ...originalDraft.other_settings, action_capabilities: { simple: { future: 'keep' }, untouched: { custom: true } } } };
    const next = updateAgentCapability(start, simplechat, 'create_group', false);
    assert.equal(next.other_settings.action_capabilities.simple.create_group, false);
    assert.equal(next.other_settings.action_capabilities.simple.future, 'keep');
    assert.deepEqual(next.other_settings.action_capabilities.untouched, { custom: true });
    assert.deepEqual(next.other_settings.assigned_knowledge, start.other_settings.assigned_knowledge);
});
await check('knowledge preview uses explicit documents OR all tags within selected sources', () => {
    const config = readAgentKnowledge(originalDraft);
    assert.deepEqual(resolvedAgentDocuments(config, catalog).map((document) => document.id), ['explicit', 'all-tags']);
    assert.deepEqual(resolvedAgentDocuments({ ...config, document_ids: [], tags: [] }, catalog).map((document) => document.id), ['explicit', 'all-tags', 'one-tag']);
    assert.deepEqual(resolvedAgentDocuments({ ...config, enabled: false }, catalog), []);
});
await check('knowledge toggles retain unavailable document/source references and unknown settings', () => {
    const next = toggleAgentKnowledgeSource(originalDraft, catalog.sources[0], false);
    assert.deepEqual(readAgentKnowledge(next).document_ids, ['explicit', 'unavailable-document']);
    assert.ok(selectedKnowledgeSources(readAgentKnowledge(next)).includes('public:unavailable-public'));
    assert.equal(readAgentKnowledge(next).future_option.keep, false);
    assert.deepEqual(readAgentKnowledge(next).allowed_user_workspace_actions, []);
    assert.throws(() => toggleAgentKnowledgeSource(next, { scope: 'group', id: 'group', label: 'Group' }, true), /only authorized personal and public/);
    assert.deepEqual(readAgentKnowledge(updateAgentKnowledge(next, { enabled: false })).document_ids, ['explicit', 'unavailable-document']);
});
await check('legacy knowledge aliases display and cannot resurrect explicitly removed references', () => {
    const legacy = { ...originalDraft, other_settings: { assigned_knowledge: {
        enabled: true, personal: true, public_workspace_ids: ['legacy-public'], selected_document_ids: ['legacy-document'],
        sources: [{ scope: 'public', id: 'source-public' }, { scope: 'future', id: 'retain-future' }],
        web_sources: [{ href: 'https://example.org/page', deep_research: true, extra: false }],
    } } };
    assert.equal(readAgentKnowledge(legacy).scopes.personal, true);
    assert.deepEqual(readAgentKnowledge(legacy).scopes.public_workspace_ids, ['legacy-public', 'source-public']);
    assert.deepEqual(readAgentKnowledge(legacy).document_ids, ['legacy-document']);
    let next = updateAgentKnowledge(legacy, { document_ids: [] });
    next = toggleAgentKnowledgeSource(next, { scope: 'personal', id: 'personal', label: 'Personal' }, false);
    const config = readAgentKnowledge(next);
    assert.deepEqual(config.document_ids, []);
    assert.equal(config.scopes.personal, false);
    assert.deepEqual(config.sources, [{ scope: 'future', id: 'retain-future' }]);
    assert.deepEqual(config.scopes.public_workspace_ids, ['legacy-public', 'source-public']);
    next = updateAgentKnowledge(next, { web_sources: [{ ...config.web_sources[0], mode: 'url_review' }] });
    assert.equal(readAgentKnowledge(next).web_sources[0].mode, 'url_review');
    assert.equal(readAgentKnowledge(next).web_sources[0].extra, false);
    const write = buildEditorWrite(next, { ...original, record: legacy });
    assert.ok(write.removed_paths.includes('/other_settings/assigned_knowledge/selected_document_ids'));
    assert.ok(write.removed_paths.includes('/other_settings/assigned_knowledge/personal'));
    const pasted = parseAgentSettings('{"assigned_knowledge":{"document_ids":[],"scopes":{"personal":false}}}', legacy.other_settings);
    const pastedConfig = readAgentKnowledge({ ...legacy, other_settings: pasted });
    assert.deepEqual(pastedConfig.document_ids, []);
    assert.equal(pastedConfig.scopes.personal, false);
    assert.deepEqual(pastedConfig.scopes.public_workspace_ids, ['legacy-public', 'source-public']);
    assert.deepEqual(legacy.other_settings.assigned_knowledge.selected_document_ids, ['legacy-document']);
});
await check('assigned URL normalization, legacy mode, explicit limits and empty user actions are correct', () => {
    assert.equal(normalizeAgentKnowledgeUrl('https://example.org/page#part'), 'https://example.org/page');
    for (const url of ['javascript:alert(1)', '/relative', 'https://user:password@example.org']) assert.equal(normalizeAgentKnowledgeUrl(url), '');
    const legacy = { ...originalDraft, other_settings: { assigned_knowledge: { web_sources: { urls: ['https://example.org'], deep_research: true } } } };
    assert.equal(readAgentKnowledge(legacy).web_sources[0].mode, 'deep_research');
    assert.match(agentKnowledgeErrors(updateAgentKnowledge(originalDraft, { document_ids: Array.from({ length: 201 }, (_, index) => String(index)) })).join(' '), /200/);
    assert.deepEqual(readAgentKnowledge(originalDraft).allowed_user_workspace_actions, []);
});
await check('instruction references use the exact quoting grammar and bounded non-word trigger', () => {
    assert.equal(agentActionToken('Calendar helper', 'send_mail'), '#action:"Calendar helper":send_mail');
    assert.equal(agentKnowledgeToken('doc', 'Q3: "Review".pdf'), '#knowledge:doc:"Q3: \'Review\'.pdf"');
    assert.equal(agentKnowledgeToken('web', 'https://example.org'), '#knowledge:web:"https://example.org"');
    assert.equal(agentMentionTrigger('mid#word', 8), null);
    assert.equal(agentMentionTrigger('#old\nnext', 9), null);
    assert.equal(agentMentionTrigger(`${'x'.repeat(100000)} #action:cal`, 100012)?.query, 'action:cal');
    const mentions = agentMentions(originalDraft, actions, catalog);
    assert.ok(mentions.some((item) => item.token === '#action:call-agent'));
    assert.ok(mentions.some((item) => item.token === '#knowledge:doc:Handbook.pdf'));
    assert.ok(filterAgentMentions(mentions, 'knowledge:doc').every((item) => item.description === 'Assigned document'));
});
await check('draft requests carry action capabilities and selected knowledge without credentials', () => {
    const payload = agentInstructionRequest(originalDraft, actions, catalog);
    assert.equal(payload.agent_scope, 'user');
    assert.equal(payload.selected_actions[1].type, 'agent');
    assert.equal(payload.selected_actions[2].type, 'unavailable');
    assert.equal(payload.assigned_knowledge.documents.length, 2);
    assert.equal(payload.assigned_knowledge.documents[0].is_explicit, true);
    assert.ok(!JSON.stringify(payload).includes(EDITOR_SECRET_MASK));
    assert.deepEqual(agentSelectedActionsContext({ ...originalDraft, agent_type: 'new_foundry' }, actions), []);
    assert.equal(agentKnowledgeReference({ ...originalDraft, agent_type: 'new_foundry' }, catalog).enabled, false);
});
await check('late instruction results are proposals and cannot overwrite newer text', () => {
    const latest = { ...originalDraft, instructions: 'User edited while request was pending.' };
    const next = withAgentInstructionProposal(latest, 'Generated proposal', originalDraft.instructions);
    assert.equal(next.instructions, latest.instructions);
    assert.equal(next._editor_instruction_proposal, 'Generated proposal');
    assert.equal(next._editor_instruction_baseline, originalDraft.instructions);
    const write = buildEditorWrite(next, original);
    assert.ok(!Object.keys(write.updates).some((key) => key.startsWith('_editor')));
});
await check('template recipes strip credentials and preserve unresolved action references', () => {
    const safe = safeAgentTemplateSettings({
        custom: { password: 'synthetic', additional__Secret: 'synthetic', visible: false, zero: 0 },
        endpoint: 'https://example.org', mask: EDITOR_SECRET_MASK,
        vault: 'https://vault.example.org/secrets/credential', unsafe_url: 'https://user:password@example.org',
        assigned_knowledge: { enabled: false, scopes: { personal: false } },
    });
    assert.deepEqual(safe, { custom: { visible: false, zero: 0 }, assigned_knowledge: { enabled: false, scopes: { personal: false } } });
    const template = { id: 'template', title: 'Sample', display_name: 'Sample agent', description: 'Example', instructions: 'Do the task.',
        actions_to_load: ['ordinary', 'missing'], additional_settings: JSON.stringify({ key: 'synthetic', keep: 0 }) };
    const next = agentDraftFromTemplate(template, actions);
    assert.deepEqual(next.actions_to_load, ['ordinary', 'missing']);
    assert.deepEqual(next.other_settings, { keep: 0 });
    assert.equal(next.id, '');
    assert.equal(next.max_completion_tokens, -1);
    const payload = agentTemplateSubmission(originalDraft).template;
    assert.equal(payload.source_scope, 'personal');
    assert.equal(payload.source_agent_id, originalDraft.id);
    assert.ok(!JSON.stringify(payload).includes(EDITOR_SECRET_MASK));
    assert.throws(() => agentDraftFromTemplate({ ...template, additional_settings: '[]' }, actions), /invalid additional settings/);
});
await check('stored secret controls handle escaped pointers, array siblings, and explicit keep/replace/clear', () => {
    const source = {
        ...originalDraft, other_settings: { 'a/b~c': { token: EDITOR_SECRET_MASK }, list: [{ key: EDITOR_SECRET_MASK, keep: 1 }, { key: EDITOR_SECRET_MASK }] },
    };
    assert.equal(secretValueAt(source, '/other_settings/a~1b~0c/token'), EDITOR_SECRET_MASK);
    const next = setAgentSecret(source, '/other_settings/list/0/key', 'synthetic-replacement');
    assert.ok(Array.isArray(next.other_settings.list));
    assert.equal(next.other_settings.list[0].key, 'synthetic-replacement');
    assert.equal(next.other_settings.list[0].keep, 1);
    assert.equal(next.other_settings.list[1].key, EDITOR_SECRET_MASK);
    assert.equal(secretValueAt(source, '/other_settings/list/0/key'), EDITOR_SECRET_MASK);
    assert.equal(secretIntent(EDITOR_SECRET_MASK, EDITOR_SECRET_MASK), 'keep');
    assert.equal(secretIntent('', EDITOR_SECRET_MASK), 'clear');
    assert.equal(secretIntent(undefined, EDITOR_SECRET_MASK), 'clear');
    assert.equal(secretIntent('replacement', EDITOR_SECRET_MASK), 'replace');
    assert.deepEqual(buildEditorWrite({ ...originalDraft, azure_openai_gpt_key: '' }, original).clear_secret_paths, ['/azure_openai_gpt_key']);
    assert.ok(!JSON.stringify(buildEditorWrite(originalDraft, original).updates).includes(EDITOR_SECRET_MASK));
});
const arraySecretResource = {
    ...original,
    record: {
        ...originalDraft,
        other_settings: {
            'a/b~c': [
                { id: 'first', destination: 'first', key: EDITOR_SECRET_MASK },
                { id: 'second', destination: 'second', key: EDITOR_SECRET_MASK },
            ],
            outside: { preserved: 0 },
        },
    },
    secret_paths: ['/other_settings/a~1b~0c/0/key', '/other_settings/a~1b~0c/1/key'],
};
await check('kept array secrets permit unrelated JSON changes and explicit same-position replacement or clear', () => {
    const next = structuredClone(arraySecretResource.record);
    next.other_settings.outside.preserved = 1;
    assert.equal(agentStoredArrayEditError(next, arraySecretResource), null);
    const replaced = setAgentSecret(next, arraySecretResource.secret_paths[0], 'synthetic-replacement');
    replaced.other_settings['a/b~c'][0].destination = 'explicit-replacement-destination';
    assert.equal(agentStoredArrayEditError(replaced, arraySecretResource), null);
    const cleared = setAgentSecret(next, arraySecretResource.secret_paths[0], '');
    assert.equal(agentStoredArrayEditError(cleared, arraySecretResource), null);
    assert.deepEqual(buildEditorWrite(cleared, arraySecretResource).clear_secret_paths, [arraySecretResource.secret_paths[0]]);
});
await check('array reordering insertion removal and retained-entry identity changes cannot move hidden credentials', () => {
    const before = structuredClone(arraySecretResource);
    for (const mutate of [
        (items) => items.reverse(),
        (items) => items.splice(0, 1),
        (items) => items.push({ id: 'third', key: '' }),
        (items) => { items[0].id = 'second'; },
        (items) => { items[0].destination = 'different'; },
    ]) {
        const next = structuredClone(arraySecretResource.record);
        mutate(next.other_settings['a/b~c']);
        assert.match(agentStoredArrayEditError(next, arraySecretResource), /saved array positions/);
    }
    assert.deepEqual(arraySecretResource, before);
});
await check('trimming only trailing credential entries retains the unchanged prefix and clears removed secrets', () => {
    const next = structuredClone(arraySecretResource.record);
    next.other_settings['a/b~c'].pop();
    assert.equal(agentStoredArrayEditError(next, arraySecretResource), null);
    assert.deepEqual(buildEditorWrite(next, arraySecretResource).clear_secret_paths, [arraySecretResource.secret_paths[1]]);
    assert.deepEqual(next.other_settings['a/b~c'][0], arraySecretResource.record.other_settings['a/b~c'][0]);
});
await check('resolving every array credential permits explicit restructuring or whole-array removal', () => {
    let next = structuredClone(arraySecretResource.record);
    for (const path of arraySecretResource.secret_paths) next = setAgentSecret(next, path, '');
    next.other_settings['a/b~c'].reverse();
    assert.equal(agentStoredArrayEditError(next, arraySecretResource), null);
    assert.deepEqual(buildEditorWrite(next, arraySecretResource).clear_secret_paths, arraySecretResource.secret_paths);
    const removed = structuredClone(arraySecretResource.record);
    delete removed.other_settings['a/b~c'];
    assert.equal(agentStoredArrayEditError(removed, arraySecretResource), null);
    assert.deepEqual(buildEditorWrite(removed, arraySecretResource).clear_secret_paths, arraySecretResource.secret_paths);
});
await check('unsafe agent updates retain their previous values and buffer a visible resettable error', () => {
    const current = structuredClone(arraySecretResource.record);
    const next = structuredClone(current);
    next.other_settings['a/b~c'].reverse();
    next._editor_settings_text = JSON.stringify(next.other_settings);
    const rejected = applySafeAgentDraft(current, next, arraySecretResource);
    assert.deepEqual(rejected.other_settings, current.other_settings);
    assert.equal(rejected._editor_settings_text, next._editor_settings_text);
    assert.match(rejected._editor_array_secret_error, /saved array positions/);
    assert.deepEqual(buildEditorWrite(rejected, arraySecretResource).updates, {});
    const reset = applySafeAgentDraft(rejected, clearAgentDraftFields(rejected, '_editor_settings_text', '_editor_array_secret_error'), arraySecretResource);
    assert.ok(sameEditorValue(reset, current));
});
await check('nested secret arrays remain positional and numeric object keys are not treated as arrays', () => {
    const nested = {
        ...original,
        record: { ...originalDraft, other_settings: { groups: [{ id: 'group', credentials: [
            { id: 'one', key: EDITOR_SECRET_MASK }, { id: 'two', key: EDITOR_SECRET_MASK },
        ] }] } },
        secret_paths: ['/other_settings/groups/0/credentials/0/key', '/other_settings/groups/0/credentials/1/key'],
    };
    const moved = structuredClone(nested.record);
    moved.other_settings.groups[0].credentials.reverse();
    assert.match(agentStoredArrayEditError(moved, nested), /saved array positions/);
    const replaced = setAgentSecret(nested.record, nested.secret_paths[0], 'synthetic');
    replaced.other_settings.groups[0].credentials[0].id = 'updated-explicit-entry';
    assert.equal(agentStoredArrayEditError(replaced, nested), null);
    const objectRecord = {
        ...original, record: { ...originalDraft, other_settings: { mapping: { 0: { key: EDITOR_SECRET_MASK, label: 'before' } } } },
        secret_paths: ['/other_settings/mapping/0/key'],
    };
    const objectDraft = structuredClone(objectRecord.record);
    objectDraft.other_settings.mapping[0].label = 'after';
    assert.equal(agentStoredArrayEditError(objectDraft, objectRecord), null);
});
await check('image icon sources are restricted to bounded PNG/JPEG data', () => {
    assert.ok(isAgentIconImage('data:image/png;base64,aGVsbG8='));
    assert.ok(isAgentIconImage('data:image/jpeg;base64,aGVsbG8='));
    assert.ok(!isAgentIconImage('data:image/svg+xml;base64,aGVsbG8='));
    assert.ok(!isAgentIconImage('https://example.org/icon.png'));
    assert.ok(!isAgentIconImage(`data:image/png;base64,${'A'.repeat(350000)}`));
});

await check('a conflict sends one conditional write and never replaces the original revision', async () => {
    const originalFetch = globalThis.fetch;
    const snapshot = structuredClone(original);
    const draft = { ...originalDraft, description: 'Unsaved changes remain for review.' };
    let requests = 0;
    globalThis.fetch = async (url, init) => {
        requests += 1;
        assert.equal(url, '/api/user/agents/agent-one?view=editor');
        assert.equal(init.method, 'PATCH');
        assert.equal(JSON.parse(init.body).expected_revision, 'one');
        return new Response(JSON.stringify({ error: 'This agent changed in another session.' }), {
            status: 409, headers: { 'content-type': 'application/json' },
        });
    };
    try {
        await assert.rejects(() => saveAgentConfiguration(draft, original), (error) => error.status === 409);
        assert.equal(requests, 1);
        assert.deepEqual(original, snapshot);
        assert.equal(draft.description, 'Unsaved changes remain for review.');
    } finally {
        globalThis.fetch = originalFetch;
    }
});

await check('explicit commands use existing scoped APIs and visible failures propagate', async () => {
    const originalFetch = globalThis.fetch;
    const requests = [];
    globalThis.fetch = async (url, init = {}) => {
        requests.push({ url, init, body: init.body ? JSON.parse(init.body) : undefined });
        const result = String(url).includes('draft-instructions') ? { success: true, instructions: 'Generated text' }
            : String(url).includes('foundry/agents') ? { agents: [{ id: 'remote' }], responses_api_version: 'v1' }
            : String(url).includes('agent-templates') ? { templates: [] } : catalog;
        return new Response(JSON.stringify(result), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    try {
        const controller = new AbortController();
        assert.equal(await draftAgentInstructions(originalDraft, actions, catalog, controller.signal), 'Generated text');
        assert.equal(requests[0].url, '/api/agents/draft-instructions');
        assert.equal(requests[0].init.signal, controller.signal);
        assert.equal(requests[0].body.selected_actions[1].type, 'agent');
        await discoverAgentFoundryResources({ id: 'personal-foundry', provider: 'new_foundry', scope: 'personal' }, 'foundry_workflow', controller.signal);
        assert.deepEqual(requests[1].body, { endpoint_id: 'personal-foundry', scope: 'personal', resource_type: 'workflow' });
        await fetchAgentKnowledgeCatalog(controller.signal);
        assert.equal(requests[2].url, '/api/agents/assigned-knowledge/catalog?agent_scope=personal');
        await fetchAgentTemplates(controller.signal);
        assert.equal(requests[3].url, '/api/agent-templates');
        globalThis.fetch = async () => new Response(JSON.stringify({ error: 'Discovery denied.' }), { status: 403, headers: { 'content-type': 'application/json' } });
        await assert.rejects(() => fetchAgentKnowledgeCatalog(), /Discovery denied/);
        await assert.rejects(() => draftAgentInstructions(originalDraft, actions, catalog), /Discovery denied/);
        await assert.rejects(() => fetchAgentTemplates(), /Discovery denied/);
        globalThis.fetch = async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
        await assert.rejects(() => fetchAgentKnowledgeCatalog(), /invalid response/);
        await assert.rejects(() => draftAgentInstructions(originalDraft, actions, catalog), /no instructions/);
        await assert.rejects(() => fetchAgentTemplates(), /invalid response/);
        await assert.rejects(() => discoverAgentFoundryResources({ id: 'endpoint', provider: 'new_foundry' }, 'new_foundry'), /invalid resource list/);
    } finally {
        globalThis.fetch = originalFetch;
    }
});
console.log(`${checks} native agent authoring runtime checks passed.`);
