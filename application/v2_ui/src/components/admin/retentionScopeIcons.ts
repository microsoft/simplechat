// retentionScopeIcons.ts
// One icon per workspace type, shared by the Retention Policy switches and the run and
// reset reviews so a type looks the same wherever it is named.

import { Globe, User, Users, type LucideIcon } from 'lucide-react';
import type { RetentionScope } from '../../lib/retentionPolicy';

export const RETENTION_SCOPE_ICONS: Readonly<Record<RetentionScope, LucideIcon>> = {
    personal: User,
    group: Users,
    public: Globe,
};
