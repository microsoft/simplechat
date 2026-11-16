// InlineMapCard.tsx
// Interactive maps an Azure Maps action attached to an assistant reply.
//
// A map is drawn with the vendored OpenLayers build the classic chat uses, loaded only when a
// reply has a map. Tiles come through SimpleChat's tile proxy, which keeps the Azure Maps key
// on the server. Every title, label, description and field is action output, so it is only ever
// written as text: React renders the card, the popup is filled with `textContent`, and
// OpenLayers' own attribution control, which writes HTML, is replaced by a plain-text footer.
// A marker's photo loads only from the https link the map reader accepted, and only once someone
// points at the marker or opens the list.

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MapPin, Route, Square } from 'lucide-react';
import { apiUrl, CREDENTIALS_MODE } from '../../lib/apiClient';
import { fetchAgentCitation } from '../../lib/endpoints';
import { resolveImageSource } from '../../lib/images';
import {
    collectMapCitations,
    describeMapContents,
    readInlineMap,
    type InlineMap,
    type LonLat,
    type MapField,
    type MapImage,
} from '../../lib/inlineMaps';
import { loadOpenLayers } from '../../lib/vendorAssets';
import type { OlFeature, OpenLayersStatic } from '../../lib/vendor';
import { ImageLightbox } from './ImageLightbox';

/**
 * Tiles carry the session cookie. Same-origin requests send it in `anonymous` mode; a split
 * deployment, where the API is on another origin, has to ask for credentials explicitly.
 */
const TILE_CROSS_ORIGIN = CREDENTIALS_MODE === 'include' ? 'use-credentials' : 'anonymous';

/** Scrolling the chat over a map should scroll the chat, so the wheel zooms only with a modifier. */
const ZOOM_HINT = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)
    ? '\u2318 + scroll to zoom'
    : 'Ctrl + scroll to zoom';

/** What the popup and the list show for one marker, path or area. */
interface FeatureDetails {
    label: string;
    description: string;
    image: MapImage | null;
    fields: MapField[];
    /** A marker's own position, so its popup stays put while the pointer moves over the marker. */
    anchor?: number[];
}

/** A marker's photo opened full size, named by its caption or else by the marker's label. */
interface OpenedImage {
    url: string;
    title: string;
}

type OpenImage = (image: OpenedImage) => void;

function openedImage(image: MapImage, label: string): OpenedImage {
    return { url: image.url, title: image.caption || label };
}

/** A clickable photo and its caption, for the popup. */
function createPhoto(image: MapImage, label: string, onOpenImage: OpenImage): HTMLElement[] {
    const opened = openedImage(image, label);
    const button = document.createElement('button');
    button.type = 'button';
    button.title = 'View the full-size photo';
    button.setAttribute('aria-label', `View the full-size photo: ${opened.title}`);
    button.setAttribute('aria-haspopup', 'dialog');
    button.className = 'mb-1.5 block w-full cursor-zoom-in overflow-hidden rounded-md bg-black';
    const photo = document.createElement('img');
    photo.alt = opened.title;
    photo.referrerPolicy = 'no-referrer';
    photo.decoding = 'async';
    // A fixed height, so the popup has its final size before the photo arrives.
    photo.className = 'block h-36 w-full object-contain';
    photo.addEventListener('error', () => {
        const note = document.createElement('div');
        note.className = 'mb-1.5 italic text-text-3';
        note.textContent = 'The photo could not be loaded.';
        button.replaceWith(note);
    });
    photo.src = image.url;
    button.append(photo);
    button.addEventListener('click', () => onOpenImage(opened));
    if (!image.caption) {
        return [button];
    }
    const caption = document.createElement('div');
    caption.className = '-mt-0.5 mb-1.5 text-[11px] text-text-3';
    caption.textContent = image.caption;
    return [button, caption];
}

