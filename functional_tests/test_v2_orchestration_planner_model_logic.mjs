// test_v2_orchestration_planner_model_logic.mjs
// Version: 0.261.137
// Implemented in: 0.261.137
// Executes the real planner-model choice logic of both admin interfaces -- the V2 library and the
// classic ES module -- against the same cases, so the two dropdowns write the same four settings.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
            return nextResolve(`${specifier}.ts`, context);
        }
        return nextResolve(specifier, context);
    },
});

const v2 = await import('../application/v2_ui/src/lib/orchestrationPlannerModel.ts');
const classic = await import('../application/single_app/static/js/admin/admin_orchestration_planner_model.js');

const KEYS = [
    'chat_orchestration_planner_deployment', 'chat_orchestration_planner_model_id',
    'chat_orchestration_planner_model_endpoint_id', 'chat_orchestration_planner_model_provider',
];
const BLANK = { deployment: '', modelId: '', endpointId: '', provider: '' };

// The V2 list comes from the capability-model API; the classic list from the page's endpoints.
const connectionChoicesV2 = v2.connectionPlannerChoices([
    { endpointId: 'east', modelId: 'mini', provider: 'aoai', connectionName: 'East', modelLabel: 'GPT-5 mini', deploymentName: 'gpt-5-mini' },
    { endpointId: 'west', modelId: 'terra', provider: 'new_foundry', connectionName: 'West', modelLabel: 'Terra', deploymentName: 'Terra' },
    { endpointId: '', modelId: 'orphan', provider: 'aoai', connectionName: 'None', modelLabel: 'Orphan', deploymentName: 'orphan' },
]);
const connectionChoicesClassic = classic.connectionChoices([
    { id: 'east', name: 'East', provider: 'aoai', models: [
        { id: 'mini', deploymentName: 'gpt-5-mini', displayName: 'GPT-5 mini' },
        { id: 'embed', deploymentName: 'embed', displayName: 'Embeddings', chat: false },
        { id: 'off', deploymentName: 'off', displayName: 'Off', enabled: false },
    ] },
    { id: 'west', name: 'West', provider: 'new_foundry', models: [{ deploymentName: 'terra', displayName: 'Terra' }] },
    { id: 'compat', name: 'Compatible', provider: 'openai_compatible', models: [{ id: 'x', deploymentName: 'x' }] },
    { id: 'disabled', name: 'Disabled', provider: 'aoai', enabled: false, models: [{ id: 'y', deploymentName: 'y' }] },
], (model) => model.enabled !== false && model.chat !== false);

function testConnectionChoices() {
    assert.deepEqual(connectionChoicesV2.map((choice) => choice.selection), [
        { deployment: '', modelId: 'mini', endpointId: 'east', provider: 'aoai' },
        { deployment: '', modelId: 'terra', endpointId: 'west', provider: 'new_foundry' },
    ], 'a connection model is saved by endpoint and id, never by a copied deployment');
    assert.deepEqual(connectionChoicesV2.map((choice) => choice.label), ['GPT-5 mini (gpt-5-mini)', 'Terra']);
    assert.deepEqual(connectionChoicesV2.map((choice) => choice.group), ['East', 'West']);
    assert.deepEqual(connectionChoicesClassic.map((choice) => choice.selection), [
        { deployment: '', modelId: 'mini', endpointId: 'east', provider: 'aoai' },
        { deployment: '', modelId: 'terra', endpointId: 'west', provider: 'new_foundry' },
    ], 'disabled, embedding-only, compatibility-only and unpublished models are not offered');
    assert.deepEqual(
        connectionChoicesClassic.map((choice) => choice.value),
        connectionChoicesV2.map((choice) => choice.value),
        'both interfaces identify the same model with the same option value',
    );
}

