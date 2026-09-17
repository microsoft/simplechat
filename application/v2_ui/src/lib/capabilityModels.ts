// capabilityModels.ts
// Shared defaults use saved references, never a second copy of connection credentials.

import { api } from './apiClient';
import {
    toDefaultModelSelection,
    type ConnectionMigrationNotice,
    type DefaultModelChoice,
    type DefaultModelSelection,
    type EmbeddingPolicy,
    type ImplementedCapability,
    type ModelCapabilityStatus,
} from './modelConnections';

export interface CapabilityModelChoice extends DefaultModelChoice {
    capability: ModelCapabilityStatus;
    embedding_policy?: EmbeddingPolicy;
}

export interface EmbeddingCompatibility {
    status: string;
    message: string;
    dimensions?: number;
    profile_id?: string;
}

export interface CapabilityModelsResponse {
    capability: ImplementedCapability;
    selection: DefaultModelSelection;
    choices: CapabilityModelChoice[];
    reason: string | null;
    enabled: boolean;
    migration: ConnectionMigrationNotice | null;
    compatibility?: EmbeddingCompatibility;
}

export const CAPABILITY_DETAILS = {
    chat: {
        label: 'Default chat model',
        id: 'chat-default-model',
        modelKind: 'chat',
        independence: 'Only chat models are listed. Image-only and embedding-only models stay in AI Connections.',
    },
    image_generation: {
        label: 'Default image model',
        id: 'image-generation-default-model',
        modelKind: 'image',
        independence: 'Chat, images and embeddings have independent defaults. Image generation does not require enabling chat connections.',
    },
    embeddings: {
        label: 'Default embedding model',
        id: 'embedding-default-model',
        modelKind: 'embedding',
        independence: 'One global embedding default serves personal, group and public search and fact memory, independently of chat and images.',
    },
} as const;

