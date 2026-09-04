// test_v2_model_connections_logic.mjs
//
// Runtime test for the V2 global model connection form logic.
// Version: 0.261.059
// Implemented in: 0.261.059
//
// The classic connection editor decided which fields a provider and auth type needed by
// toggling `d-none` across two dozen elements from three separate listeners, and reported
// a validation failure as a toast that named the problem but not the control. Both are why
// it was hard to tell what a connection still needed.
//
// The replacement derives visibility and validation from the draft in one place, so those
// rules can be executed here rather than inferred from the rendered DOM. The payload
// builder is checked too, because two of its decisions are silent if wrong: sending a blank
// secret would erase a stored key, and sending a provider's unused fields would persist
// coordinates that no longer apply.
//
// Run directly with `node functional_tests/test_v2_model_connections_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';

import './test_support/tsResolve.mjs';

const {
    buildConnectionPayload,
    emptyConnection,
    enabledModelCount,
    endpointIncludesProject,
    isFoundryProvider,
    mergeDiscoveredModels,
    projectNameFromEndpoint,
    providerLabel,
    toEditableConnection,
    validateConnection,
    visibleFields,
} = await import('../application/v2_ui/src/lib/modelConnections.ts');

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/** A connection that passes validation, so each check can break exactly one thing. */
function validAoai(overrides = {}) {
    const base = emptyConnection();
    return {
        ...base,
        ...overrides,
        name: 'Primary',
        connection: {
            ...base.connection,
            endpoint: 'https://example.openai.azure.com',
            ...(overrides.connection ?? {}),
        },
        management: {
            subscription_id: '00000000-0000-0000-0000-000000000000',
            resource_group: 'rg-ai',
            ...(overrides.management ?? {}),
        },
        auth: { ...base.auth, ...(overrides.auth ?? {}) },
    };
}

/* ------------------------------- provider shape ------------------------------ */

check('foundry providers are recognised by both stored names', () => {
    assert.equal(isFoundryProvider('aifoundry'), true);
    assert.equal(isFoundryProvider('new_foundry'), true);
    assert.equal(isFoundryProvider('aoai'), false);
});

check('provider labels fall back to the raw value rather than going blank', () => {
    assert.equal(providerLabel('aoai'), 'Azure OpenAI');
    assert.equal(providerLabel('anthropic'), 'anthropic');
    assert.equal(providerLabel(''), 'Connection');
});

check('a project endpoint URL yields its project name', () => {
    assert.equal(endpointIncludesProject('https://x.services.ai.azure.com/api/projects/proj'), true);
    assert.equal(
        projectNameFromEndpoint('https://x.services.ai.azure.com/api/projects/my-project'),
        'my-project',
    );
    // A half-typed endpoint is not a parseable URL, but the hint should still work.
    assert.equal(projectNameFromEndpoint('x.services.ai/api/projects/partial?x=1'), 'partial');
    assert.equal(projectNameFromEndpoint('https://example.openai.azure.com'), '');
});

/* ------------------------------- field visibility ---------------------------- */

check('an API key connection hides the Azure discovery fields', () => {
    // Discovery goes through Azure Resource Manager, which an API key cannot reach, so
    // asking for a subscription and resource group would be asking for nothing.
    const shown = visibleFields(validAoai({ auth: { type: 'api_key' } }));
    assert.equal(shown.apiKey, true);
    assert.equal(shown.management, false);
    assert.equal(shown.managementCloud, false);
    assert.equal(shown.servicePrincipal, false);
    assert.equal(shown.managedIdentity, false);
});

check('managed identity shows a client id only when user assigned', () => {
    const system = visibleFields(validAoai({ auth: { type: 'managed_identity' } }));
    assert.equal(system.userAssignedClientId, false);

    const user = visibleFields(
        validAoai({ auth: { type: 'managed_identity', managed_identity_type: 'user_assigned' } }),
    );
    assert.equal(user.userAssignedClientId, true);
});

check('a custom management cloud reveals the authority field', () => {
    const publicCloud = visibleFields(validAoai({ auth: { type: 'service_principal' } }));
    assert.equal(publicCloud.customAuthority, false);

    const custom = visibleFields(
        validAoai({ auth: { type: 'service_principal', management_cloud: 'custom' } }),
    );
    assert.equal(custom.customAuthority, true);
});

