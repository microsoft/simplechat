// ScreeningDiffPreview.tsx

import type { ScreeningDiff } from '../../lib/contentScreeningReview';

export function ScreeningDiffPreview({ differences }: { differences: ScreeningDiff[] }) {
    return (
        <section className="min-w-0 space-y-3" aria-label="Candidate edit preview">
            <h3 className="text-sm font-semibold text-text-1">Edit preview</h3>
            <p className="text-xs text-text-3">
                Local before/after preview. The server validates the exact source hashes, creates an
                immutable candidate, and rescans complete coverage before a separate clean approval.
            </p>
            {differences.map((difference) => (
                <div key={`${difference.unit_id}:${difference.text_offset}`} className="min-w-0 rounded-xl border border-edge p-3">
                    <h4 className="mb-2 text-xs font-semibold text-text-2">{difference.label}</h4>
                    <div className="grid min-w-0 gap-3 lg:grid-cols-2">
                        <div className="min-w-0">
                            <p className="mb-1 text-xs font-medium text-text-3">Before</p>
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-danger-soft p-2 font-mono text-xs text-text-1">
                                {difference.before}
                            </pre>
                        </div>
                        <div className="min-w-0">
                            <p className="mb-1 text-xs font-medium text-text-3">After</p>
                            {difference.removed ? (
                                <p className="rounded-lg bg-surface-2 p-2 text-xs text-text-3">Source unit removed</p>
                            ) : (
                                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-ok-soft p-2 font-mono text-xs text-text-1">
                                    {difference.after || '(empty)'}
                                </pre>
                            )}
                        </div>
                    </div>
                </div>
            ))}
        </section>
    );
}
