// useActionAuth.ts

import { useSyncExternalStore } from 'react';
import { actionAuthController } from './actionAuthController';

export function useActionAuthInteraction() {
    return useSyncExternalStore(actionAuthController.subscribe, actionAuthController.getSnapshot, () => null);
}
