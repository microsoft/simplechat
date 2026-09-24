// OrchestrationResultBindings.tsx

import type { OrchestrationPlan, OrchestrationStep } from '../../lib/orchestration';
import { describeInputBinding } from '../../lib/orchestrationPlan';

export function OrchestrationResultBindings({
    plan, step,
}: { plan: OrchestrationPlan; step: OrchestrationStep }) {
    if (plan.planner_contract_version !== 2) return null;
    const inputs = Object.entries(step.inputs ?? {});
    const outputs = step.outputs ?? [];
    const dependencies = step.depends_on.map((id) =>
        plan.steps.find((candidate) => candidate.step_id === id)?.title || id,
    );
    if (!inputs.length && !outputs.length && !dependencies.length) return null;

    return (
        <section aria-label={`Result bindings for ${step.title}`} className="mt-2 space-y-2 break-words text-xs">
            {dependencies.length ? (
                <p className="text-text-3"><strong>After:</strong> {dependencies.join('; ')}</p>
            ) : null}
            {inputs.length ? (
                <div>
                    <h4 className="font-medium text-text-2">Named inputs</h4>
                    <dl className="mt-1 space-y-1 text-text-3">
                        {inputs.map(([name, input]) => (
                            <div key={name}>
                                <dt className="font-mono text-text-2">{name}</dt>
                                <dd>
                                    {describeInputBinding(plan, input.binding)}.
                                    {' '}{input.allow_partial ? 'Partial results accepted.' : 'Complete results required.'}
                                    {input.optional
                                        ? ' Optional: if it cannot be gathered, the answer continues from general knowledge and says so.'
                                        : ''}
                                </dd>
                            </div>
                        ))}
                    </dl>
                </div>
            ) : null}
            {outputs.length ? (
                <div>
                    <h4 className="font-medium text-text-2">Named outputs</h4>
                    <dl className="mt-1 space-y-2 text-text-3">
                        {outputs.map((output, index) => (
                            <div key={`${output.name}-${index}`}>
                                <dt className="font-mono text-text-2">{output.name || 'Unnamed output'}</dt>
                                <dd className="space-y-1">
                                    <p>Kind: {output.kind || 'Unavailable'}</p>
                                    {output.profile ? <p>Prepared-content profile: {output.profile}</p> : null}
                                    {output.columns?.length ? (
                                        <div>
                                            <p>Ordered columns:</p>
                                            <ol className="list-inside list-decimal">
                                                {output.columns.map((column, index) => (
                                                    <li key={`${column.name}-${index}`}>
                                                        {column.name} ({column.value_type}{column.nullable ? ', nullable' : ''})
                                                    </li>
                                                ))}
                                            </ol>
                                        </div>
                                    ) : null}
                                    {output.schema ? (
                                        <details>
                                            <summary className="cursor-pointer text-text-2">Prepared output schema</summary>
                                            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-sunken p-2">
                                                {JSON.stringify(output.schema, null, 2)}
                                            </pre>
                                        </details>
                                    ) : null}
                                </dd>
                            </div>
                        ))}
                    </dl>
                </div>
            ) : null}
        </section>
    );
}
