// harness_entry.tsx
// Version: 0.261.127. Admin wrapper; workspace surfaces use their real-SPA suites.

import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { AdminSettingsPage } from '../../../application/v2_ui/src/pages/AdminSettingsPage';
import { useBootstrapStore } from '../../../application/v2_ui/src/stores/bootstrapStore';
import type { BootstrapPayload } from '../../../application/v2_ui/src/lib/types';

type View = 'admin';

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
            admin: <AdminSettingsPage />,
        };
        root.render(<MemoryRouter>{pages[view]}</MemoryRouter>);
    },
};
