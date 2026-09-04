// modelSelection.ts
// Types, API wrappers and pure logic for the classic embedding and image-generation
// deployment catalogs.
//
// These predate connections and work nothing like them. A connection publishes several
// models and is picked per conversation; an embedding or image route has exactly one
// deployment in force for the whole application, and it is stored as
// `{selected: [...], all: [...]}` -- the deployments discovery last returned, plus the
// one in use.
//
// The list is not authoritative. It is a cache of what Azure answered the last time
// someone pressed Fetch, so it can name a deployment that has since been removed, and it
// is empty until someone presses Fetch at all. Both cases are ordinary rather than
// errors, and the helpers here exist so the component can say which one it is in.
//
// Discovery reuses `/api/models/embedding` and `/api/models/image`, the admin-gated
// routes the classic page already calls. Persistence goes through
// `/api/v2/admin/model-selection/<kind>`, because the stored value is a dict and the
// settings PATCH refuses it.

import { api } from './apiClient';

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

/** Which catalog is being edited. Matches `MODEL_CATALOG_KINDS` on the server. */
export type ModelCatalogKind = 'embedding' | 'image';

/** One deployment, in the shape both admin interfaces store. */
export interface ModelDeployment {
    deploymentName: string;
    modelName?: string;
}

export interface ModelCatalog {
    kind: ModelCatalogKind;
    selected: ModelDeployment | null;
    models: ModelDeployment[];
    /** The admin-gated discovery route for this catalog, named by the server. */
    discovery_path?: string;
}

export interface ModelDiscoveryResponse {
    models?: Array<Record<string, unknown>>;
    error?: string;
}

/* -------------------------------------------------------------------------- */
/* Pure logic                                                                  */
/* -------------------------------------------------------------------------- */

/** Read one deployment from an API response, or null when it is not addressable. */
export function toModelDeployment(value: unknown): ModelDeployment | null {
    if (!value || typeof value !== 'object') {
        return null;
    }
    const source = value as Record<string, unknown>;
    const deploymentName = String(source.deploymentName ?? '').trim();
    if (!deploymentName) {
        return null;
    }
    const modelName = String(source.modelName ?? '').trim();
    return modelName ? { deploymentName, modelName } : { deploymentName };
}

/**
 * Read a discovered list, dropping anything that cannot be sent as a deployment name.
 *
 * A duplicate deployment name is collapsed rather than listed twice: the name is the
 * whole identity here, so two rows carrying it would be two ways to choose one thing.
 */
export function toModelDeployments(value: unknown): ModelDeployment[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const seen = new Set<string>();
    const deployments: ModelDeployment[] = [];
    for (const entry of value) {
        const deployment = toModelDeployment(entry);
        if (!deployment || seen.has(deployment.deploymentName)) {
            continue;
        }
        seen.add(deployment.deploymentName);
        deployments.push(deployment);
    }
    return deployments;
}

/** How a deployment reads in the list: the deployment, then the model when they differ. */
export function deploymentLabel(deployment: ModelDeployment): string {
    if (deployment.modelName && deployment.modelName !== deployment.deploymentName) {
        return `${deployment.deploymentName} (${deployment.modelName})`;
    }
    return deployment.deploymentName;
}

/** Where a deployment sits in the list, or -1. Deployment name is the identity. */
export function findDeploymentIndex(
    deployments: ModelDeployment[],
    selected: ModelDeployment | null,
): number {
    if (!selected) {
        return -1;
    }
    return deployments.findIndex(
        (deployment) => deployment.deploymentName === selected.deploymentName,
    );
}

/**
 * Merge a fresh discovery over the stored catalog.
 *
 * The selection survives only if the deployment is still there. Keeping one that Azure
 * no longer reports would leave the page showing a deployment in use that every request
 * is about to fail on, and the server refuses it anyway, so it is dropped here where the
 * reason can still be explained.
 */
export function applyDiscoveredModels(
    discovered: ModelDeployment[],
    selected: ModelDeployment | null,
): { models: ModelDeployment[]; selected: ModelDeployment | null; droppedSelection: boolean } {
    const index = findDeploymentIndex(discovered, selected);
    return {
        models: discovered,
        selected: index >= 0 ? discovered[index] : null,
        droppedSelection: Boolean(selected) && index < 0,
    };
}

/**
 * Whether the stored selection names something no longer in the list.
 *
 * Worth stating separately from "nothing selected": one means nobody has chosen yet, the
 * other means the choice stopped resolving, and only the second needs acting on.
 */
export function isDanglingSelection(
    deployments: ModelDeployment[],
    selected: ModelDeployment | null,
): boolean {
    return Boolean(selected) && findDeploymentIndex(deployments, selected) < 0;
}

/**
 * The saved settings each catalog's discovery reads.
 *
 * Discovery addresses the resource through Azure Resource Manager using the *stored*
 * endpoint, subscription id and resource group, not whatever is on screen. Fetching
 * after editing one of these but before saving therefore lists the previous resource's
 * deployments, which reads as a wrong answer rather than as a stale question. The
 * classic page carries this as fine print under the button; here it is checkable.
 */
export const DISCOVERY_SETTING_KEYS: Record<ModelCatalogKind, string[]> = {
    embedding: [
        'azure_openai_embedding_endpoint',
        'azure_openai_embedding_subscription_id',
        'azure_openai_embedding_resource_group',
    ],
    image: [
        'azure_openai_image_gen_endpoint',
        'azure_openai_image_gen_subscription_id',
        'azure_openai_image_gen_resource_group',
    ],
};

/** Whether an unsaved edit would make a fetch ask about the wrong resource. */
export function hasUnsavedDiscoveryEdits(
    kind: ModelCatalogKind,
    draftKeys: string[],
): boolean {
    return DISCOVERY_SETTING_KEYS[kind].some((key) => draftKeys.includes(key));
}

/* -------------------------------------------------------------------------- */
/* API                                                                         */
/* -------------------------------------------------------------------------- */

const BASE = '/api/v2/admin/model-selection';

/** The admin-gated discovery route for each catalog, shared with the classic page. */
export const DISCOVERY_PATHS: Record<ModelCatalogKind, string> = {
    embedding: '/api/models/embedding',
    image: '/api/models/image',
};

export const fetchModelCatalog = (kind: ModelCatalogKind, signal?: AbortSignal) =>
    api.get<ModelCatalog>(`${BASE}/${kind}`, signal);

export const saveModelCatalog = (
    kind: ModelCatalogKind,
    payload: { selected: ModelDeployment | null; models: ModelDeployment[] },
) => api.put<ModelCatalog>(`${BASE}/${kind}`, payload);

/** List the deployments the configured resource currently exposes. */
export const discoverCatalogModels = (kind: ModelCatalogKind, signal?: AbortSignal) =>
    api.get<ModelDiscoveryResponse>(DISCOVERY_PATHS[kind], signal);
