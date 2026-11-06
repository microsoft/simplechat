// TaskCompletenessDetails.tsx
// Inert, allowlisted verification metadata shared by workflow and orchestration views.
import {
    completenessActivity, completenessReport, completenessStages, completenessValidationSummary,
} from '../../lib/taskCompleteness';

const labels: Record<string, string> = {
    complete: 'Complete',
    incomplete: 'Incomplete',
    verification_unavailable: 'Verification unavailable',
    checking: 'Checking answer',
    checked: 'Answer checked',
    correcting: 'Correcting answer',
    repairing_assessment: 'Checking answer',
    disabled: 'Not checked',
};

function record(value: unknown): Record<string, unknown> | null {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown> : null;
}

export function TaskCompletenessDetails({ value }: { value: unknown }) {
    const report = completenessReport(value);
    if (!report || typeof report.status !== 'string' || !Object.hasOwn(labels, report.status)) {
        return null;
    }
    const corrections = typeof report.corrections === 'number' ? report.corrections : 0;
    const requirements = Array.isArray(report.requirements)
        ? report.requirements.map(record).filter((item): item is Record<string, unknown> => item !== null) : [];
    const label = completenessActivity(value) ?? labels[report.status];
    const stages = completenessStages(value);
    return (
        <details className="min-w-0 text-xs text-text-2" data-testid="task-completeness">
            <summary className="cursor-pointer rounded py-1 font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                Answer checking: {label}
            </summary>
            <div className="space-y-2 py-2">
                <CheckStageList value={value} />
                {!stages.length ? <p>Detailed stage history was not saved for this report.</p> : null}
                {typeof report.semantic_skip_reason === 'string'
                    && stages.some((stage) => stage.id === 'semantic' && stage.status === 'skipped') ? (
                    <p>Optional review was skipped after a checker error. Required checks completed.</p>
                ) : null}
                <p>Model-assisted review is not a guarantee of factual accuracy. Required format and safety checks remain separate.</p>
                <p>{corrections} adjustment{corrections === 1 ? '' : 's'}</p>
                {typeof report.reason_code === 'string' && report.reason_code ? <p>{report.reason_code}</p> : null}
                {typeof report.semantic_skip_reason === 'string' && report.semantic_skip_reason
                    ? <p>{report.semantic_skip_reason}</p> : null}
                <ul className="space-y-2">
                    {requirements.map((item, index) => (
                        <li key={index} className="break-words">
                            <span className="font-medium">{String(item.requirement ?? '')}</span>
                            {' — '}{String(item.status ?? '')}
                            {typeof item.reason === 'string' && item.reason ? <p>{item.reason}</p> : null}
                        </li>
                    ))}
                </ul>
            </div>
        </details>
    );
}

export function ValidationStatement({ value }: { value: unknown }) {
    const summary = completenessValidationSummary(value);
    return summary ? (
        <p className="mt-2 text-xs font-medium text-ok-strong" data-testid="answer-validation-summary">
            {summary}
        </p>
    ) : null;
}

export function CheckStageList({ value, showOptionalSkip = true }: { value: unknown; showOptionalSkip?: boolean }) {
    const report = completenessReport(value);
    const stages = completenessStages(value).filter((stage) => showOptionalSkip
        || stage.id !== 'semantic' || stage.status !== 'skipped'
        || typeof report?.semantic_skip_reason !== 'string');
    if (!stages.length && report?.preparation_status !== 'prepared') return null;
    return (
        <ul aria-label="Answer checking stages" className="mt-1 space-y-1 text-xs text-text-2">
            {!stages.some((stage) => stage.id === 'prepare') && report?.preparation_status === 'prepared'
                ? <li>Answer prepared — Completed</li> : null}
            {stages.map((stage) => (
                <li key={stage.id} data-check-stage={stage.id} data-check-status={stage.status}>
                    {stage.id === 'prepare' && stage.status === 'completed' ? 'Answer prepared' : stage.label}
                    {' — '}{stage.status === 'completed' ? 'Completed'
                        : stage.status === 'failed' ? report?.status === 'incomplete' ? 'Needs revision' : "Couldn't finish"
                        : stage.status === 'skipped' ? 'Skipped'
                        : stage.status === 'running' ? 'In progress' : 'Pending'}
                </li>
            ))}
        </ul>
    );
}
