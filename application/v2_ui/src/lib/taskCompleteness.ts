// taskCompleteness.ts
// Public check metadata only; never infer a successful runtime stage from a step failure.
import type { OrchestrationStep } from './orchestration';

export interface CheckStage {
    id: 'prepare' | 'format' | 'semantic';
    label: string;
    status: 'completed' | 'running' | 'failed' | 'pending' | 'skipped';
}

export function completenessReport(value: unknown): Record<string, unknown> | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const report = value as Record<string, unknown>;
    return (report.version === 1 || report.version === 2) && typeof report.status === 'string'
        ? report : null;
}

export function completenessActivity(value: unknown): string | null {
    const report = completenessReport(value);
    if (!report) return null;
    switch (report.status) {
        case 'checking': return Number(report.corrections) > 0 ? 'Checking again'
            : report.check_kind === 'deterministic' ? 'Validating format' : 'Checking answer';
        case 'repairing_assessment': return 'Checking answer';
        case 'correcting': return 'Adjusting answer';
        case 'complete': return report.semantic_enabled === false ? 'Required checks complete'
            : Number(report.corrections) > 0 ? 'Reviewed after adjustment' : 'Review complete';
        case 'incomplete': return 'Answer needs revision';
        case 'verification_unavailable': return "Checking couldn't finish";
        case 'disabled': return 'Semantic review off';
        default: return null;
    }
}

export function completenessStages(value: unknown): CheckStage[] {
    const report = completenessReport(value);
    if (report?.version !== 2 || !Array.isArray(report.stages)) return [];
    return report.stages.flatMap((item) => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) return [];
        const stage = item as CheckStage;
        if (!['prepare', 'format', 'semantic'].includes(stage.id)
            || !['completed', 'running', 'failed', 'pending', 'skipped'].includes(stage.status)
            || typeof stage.label !== 'string') return [];
        return [{ id: stage.id, status: stage.status, label: stage.label.slice(0, 180) }];
    });
}

function candidateRevision(report: Record<string, unknown> | null): number | null {
    if (!Array.isArray(report?.stages)) return null;
    const revisions = report.stages.flatMap((stage) => {
        if (!stage || typeof stage !== 'object' || Array.isArray(stage)) return [];
        const revision = (stage as Record<string, unknown>).candidate_revision;
        return typeof revision === 'number' && Number.isInteger(revision) && revision >= 0 ? [revision] : [];
    });
    return revisions.length ? Math.max(...revisions) : null;
}

/** Late progress must not certify an older candidate or reopen a settled check. */
export function canAdoptCompletenessReport(current: unknown, next: unknown): boolean {
    const previous = completenessReport(current);
    const incoming = completenessReport(next);
    if (!incoming) return false;
    if (!previous) return true;
    const oldRevision = candidateRevision(previous);
    const newRevision = candidateRevision(incoming);
    if (oldRevision !== null && newRevision !== null && newRevision < oldRevision) return false;
    if (oldRevision === newRevision && ['complete', 'disabled'].includes(String(previous.status))
        && ['checking', 'repairing_assessment', 'correcting'].includes(String(incoming.status))) return false;
    return true;
}

/** Proposed stages are explicitly labelled planned, never substituted for saved runtime history. */
export function plannedCheckStages(step: OrchestrationStep): string[] {
    if (step.capability_id === 'compose') {
        const semantic = step.arguments.semantic_review;
        return ['Prepare answer', 'Validate required format',
            semantic === 'off' ? 'Semantic review off'
                : step.arguments.knowledge_basis === 'general_knowledge' ? 'Review against your instructions'
                    : 'Review against your request and available evidence'];
    }
    if (step.capability_id === 'render_file') return ['Create file', 'Validate file'];
    return [];
}
