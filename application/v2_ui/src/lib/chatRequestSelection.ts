// chatRequestSelection.ts
// Turning the composer's model / agent / reasoning selections into request fields.
//
// The rule this file exists for: AN AGENT WINS. When one is selected it answers with its own
// deployment (`azure_openai_gpt_deployment`, read by semantic_kernel_loader.py), and
// `reasoning_effort` only ever reaches the direct-model path
// (`_resolve_reasoning_effort_for_model` in route_backend_chats.py). So neither the model
// identity nor the reasoning level can be acted on, and sending them is not merely redundant:
//
//     should_use_default_model = (
//         _has_chat_agent_selection(request_agent_info)
//         and settings.get('enable_multi_model_endpoints', False)
//         and not data.get('model_id')
//         and not data.get('model_endpoint_id')
//     )
//     (route_backend_chats.py)
//
// A model identity sent alongside `agent_info` reads to the server as a deliberate override,
// so the agent's own default-model handling never runs. The server has that handling for
// every configuration -- the multi-endpoint default, the first APIM deployment, and the
// configured default model -- and a request that always names a model never reaches any of it.
//
// The classic client does send a model alongside an agent, because `getCurrentModelSelection`
// reads the model select without checking that agent mode has hidden it. That is the bug
// being fixed here rather than the behaviour being matched.

import { agentInfoForSelection } from './agents';
import { modelIdentityForSelection, type ModelCatalogEntry } from './models';
import { requestReasoningEffort } from './reasoning';
import type { Json } from './types';

export interface SelectionInput {
    /** Agent catalog from bootstrap. */
    agents?: Record<string, unknown>[];
    /** Model catalog from bootstrap. */
    models?: ModelCatalogEntry[];
    /** Picker selection key for the agent, if one is chosen. */
    agentSelection?: string;
    /** Picker selection key for the model. Not a deployment name. */
    modelDeployment?: string;
    reasoningEffort?: string;
}

/** The mutually exclusive halves of a chat request's routing. */
export interface SelectionFields {
    agent_info?: Json;
    model_deployment?: string;
    model_id?: string;
    model_endpoint_id?: string;
    model_provider?: string;
    reasoning_effort?: string;
}

/**
 * Build the routing fields for a chat request.
 *
 * Resolution is against the catalog, not the raw selection key, so a selection left over from
 * a catalog that no longer contains it degrades to model mode rather than producing a request
 * that claims an agent the server cannot find.
 */
export function buildSelectionFields(input: SelectionInput): SelectionFields {
    const agentInfo = input.agentSelection
        ? agentInfoForSelection(input.agents, input.agentSelection)
        : null;

    if (agentInfo) {
        return { agent_info: agentInfo as Json };
    }

    const fields: SelectionFields = {
        ...modelIdentityForSelection(input.models, input.modelDeployment),
    };

    // `none` is a real choice in the picker but not a value the endpoint takes, so it is
    // dropped here rather than at each caller: this is where a request's reasoning level is
    // decided, and the classic client's getCurrentReasoningEffort() returns null for it.
    const reasoningEffort = requestReasoningEffort(input.reasoningEffort);
    if (reasoningEffort) {
        fields.reasoning_effort = reasoningEffort;
    }

    return fields;
}

/**
 * Whether a selection resolves to an agent the server can act on.
 *
 * The composer greys out the model picker on this answer rather than on the raw selection
 * key, so an unresolvable agent leaves the model picker looking exactly as live as it is.
 */
export function hasResolvableAgent(
    agents: Record<string, unknown>[] | undefined,
    agentSelection: string | undefined,
): boolean {
    return Boolean(agentSelection && agentInfoForSelection(agents, agentSelection));
}
