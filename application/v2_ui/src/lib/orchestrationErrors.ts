// orchestrationErrors.ts

import { ApiError } from './apiClient';

export const LEGACY_PLAN_ERROR_CODE = 'legacy_plan';

function payloadRecord(error: ApiError): Record<string, unknown> {
    return error.payload && typeof error.payload === 'object' && !Array.isArray(error.payload)
        ? error.payload as Record<string, unknown>
        : {};
}

export function isLegacyPlanError(error: unknown): error is ApiError {
    return error instanceof ApiError
        && error.status === 409
        && payloadRecord(error).code === LEGACY_PLAN_ERROR_CODE;
}

export function legacyPlanErrorMessage(error: unknown): string | null {
    if (!isLegacyPlanError(error)) return null;
    const payload = payloadRecord(error);
    return typeof payload.error === 'string' && payload.error ? payload.error : error.message;
}
