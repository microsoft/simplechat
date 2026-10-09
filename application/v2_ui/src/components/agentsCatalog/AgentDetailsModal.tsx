// AgentDetailsModal.tsx

import {
    catalogAgentTypeLabel, catalogDisplayName, catalogUsageCount, normalizeCatalogText, type CatalogAgent,
} from '../../lib/agentCatalog';
import { Modal } from '../ui/Modal';
import { PlainMarkdown } from '../ui/PlainMarkdown';
import { GlassButton } from '../ui/primitives';
import { Pill } from '../workspace/primitives';
import { AgentIcon } from '../workspaceAgents/AgentIdentityFields';
import { AgentCatalogBadges, AgentChatLink } from './AgentCatalogParts';

export function AgentDetailsModal({
    agent, showInstructions, onClose,
}: {
    agent: CatalogAgent;
    showInstructions: boolean;
    onClose: () => void;
}) {
    const actions = agent.action_labels ?? agent.actions_to_load ?? [];
    const tags = agent.tags ?? [];
    return (
        <Modal title={`Details for ${catalogDisplayName(agent)}`} size="lg" onClose={onClose}
            footer={<><GlassButton size="sm" onClick={onClose}>Close</GlassButton><AgentChatLink agent={agent} /></>}>
            <div className="min-w-0 space-y-5 break-words">
                <div className="flex items-start gap-3">
                    <AgentIcon icon={agent.icon} />
                    <div className="min-w-0 space-y-1.5">
                        <h3 className="text-lg font-semibold text-text-1">{catalogDisplayName(agent)}</h3>
                        {agent.name ? <p className="break-all font-mono text-xs text-text-3">{agent.name}</p> : null}
                        <AgentCatalogBadges agent={agent} />
                    </div>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-2">
                    {agent.description?.trim() || 'No description available.'}
                </p>
                <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                    <div>
                        <dt className="text-text-3">Agent type</dt>
                        <dd className="mt-0.5 text-text-1">{catalogAgentTypeLabel(agent)}</dd>
                    </div>
                    <div>
                        <dt className="text-text-3">Model</dt>
                        <dd className="mt-0.5 text-text-1">{normalizeCatalogText(agent.model_label) || 'Default'}</dd>
                    </div>
                    <div>
                        <dt className="text-text-3">Times used, all time</dt>
                        <dd className="mt-0.5 tabular-nums text-text-1">{catalogUsageCount(agent, 'all_time').toLocaleString()}</dd>
                    </div>
                    <div>
                        <dt className="text-text-3">Times used, last 30 days</dt>
                        <dd className="mt-0.5 tabular-nums text-text-1">{catalogUsageCount(agent, '30_days').toLocaleString()}</dd>
                    </div>
                </dl>
                <section aria-label="Actions">
                    <h3 className="mb-2 text-sm font-semibold text-text-1">Actions</h3>
                    {actions.length ? (
                        <ul className="list-inside list-disc space-y-1 text-sm text-text-2">
                            {actions.map((action, index) => <li key={`${index}:${action}`}>{action}</li>)}
                        </ul>
                    ) : <p className="text-sm text-text-3">No actions assigned.</p>}
                </section>
                <section aria-label="Tags">
                    <h3 className="mb-2 text-sm font-semibold text-text-1">Tags</h3>
                    {tags.length ? (
                        <div className="flex flex-wrap gap-1.5 [&>span]:max-w-full [&>span]:break-words [&>span]:whitespace-normal">
                            {tags.map((tag, index) => <Pill key={`${index}:${tag}`}>{tag}</Pill>)}
                        </div>
                    ) : <p className="text-sm text-text-3">No tags assigned.</p>}
                </section>
                {showInstructions && agent.instructions?.trim() ? (
                    <section aria-label="Instructions">
                        <h3 className="mb-2 text-sm font-semibold text-text-1">Instructions</h3>
                        <div className="min-w-0 max-w-full overflow-x-auto">
                            <PlainMarkdown content={agent.instructions} className="[&_p]:break-words" />
                        </div>
                    </section>
                ) : null}
            </div>
        </Modal>
    );
}
