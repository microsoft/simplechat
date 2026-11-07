// ScreeningBaselineSummary.tsx

import { LockKeyhole } from 'lucide-react';
import type { ScreeningBaselineSummary as BaselineSummary } from '../../lib/contentScreeningPolicy';

export function ScreeningBaselineSummary({ summary }: { summary: BaselineSummary }) {
    return (
        <section className="space-y-2 rounded-xl border border-edge bg-surface-2 p-3" aria-label="Required administrative baseline">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-text-1">
                <LockKeyhole size={14} />Required administrative baseline
            </h3>
            <p className="text-xs text-text-2">
                {summary.enabled
                    ? `${summary.rule_count} deterministic checks and ${summary.ai_check_count} model checks are inherited.`
                    : 'The administrative baseline is disabled. Workspace additions cannot activate it.'}
                {' '}Workspace additions cannot remove, replace, or weaken mandatory checks.
            </p>
            <dl className="grid gap-1 text-xs text-text-3">
                <div><dt className="inline font-medium">Rule types: </dt><dd className="inline">{summary.rule_types.join(', ') || 'None'}</dd></div>
                <div><dt className="inline font-medium">Structured PII: </dt><dd className="inline">{summary.pii_types.join(', ') || 'None'}</dd></div>
                <div><dt className="inline font-medium">Severities: </dt><dd className="inline">{summary.severities.join(', ') || 'None'}</dd></div>
                <div className="break-all"><dt className="inline font-medium">Baseline fingerprint: </dt><dd className="inline">{summary.fingerprint}</dd></div>
            </dl>
            <p className="text-xs text-text-3">
                Required rule names, custom values, patterns, and model instructions remain protected.
                Only this safe inheritance summary is provided to the workspace.
            </p>
        </section>
    );
}
