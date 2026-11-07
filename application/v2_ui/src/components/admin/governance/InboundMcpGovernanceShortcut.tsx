// InboundMcpGovernanceShortcut.tsx
// The governance step of Inbound MCP, shown in the Inbound MCP settings themselves.
//
// A request that passes every check on that card still gets no tools until an inbound MCP
// source policy allows the person, and that policy lives two categories away under
// Governance. This says how many source policies exist and offers to create one, matching
// the source mode the card is set to.

import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight } from 'lucide-react';
import { asBoolean } from '../../../lib/adminFields';
import {
    INBOUND_MCP_SOURCE_ENTITY_TYPE,
    fetchItemPolicyPage,
    newItemPolicyDraft,
    readDraftAware,
} from '../../../lib/governance';
import type { Json } from '../../../lib/types';
import { openGovernanceEditor, useGovernanceStore } from '../../../stores/governanceStore';
import { GlassButton } from '../../ui/primitives';

const INBOUND_GOVERNANCE_SECTION_ID = 'governance-inbound-mcp-section';

export function InboundMcpGovernanceShortcut({
    label,
    help,
    settings,
    draft,
    onNavigate,
}: {
    label: string;
    help?: string;
    settings: Json;
    draft: Json;
    onNavigate: (sectionId: string) => void;
}) {
    const revision = useGovernanceStore((state) => state.revision);
    const [count, setCount] = useState<number | null>(null);
    const [failed, setFailed] = useState(false);
    const allowAllValue = readDraftAware(settings, draft, 'inbound_mcp_allow_all_source_ids');
    const allowAllSources = allowAllValue === undefined ? true : asBoolean(allowAllValue);

    useEffect(() => {
        const controller = new AbortController();
        void fetchItemPolicyPage({ entityTypes: [INBOUND_MCP_SOURCE_ENTITY_TYPE], perPage: 100 }, controller.signal)
            .then((page) => {
                if (!controller.signal.aborted) {
                    // Runtime evaluation ignores system-managed source policies, so they are
                    // not counted as letting anyone in.
                    const listed = page.policies.filter((policy) => !policy.system_managed).length;
                    setCount(listed + Math.max(0, page.pagination.total_items - page.policies.length));
                    setFailed(false);
                }
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    setFailed(true);
                }
            });
        return () => controller.abort();
    }, [revision]);

    const create = () => openGovernanceEditor({
        draft: newItemPolicyDraft({
            entity_type: INBOUND_MCP_SOURCE_ENTITY_TYPE,
            item_id: allowAllSources ? '*' : '',
            resource_label: allowAllSources ? 'All accepted source IDs (*)' : '',
            policy_name: allowAllSources ? 'Inbound MCP all source access' : 'Inbound MCP source access',
            allow_all: false,
        }),
        entityTypes: [INBOUND_MCP_SOURCE_ENTITY_TYPE],
    });

    const summary = failed
        ? 'Source policies could not be checked.'
        : count === null
            ? 'Checking source policies…'
            : count === 0
                ? 'No source policy yet, so inbound MCP returns no tools to anyone.'
                : `${count} source ${count === 1 ? 'policy decides' : 'policies decide'} who receives tools.`;

    return (
        <div className="flex flex-wrap items-start justify-between gap-3 py-3">
            <div className="min-w-0 flex-[1_1_20rem]">
                <p className="text-sm font-semibold text-text-1">{label}</p>
                <p className={count === 0 ? 'mt-0.5 flex items-start gap-1.5 text-xs text-warn' : 'mt-0.5 text-xs text-text-2'} role="status">
                    {count === 0 ? <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" /> : null}
                    {summary}
                </p>
                {help ? <p className="mt-1 max-w-[72ch] text-xs leading-relaxed text-text-3">{help}</p> : null}
            </div>
            <div className="flex flex-wrap gap-2">
                <GlassButton type="button" size="sm" variant="subtle" onClick={create}>
                    {allowAllSources ? 'Create a policy for any source' : 'Create a source policy'}
                </GlassButton>
                <GlassButton type="button" size="sm" variant="ghost" onClick={() => onNavigate(INBOUND_GOVERNANCE_SECTION_ID)}>
                    Review in Governance
                    <ArrowRight size={13} aria-hidden="true" />
                </GlassButton>
            </div>
        </div>
    );
}
