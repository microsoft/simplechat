// TaskCompletenessDetails.tsx
// Inert, allowlisted verification metadata shared by workflow and orchestration views.

const labels: Record<string, string> = {
    complete: 'Complete',
    incomplete: 'Incomplete',
    verification_unavailable: 'Verification unavailable',
    checking: 'Checking answer',
    checked: 'Answer checked',
    correcting: 'Correcting answer',
    disabled: 'Not checked',
};

function record(value: unknown): Record<string, unknown> | null {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown> : null;
}

export function TaskCompletenessDetails({ value }: { value: unknown }) {
    const report = record(value);
    if (!report || report.version !== 1 || typeof report.status !== 'string' || !Object.hasOwn(labels, report.status)) {
        return null;
    }
    const corrections = typeof report.corrections === 'number' ? report.corrections : 0;
    const requirements = Array.isArray(report.requirements)
        ? report.requirements.map(record).filter((item): item is Record<string, unknown> => item !== null) : [];
    const label = report.status === 'complete' && corrections > 0 ? 'Corrected and complete' : labels[report.status];
    return (
        <details className="min-w-0 text-xs text-text-2" data-testid="task-completeness">
            <summary className="cursor-pointer rounded py-1 font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                Answer completeness: {label} · {corrections} correction{corrections === 1 ? '' : 's'}
            </summary>
            <div className="space-y-2 py-2">
                <p>Model-assisted assessment, separate from format validation.</p>
                {typeof report.reason_code === 'string' && report.reason_code ? <p>{report.reason_code}</p> : null}
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