function testClassicDeployments() {
    const legacy = [{ deploymentName: 'gpt-4o', modelName: 'gpt-4o' }, { deploymentName: 'small', modelName: 'gpt-4o-mini' }, { deploymentName: 'small' }];
    const v2Legacy = v2.classicPlannerChoices((key) => ({ gpt_model: { selected: legacy } })[key]);
    const classicLegacy = classic.classicChoices({ apimEnabled: false, legacyModels: legacy });
    for (const choices of [v2Legacy, classicLegacy]) {
        assert.deepEqual(choices.map((choice) => choice.label), ['gpt-4o', 'small (gpt-4o-mini)']);
        assert.deepEqual(choices[1].selection, { ...BLANK, deployment: 'small' });
    }
    const v2Apim = v2.classicPlannerChoices((key) => ({ enable_gpt_apim: true, azure_apim_gpt_deployment: ' a, b ,, a' })[key]);
    const classicApim = classic.classicChoices({ apimEnabled: true, apimDeployments: ' a, b ,, a' });
    for (const choices of [v2Apim, classicApim]) {
        assert.deepEqual(choices.map((choice) => choice.selection.deployment), ['a', 'b']);
    }
}

function testSelectionValues() {
    const cases = [
        [BLANK, ''],
        [{ ...BLANK, modelId: 'mini', endpointId: 'east', provider: 'aoai' }, connectionChoicesV2[0].value],
        [{ ...BLANK, modelId: 'mini', endpointId: 'east' }, connectionChoicesV2[0].value],
        [{ deployment: 'stale-copy', modelId: 'terra', endpointId: 'west', provider: 'new_foundry' }, connectionChoicesV2[1].value],
        [{ ...BLANK, modelId: 'retired', endpointId: 'east' }, '__saved__'],
        [{ ...BLANK, modelId: 'mini', endpointId: 'gone' }, '__saved__'],
        [{ ...BLANK, deployment: 'gpt-5-mini' }, '__saved__'],
        [{ ...BLANK, provider: 'aoai' }, '__saved__'],
    ];
    for (const [selection, expected] of cases) {
        assert.equal(v2.plannerSelectionValue(selection, connectionChoicesV2), expected, JSON.stringify(selection));
        assert.equal(classic.selectionValue(selection, connectionChoicesClassic), expected, JSON.stringify(selection));
    }
    const legacy = v2.classicPlannerChoices((key) => ({ gpt_model: { selected: [{ deploymentName: 'gpt-4o' }] } })[key]);
    assert.equal(v2.plannerSelectionValue({ ...BLANK, deployment: 'gpt-4o' }, legacy), 'classic:gpt-4o');
    assert.equal(v2.plannerSelectionValue({ ...BLANK, deployment: 'gpt-4o', provider: 'AOAI' }, legacy), 'classic:gpt-4o');
    assert.equal(v2.plannerSelectionValue({ ...BLANK, deployment: 'gpt-4o', provider: 'custom' }, legacy), '__saved__');
    assert.equal(v2.describePlannerSelection({ ...BLANK, modelId: 'old', endpointId: 'gone' }), 'old on gone');
    assert.equal(classic.describeSelection({ ...BLANK, modelId: 'old', endpointId: 'gone' }), 'old on gone');
    assert.equal(v2.describePlannerSelection({ ...BLANK, deployment: 'planner' }), 'planner');
}

function testUpdates() {
    assert.deepEqual(v2.plannerSelectionUpdates('', connectionChoicesV2), Object.fromEntries(KEYS.map((key) => [key, ''])));
    assert.deepEqual(v2.plannerSelectionUpdates(connectionChoicesV2[1].value, connectionChoicesV2), {
        chat_orchestration_planner_deployment: '', chat_orchestration_planner_model_id: 'terra',
        chat_orchestration_planner_model_endpoint_id: 'west', chat_orchestration_planner_model_provider: 'new_foundry',
    });
    assert.equal(v2.plannerSelectionUpdates('__saved__', connectionChoicesV2), null, 'keeping the saved value writes nothing');
    assert.equal(v2.plannerSelectionUpdates('connection:["nope","x"]', connectionChoicesV2), null);
    assert.deepEqual(classic.selectionForValue('', connectionChoicesClassic), BLANK);
    assert.deepEqual(classic.selectionForValue(connectionChoicesClassic[1].value, connectionChoicesClassic), connectionChoicesClassic[1].selection);
    assert.equal(classic.selectionForValue('__saved__', connectionChoicesClassic), null);
    assert.deepEqual(Object.values(v2.PLANNER_MODEL_KEYS), KEYS);
    assert.deepEqual(Object.values(classic.PLANNER_FIELD_IDS), KEYS);
}

for (const test of [testConnectionChoices, testClassicDeployments, testSelectionValues, testUpdates]) {
    test();
    console.log(`ok ${test.name}`);
}
