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

export interface CapabilityModelChoice extends DefaultModelChoice {
    capability: ModelCapabilityStatus;
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
            capability: {
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
          : 'Text output';
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
