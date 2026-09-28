// GroupEndpointsSection.tsx
// The group workspace model endpoints section: connections a group owns for its own agents and
// workflows, separate from the tenant-wide connections an administrator manages.
//
// This reuses the admin ModelConnectionsManager wholesale, driven by a scope-aware adapter rather
// than a fork. The group adapter routes reads and writes to /api/groups/<g>/model-endpoints and the
// group /api/groups/<g>/models/* discovery and test routes, hides the admin-only affordances
// (tenant test-connection, capability tests, network policy, default-model and migration notices),
// and gates create on the workspace's endpoint_management hint and per-row edit, enable, delete and
// test on each endpoint's endpoint_actions -- so a member sees a read-only list.

import { ModelConnectionsManager } from '../../components/admin/ModelConnectionsManager';
import { SectionIntro } from '../../components/workspace/primitives';
import type { ModelConnectionsAdapter } from '../../lib/modelConnections';

export function GroupEndpointsSection({ adapter }: { adapter: ModelConnectionsAdapter }) {
    return (
        <div className="space-y-4">
            <SectionIntro
                title="Endpoints"
                description="Model connections this group owns, for its own agents and workflows to use. These are separate from the tenant-wide connections an administrator manages. Keys and secrets are held server-side and never sent back to the browser."
            />
            <ModelConnectionsManager adapter={adapter} />
        </div>
    );
}
