// harness_entry.tsx
// Version: 0.261.096. Group/admin wrappers; personal authoring uses the real-SPA suite.

import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { GroupAgentDelegationPage } from '../../../application/v2_ui/src/pages/GroupAgentDelegationPage';
import { AdminSettingsPage } from '../../../application/v2_ui/src/pages/AdminSettingsPage';
import { useBootstrapStore } from '../../../application/v2_ui/src/stores/bootstrapStore';
import type { BootstrapPayload } from '../../../application/v2_ui/src/lib/types';

type View = 'groups' | 'admin';

declare global {
    interface Window {
        AgentDelegationHarness: { mount: (view: View, admin?: boolean) => void };
    }
}

const container = document.getElementById('root');
if (!container) {
    throw new Error('Missing harness root');
}
const root = createRoot(container);
window.AgentDelegationHarness = {
    mount(view, admin = true) {
        // Only identity is read by the pages under test; all resource data crosses the real API client.
        useBootstrapStore.setState({ data: { user: { is_admin: admin } } as BootstrapPayload, loading: false });
        const pages = {
            groups: <GroupAgentDelegationPage />,
            admin: <AdminSettingsPage />,
        };
        root.render(<MemoryRouter>{pages[view]}</MemoryRouter>);
    },
};