/** The popup shown for a hovered or clicked marker, path or area. Built here so React never owns it. */
function createPopup(onOpenImage: OpenImage) {
    const element = document.createElement('div');
    element.className =
        'hidden max-w-[16rem] rounded-lg border border-edge bg-surface-solid px-2.5 py-1.5 text-xs text-text-1 shadow-lift';
    const media = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'font-medium';
    const description = document.createElement('div');
    description.className = 'mt-0.5 text-text-2';
    const fieldList = document.createElement('dl');
    fieldList.className = 'mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5';
    element.append(media, title, description, fieldList);
    let shown: FeatureDetails | null = null;

    return {
        element,
        show(details: FeatureDetails) {
            element.classList.remove('hidden');
            if (details === shown) {
                return;
            }
            shown = details;
            element.classList.toggle('w-72', Boolean(details.image));
            element.classList.toggle('max-w-[16rem]', !details.image);
            media.replaceChildren(...(details.image ? createPhoto(details.image, details.label, onOpenImage) : []));
            title.textContent = details.label;
            description.textContent = details.description;
            description.classList.toggle('hidden', !description.textContent);
            fieldList.replaceChildren(...details.fields.flatMap((field) => {
                const term = document.createElement('dt');
                term.className = 'text-text-3';
                term.textContent = field.label;
                const value = document.createElement('dd');
                value.className = 'min-w-0 break-words';
                value.textContent = field.value;
                return [term, value];
            }));
            fieldList.classList.toggle('hidden', details.fields.length === 0);
        },
        hide() {
            element.classList.add('hidden');
        },
    };
}

/** Draw a map into `target` and return the function that tears it down. */
function drawMap(ol: OpenLayersStatic, target: HTMLElement, map: InlineMap, onOpenImage: OpenImage): () => void {
    const toMap = (point: LonLat) => ol.proj.fromLonLat(point);
    const features: OlFeature[] = [];
    const addFeature = (geometry: unknown, details: FeatureDetails, style: unknown) => {
        const feature = new ol.Feature({ geometry, details });
        feature.setStyle(style);
        features.push(feature);
    };

    // Areas first and markers last, so a marker is never hidden under a shaded area.
    for (const area of map.areas) {
        addFeature(new ol.geom.Polygon([area.coordinates.map(toMap)]),
            { label: area.label, description: area.description, image: null, fields: [] },
            new ol.style.Style({
                stroke: new ol.style.Stroke({ color: area.strokeColor, width: 2 }),
                fill: new ol.style.Fill({ color: area.fillColor }),
            }));
    }
    for (const path of map.paths) {
        addFeature(new ol.geom.LineString(path.coordinates.map(toMap)),
            { label: path.label, description: path.description, image: null, fields: [] },
            new ol.style.Style({ stroke: new ol.style.Stroke({ color: path.color, width: path.width }) }));
    }
    for (const marker of map.markers) {
        const position = toMap(marker.lonLat);
        addFeature(new ol.geom.Point(position),
            { label: marker.label, description: marker.description, image: marker.image, fields: marker.fields, anchor: position },
            new ol.style.Style({
                image: new ol.style.Circle({
                    radius: 7,
                    fill: new ol.style.Fill({ color: marker.color }),
                    stroke: new ol.style.Stroke({ color: '#ffffff', width: 2 }),
                }),
            }));
    }

    const source = new ol.source.Vector();
    source.addFeatures(features);
    const popup = createPopup(onOpenImage);
    const overlay = new ol.Overlay({
        element: popup.element,
        positioning: 'bottom-center',
        // Clicks inside the popup, such as on a photo, stay there instead of closing it.
        stopEvent: true,
        offset: [0, -12],
    });
    const view = new ol.View({
        center: toMap(map.view.center),
        zoom: map.view.zoom,
        maxZoom: map.view.maxZoom,
    });
    const olMap = new ol.Map({
        target,
        layers: [
            new ol.layer.Tile({
                source: new ol.source.XYZ({
                    url: apiUrl(map.tileUrlTemplate),
                    crossOrigin: TILE_CROSS_ORIGIN,
                    maxZoom: map.view.maxZoom,
                }),
            }),
            new ol.layer.Vector({ source }),
        ],
        overlays: [overlay],
        view,
        controls: ol.control.defaults.defaults({ attribution: false }),
        interactions: ol.interaction.defaults.defaults({ mouseWheelZoom: false }),
    });
    olMap.addInteraction(new ol.interaction.MouseWheelZoom({
        condition: ol.events.condition.platformModifierKeyOnly,
    }));
    // OpenLayers labels the button with a glyph and a tooltip only, so it is named explicitly.
    const fullScreen = new ol.control.FullScreen({ tipLabel: 'Full screen' });
    fullScreen.element.querySelector('button')?.setAttribute('aria-label', 'Full screen');
    olMap.addControl(fullScreen);

    // Hovering a marker, path or area shows its details; clicking keeps them open until the
    // reader clicks somewhere else on the map or presses Escape.
    let pinned = false;
    const hide = () => {
        popup.hide();
        overlay.setPosition(undefined);
    };
    const showDetails = (feature: OlFeature, pixel: number[], coordinate: number[]) => {
        const details = feature.getProperties().details as FeatureDetails;
        // Open on whichever side of the point has more room, so the card's edge does not cut it off.
        const [width = 0, height = 0] = olMap.getSize() ?? [];
        const vertical = pixel[1] < height / 2 ? 'top' : 'bottom';
        const horizontal = pixel[0] < width / 3 ? 'left' : pixel[0] > (width * 2) / 3 ? 'right' : 'center';
        overlay.setPositioning(`${vertical}-${horizontal}`);
        overlay.setOffset([0, vertical === 'top' ? 12 : -12]);
        popup.show(details);
        overlay.setPosition(details.anchor ?? coordinate);
    };
    olMap.on('pointermove', (event) => {
        if (event.dragging) {
            return;
        }
        const feature = olMap.forEachFeatureAtPixel(event.pixel, (found) => found);
        target.style.cursor = feature ? 'pointer' : '';
        if (pinned) {
            return;
        }
        if (feature) {
            showDetails(feature, event.pixel, event.coordinate);
        } else {
            hide();
        }
    });
    olMap.on('click', (event) => {
        const feature = olMap.forEachFeatureAtPixel(event.pixel, (found) => found);
        pinned = Boolean(feature);
        if (feature) {
            showDetails(feature, event.pixel, event.coordinate);
            // A pinned popup is there to be read and clicked, so the map moves to show all of it.
            overlay.panIntoView({ animation: { duration: 200 }, margin: 12 });
        } else {
            hide();
        }
    });
    const onPointerLeave = () => {
        if (!pinned) {
            hide();
        }
    };
    const onKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
            pinned = false;
            hide();
        }
    };
    target.addEventListener('pointerleave', onPointerLeave);
    target.addEventListener('keydown', onKeyDown);

    // Fit once the card has its final size, so every marker and path starts in view.
    const frame = requestAnimationFrame(() => {
        olMap.updateSize();
        const extent = source.getExtent();
        if (map.view.fitToFeatures && features.length > 0 && !ol.extent.isEmpty(extent)) {
            view.fit(extent, { padding: [40, 40, 40, 40], maxZoom: map.view.maxZoom, duration: 0 });
        }
    });

    return () => {
        cancelAnimationFrame(frame);
        target.removeEventListener('pointerleave', onPointerLeave);
        target.removeEventListener('keydown', onKeyDown);
        olMap.setTarget(undefined);
        olMap.dispose();
    };
}

