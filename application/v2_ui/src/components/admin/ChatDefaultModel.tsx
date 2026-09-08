// ChatDefaultModel.tsx

import { CapabilityModelPicker } from './CapabilityModelPicker';

export function ChatDefaultModel({ multiEndpointEnabled, help }: {
    multiEndpointEnabled: boolean;
    help?: string;
}) {
    return <CapabilityModelPicker capability="chat" featureEnabled={multiEndpointEnabled} help={help} />;
}
