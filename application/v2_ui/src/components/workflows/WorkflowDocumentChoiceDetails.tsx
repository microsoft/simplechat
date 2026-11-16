// WorkflowDocumentChoiceDetails.tsx
// Public runtime decision summary, separate from document-processing cost.

import { isRecord } from '../../lib/workspaceAuthoring';

export function WorkflowDocumentChoiceDetails({ choice }: { choice: unknown }) {
    if (!isRecord(choice) || typeof choice.action !== 'string') return null;
    const names: Record<string, string> = { analyze: 'Analyze', search: 'Search', comparison: 'Compare', merge: 'Merge', refuse: 'Refused' };
    if (!names[choice.action]) return null;
    const usage = isRecord(choice.selection_token_usage) ? choice.selection_token_usage : {};
    return <div className="space-y-1 break-words rounded-lg border border-edge p-3 text-sm text-text-2">
        <p className="font-medium text-text-1">Runtime document action: {names[choice.action]}</p>
        {typeof choice.summary === 'string' ? <p>{choice.summary}</p> : null}
        <p className="text-xs text-text-3">
            {typeof choice.input_count === 'number' ? `${choice.input_count} captured inputs. ` : ''}
            Selection-model tokens: {typeof usage.total_tokens === 'number' ? usage.total_tokens : 'not reported'}.
            {' '}Selection cost is separate from document processing.
        </p>
    </div>;
}