/** A text list of everything on the map, for keyboard and screen reader users. */
function MapContentsList({ map, onOpenImage }: { map: InlineMap; onOpenImage: OpenImage }) {
    const items: Array<{ icon: typeof MapPin; label: string; description: string; image: MapImage | null; fields: MapField[] }> = [
        ...map.markers.map((marker) => ({
            icon: MapPin, label: marker.label, description: marker.description, image: marker.image, fields: marker.fields,
        })),
        ...map.paths.map((path) => ({ icon: Route, label: path.label, description: path.description, image: null, fields: [] })),
        ...map.areas.map((area) => ({ icon: Square, label: area.label, description: area.description, image: null, fields: [] })),
    ];

    return (
        <details className="border-t border-edge text-xs">
            <summary className="cursor-pointer px-3 py-1.5 text-text-2 hover:text-text-1">List what the map shows</summary>
            <ol className="max-h-56 space-y-1 overflow-y-auto px-3 pb-2">
                {items.map((item, index) => {
                    const Icon = item.icon;
                    const image = item.image ? openedImage(item.image, item.label) : null;
                    return (
                        <li key={index} className="flex gap-1.5">
                            <Icon size={12} className="mt-0.5 shrink-0 text-text-3" aria-hidden="true" />
                            <span className="min-w-0 flex-1">
                                <span className="font-medium text-text-1">{item.label}</span>
                                {item.description && <span className="text-text-3"> {'\u2014'} {item.description}</span>}
                                {item.fields.length > 0 && (
                                    <span className="block text-text-3">
                                        {item.fields.map((field) => `${field.label}: ${field.value}`).join(' \u00b7 ')}
                                    </span>
                                )}
                            </span>
                            {image && (
                                <button
                                    type="button"
                                    onClick={() => onOpenImage(image)}
                                    title="View the full-size photo"
                                    aria-label={`View the full-size photo: ${image.title}`}
                                    aria-haspopup="dialog"
                                    className="shrink-0 overflow-hidden rounded border border-edge bg-black"
                                >
                                    <img src={image.url} alt="" loading="lazy" referrerPolicy="no-referrer" className="block h-10 w-16 object-cover" />
                                </button>
                            )}
                        </li>
                    );
                })}
            </ol>
        </details>
    );
}

