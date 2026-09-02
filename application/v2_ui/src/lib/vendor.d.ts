// vendor.d.ts
// Types for the vendored browser libraries loaded at runtime by `vendorAssets.ts`.
//
// These are hand-written rather than pulled from `@types/*` or the packages' own bundled
// declarations, because doing so would reintroduce the npm dependency that vendoring exists
// to avoid. Only the API surface SimpleChat actually calls is declared, so an unused option
// cannot be reached by mistake, and each is checked against the vendored version's
// documentation.

/** KaTeX 0.18.4 — https://katex.org/docs/options */
export interface KatexOptions {
    /** Render as a centred block rather than inline with the surrounding text. */
    displayMode?: boolean;
    /**
     * Whether to trust input that can inject markup or navigate.
     *
     * Always false here. Model output is untrusted, and `false` disables `\href`, `\url`,
     * `\includegraphics` and `\htmlClass`.
     */
    trust?: boolean;
    /** 'ignore' renders questionable-but-valid TeX rather than refusing it. */
    strict?: boolean | string | ((errorCode: string) => string | undefined);
    /** Render invalid TeX as flagged source instead of throwing. */
    throwOnError?: boolean;
    /** Colour used for the text of an expression KaTeX could not parse. */
    errorColor?: string;
    /** Cap on macro expansion, which bounds the cost of hostile input. */
    maxExpand?: number;
    output?: 'html' | 'mathml' | 'htmlAndMathml';
}

export interface KatexStatic {
    renderToString(tex: string, options?: KatexOptions): string;
}

/** Mermaid 11.17.2 — https://mermaid.js.org/config/schema-docs/config.html */
export interface MermaidConfig {
    /** False so diagrams are only rendered through explicit `render` calls. */
    startOnLoad?: boolean;
    /**
     * 'strict' sanitizes generated markup with mermaid's bundled DOMPurify and disables
     * interaction directives. Required, because diagram source arrives from model output.
     */
    securityLevel?: 'strict' | 'loose' | 'antiscript' | 'sandbox';
    theme?: 'default' | 'dark' | 'forest' | 'neutral' | 'base' | 'null';
    /**
     * Theme colour overrides, applied on top of the selected theme.
     *
     * Only meaningful with `theme: 'base'`, which exists to be overridden. Every value written
     * here is normalised to `#rrggbb` first (visualPalettes.ts): mermaid's own directive
     * sanitizer rejects values containing markup, and matching one accepted form removes the
     * question of what else could be passed.
     */
    themeVariables?: Record<string, string>;
    /** Suppresses mermaid writing its own error diagram into the page on failure. */
    suppressErrorRendering?: boolean;
    fontFamily?: string;
    /** False keeps labels as SVG text rather than embedded foreignObject HTML. */
    htmlLabels?: boolean;
    flowchart?: { htmlLabels?: boolean; useMaxWidth?: boolean };
    sequence?: { useMaxWidth?: boolean };
    gantt?: { useMaxWidth?: boolean };
    class?: { htmlLabels?: boolean; useMaxWidth?: boolean };
    logLevel?: number | string;
    maxTextSize?: number;
    maxEdges?: number;
}

export interface MermaidRenderResult {
    svg: string;
}

export interface MermaidStatic {
    initialize(config: MermaidConfig): void;
    /** Throws when the diagram source is not valid, which is how invalid input is detected. */
    parse(text: string): Promise<boolean>;
    /**
     * Render to an SVG string.
     *
     * The `bindFunctions` member of the real return value is deliberately not declared:
     * calling it attaches mermaid's interaction handlers, which must never run for
     * model-authored diagrams.
     */
    render(id: string, text: string): Promise<MermaidRenderResult>;
}

/** Chart.js 4.5.1 — the UMD build, which self-registers every controller and scale. */
export interface ChartJsInstance {
    destroy(): void;
    update(mode?: string): void;
    resize(): void;
    toBase64Image(type?: string, quality?: number): string;
}

export interface ChartJsConstructor {
    new (
        target: HTMLCanvasElement | CanvasRenderingContext2D,
        config: Record<string, unknown>,
    ): ChartJsInstance;
    defaults: Record<string, unknown>;
}

/** DOMPurify 3.4.14 — https://github.com/cure53/DOMPurify */
export interface DomPurifyConfig {
    USE_PROFILES?: { svg?: boolean; svgFilters?: boolean; html?: boolean; mathMl?: boolean };
    ADD_TAGS?: string[];
    ADD_ATTR?: string[];
    FORBID_TAGS?: string[];
    FORBID_ATTR?: string[];
}

export interface DomPurifyStatic {
    sanitize(dirty: string, config?: DomPurifyConfig): string;
}

declare global {
    interface Window {
        katex?: KatexStatic;
        mermaid?: MermaidStatic;
        Chart?: ChartJsConstructor;
        DOMPurify?: DomPurifyStatic;
    }
}
