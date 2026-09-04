// test_v2_admin_field_visibility.mjs
//
// Runtime test for V2 admin field visibility and the deployment picker's pure logic.
// Version: 0.261.075
// Implemented in: 0.261.075
//
// Two rules are exercised here because both are invisible until a specific combination
// of settings is on screen, and both fail silently when wrong.
//
// Visibility. The server field schema is flat, but the panes it mirrors are nested: the
// Azure OpenAI key sits inside the direct-connection block *and* inside the
// key-authentication block. A single `depends_on` expresses one of those, so the other
// has to be inherited from the field it depends on. Get that wrong and switching a
// section to APIM leaves a direct-connection credential on screen, next to fields that
// are not being used -- which reads as though the direct connection is still live.
//
// Selection. The deployment list is a cache of the last discovery, so it can name a
// deployment that has since been removed. The server refuses a selection outside the
// list, so the picker has to drop one that discovery no longer reports rather than
// submit it and surface a rejection the administrator did not cause.
//
// Run directly with `node functional_tests/test_v2_admin_field_visibility.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';

import './test_support/tsResolve.mjs';

const { hasStoredSecret, isFieldVisible, readSecretValue } = await import(
    '../application/v2_ui/src/lib/adminFields.ts'
);

const {
    applyDiscoveredModels,
    deploymentLabel,
    findDeploymentIndex,
    hasUnsavedDiscoveryEdits,
    isDanglingSelection,
    toModelDeployment,
    toModelDeployments,
} = await import('../application/v2_ui/src/lib/modelSelection.ts');

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/** The embeddings section, shaped the way `admin_settings_fields.py` declares it. */
function embeddingFields() {
    return [
        { key: 'enable_embedding_apim', type: 'switch', label: 'APIM', default: false },
        {
            key: 'azure_openai_embedding_endpoint',
            type: 'text',
            label: 'Endpoint',
            default: '',
            depends_on: { key: 'enable_embedding_apim', equals: false },
        },
        {
            key: 'azure_openai_embedding_authentication_type',
            type: 'select',
            label: 'Authentication Type',
            default: 'key',
            options: [
                { value: 'key', label: 'Key' },
                { value: 'managed_identity', label: 'Managed Identity' },
            ],
            depends_on: { key: 'enable_embedding_apim', equals: false },
        },
        {
            key: 'azure_openai_embedding_key',
            type: 'password',
            label: 'Key',
            default: '',
            depends_on: {
                key: 'azure_openai_embedding_authentication_type',
                equals: 'key',
            },
        },
        {
            key: 'azure_apim_embedding_endpoint',
            type: 'text',
            label: 'APIM endpoint',
            default: '',
            depends_on: { key: 'enable_embedding_apim', equals: true },
        },
    ];
}

const fieldsByKey = Object.fromEntries(embeddingFields().map((field) => [field.key, field]));

function visible(key, settings, draft = {}) {
    return isFieldVisible(fieldsByKey[key], settings, draft, embeddingFields());
}

/* ------------------------------- visibility -------------------------------- */

check('a boolean dependency still decides visibility', () => {
    const direct = { enable_embedding_apim: false };
    assert.equal(visible('azure_openai_embedding_endpoint', direct), true);
    assert.equal(visible('azure_apim_embedding_endpoint', direct), false);

    const apim = { enable_embedding_apim: true };
    assert.equal(visible('azure_openai_embedding_endpoint', apim), false);
    assert.equal(visible('azure_apim_embedding_endpoint', apim), true);
});

check('a string dependency compares the value, not its truthiness', () => {
    const withKey = {
        enable_embedding_apim: false,
        azure_openai_embedding_authentication_type: 'key',
    };
    assert.equal(visible('azure_openai_embedding_key', withKey), true);

    // 'managed_identity' is truthy, so a boolean comparison would show the key field.
    const withIdentity = {
        enable_embedding_apim: false,
        azure_openai_embedding_authentication_type: 'managed_identity',
    };
    assert.equal(visible('azure_openai_embedding_key', withIdentity), false);
});

