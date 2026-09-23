// OrchestrationPlannedFile.tsx

import type { OrchestrationPlan, OrchestrationStep } from '../../lib/orchestration';
import { plannedFileSpecification } from '../../lib/orchestrationExports';
import { describeInputBinding } from '../../lib/orchestrationPlan';

export function OrchestrationPlannedFile({
    plan, step,
}: { plan: OrchestrationPlan; step: OrchestrationStep }) {
    if (plan.planner_contract_version !== 2 || step.capability_id !== 'render_file' || step.role !== 'render') return null;
    const specification = plannedFileSpecification(step);
    const inputs = Object.entries(step.inputs ?? {});
    return (
        <section aria-label={`Planned file for ${step.title}`} className="mt-2 space-y-1 break-words text-xs text-text-2">
            <h4 className="font-medium">Planned file</h4>
            <p className="text-text-3">Requested output, not a completed download.</p>
            {specification ? (
                <dl className="space-y-1">
                    <div><dt className="font-medium">File name</dt><dd className="break-all">{specification.file_name}</dd></div>
                    <div><dt className="font-medium">Format</dt><dd>{specification.output_format}</dd></div>
                    <div><dt className="font-medium">Profile</dt><dd>{specification.profile}</dd></div>
                    <div>
                        <dt className="font-medium">Source</dt>
                        <dd>{inputs.length === 1
                            ? `${inputs[0][0]}: ${describeInputBinding(plan, inputs[0][1].binding)}`
                            : 'Source binding details require server review.'}</dd>
                    </div>
                    <div>
                        <dt className="font-medium">Options</dt>
                        <dd>
                            {Object.keys(specification.options).length ? (
                                <dl className="mt-1 space-y-1 pl-2">
                                    {Object.entries(specification.options).map(([name, value]) => (
                                        <div key={name}>
                                            <dt>{name}</dt>
                                            <dd className="whitespace-pre-wrap break-all">
                                                {typeof value === 'string' ? value : JSON.stringify(value)}
                                            </dd>
                                        </div>
                                    ))}
                                </dl>
                            ) : 'No explicit options.'}
                        </dd>
                    </div>
                </dl>
            ) : (
                <p role="alert" className="alert text-warn">
                    The file specification is unavailable. Refresh the saved plan or ask the planner to revise it.
                </p>
            )}
        </section>
    );
}
