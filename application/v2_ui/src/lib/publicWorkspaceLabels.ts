// publicWorkspaceLabels.ts
//
// The single source of end-user Public Workspace copy for the V2 SPA. An administrator can rename
// the surface (admin field `public_workspace_display_name`), and the server resolves the five label
// forms into `public_workspace_labels` inside sanitized bootstrap settings. This selector reads that
// block with a per-key fallback, mirroring the classic `getPublicWorkspaceLabel` helper in
// templates/base.html so both interfaces render an admin's custom name identically. The capability is
// an interface hint only: a missing or malformed block leaves the default English labels rather than
// blanking or degrading the surface.

import { useBootstrapStore } from '../stores/bootstrapStore';
import { isRecord } from './workspaceAuthoring';
import type { PublicWorkspaceLabels } from './types';

export const DEFAULT_PUBLIC_WORKSPACE_LABELS: PublicWorkspaceLabels = {
    singular: 'Public Workspace',
    plural: 'Public Workspaces',
    lower_singular: 'public workspace',
    lower_plural: 'public workspaces',
    short: 'Public',
    is_custom: false,
    max_length: 32,
};

function pickString(source: Record<string, unknown>, key: keyof PublicWorkspaceLabels, fallback: string): string {
    const value = source[key as string];
    // Mirror classic `(labels && labels[key]) || defaults[key]`: any empty or non-string override
    // falls back to the default, so a partial or malformed block never blanks a label.
    return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
}

/**
 * Resolve the label forms from a sanitized settings object. Pure and store-independent, so the
 * logic pin can exercise it against the server's `get_public_workspace_label_context` shape.
 */
export function readPublicWorkspaceLabels(settings: unknown): PublicWorkspaceLabels {
    const block = isRecord(settings) ? settings.public_workspace_labels : null;
    if (!isRecord(block)) {
        return DEFAULT_PUBLIC_WORKSPACE_LABELS;
    }
    const maxLength = block.max_length;
    return {
        singular: pickString(block, 'singular', DEFAULT_PUBLIC_WORKSPACE_LABELS.singular),
        plural: pickString(block, 'plural', DEFAULT_PUBLIC_WORKSPACE_LABELS.plural),
        lower_singular: pickString(block, 'lower_singular', DEFAULT_PUBLIC_WORKSPACE_LABELS.lower_singular),
        lower_plural: pickString(block, 'lower_plural', DEFAULT_PUBLIC_WORKSPACE_LABELS.lower_plural),
        short: pickString(block, 'short', DEFAULT_PUBLIC_WORKSPACE_LABELS.short),
        is_custom: block.is_custom === true,
        max_length: typeof maxLength === 'number' && Number.isInteger(maxLength) && maxLength > 0
            ? maxLength : DEFAULT_PUBLIC_WORKSPACE_LABELS.max_length,
    };
}

/** Read the labels from the resolved bootstrap payload, outside a React render. */
export function getPublicWorkspaceLabels(): PublicWorkspaceLabels {
    return readPublicWorkspaceLabels(useBootstrapStore.getState().data?.settings);
}

/** Subscribe a component to the labels, re-rendering if the bootstrap payload is re-read. */
export function usePublicWorkspaceLabels(): PublicWorkspaceLabels {
    // Select the stable settings reference, then derive: returning a fresh object straight from a
    // Zustand selector would trip its "getSnapshot should be cached" guard.
    const settings = useBootstrapStore((state) => state.data?.settings);
    return readPublicWorkspaceLabels(settings);
}