check('a field whose dependency is hidden is hidden too', () => {
    // Authentication type is still 'key', but the whole direct-connection block is gone.
    const apim = {
        enable_embedding_apim: true,
        azure_openai_embedding_authentication_type: 'key',
    };
    assert.equal(visible('azure_openai_embedding_key', apim), false);
});

check('an unsaved edit decides visibility before the save lands', () => {
    const settings = {
        enable_embedding_apim: false,
        azure_openai_embedding_authentication_type: 'key',
    };
    assert.equal(
        visible('azure_openai_embedding_key', settings, {
            azure_openai_embedding_authentication_type: 'managed_identity',
        }),
        false,
    );
    assert.equal(
        visible('azure_openai_embedding_key', settings, { enable_embedding_apim: true }),
        false,
    );
});

check('an absent value falls back to the declared default', () => {
    // A settings document that predates a key has no value for it. Reading that as empty
    // would hide the API key permanently, because the default authentication is 'key'.
    assert.equal(visible('azure_openai_embedding_key', {}), true);
    assert.equal(visible('azure_apim_embedding_endpoint', {}), false);
});

check('a field with no dependency is always visible', () => {
    assert.equal(visible('enable_embedding_apim', {}), true);
});

check('a dependency cycle terminates instead of hanging the page', () => {
    const a = { key: 'a', type: 'switch', label: 'A', default: true, depends_on: { key: 'b', equals: true } };
    const b = { key: 'b', type: 'switch', label: 'B', default: true, depends_on: { key: 'a', equals: true } };
    assert.equal(isFieldVisible(a, { a: true, b: true }, {}, [a, b]), true);
});

check('visibility works without siblings, using the stored value alone', () => {
    // The page passes the section's declared list, but the helper must not require it.
    const field = fieldsByKey.azure_openai_embedding_key;
    assert.equal(
        isFieldVisible(field, { azure_openai_embedding_authentication_type: 'key' }, {}),
        true,
    );
    assert.equal(
        isFieldVisible(
            field,
            { azure_openai_embedding_authentication_type: 'managed_identity' },
            {},
        ),
        false,
    );
});

/* --------------------------------- secrets --------------------------------- */

check('a stored secret is reported as present, never as its value', () => {
    assert.equal(hasStoredSecret({ azure_openai_embedding_key: 'sk-live' }, 'azure_openai_embedding_key'), true);
    assert.equal(hasStoredSecret({ azure_openai_embedding_key: '' }, 'azure_openai_embedding_key'), false);
    assert.equal(hasStoredSecret({ azure_openai_embedding_key: '   ' }, 'azure_openai_embedding_key'), false);
    assert.equal(hasStoredSecret({}, 'azure_openai_embedding_key'), false);
    assert.equal(hasStoredSecret({ azure_openai_embedding_key: 'sk-live' }, undefined), false);
});

check('a password control shows only what was typed this session', () => {
    const field = fieldsByKey.azure_openai_embedding_key;
    const settings = { azure_openai_embedding_key: 'sk-live' };

    // The stored secret must not reach the control, even though the admin settings
    // payload carries it.
    assert.equal(readSecretValue(field, {}), '');
    assert.notEqual(readSecretValue(field, {}), settings.azure_openai_embedding_key);

    assert.equal(readSecretValue(field, { azure_openai_embedding_key: 'typed' }), 'typed');
    // An explicit removal is held as null so the control can say what will happen.
    assert.equal(readSecretValue(field, { azure_openai_embedding_key: null }), null);
});

/* ---------------------------- deployment picker ---------------------------- */

function discovered() {
    return [
        { deploymentName: 'text-embedding-3-large', modelName: 'text-embedding-3-large' },
        { deploymentName: 'ada-002', modelName: 'text-embedding-ada-002' },
    ];
}

check('a deployment with no name is not addressable', () => {
    assert.equal(toModelDeployment({ modelName: 'nameless' }), null);
    assert.equal(toModelDeployment(null), null);
    assert.deepEqual(toModelDeployment({ deploymentName: '  ada-002 ' }), {
        deploymentName: 'ada-002',
    });
});

