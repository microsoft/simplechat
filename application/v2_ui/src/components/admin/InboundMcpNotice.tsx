// InboundMcpNotice.tsx
// What the Inbound MCP section shows while its preview gate is off.
//
// The gate is `ENABLE_MCP_UI`, an App Service application setting rather than a stored
// setting, so there is nothing on this page that can turn it on. Hiding the section
// entirely would leave an administrator with no way to discover that, which is why the
// server-rendered page shows the same instructions.
//
// Turning the gate on only reveals the configuration. The runtime stays off until
// "Enable Inbound MCP Server" is switched on, after the authentication, allowlist and
// governance prerequisites are in place.

import { Info } from 'lucide-react';

export function InboundMcpNotice() {
    return (
        <div className="py-3">
            <div className="rounded-lg border border-edge bg-surface-1 p-3">
                <p className="flex items-center gap-2 text-sm font-medium text-text-1">
                    <Info size={15} className="shrink-0 text-text-3" aria-hidden="true" />
                    Inbound MCP configuration is not available on this deployment
                </p>

                <p className="mt-2 text-xs leading-relaxed text-text-3">
                    Inbound MCP lets external MCP clients, such as an editor, call
                    SimpleChat tools on a user&apos;s behalf. It is a preview capability
                    and its settings stay hidden until the deployment opts in.
                </p>

                <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs leading-relaxed text-text-3">
                    <li>Open the Azure App Service that hosts SimpleChat.</li>
                    <li>
                        Add an application setting named{' '}
                        <code className="rounded bg-surface-2 px-1 py-0.5 font-mono">
                            ENABLE_MCP_UI
                        </code>{' '}
                        with the value{' '}
                        <code className="rounded bg-surface-2 px-1 py-0.5 font-mono">
                            true
                        </code>
                        .
                    </li>
                    <li>Save, and restart the app if your host does not restart it.</li>
                    <li>Reload this page.</li>
                </ol>

                <p className="mt-2 text-xs leading-relaxed text-text-3">
                    That only reveals the settings. The endpoint itself stays closed until
                    it is enabled here, and every request is then still checked against the
                    delegated scope, the Entra role, the client and source allowlists, and
                    governance policy.
                </p>
            </div>
        </div>
    );
}
