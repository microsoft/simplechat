// EndpointsSection.tsx

import { ModelConnectionsManager } from '../../components/admin/ModelConnectionsManager';
import { SectionIntro } from '../../components/workspace/primitives';
import { createPersonalModelConnectionsAdapter } from '../../lib/modelConnections';

const PERSONAL_ENDPOINT_ADAPTER = createPersonalModelConnectionsAdapter();

export function EndpointsSection() {
    return (
        <div className="space-y-4">
            <SectionIntro
                title="Endpoints"
                description="Model connections you own, for your agents and workflows. Credentials stay server-side; leave a stored secret blank to keep it."
            />
            <ModelConnectionsManager adapter={PERSONAL_ENDPOINT_ADAPTER} />
        </div>
    );
}