check('a duplicated deployment name is listed once', () => {
    const models = toModelDeployments([
        { deploymentName: 'ada-002' },
        { deploymentName: 'ada-002', modelName: 'again' },
        { modelName: 'dropped' },
    ]);
    assert.deepEqual(models, [{ deploymentName: 'ada-002' }]);
});

check('a non-array discovery response yields no deployments', () => {
    assert.deepEqual(toModelDeployments(undefined), []);
    assert.deepEqual(toModelDeployments({ models: [] }), []);
});

check('the label names the model only when it differs from the deployment', () => {
    assert.equal(
        deploymentLabel({ deploymentName: 'ada-002', modelName: 'text-embedding-ada-002' }),
        'ada-002 (text-embedding-ada-002)',
    );
    assert.equal(deploymentLabel({ deploymentName: 'ada-002', modelName: 'ada-002' }), 'ada-002');
    assert.equal(deploymentLabel({ deploymentName: 'ada-002' }), 'ada-002');
});

check('a selection survives a rediscovery that still lists it', () => {
    const result = applyDiscoveredModels(discovered(), { deploymentName: 'ada-002' });
    assert.equal(result.selected.deploymentName, 'ada-002');
    assert.equal(result.droppedSelection, false);
    // Refreshed from the discovered entry, so the model name follows the resource.
    assert.equal(result.selected.modelName, 'text-embedding-ada-002');
});

check('a selection discovery no longer reports is dropped, and said so', () => {
    const result = applyDiscoveredModels(discovered(), { deploymentName: 'retired' });
    assert.equal(result.selected, null);
    assert.equal(result.droppedSelection, true);
});

check('discovering with nothing selected drops nothing', () => {
    const result = applyDiscoveredModels(discovered(), null);
    assert.equal(result.selected, null);
    assert.equal(result.droppedSelection, false);
});

check('a stored selection outside the list is dangling, an empty one is not', () => {
    assert.equal(isDanglingSelection(discovered(), { deploymentName: 'retired' }), true);
    assert.equal(isDanglingSelection(discovered(), { deploymentName: 'ada-002' }), false);
    assert.equal(isDanglingSelection(discovered(), null), false);
    // Nothing fetched yet is also dangling: the selection cannot be shown in the list.
    assert.equal(isDanglingSelection([], { deploymentName: 'ada-002' }), true);
});

check('the index is the position in the list the select renders', () => {
    assert.equal(findDeploymentIndex(discovered(), { deploymentName: 'ada-002' }), 1);
    assert.equal(findDeploymentIndex(discovered(), { deploymentName: 'retired' }), -1);
    assert.equal(findDeploymentIndex(discovered(), null), -1);
});

check('an unsaved endpoint edit blocks a fetch that would ask the wrong resource', () => {
    // Discovery reads the stored endpoint, subscription and resource group, so fetching
    // mid-edit lists the previous resource -- which reads as a wrong answer, not a stale
    // question.
    assert.equal(
        hasUnsavedDiscoveryEdits('embedding', ['azure_openai_embedding_endpoint']),
        true,
    );
    assert.equal(
        hasUnsavedDiscoveryEdits('embedding', ['azure_openai_embedding_subscription_id']),
        true,
    );
    assert.equal(
        hasUnsavedDiscoveryEdits('image', ['azure_openai_image_gen_resource_group']),
        true,
    );
});

check('an unrelated edit does not block a fetch', () => {
    // The API version and the key are sent with the request rather than used to address
    // the resource, so editing them cannot make discovery answer about the wrong one.
    assert.equal(
        hasUnsavedDiscoveryEdits('embedding', ['azure_openai_embedding_api_version']),
        false,
    );
    assert.equal(hasUnsavedDiscoveryEdits('embedding', []), false);
    // And the two catalogs do not gate each other.
    assert.equal(
        hasUnsavedDiscoveryEdits('embedding', ['azure_openai_image_gen_endpoint']),
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
