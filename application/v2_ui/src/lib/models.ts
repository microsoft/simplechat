// models.ts
// Identifying a selected model, and shaping it the way the chat endpoint expects.
//
// A model is NOT identified by its deployment name alone. When
// `enable_multi_model_endpoints` is on, the same deployment name can exist on several
// endpoints, so the server resolves a selection from four fields together
// (`resolve_streaming_multi_endpoint_gpt_config` in route_backend_chats.py):
//
//     model_endpoint_id, model_id, model_provider, model_deployment
//
// Sending only `model_deployment` makes that resolver return None, and the request silently
// falls back to the legacy single-endpoint client — a different endpoint from the one the
// user picked, with no error. That is why the picker has to carry the whole identity.
//
// The server also validates the combination:
//   - `model_id` without `model_endpoint_id` is rejected outright.
//   - `model_endpoint_id` requires `model_id` or `model_deployment`.
// So the fields are sent as a set or not at all.

/** Catalog record fields, as produced by `_build_chat_model_catalog`. */
export interface ModelCatalogEntry {
    selection_key?: string;
    model_id?: string;
    deployment_name?: string;
    endpoint_id?: string;
    provider?: string;
    display_name?: string;
    option_value?: string;
    [key: string]: unknown;
}

/** The request fields that together identify a model. */
export interface ModelIdentity {
    model_deployment?: string;
    model_id?: string;
    model_endpoint_id?: string;
    model_provider?: string;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * Stable key for a model in the picker.
 *
 * `selection_key` is `scope:scopeId:endpointId:modelId`, so it is unique across endpoints
 * where a deployment name is not.
 */
export function modelSelectionKey(model: ModelCatalogEntry | undefined): string {
    if (!model) {
        return '';
    }
    return (
        text(model.selection_key) ||
        text(model.deployment_name) ||
        text(model.model_id) ||
        text(model.option_value)
    );
}

export function findModel(
    models: ModelCatalogEntry[] | undefined,
    selection: string | undefined,
): ModelCatalogEntry | undefined {
    if (!selection || !models?.length) {
        return undefined;
    }
    return models.find((model) => modelSelectionKey(model) === selection);
}

/**
 * Build the request fields for a selected model.
 *
 * Mirrors the mapping the classic client uses (chat-messages.js): deployment from
 * `deployment_name`, id from `model_id`, endpoint from `endpoint_id`, provider from
 * `provider`.
 *
 * `model_id` and `model_endpoint_id` are only included together, because the server rejects
 * an id without an endpoint.
 */
export function buildModelIdentity(model: ModelCatalogEntry | undefined): ModelIdentity {
    if (!model) {
        return {};
    }

    const deployment = text(model.deployment_name) || text(model.option_value);
    const modelId = text(model.model_id);
    const endpointId = text(model.endpoint_id);
    const provider = text(model.provider);

    const identity: ModelIdentity = {};

    if (deployment) {
        identity.model_deployment = deployment;
    }

    if (endpointId) {
        identity.model_endpoint_id = endpointId;
        if (modelId) {
            identity.model_id = modelId;
        }
        if (provider) {
            identity.model_provider = provider;
        }
    } else if (!deployment && modelId) {
        // No endpoint to pair it with, so the id can only be used as the deployment.
        identity.model_deployment = modelId;
    }

    return identity;
}

/** Convenience for request construction: selection key straight to request fields. */
export function modelIdentityForSelection(
    models: ModelCatalogEntry[] | undefined,
    selection: string | undefined,
): ModelIdentity {
    return buildModelIdentity(findModel(models, selection));
}