export function InlineMapCard({ map }: { map: InlineMap }) {
    const targetRef = useRef<HTMLDivElement>(null);
    const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
    const [opened, setOpened] = useState<OpenedImage | null>(null);
    // Redraw only when the map itself changes, not each time the message object is replaced.
    const signature = useMemo(() => JSON.stringify(map), [map]);
    const latestMap = useRef(map);
    latestMap.current = map;

    useEffect(() => {
        const target = targetRef.current;
        if (!target) {
            return undefined;
        }
        let disposed = false;
        let release: (() => void) | null = null;
        setStatus('loading');
        loadOpenLayers()
            .then((ol) => {
                if (!disposed) {
                    release = drawMap(ol, target, latestMap.current, setOpened);
                    setStatus('ready');
                }
            })
            .catch(() => {
                if (!disposed) {
                    setStatus('failed');
                }
            });
        return () => {
            disposed = true;
            release?.();
        };
    }, [signature]);

    const openedSource = opened ? resolveImageSource(opened.url) : null;

    return (
        <figure className="m-0 w-full max-w-3xl overflow-hidden rounded-xl border border-edge bg-surface-1">
            <figcaption className="flex items-start gap-2 px-3 py-2">
                <MapPin size={15} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-text-1">{map.title}</span>
                    {map.summary && <span className="mt-0.5 block text-xs text-text-2">{map.summary}</span>}
                </span>
                <span className="shrink-0 pt-0.5 text-[11px] text-text-3">{describeMapContents(map).join(' \u00b7 ')}</span>
            </figcaption>
            <div className="relative">
                <div
                    ref={targetRef}
                    tabIndex={0}
                    role="region"
                    aria-label={`Interactive map: ${map.title}. Arrow keys pan, plus and minus zoom, Escape closes details.`}
                    className="h-[22rem] w-full bg-surface-sunken outline-none focus-visible:ring-2 focus-visible:ring-accent"
                />
                {status !== 'ready' && (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 text-center text-xs text-text-3">
                        {status === 'loading'
                            ? 'Loading map\u2026'
                            : 'This map could not be drawn in this browser. Everything it shows is listed below.'}
                    </div>
                )}
            </div>
            <MapContentsList map={map} onOpenImage={setOpened} />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-t border-edge px-3 py-1.5 text-[11px] text-text-3">
                <span>{map.provider}</span>
                {map.sourceActionName && (
                    <>
                        <span aria-hidden="true">{'\u00b7'}</span>
                        <span>{map.sourceActionName}</span>
                    </>
                )}
                {map.attribution && (
                    <>
                        <span aria-hidden="true">{'\u00b7'}</span>
                        <span>{map.attribution}</span>
                    </>
                )}
                <span className="ml-auto">{ZOOM_HINT}</span>
            </div>
            {opened && openedSource &&
                createPortal(
                    <ImageLightbox
                        source={openedSource}
                        title={opened.title}
                        naming={{ prompt: opened.title }}
                        onClose={() => setOpened(null)}
                    />,
                    document.body,
                )}
        </figure>
    );
}

/**
 * Every map attached to a message, drawn under the reply.
 *
 * A map stored as a compact citation is fetched once, by artifact, before it is drawn.
 */
export function InlineMapCards({ citations, conversationId }: { citations: unknown; conversationId: string }) {
    const entries = useMemo(() => collectMapCitations(citations), [citations]);
    const [stored, setStored] = useState<Record<string, InlineMap | null>>({});
    const requested = useRef(new Set<string>());

    useEffect(() => {
        if (!conversationId) {
            return;
        }
        for (const entry of entries) {
            const artifactId = entry.artifactId;
            if (!artifactId || requested.current.has(artifactId)) {
                continue;
            }
            requested.current.add(artifactId);
            fetchAgentCitation(conversationId, artifactId)
                .then((response) => readInlineMap(response?.citation))
                .catch(() => null)
                .then((map) => setStored((current) => ({ ...current, [artifactId]: map })));
        }
    }, [entries, conversationId]);

    const maps = entries.flatMap((entry) => {
        const map = entry.map ?? (entry.artifactId ? stored[entry.artifactId] : null);
        return map ? [{ key: entry.key, map }] : [];
    });
    if (maps.length === 0) {
        return null;
    }

    return (
        <div className="mt-3 flex flex-col gap-3">
            {maps.map(({ key, map }) => (
                <InlineMapCard key={key} map={map} />
            ))}
        </div>
    );
}
