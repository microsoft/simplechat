// ScreeningFindings.tsx

export function ScreeningFindings({
    findings,
    title = 'Protected findings',
}: {
    findings: Array<Record<string, unknown>>;
    title?: string;
}) {
    return (
        <section className="min-w-0 space-y-2" aria-label={title}>
            <h3 className="text-sm font-semibold text-text-1">{title}</h3>
            {findings.length ? findings.map((finding, index) => (
                <details key={index} className="min-w-0 rounded-lg border border-edge p-2">
                    <summary className="cursor-pointer break-words text-xs font-medium text-text-2">
                        {typeof finding.rule_id === 'string' ? finding.rule_id : `Finding ${index + 1}`}
                        {typeof finding.severity === 'string' ? ` · ${finding.severity}` : ''}
                        {typeof finding.category === 'string' ? ` · ${finding.category}` : ''}
                    </summary>
                    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-text-2">
                        {JSON.stringify(finding, null, 2)}
                    </pre>
                </details>
            )) : <p className="text-xs text-text-3">No findings in this result.</p>}
        </section>
    );
}
