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
    flowchart?: {
        htmlLabels?: boolean;
        useMaxWidth?: boolean;
        /**
         * Pixel width a node label wraps at.
         *
         * Mermaid's default of 200 turns the long labels models write into narrow columns of
         * text, which makes a diagram taller and harder to read rather than shorter.
         */
        wrappingWidth?: number;
    };
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

/**
 * OpenLayers 10.6.1 — the full build, which registers the `ol` namespace.
 * https://openlayers.org/en/v10.6.1/apidoc/
 *
 * Coordinates are in the map projection (Web Mercator) unless a name says lon/lat.
 */
export type OlCoordinate = number[];
export type OlOptions = Record<string, unknown>;

export interface OlFeature {
    getProperties(): Record<string, unknown>;
    setStyle(style: unknown): void;
}

export interface OlMapBrowserEvent {
    pixel: number[];
    coordinate: OlCoordinate;
    dragging: boolean;
}

export interface OlMap {
    on(type: 'click' | 'pointermove', listener: (event: OlMapBrowserEvent) => void): unknown;
    forEachFeatureAtPixel<T>(pixel: number[], callback: (feature: OlFeature) => T): T | undefined;
    addInteraction(interaction: unknown): void;
    addControl(control: unknown): void;
    getSize(): number[] | undefined;
    updateSize(): void;
    setTarget(target?: HTMLElement): void;
    dispose(): void;
}

export interface OlView {
    fit(extent: number[], options?: { padding?: number[]; maxZoom?: number; duration?: number }): void;
}

export interface OlVectorSource {
    addFeatures(features: OlFeature[]): void;
    getExtent(): number[];
}

export interface OlOverlay {
    setPosition(position?: OlCoordinate): void;
    /** `top`, `center` or `bottom`, a dash, then `left`, `center` or `right`. */
    setPositioning(positioning: string): void;
    setOffset(offset: number[]): void;
    panIntoView(options?: OlOptions): void;
}

type OlConstructor<T = unknown> = new (options: OlOptions) => T;

export interface OpenLayersStatic {
    Map: OlConstructor<OlMap>;
    View: OlConstructor<OlView>;
    Feature: OlConstructor<OlFeature>;
    Overlay: OlConstructor<OlOverlay>;
    layer: { Tile: OlConstructor; Vector: OlConstructor };
    source: { XYZ: OlConstructor; Vector: new (options?: OlOptions) => OlVectorSource };
    geom: {
        Point: new (coordinate: OlCoordinate) => unknown;
        LineString: new (coordinates: OlCoordinate[]) => unknown;
        Polygon: new (rings: OlCoordinate[][]) => unknown;
    };
    style: { Style: OlConstructor; Circle: OlConstructor; Fill: OlConstructor; Stroke: OlConstructor };
    proj: { fromLonLat(lonLat: number[]): OlCoordinate };
    extent: { isEmpty(extent: number[]): boolean };
    /** The full build exposes each `defaults` module as a namespace holding the function. */
    interaction: {
        defaults: { defaults(options?: OlOptions): unknown };
        MouseWheelZoom: OlConstructor;
    };
    control: {
        defaults: { defaults(options?: OlOptions): unknown };
        FullScreen: OlConstructor<{ element: HTMLElement }>;
    };
    events: { condition: { platformModifierKeyOnly: (event: unknown) => boolean } };
}

declare global {
    interface Window {
        katex?: KatexStatic;
        mermaid?: MermaidStatic;
        Chart?: ChartJsConstructor;
        DOMPurify?: DomPurifyStatic;
        ol?: OpenLayersStatic;
    }
}
