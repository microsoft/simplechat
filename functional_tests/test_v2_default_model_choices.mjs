// test_v2_default_model_choices.mjs
//
// Runtime test for the V2 default chat model picker logic.
// Version: 0.261.061
// Implemented in: 0.261.061
//
// The picker's whole job is to refuse to offer a model that the server will not accept.
// `resolve_default_model_selection` clears a reference to a disabled connection or a
// disabled model on the next write, so listing one would let an administrator choose a
// value that reverts with no explanation -- the same silent-revert problem the phase 2
// work exists to remove.
//
// The filtering, labelling and index bookkeeping are pure, so they are executed here
// rather than inferred from the rendered DOM.
//
// Run directly with `node functional_tests/test_v2_default_model_choices.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';

import './test_support/tsResolve.mjs';

const {
    buildDefaultModelChoices,
    choiceToSelection,
    findChoiceIndex,
    groupChoicesByConnection,
    hasDefaultModel,
    isSameSelection,
    toDefaultModelSelection,
    EMPTY_DEFAULT_MODEL_SELECTION,
} = await import('../application/v2_ui/src/lib/modelConnections.ts');

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/** Two connections shaped the way `sanitize_model_endpoints_for_frontend` returns them. */
function connections() {
    return [
        {
            id: 'conn-live',
            name: 'Primary',
            provider: 'aoai',
            enabled: true,
            connection: { endpoint: 'https://primary.openai.azure.com' },
            models: [
                { id: 'gpt-4o', deploymentName: 'gpt-4o-prod', displayName: 'GPT-4o', enabled: true },
                { id: 'retired', deploymentName: 'retired', enabled: false },
            ],
        },
        {
            id: 'conn-off',
            name: 'Secondary',
            provider: 'aifoundry',
            enabled: false,
            connection: { endpoint: 'https://secondary.services.ai.azure.com' },
            models: [{ id: 'phi-4', deploymentName: 'phi-4', enabled: true }],
        },
    ];
}

/* --------------------------- what may be offered --------------------------- */

check('a disabled connection contributes nothing', () => {
    const choices = buildDefaultModelChoices(connections());
    assert.equal(
        choices.some((choice) => choice.endpointId === 'conn-off'),
        false,
    );
});

check('a disabled model is left out of its enabled connection', () => {
    const choices = buildDefaultModelChoices(connections());
    assert.deepEqual(
        choices.map((choice) => choice.modelId),
        ['gpt-4o'],
    );
});

check('a model with no id and no deployment name is not addressable', () => {
    const choices = buildDefaultModelChoices([
        {
            id: 'conn-live',
            name: 'Primary',
            enabled: true,
            models: [{ displayName: 'Nameless', enabled: true }],
        },
    ]);
    assert.deepEqual(choices, []);
});

check('a model missing an id falls back to its deployment name, as the server does', () => {
    const choices = buildDefaultModelChoices([
        {
            id: 'conn-live',
            name: 'Primary',
            enabled: true,
            models: [{ deploymentName: 'gpt-4o-prod', enabled: true }],
        },
    ]);
    assert.equal(choices[0].modelId, 'gpt-4o-prod');
});

check('an absent enabled flag means enabled, matching normalize_model_endpoints', () => {
    const choices = buildDefaultModelChoices([
        {
            id: 'conn-live',
            name: 'Primary',
            models: [{ id: 'gpt-4o' }],
        },
    ]);
    assert.equal(choices.length, 1);
});

check('a connection with no id cannot be referenced', () => {
    const choices = buildDefaultModelChoices([
        { id: '', name: 'Unsaved', enabled: true, models: [{ id: 'gpt-4o', enabled: true }] },
    ]);
    assert.deepEqual(choices, []);
});

/* ------------------------------- how it reads ------------------------------ */

check('a choice carries the connection provider, not the model', () => {
    const [choice] = buildDefaultModelChoices(connections());
    assert.equal(choice.provider, 'aoai');
    assert.equal(choice.connectionName, 'Primary');
});

check('an unnamed connection falls back to its endpoint so it is still identifiable', () => {
    const [choice] = buildDefaultModelChoices([
        {
            id: 'conn-live',
            enabled: true,
            connection: { endpoint: 'https://primary.openai.azure.com' },
            models: [{ id: 'gpt-4o', enabled: true }],
        },
    ]);
    assert.equal(choice.connectionName, 'https://primary.openai.azure.com');
});

check('the model label prefers the display name over the deployment', () => {
    const [choice] = buildDefaultModelChoices(connections());
    assert.equal(choice.modelLabel, 'GPT-4o');
    assert.equal(choice.deploymentName, 'gpt-4o-prod');
});

check('a model with only an id still gets a label rather than rendering blank', () => {
    const [choice] = buildDefaultModelChoices([
        { id: 'conn-live', name: 'Primary', enabled: true, models: [{ id: 'gpt-4o' }] },
    ]);
    assert.equal(choice.modelLabel, 'gpt-4o');
});

check('choices are ordered by connection then model, not by storage order', () => {
    const choices = buildDefaultModelChoices([
        {
            id: 'z',
            name: 'Zulu',
            enabled: true,
            models: [{ id: 'b', displayName: 'Beta' }, { id: 'a', displayName: 'Alpha' }],
        },
        { id: 'a', name: 'Alpha', enabled: true, models: [{ id: 'c', displayName: 'Gamma' }] },
    ]);
    assert.deepEqual(
        choices.map((choice) => `${choice.connectionName}/${choice.modelLabel}`),
        ['Alpha/Gamma', 'Zulu/Alpha', 'Zulu/Beta'],
    );
});