check('foundry fields appear only for foundry providers', () => {
    assert.equal(visibleFields(validAoai()).project, false);
    const foundry = visibleFields(validAoai({ provider: 'new_foundry' }));
    assert.equal(foundry.project, true);
    assert.equal(foundry.foundryScope, true);
    // Foundry discovery does not use ARM coordinates.
    assert.equal(foundry.management, false);
});

/* --------------------------------- validation -------------------------------- */

check('a complete Azure OpenAI connection validates', () => {
    assert.deepEqual(validateConnection(validAoai()), {});
});

check('validation reports the field, not just the failure', () => {
    const errors = validateConnection({ ...validAoai(), name: '' });
    assert.ok(errors.name, 'expected a name error');
    assert.equal(Object.keys(errors).length, 1);
});

check('an endpoint without a scheme is refused', () => {
    const errors = validateConnection(
        validAoai({ connection: { endpoint: 'example.openai.azure.com' } }),
    );
    assert.ok(errors.endpoint);
});

check('Azure OpenAI discovery requires the resource coordinates', () => {
    const errors = validateConnection(
        validAoai({ management: { subscription_id: '', resource_group: '' } }),
    );
    assert.ok(errors.subscription_id);
    assert.ok(errors.resource_group);
});

check('an API key connection does not demand the discovery coordinates', () => {
    const errors = validateConnection(
        validAoai({
            auth: { type: 'api_key', api_key: 'secret-value' },
            management: { subscription_id: '', resource_group: '' },
        }),
    );
    assert.deepEqual(errors, {});
});

check('a stored secret satisfies validation when the input is left blank', () => {
    // The server strips secrets on the way out, so the editor never holds one. Demanding a
    // value here would force an administrator to retype the key to change anything else.
    const stored = {
        ...validAoai({ auth: { type: 'api_key', api_key: '' } }),
        has_api_key: true,
    };
    assert.deepEqual(validateConnection(stored), {});

    const absent = { ...validAoai({ auth: { type: 'api_key', api_key: '' } }), has_api_key: false };
    assert.ok(validateConnection(absent).api_key);
});

check('service principal requires tenant, client and a secret unless one is stored', () => {
    const missing = validateConnection(validAoai({ auth: { type: 'service_principal' } }));
    assert.ok(missing.tenant_id);
    assert.ok(missing.client_id);
    assert.ok(missing.client_secret);

    const withStored = {
        ...validAoai({
            auth: { type: 'service_principal', tenant_id: 't', client_id: 'c', client_secret: '' },
        }),
        has_client_secret: true,
    };
    assert.deepEqual(validateConnection(withStored), {});
});

check('a foundry endpoint without a project needs the project named', () => {
    const errors = validateConnection(
        validAoai({
            provider: 'new_foundry',
            connection: {
                endpoint: 'https://x.services.ai.azure.com',
                openai_api_version: 'v1',
                project_api_version: 'v1',
                project_name: '',
            },
        }),
    );
    assert.ok(errors.project_name);

    const named = validateConnection(
        validAoai({
            provider: 'new_foundry',
            connection: {
                endpoint: 'https://x.services.ai.azure.com/api/projects/proj',
                openai_api_version: 'v1',
                project_api_version: 'v1',
            },
        }),
    );
    assert.equal(named.project_name, undefined);
});

/* ------------------------------- payload building ---------------------------- */

check('a blank secret is omitted so a stored one survives the save', () => {
    const payload = buildConnectionPayload({
        ...validAoai({ auth: { type: 'api_key', api_key: '' } }),
        has_api_key: true,
    });
    assert.equal('api_key' in payload.auth, false, 'a blank key must not be sent');

    const replaced = buildConnectionPayload(
        validAoai({ auth: { type: 'api_key', api_key: 'new-secret' } }),
    );
    assert.equal(replaced.auth.api_key, 'new-secret');
});

