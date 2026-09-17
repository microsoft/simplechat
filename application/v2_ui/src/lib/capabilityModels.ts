// capabilityModels.ts
// Shared defaults use saved references, never a second copy of connection credentials.

import { api } from './apiClient';
import {
    toDefaultModelSelection,
    type ConnectionMigrationNotice,
    type DefaultModelChoice,
    type DefaultModelSelection,
    type ImplementedCapability,
    type ModelCapabilityStatus,
} from './modelConnections';
import type { ImageEditCapability } from './types';

/** Image-only metadata is projected by the server, not inferred from a connection's provider. */
export interface ImageModelCapabilityStatus extends ModelCapabilityStatus {
    provider_label?: string;
    cloud_label?: string;
    availability?: ImageEditCapability['availability'];
    availability_reason?: string;
    editing?: boolean;
    masking?: boolean;
    mode?: ImageEditCapability['mode'];
    sizes?: string[];
    qualities?: string[];
    backgrounds?: string[];
    lifecycle?: string;
    model_name?: string;
    publisher?: string;
}

export interface CapabilityModelChoice extends DefaultModelChoice {
    capability: ImageModelCapabilityStatus;
}

export interface CapabilityModelsResponse {
    capability: ImplementedCapability;
    selection: DefaultModelSelection;
    choices: CapabilityModelChoice[];
    reason: string | null;
    enabled: boolean;
    migration: ConnectionMigrationNotice | null;
}

function record(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function options(value: unknown): string[] {
    return Array.isArray(value) ? [...new Set(value.map(text).filter(Boolean))] : [];
}

/** Unknown availability is a warning; unknown operations are not permission for inference. */
export function canGenerateImage(status: ImageModelCapabilityStatus | undefined): boolean {
    if (!status?.supported || status.availability === 'unavailable'
        || !['images', 'responses', 'mai', 'flux'].includes(status.api ?? '')) {
        return false;
    }
    return status.mode === 'masked' && status.editing === true && status.masking === true
        || status.mode === 'edit' && status.editing === true && status.masking === false
        || status.mode === 'regenerate' && status.editing === false && status.masking === false;
}

function imageStatusFields(source: Record<string, unknown>): ImageModelCapabilityStatus {
    return {
        supported: source.supported === true,
        source: text(source.source) || 'unknown',
        reason: text(source.reason),
        api: text(source.api),
        provider_label: text(source.provider_label),
        cloud_label: text(source.cloud_label),
        availability: source.availability === 'documented' || source.availability === 'unavailable'
            ? source.availability
            : 'unknown',
        availability_reason: text(source.availability_reason),
        editing: source.editing === true,
        masking: source.masking === true,
        mode: typeof source.editing === 'boolean' && typeof source.masking === 'boolean'
            && (source.mode === 'masked' || source.mode === 'edit' || source.mode === 'regenerate')
            ? source.mode
            : 'unavailable',
        sizes: options(source.sizes),
        qualities: options(source.qualities),
        backgrounds: options(source.backgrounds),
        lifecycle: text(source.lifecycle),
        model_name: text(source.model_name),
        publisher: text(source.publisher),
    };
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
        if (!text(choice.endpoint_id) || !text(choice.model_id) || support.supported !== true) {
            continue;
        }
        choices.push({
            endpointId: text(choice.endpoint_id),
            modelId: text(choice.model_id),
            provider: text(choice.provider),
            connectionName: text(choice.connection_name) || 'Connection',
            modelLabel: text(choice.label) || text(choice.deployment_name) || text(choice.model_id),
            deploymentName: text(choice.deployment_name),
            capability: capability === 'image_generation' ? imageStatusFields(support) : {
                supported: true,
                source: text(support.source) || 'unknown',
                reason: text(support.reason),
                api: text(support.api),
            },
        });
    }
    return {
        capability,
        selection: toDefaultModelSelection(source.selection),
        choices,
        reason: text(source.reason) || null,
        enabled: source.enabled,
        migration: toMigrationNotice(source.migration),
    };
}

export function capabilityDescription(status: ModelCapabilityStatus | undefined): string {
    if (!status) {
        return 'Not checked yet. Save the connection to resolve capabilities.';
    }
    if (!status.supported) {
        return status.reason || 'Not supported.';
    }
    const operation = status.api === 'responses'
        ? 'Image output through the Responses image tool'
        : status.api === 'images'
          ? 'Direct image output'
          : status.api === 'mai'
            ? 'MAI image output'
            : status.api === 'flux'
              ? 'FLUX image output'
              : status.api === 'chat' || (!status.api && !('mode' in status))
                ? 'Text output'
                : 'Unrecognized output operation';
    const source = status.source === 'legacy'
        ? 'legacy compatibility, not verified'
        : status.source === 'declared'
          ? 'administrator-declared'
          : status.source;
    return `${operation} · ${source || 'support source unknown'}`;
}

const BASE = '/api/v2/admin/capability-models';

export async function fetchCapabilityModels(capability: ImplementedCapability, signal?: AbortSignal) {
    return toCapabilityModelsResponse(await api.get<unknown>(`${BASE}/${capability}`, signal), capability);
}

export async function saveCapabilityModel(capability: ImplementedCapability, selection: DefaultModelSelection) {
    return toCapabilityModelsResponse(await api.put<unknown>(`${BASE}/${capability}`, { selection }), capability);
}

export const testImageModel = (selection: DefaultModelSelection) =>
    api.post<{ success?: boolean; message?: string; error?: string }>(
        '/api/v2/admin/settings/test-connection',
        { test_type: 'image', selection },
    );
