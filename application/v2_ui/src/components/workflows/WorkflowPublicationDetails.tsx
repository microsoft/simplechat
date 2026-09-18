// WorkflowPublicationDetails.tsx
// The same allowlisted publication facts in a waiting gate and an exact attempt.

import {
    WORKFLOW_PUBLICATION_COMPLETION_LABELS,
    type WorkflowPublicationStatus,
} from '../../lib/workflowEditor';

const stateLabels: Record<WorkflowPublicationStatus['state'], string> = {
    submitted: 'Publication submitted',
    approved: 'Publication approval requirement met',
    indexed_ready: 'Publication indexed and ready',
    waiting_approval: 'Waiting for destination approval',
    waiting_processing: 'Waiting for document processing',
    waiting_screening: 'Waiting for content screening',
    waiting_index: 'Waiting for search visibility',
    uncertain: 'Publication outcome uncertain',
    rejected: 'Destination publication rejected',
    cancelled: 'Destination publication cancelled',
    approval_failed: 'Destination approval failed',
    processing_failed: 'Document processing failed',
    unavailable: 'Publication readiness unavailable',
    content_changed: 'Published content changed',
};

function factLabel(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, ' ');
}

export function WorkflowPublicationDetails({
    publication,
    label = 'Publication status',
}: {
    publication?: WorkflowPublicationStatus;
    label?: string;
}) {
    if (!publication) return null;
    const destination = publication.destination;
    const facts = [
        ['Requested completion', WORKFLOW_PUBLICATION_COMPLETION_LABELS[publication.completion_policy]],
        ['Completion requirement', publication.policy_satisfied ? 'Met' : 'Not met'],
        ['Submission', factLabel(publication.submission)],
        ['Destination approval', factLabel(publication.approval)],
        ['Processing', factLabel(publication.processing)],
        ['Screening', factLabel(publication.screening)],
        ['Index', factLabel(publication.index)],
    ];
    const identifiers = [
        ['Receipt', publication.id],
        ['Document', publication.document_id],
        ['Document version', publication.document_version === null ? 'Not confirmed' : String(publication.document_version)],
        ['Destination', `${factLabel(destination.workspace_scope)} workspace`],
        ...(destination.group_id ? [['Group ID', destination.group_id]] : []),
        ...(destination.public_workspace_id ? [['Public workspace ID', destination.public_workspace_id]] : []),
    ];
    const waiting = publication.state.startsWith('waiting_');
    return (
        <section aria-label={label} className="min-w-0 space-y-2 rounded-xl border border-edge p-3 text-xs text-text-3">
            <p className="text-sm font-medium text-text-1">
                {publication.policy_satisfied ? 'Saved completion observation: ' : ''}{stateLabels[publication.state]}
            </p>
            <dl className="grid min-w-0 gap-2 sm:grid-cols-2">
                {facts.map(([name, value]) => (
                    <div key={name} className="min-w-0">
                        <dt className="font-medium text-text-2">{name}</dt>
                        <dd>{value}</dd>
                    </div>
                ))}
            </dl>
            <dl className="space-y-1 border-t border-edge pt-2">
                {identifiers.map(([name, value]) => (
                    <div key={name} className="min-w-0 break-all">
                        <dt className="inline font-medium text-text-2">{name}: </dt>
                        <dd className="inline">{value}</dd>
                    </div>
                ))}
            </dl>
            {publication.reason_code ? <p className="break-words">Reason code: {publication.reason_code}</p> : null}
            {publication.unresolved_stages.length ? (
                <p className="break-words">Unresolved stages: {publication.unresolved_stages.map(factLabel).join(', ')}</p>
            ) : null}
            {publication.state === 'waiting_approval' ? (
                <p>Destination reviewers decide in that workspace. Workflow task approval does not apply.</p>
            ) : null}
            {publication.state === 'content_changed' ? (
                <p>The changed content cannot satisfy the original request. Cancel this run and start a new publication if needed.</p>
            ) : !publication.policy_satisfied && !waiting && !publication.retryable ? (
                <p>This receipt cannot meet the requested level. Cancel this run and start a new publication if needed.</p>
            ) : !publication.policy_satisfied ? (
                <p>Refresh reads status only. Resume / check again, when available, checks this receipt without publishing another copy or rerunning Analyze.</p>
            ) : (
                <p>
                    These stages were saved when the requested completion level was met. Later destination changes do not update this snapshot.
                    {' '}Refresh rereads the saved observation; it does not confirm current destination approval, availability, or index readiness.
                </p>
            )}
        </section>
    );
}
