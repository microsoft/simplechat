// test_v2_agent_model_exclusivity_logic.ts
// Behavioural checks for the V2 agent / model / reasoning exclusivity.
//
// Version: 0.261.034
// Implemented in: 0.261.034
//
// The V2 interface has no unit test runner, and adding one would pull in a test framework for
// a single file. This is bundled with the esbuild that Vite already brings in and run under
// node by test_v2_agent_model_exclusivity.py, which skips it when the front-end toolchain has
// not been installed.
//
// What it protects, in rough order of importance:
//
//   - An agent selection must never travel with a model identity. The server reads
//     `model_id` / `model_endpoint_id` alongside `agent_info` as a deliberate override, so its
//     agent default-model handling never runs. That is a wrong-model bug, not a tidiness one.
//   - An agent selection must never travel with a reasoning level, which only reaches the
//     direct-model path.
//   - With no agent, the full four-field model identity must still be sent, unchanged. That is
//     the guarantee an earlier fix established and this change must not regress.
//   - A selection key that no longer matches the catalog must degrade to model mode rather
//     than suppressing the model on the strength of an agent the server cannot resolve.

import {
    buildSelectionFields,
    hasResolvableAgent,
} from '../application/v2_ui/src/lib/chatRequestSelection';
import { resolveGating } from '../application/v2_ui/src/lib/composerGating';
import type { ModelCatalogEntry } from '../application/v2_ui/src/lib/models';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/* ---- fixtures ---- */

/** Shaped like `_build_chat_model_catalog` output, including the per-endpoint selection key. */
const MODELS: ModelCatalogEntry[] = [
    {
        selection_key: 'personal::endpoint-a:gpt-5',
        model_id: 'gpt-5',
        deployment_name: 'gpt-5-deploy',
        endpoint_id: 'endpoint-a',
        provider: 'azure_openai',
        display_name: 'GPT-5 (East)',
    },
    {
        // The same deployment name on a second endpoint: why the key is not the name.
        selection_key: 'personal::endpoint-b:gpt-5',
        model_id: 'gpt-5',
        deployment_name: 'gpt-5-deploy',
        endpoint_id: 'endpoint-b',
        provider: 'azure_openai',
        display_name: 'GPT-5 (West)',
    },
];

const AGENTS: Record<string, unknown>[] = [
    {
        id: 'agent-1',
        name: 'researcher',
        display_name: 'Researcher',
        is_global: false,
        is_group: true,
        group_id: 'group-9',
        group_name: 'Research',
    },
];

const BASE_GATING = {
    prompt: '',
    features: {
        enable_web_search: true,
        enable_image_generation: true,
        enable_chat_file_uploads: true,
    } as Record<string, unknown>,
    webSearchActive: false,
    urlAccessActive: false,
    imageGenerationActive: false,
    agentActive: false,
};

const MODEL_FIELDS = [
    'model_deployment',
    'model_id',
    'model_endpoint_id',
    'model_provider',
] as const;

/* ---- an agent suppresses the model identity and the reasoning level ---- */

{
    const fields = buildSelectionFields({
        agents: AGENTS,
        models: MODELS,
        agentSelection: 'agent-1',
        modelDeployment: 'personal::endpoint-a:gpt-5',
        reasoningEffort: 'high',
    });

    check('an agent selection produces agent_info', Boolean(fields.agent_info));

    const leaked = MODEL_FIELDS.filter((field) => field in fields);
    check(
        'an agent selection sends no model identity at all',
        leaked.length === 0,
        leaked,
    );
    check(
        'an agent selection sends no reasoning level',
        !('reasoning_effort' in fields),
        fields,
    );
    check(
        'nothing but agent_info is sent for an agent',
        Object.keys(fields).join(',') === 'agent_info',
        Object.keys(fields),
    );

    // The seven fields the route resolves an agent against.
    const info = fields.agent_info as Record<string, unknown>;
    check(
        'agent_info keeps the full identity the route reads',
        info.id === 'agent-1' &&
            info.name === 'researcher' &&
            info.display_name === 'Researcher' &&
            info.is_global === false &&
            info.is_group === true &&
            info.group_id === 'group-9' &&
            info.group_name === 'Research',
        info,
    );
}

