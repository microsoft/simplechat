// mermaidLayout.ts
// The layout changes that can be made to a diagram without writing any Mermaid.
//
// These are the honest answer to "can I move that box". Mermaid is declarative: node
// coordinates come from a layout engine, and the language has no syntax for placing a node at a
// position. What it does have is a flow direction and a pair of spacing knobs, and between them
// they cover most of what someone actually wants when a diagram reads badly — it is too tall,
// too wide, or too cramped.
//
// Every function here is a pure source-to-source transform, so a change made with a button is
// the same kind of change as one typed in the source editor: it produces a new revision, it can
// be undone, and it is visible in the history. Nothing is stored out-of-band as "layout state".

/** Directions a flowchart declaration can carry. `TB` is Mermaid's synonym for `TD`. */
export const FLOW_DIRECTIONS = ['TD', 'LR', 'BT', 'RL'] as const;
export type FlowDirection = (typeof FLOW_DIRECTIONS)[number];

export const FLOW_DIRECTION_LABELS: Record<FlowDirection, string> = {
    TD: 'Top to bottom',
    LR: 'Left to right',
    BT: 'Bottom to top',
    RL: 'Right to left',
};

/**
 * The declaration line of a flowchart, with its direction.
 *
 * Only `graph` and `flowchart` take a direction. A sequence or class diagram has no equivalent,
 * which is why the direction control reports "not available" rather than silently doing nothing.
 */
const FLOW_DECLARATION = /^([ \t]*)(graph|flowchart)([ \t]+)(TB|TD|BT|RL|LR)\b/im;

/**
 * A Mermaid init directive.
 *
 * Deliberately single-line: `.` does not match a newline, so a stray `%%{` in a node label
 * cannot swallow the rest of the diagram on its way to finding a closing `}%%`.
 */
const INIT_DIRECTIVE = /^[ \t]*%%\{\s*init\s*:\s*(.*)\}%%[ \t]*$/m;

/** How generously a diagram is spaced, as a preset rather than two raw numbers. */
export const SPACING_PRESETS = ['compact', 'normal', 'roomy'] as const;
export type SpacingPreset = (typeof SPACING_PRESETS)[number];

export const SPACING_LABELS: Record<SpacingPreset, string> = {
    compact: 'Compact',
    normal: 'Normal',
    roomy: 'Roomy',
};

/**
 * Node and rank spacing for each preset.
 *
 * `normal` is Mermaid's own default, which is why choosing it removes the setting rather than
 * writing those numbers: a diagram that has never been spaced and one explicitly set back to
 * normal should produce the same source.
 */
const SPACING_VALUES: Record<Exclude<SpacingPreset, 'normal'>, {
    nodeSpacing: number;
    rankSpacing: number;
}> = {
    compact: { nodeSpacing: 25, rankSpacing: 30 },
    roomy: { nodeSpacing: 80, rankSpacing: 90 },
};

/** The direction a diagram is drawn in, or null when it is not a kind that has one. */
export function readFlowDirection(source: string): FlowDirection | null {
    const match = FLOW_DECLARATION.exec(String(source ?? ''));
    if (!match) {
        return null;
    }
    const direction = match[4].toUpperCase();
    return (direction === 'TB' ? 'TD' : direction) as FlowDirection;
}

/** Whether the direction control applies to this diagram at all. */
export function supportsFlowDirection(source: string): boolean {
    return readFlowDirection(source) !== null;
}

/**
 * Redraw a diagram in a different direction.
 *
 * Returns the source unchanged when it has no declaration to rewrite, so a caller can apply
 * this without first checking and get a no-op rather than a broken diagram.
 */
export function setFlowDirection(source: string, direction: FlowDirection): string {
    const text = String(source ?? '');
    if (!FLOW_DECLARATION.test(text)) {
        return text;
    }
    return text.replace(
        FLOW_DECLARATION,
        (_match, indent: string, keyword: string, gap: string) =>
            `${indent}${keyword}${gap}${direction}`,
    );
}

/** Parse the init directive's payload, or null when there is not a readable one. */
function readInitConfig(source: string): Record<string, unknown> | null {
    const match = INIT_DIRECTIVE.exec(String(source ?? ''));
    if (!match) {
        return null;
    }
    try {
        const parsed = JSON.parse(`{${match[1].replace(/^\s*\{/, '').replace(/\}\s*$/, '')}}`);
        return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
    } catch {
        return null;
    }
}

/** The spacing preset a diagram currently uses. */
export function readSpacingPreset(source: string): SpacingPreset {
    const config = readInitConfig(source);
    const flowchart = config?.flowchart;
    if (!flowchart || typeof flowchart !== 'object') {
        return 'normal';
    }
    const nodeSpacing = (flowchart as Record<string, unknown>).nodeSpacing;
    for (const preset of ['compact', 'roomy'] as const) {
        if (nodeSpacing === SPACING_VALUES[preset].nodeSpacing) {
            return preset;
        }
    }
    return 'normal';
}

/**
 * Rewrite a diagram's spacing.
 *
 * The init directive is merged rather than replaced, so a diagram carrying an unrelated setting
 * such as a theme keeps it. Choosing `normal` removes only the two spacing keys, and removes
 * the whole directive when nothing else was in it, rather than leaving `%%{init: {}}%%` behind.
 */
export function setSpacingPreset(source: string, preset: SpacingPreset): string {
    const text = String(source ?? '');
    const existing = readInitConfig(text) ?? {};
    const flowchart = {
        ...((existing.flowchart && typeof existing.flowchart === 'object'
            ? existing.flowchart
            : {}) as Record<string, unknown>),
    };

    if (preset === 'normal') {
        delete flowchart.nodeSpacing;
        delete flowchart.rankSpacing;
    } else {
        Object.assign(flowchart, SPACING_VALUES[preset]);
    }

    const config: Record<string, unknown> = { ...existing };
    if (Object.keys(flowchart).length > 0) {
        config.flowchart = flowchart;
    } else {
        delete config.flowchart;
    }

    const hasDirective = INIT_DIRECTIVE.test(text);
    if (Object.keys(config).length === 0) {
        if (!hasDirective) {
            return text;
        }
        // Drop the directive line entirely, including the newline it sat on.
        return text.replace(INIT_DIRECTIVE, '').replace(/^\n/, '');
    }

    const directive = `%%{init: ${JSON.stringify(config)}}%%`;
    if (hasDirective) {
        return text.replace(INIT_DIRECTIVE, directive);
    }
    return `${directive}\n${text}`;
}
