// orchestrationApproval.ts

import type { ApprovalMode } from './orchestration';
import type { OrchestrationBootstrap } from './types';

type ApprovalPolicy = Pick<
    OrchestrationBootstrap,
    'default_approval_mode' | 'allow_user_approval_override'
>;

export function isApprovalMode(value: unknown): value is ApprovalMode {
    return value === 'manual' || value === 'timed' || value === 'auto';
}

export function resolveOrchestrationApproval(
    policy: ApprovalPolicy | undefined,
    preference: unknown,
): { mode: ApprovalMode; invalidPreference: boolean } {
    const defaultMode = isApprovalMode(policy?.default_approval_mode)
        ? policy.default_approval_mode
        : 'manual';
    const overridable = Boolean(policy?.allow_user_approval_override);

    return {
        mode: overridable && isApprovalMode(preference) ? preference : defaultMode,
        invalidPreference: overridable && preference !== undefined && !isApprovalMode(preference),
    };
}