/* ---- without an agent, the model identity is unchanged ---- */

{
    const fields = buildSelectionFields({
        agents: AGENTS,
        models: MODELS,
        modelDeployment: 'personal::endpoint-b:gpt-5',
        reasoningEffort: 'medium',
    });

    check('no agent means no agent_info', !('agent_info' in fields));
    check(
        'the endpoint the user actually picked is what is sent',
        fields.model_endpoint_id === 'endpoint-b',
        fields,
    );
    check(
        'the deployment name is resolved from the catalog, not the selection key',
        fields.model_deployment === 'gpt-5-deploy',
        fields,
    );
    check('the model id travels with its endpoint', fields.model_id === 'gpt-5', fields);
    check('the provider travels too', fields.model_provider === 'azure_openai', fields);
    check('the reasoning level is sent', fields.reasoning_effort === 'medium', fields);
}

/* ---- an agent selection the catalog cannot resolve must not suppress the model ---- */

{
    const fields = buildSelectionFields({
        agents: AGENTS,
        models: MODELS,
        agentSelection: 'agent-that-was-deleted',
        modelDeployment: 'personal::endpoint-a:gpt-5',
        reasoningEffort: 'low',
    });

    check('an unresolvable agent produces no agent_info', !('agent_info' in fields));
    check(
        'an unresolvable agent falls back to the model, rather than to nothing',
        fields.model_endpoint_id === 'endpoint-a' &&
            fields.model_deployment === 'gpt-5-deploy',
        fields,
    );
    check(
        'an unresolvable agent leaves the reasoning level in place',
        fields.reasoning_effort === 'low',
        fields,
    );
    check(
        'the composer agrees the agent is not in force',
        hasResolvableAgent(AGENTS, 'agent-that-was-deleted') === false,
    );
    check(
        'a resolvable agent is reported as in force',
        hasResolvableAgent(AGENTS, 'agent-1') === true,
    );
    check('no selection is not an agent', hasResolvableAgent(AGENTS, undefined) === false);
}

/* ---- an empty request stays empty ---- */

{
    const fields = buildSelectionFields({ agents: AGENTS, models: MODELS });
    check(
        'no selection at all sends no routing fields',
        Object.keys(fields).length === 0,
        fields,
    );
}

/* ---- the toolbar reflects the same rule ---- */

{
    const withAgent = resolveGating({ ...BASE_GATING, agentActive: true });
    const withoutAgent = resolveGating({ ...BASE_GATING, agentActive: false });
    const withImage = resolveGating({ ...BASE_GATING, imageGenerationActive: true });

    check('an agent marks the model picker overridden', withAgent.modelPickerInactive);
    check(
        'the model picker is still shown, not removed',
        withAgent.showModelPicker,
        withAgent,
    );
    check('an agent hides the reasoning picker', withAgent.showReasoning === false);

    check('no agent leaves the model picker live', withoutAgent.modelPickerInactive === false);
    check('no agent leaves the reasoning picker available', withoutAgent.showReasoning);

    // Matches updateReasoningButtonVisibility in static/js/chat/chat-reasoning.js.
    check('image generation hides the reasoning picker', withImage.showReasoning === false);
    check(
        'image generation still hides the model picker outright',
        withImage.showModelPicker === false,
    );
    check(
        'image generation alone does not mark the model picker merely overridden',
        withImage.modelPickerInactive === false,
    );

    // Nothing else in the gating rule may move because an agent was picked.
    const unrelated = (
        ['showDocuments', 'showWeb', 'showImage', 'showUrlAccess', 'showDeepResearch', 'showFileUpload', 'disabledByImageGeneration'] as const
    ).filter((key) => withAgent[key] !== withoutAgent[key]);
    check(
        'selecting an agent changes nothing else in the toolbar',
        unrelated.length === 0,
        unrelated,
    );
}

if (failures > 0) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
}