function record(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function positiveInteger(value: unknown): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

export function toEmbeddingPolicy(value: unknown): EmbeddingPolicy | undefined {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    const source = record(value);
    const policy: EmbeddingPolicy = {};
    for (const key of [
        'dimensions', 'default_dimensions', 'request_dimensions', 'min_dimensions', 'max_dimensions',
        'max_input_tokens', 'max_batch_size', 'max_batch_tokens',
    ] as const) {
        if (positiveInteger(source[key])) policy[key] = source[key];
    }
    for (const key of ['supports_dimensions', 'requires_input_type'] as const) {
        if (typeof source[key] === 'boolean') policy[key] = source[key];
    }
    if (source.tokenizer === 'cl100k_base' || source.tokenizer === 'conservative') policy.tokenizer = source.tokenizer;
    if (source.api === 'openai' || source.api === 'unsupported') policy.api = source.api;
    if (Array.isArray(source.allowed_dimensions)) {
        policy.allowed_dimensions = source.allowed_dimensions.filter(positiveInteger);
    }
    return policy;
}

export function embeddingPolicyDescription(policy: EmbeddingPolicy | undefined): string {
    if (!policy) return 'Embedding dimensions and input limits are resolved when the connection is saved.';
    const dimensions = policy.dimensions ?? policy.default_dimensions;
    const parts = [
        dimensions ? `${dimensions.toLocaleString()} dimensions` : 'Dimensions not configured',
        policy.max_input_tokens ? `${policy.max_input_tokens.toLocaleString()} input tokens per text` : 'Input token limit not configured',
    ];
    if (policy.api === 'unsupported' || policy.requires_input_type) {
        parts.push('This model requires an operation contract not supported by the current embedding API.');
    }
    return parts.join(' · ');
}

export function toMigrationNotice(value: unknown): ConnectionMigrationNotice | null {
    const source = record(value);
    if (!text(source.status)) {
        return null;
    }
    return {
        status: text(source.status),
        message: text(source.message),
        ...(typeof source.imported_connections === 'number'
            ? { imported_connections: source.imported_connections } : {}),
    };
}

export function toCapabilityModelsResponse(
    value: unknown,
    capability: ImplementedCapability,
): CapabilityModelsResponse {
    const source = record(value);
    if (source.capability !== capability || !Array.isArray(source.choices) || typeof source.enabled !== 'boolean') {
        throw new Error('The capability model list could not be read. Reload and try again.');
    }
    const choices: CapabilityModelChoice[] = [];
    for (const item of source.choices) {
        const choice = record(item);
        const support = record(choice.capability);
        if (!text(choice.endpoint_id) || !text(choice.model_id) || support.supported !== true || support.available === false) {
            continue;
        }
        choices.push({
            endpointId: text(choice.endpoint_id),
            modelId: text(choice.model_id),
            provider: text(choice.provider),
            connectionName: text(choice.connection_name) || 'Connection',
            modelLabel: text(choice.label) || text(choice.deployment_name) || text(choice.model_id),
            deploymentName: text(choice.deployment_name),
            capability: {
                supported: true,
                available: support.available !== false,
                source: text(support.source) || 'unknown',
                reason: text(support.reason),
                api: text(support.api),
            },
            ...(capability === 'embeddings' ? { embedding_policy: toEmbeddingPolicy(choice.embedding_policy) } : {}),
        });
    }
    const compatibility = record(source.compatibility);
    return {
        capability,
        selection: toDefaultModelSelection(source.selection),
        choices,
        reason: text(source.reason) || null,
        enabled: source.enabled,
        migration: toMigrationNotice(source.migration),
        ...(capability === 'embeddings' && text(compatibility.status) ? {
            compatibility: {
                status: text(compatibility.status),
                message: text(compatibility.message),
                ...(positiveInteger(compatibility.dimensions) ? { dimensions: compatibility.dimensions } : {}),
                ...(text(compatibility.profile_id) ? { profile_id: text(compatibility.profile_id) } : {}),
            },
        } : {}),
    };
}

export function capabilityDescription(status: ModelCapabilityStatus | undefined, capability?: ImplementedCapability): string {
    if (!status) {
        return 'Not checked yet. Save the connection to resolve capabilities.';
    }
    if (!status.supported) {
        return status.reason || 'Not supported.';
    }
    const operation = capability === 'embeddings'
        ? 'Text embeddings'
        : status.api === 'responses'
        ? 'Image output through the Responses image tool'
        : status.api === 'images'
          ? 'Direct image output'
          : 'Text output';
    const source = status.source === 'legacy'
        ? 'legacy compatibility, not verified'
        : status.source === 'declared'
          ? 'administrator-declared'
          : status.source;
    return `${operation} · ${source || 'support source unknown'}${status.available === false && status.reason ? ` · ${status.reason}` : ''}`;
}

const BASE = '/api/v2/admin/capability-models';

export async function fetchCapabilityModels(capability: ImplementedCapability, signal?: AbortSignal) {
    return toCapabilityModelsResponse(await api.get<unknown>(`${BASE}/${capability}`, signal), capability);
}

export async function saveCapabilityModel(capability: ImplementedCapability, selection: DefaultModelSelection) {
    return toCapabilityModelsResponse(await api.put<unknown>(`${BASE}/${capability}`, { selection }), capability);
}

export interface ModelOperationTestResponse {
    success?: boolean;
    message?: string;
    error?: string;
    dimensions?: number;
    code?: string;
}

export const testCapabilityModel = (capability: 'image_generation' | 'embeddings', selection: DefaultModelSelection) =>
    api.post<ModelOperationTestResponse>(
        '/api/v2/admin/settings/test-connection',
        { test_type: capability === 'embeddings' ? 'embedding' : 'image', selection },
    );

export const testImageModel = (selection: DefaultModelSelection) => testCapabilityModel('image_generation', selection);
export const testEmbeddingModel = (selection: DefaultModelSelection) => testCapabilityModel('embeddings', selection);
