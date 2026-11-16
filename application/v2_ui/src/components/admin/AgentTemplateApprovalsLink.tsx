// AgentTemplateApprovalsLink.tsx
// Where submitted agent templates are reviewed.
//
// Template review happens in the shared approvals queue, beside the other requests an
// administrator handles. This points there rather than keeping a second copy of the queue.
// It opens in a new tab, so leaving for the queue never drops settings that have not been
// saved yet.

import { ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';

export function AgentTemplateApprovalsLink({ help }: { help?: string }) {
    return (
        <div className="py-3">
            {help ? <p className="mb-2 text-xs leading-relaxed text-text-3">{help}</p> : null}
            <Link
                to="/approvals/agent-templates"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
            >
                Open the approvals queue
                <span className="sr-only"> (opens in a new tab)</span>
                <ExternalLink size={13} aria-hidden="true" />
            </Link>
        </div>
    );
}