check('a provider only sends the auth fields it uses', () => {
    const payload = buildConnectionPayload(validAoai({ auth: { type: 'api_key', api_key: 'k' } }));
    assert.equal('tenant_id' in payload.auth, false);
    assert.equal('managed_identity_type' in payload.auth, false);

    const identity = buildConnectionPayload(validAoai());
    assert.equal(identity.auth.managed_identity_type, 'system_assigned');
    assert.equal('client_secret' in identity.auth, false);
});

check('foundry connections send project details and no ARM coordinates', () => {
    const payload = buildConnectionPayload(
        validAoai({
            provider: 'new_foundry',
            connection: {
                endpoint: 'https://x.services.ai.azure.com/api/projects/proj',
                openai_api_version: 'v1',
                project_api_version: 'v1',
            },
        }),
    );
    assert.equal(payload.connection.project_api_version, 'v1');
    // Derived from the endpoint rather than requiring it to be typed twice.
    assert.equal(payload.connection.project_name, 'proj');
    assert.deepEqual(payload.management, {});
});

check('azure openai connections send the ARM coordinates', () => {
    const payload = buildConnectionPayload(validAoai());
    assert.equal(payload.management.resource_group, 'rg-ai');
    assert.equal('project_api_version' in payload.connection, false);
});

check('a model with no display name falls back to its deployment name', () => {
    const payload = buildConnectionPayload({
        ...validAoai(),
        models: [{ deploymentName: 'gpt-4o', displayName: '', enabled: true }],
    });
    assert.equal(payload.models[0].displayName, 'gpt-4o');
});

check('an id is sent only when the connection already has one', () => {
    assert.equal('id' in buildConnectionPayload(validAoai()), false);
    assert.equal(buildConnectionPayload({ ...validAoai(), id: 'ep-1' }).id, 'ep-1');
});

/* ------------------------------- model discovery ----------------------------- */

check('discovery does not duplicate a model already listed', () => {
    const { models, added } = mergeDiscoveredModels(
        [{ deploymentName: 'gpt-4o', displayName: 'Renamed by hand', enabled: true }],
        [{ deploymentName: 'GPT-4o' }, { deploymentName: 'gpt-4o-mini' }],
    );
    assert.equal(added, 1);
    assert.equal(models.length, 2);
    // Matching is case-insensitive, so an edited display name is not overwritten.
    assert.equal(models[0].displayName, 'Renamed by hand');
});

check('discovered models arrive switched off', () => {
    // Discovery finding a deployment is not the same as choosing to publish it.
    const { models } = mergeDiscoveredModels([], [{ deploymentName: 'gpt-4o' }]);
    assert.equal(models[0].enabled, false);
    assert.equal(models[0].isDiscovered, true);
});

check('a deployment with no name is skipped rather than added blank', () => {
    const { models, added } = mergeDiscoveredModels([], [{ modelName: 'gpt-4o' }, {}]);
    assert.equal(added, 0);
    assert.equal(models.length, 0);
});

check('the deployment field is read under either name the API uses', () => {
    const { added } = mergeDiscoveredModels([], [{ deployment: 'legacy-shape' }]);
    assert.equal(added, 1);
});

check('available model count treats a missing flag as enabled', () => {
    assert.equal(
        enabledModelCount({ models: [{ enabled: true }, { enabled: false }, {}] }),
        2,
    );
});

/* --------------------------------- edit shape -------------------------------- */

check('editing a sparse stored connection fills every control', () => {
    // A connection saved before a field existed has no value for it, and an undefined
    // value would make React drop the first keystroke into that control.
    const editable = toEditableConnection({ id: 'ep-1', name: 'Old', provider: 'aoai' });
    assert.equal(editable.auth.type, 'managed_identity');
    assert.equal(editable.connection.endpoint, '');
    assert.equal(editable.identity_header.mode, 'inherit');
    assert.deepEqual(editable.models, []);
    assert.equal(editable.id, 'ep-1');
});

check('editing preserves keys the editor does not know about', () => {
    const editable = toEditableConnection({ id: 'ep-1', custom_future_field: 'keep me' });
    assert.equal(editable.custom_future_field, 'keep me');
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`ok   ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL ${name}`);
        console.log(`     ${error.message}`);
        failed += 1;
    }
}

console.log(`\n${passed}/${passed + failed} runtime checks passed`);
process.exit(failed > 0 ? 1 : 0);