/* ------------------------------- grouping ---------------------------------- */

check('grouping keeps each choice next to the index the select uses', () => {
    const choices = buildDefaultModelChoices([
        {
            id: 'a',
            name: 'Alpha',
            enabled: true,
            models: [{ id: 'one', displayName: 'One' }, { id: 'two', displayName: 'Two' }],
        },
        { id: 'z', name: 'Zulu', enabled: true, models: [{ id: 'three', displayName: 'Three' }] },
    ]);
    const groups = groupChoicesByConnection(choices);

    assert.deepEqual(
        groups.map((group) => group.connectionName),
        ['Alpha', 'Zulu'],
    );
    for (const group of groups) {
        for (const { choice, index } of group.items) {
            assert.equal(choices[index], choice);
        }
    }
});

check('two connections sharing a name are not merged into one group', () => {
    // Names are free text, so duplicates happen. Merging them would put a model under
    // a connection it does not belong to.
    const choices = [
        { endpointId: 'a', modelId: '1', provider: '', connectionName: 'Same', modelLabel: 'One', deploymentName: '' },
        { endpointId: 'b', modelId: '2', provider: '', connectionName: 'Other', modelLabel: 'Two', deploymentName: '' },
        { endpointId: 'c', modelId: '3', provider: '', connectionName: 'Same', modelLabel: 'Three', deploymentName: '' },
    ];
    assert.equal(groupChoicesByConnection(choices).length, 3);
});

/* --------------------------- selection round trip -------------------------- */

check('a stored selection is found in the offered list', () => {
    const choices = buildDefaultModelChoices(connections());
    const index = findChoiceIndex(choices, {
        endpoint_id: 'conn-live',
        model_id: 'gpt-4o',
        provider: 'aoai',
    });
    assert.equal(index, 0);
});

check('a selection naming something no longer offered reports -1, not a wrong match', () => {
    const choices = buildDefaultModelChoices(connections());
    assert.equal(
        findChoiceIndex(choices, { endpoint_id: 'conn-off', model_id: 'phi-4', provider: '' }),
        -1,
    );
    assert.equal(
        findChoiceIndex(choices, { endpoint_id: 'conn-live', model_id: 'retired', provider: '' }),
        -1,
    );
});

check('the same model id on two connections does not cross-match', () => {
    const choices = buildDefaultModelChoices([
        { id: 'first', name: 'A', enabled: true, models: [{ id: 'gpt-4o' }] },
        { id: 'second', name: 'B', enabled: true, models: [{ id: 'gpt-4o' }] },
    ]);
    assert.equal(
        findChoiceIndex(choices, { endpoint_id: 'second', model_id: 'gpt-4o', provider: '' }),
        1,
    );
});

check('an empty selection matches nothing rather than the first option', () => {
    const choices = buildDefaultModelChoices(connections());
    assert.equal(findChoiceIndex(choices, EMPTY_DEFAULT_MODEL_SELECTION), -1);
});

check('a picked choice converts back to the shape the API stores', () => {
    const [choice] = buildDefaultModelChoices(connections());
    assert.deepEqual(choiceToSelection(choice), {
        endpoint_id: 'conn-live',
        model_id: 'gpt-4o',
        provider: 'aoai',
    });
});

check('clearing converts to the empty selection the server expects', () => {
    assert.deepEqual(choiceToSelection(null), {
        endpoint_id: '',
        model_id: '',
        provider: '',
    });
});

/* ------------------------------ shape coercion ----------------------------- */

check('a missing or malformed stored selection reads as empty', () => {
    for (const value of [undefined, null, 'gpt-4o', 42, {}]) {
        assert.deepEqual(toDefaultModelSelection(value), {
            endpoint_id: '',
            model_id: '',
            provider: '',
        });
    }
});

check('the provider is lowercased, matching normalize_default_model_selection', () => {
    assert.deepEqual(
        toDefaultModelSelection({ endpoint_id: ' a ', model_id: ' b ', provider: 'AOAI' }),
        { endpoint_id: 'a', model_id: 'b', provider: 'aoai' },
    );
});

check('half a reference is not a default', () => {
    assert.equal(hasDefaultModel({ endpoint_id: 'a', model_id: '', provider: '' }), false);
    assert.equal(hasDefaultModel({ endpoint_id: '', model_id: 'b', provider: '' }), false);
    assert.equal(hasDefaultModel({ endpoint_id: 'a', model_id: 'b', provider: '' }), true);
});

check('two selections match on the reference alone, ignoring the provider', () => {
    // The provider is derived from the connection on every write, so a difference there
    // is not a different selection.
    assert.equal(
        isSameSelection(
            { endpoint_id: 'a', model_id: 'b', provider: 'aoai' },
            { endpoint_id: 'a', model_id: 'b', provider: '' },
        ),
        true,
    );
    assert.equal(
        isSameSelection(
            { endpoint_id: 'a', model_id: 'b', provider: 'aoai' },
            { endpoint_id: 'a', model_id: 'c', provider: 'aoai' },
        ),
        false,
    );
});

/* ---------------------------------- run ------------------------------------ */

let passed = 0;
const failures = [];

for (const [name, fn] of checks) {
    try {
        fn();
        passed += 1;
    } catch (error) {
        failures.push(`${name}: ${error.message}`);
    }
}

console.log(`Results: ${passed}/${checks.length} checks passed`);
if (failures.length) {
    for (const failure of failures) {
        console.error(`FAILED ${failure}`);
    }
    process.exit(1);
}
