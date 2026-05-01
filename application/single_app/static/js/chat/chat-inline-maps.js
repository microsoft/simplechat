// chat-inline-maps.js
import { fetchAgentCitationArtifact } from "./chat-citations.js";
import { escapeHtml } from "./chat-utils.js";

const AZURE_MAPS_RENDER_TYPE = "azure_maps_openlayers";

function toFiniteNumber(value) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : null;
}

function normalizeCoordinatePair(rawCoordinate) {
    if (!Array.isArray(rawCoordinate) || rawCoordinate.length < 2) {
        return null;
    }

    const longitude = toFiniteNumber(rawCoordinate[0]);
    const latitude = toFiniteNumber(rawCoordinate[1]);
    if (longitude === null || latitude === null) {
        return null;
    }

    return [longitude, latitude];
}

function parseJsonValue(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    if (typeof value === "object") {
        return value;
    }

    try {
        return JSON.parse(value);
    } catch (error) {
        return null;
    }
}

function getCitationResult(candidate) {
    if (!candidate || typeof candidate !== "object") {
        return null;
    }

    if (candidate.render_type && candidate.map_payload) {
        return candidate;
    }

    const parsedResult = parseJsonValue(candidate.function_result);
    if (parsedResult && typeof parsedResult === "object") {
        return parsedResult;
    }

    return null;
}

function isAzureMapsVisualization(result) {
    return Boolean(
        result
        && result.success !== false
        && result.render_type === AZURE_MAPS_RENDER_TYPE
        && result.map_payload
        && typeof result.map_payload === "object"
        && result.map_payload.tile_url_template
    );
}

function normalizeMarkers(rawMarkers = []) {
    if (!Array.isArray(rawMarkers)) {
        return [];
    }

    return rawMarkers
        .map((marker) => {
            if (!marker || typeof marker !== "object" || Array.isArray(marker)) {
                return null;
            }

            const longitude = toFiniteNumber(marker.longitude ?? marker.lon ?? marker.lng);
            const latitude = toFiniteNumber(marker.latitude ?? marker.lat);
            if (longitude === null || latitude === null) {
                return null;
            }

            return {
                ...marker,
                longitude,
                latitude,
                label: typeof marker.label === "string" && marker.label.trim() ? marker.label.trim() : "Location",
                description: typeof marker.description === "string" ? marker.description : "",
            };
        })
        .filter(Boolean);
}

function normalizeAreas(rawAreas = []) {
    if (!Array.isArray(rawAreas)) {
        return [];
    }

    return rawAreas
        .map((area) => {
            if (!area || typeof area !== "object" || Array.isArray(area)) {
                return null;
            }

            let rawCoordinates = area.coordinates;
            if (
                Array.isArray(rawCoordinates)
                && Array.isArray(rawCoordinates[0])
                && Array.isArray(rawCoordinates[0][0])
            ) {
                rawCoordinates = rawCoordinates[0];
            }

            const coordinates = Array.isArray(rawCoordinates)
                ? rawCoordinates.map((coordinate) => normalizeCoordinatePair(coordinate)).filter(Boolean)
                : [];

            if (coordinates.length < 3) {
                return null;
            }

            const firstCoordinate = coordinates[0];
            const lastCoordinate = coordinates[coordinates.length - 1];
            if (!lastCoordinate || firstCoordinate[0] !== lastCoordinate[0] || firstCoordinate[1] !== lastCoordinate[1]) {
                coordinates.push([...firstCoordinate]);
            }

            return {
                ...area,
                coordinates,
                label: typeof area.label === "string" && area.label.trim() ? area.label.trim() : "Area",
                description: typeof area.description === "string" ? area.description : "",
            };
        })
        .filter(Boolean);
}

function normalizePaths(rawPaths = []) {
    if (!Array.isArray(rawPaths)) {
        return [];
    }

    return rawPaths
        .map((path) => {
            if (!path || typeof path !== "object" || Array.isArray(path)) {
                return null;
            }

            let rawCoordinates = path.coordinates;
            if (
                Array.isArray(rawCoordinates)
                && Array.isArray(rawCoordinates[0])
                && Array.isArray(rawCoordinates[0][0])
            ) {
                rawCoordinates = rawCoordinates[0];
            }

            const coordinates = Array.isArray(rawCoordinates)
                ? rawCoordinates.map((coordinate) => normalizeCoordinatePair(coordinate)).filter(Boolean)
                : [];

            if (coordinates.length < 2) {
                return null;
            }

            const lineWidth = toFiniteNumber(path.line_width ?? path.lineWidth ?? path.width);
            return {
                ...path,
                coordinates,
                label: typeof path.label === "string" && path.label.trim() ? path.label.trim() : "Path",
                description: typeof path.description === "string" ? path.description : "",
                line_width: lineWidth === null ? 4 : lineWidth,
            };
        })
        .filter(Boolean);
}

function buildFallbackCenter(markers, areas, paths) {
    if (markers.length > 0) {
        return [markers[0].longitude, markers[0].latitude];
    }

    if (areas.length > 0 && Array.isArray(areas[0].coordinates) && areas[0].coordinates.length > 0) {
        return [...areas[0].coordinates[0]];
    }

    if (paths.length > 0 && Array.isArray(paths[0].coordinates) && paths[0].coordinates.length > 0) {
        return [...paths[0].coordinates[0]];
    }

    return [0, 20];
}

function normalizeView(rawView = {}, markers = [], areas = [], paths = []) {
    const fallbackCenter = buildFallbackCenter(markers, areas, paths);
    const parsedCenter = normalizeCoordinatePair(rawView?.center);
    const zoom = toFiniteNumber(rawView?.zoom);
    const maxZoom = toFiniteNumber(rawView?.max_zoom);

    return {
        center: parsedCenter || fallbackCenter,
        zoom: zoom === null ? (markers.length === 1 && areas.length === 0 && paths.length === 0 ? 14 : 10) : zoom,
        max_zoom: maxZoom === null ? 15 : maxZoom,
        fit_to_features: rawView?.fit_to_features !== false,
    };
}

function normalizeAzureMapsResult(result) {
    if (!isAzureMapsVisualization(result)) {
        return null;
    }

    const payload = result.map_payload || {};
    const markers = normalizeMarkers(payload.markers);
    const areas = normalizeAreas(payload.areas);
    const paths = normalizePaths(payload.paths);
    if (markers.length === 0 && areas.length === 0 && paths.length === 0) {
        return null;
    }

    return {
        ...result,
        map_payload: {
            ...payload,
            markers,
            paths,
            areas,
            view: normalizeView(payload.view || {}, markers, areas, paths),
        },
    };
}

async function hydrateAzureMapsCitation(conversationId, artifactId) {
    try {
        const hydratedCitation = await fetchAgentCitationArtifact(conversationId, artifactId);
        return normalizeAzureMapsResult(getCitationResult(hydratedCitation));
    } catch (error) {
        console.warn("Failed to hydrate Azure Maps citation artifact", error);
        return null;
    }
}

async function resolveAzureMapsVisualization(citation, conversationId) {
    const shouldPreferArtifact = Boolean(citation?.artifact_id && conversationId);

    if (shouldPreferArtifact) {
        const hydratedResult = await hydrateAzureMapsCitation(conversationId, citation.artifact_id);
        if (hydratedResult) {
            return hydratedResult;
        }
    }

    const localResult = normalizeAzureMapsResult(getCitationResult(citation));
    if (localResult) {
        return localResult;
    }

    if (!citation?.artifact_id || !conversationId || shouldPreferArtifact) {
        return null;
    }

    return hydrateAzureMapsCitation(conversationId, citation.artifact_id);
}

function createBadge(label, value) {
    const badge = document.createElement("span");
    badge.className = "inline-map-badge";
    badge.textContent = `${label}: ${value}`;
    return badge;
}

function buildPopupHtml(properties) {
    const label = escapeHtml(properties?.label || "Map item");
    const description = properties?.description
        ? `<div class="inline-map-popup-description">${escapeHtml(properties.description)}</div>`
        : "";

    return `
        <div class="inline-map-popup-title">${label}</div>
        ${description}
    `;
}

function createMarkerFeature(olRef, marker) {
    const feature = new olRef.Feature({
        geometry: new olRef.geom.Point(olRef.proj.fromLonLat([
            Number(marker.longitude),
            Number(marker.latitude),
        ])),
        featureType: "marker",
        label: marker.label || "Location",
        description: marker.description || "",
    });

    feature.setStyle(new olRef.style.Style({
        image: new olRef.style.Circle({
            radius: 8,
            fill: new olRef.style.Fill({
                color: marker.color || "#0d6efd",
            }),
            stroke: new olRef.style.Stroke({
                color: "#ffffff",
                width: 2,
            }),
        }),
    }));

    return feature;
}

function createAreaFeature(olRef, area) {
    const ring = (area.coordinates || []).map((coordinate) => olRef.proj.fromLonLat([
        Number(coordinate[0]),
        Number(coordinate[1]),
    ]));

    const feature = new olRef.Feature({
        geometry: new olRef.geom.Polygon([ring]),
        featureType: "area",
        label: area.label || "Area",
        description: area.description || "",
    });

    feature.setStyle(new olRef.style.Style({
        stroke: new olRef.style.Stroke({
            color: area.stroke_color || "#b02a37",
            width: 2,
        }),
        fill: new olRef.style.Fill({
            color: area.fill_color || "rgba(176, 42, 55, 0.20)",
        }),
    }));

    return feature;
}

function createPathFeature(olRef, path) {
    const line = (path.coordinates || []).map((coordinate) => olRef.proj.fromLonLat([
        Number(coordinate[0]),
        Number(coordinate[1]),
    ]));

    const feature = new olRef.Feature({
        geometry: new olRef.geom.LineString(line),
        featureType: "path",
        label: path.label || "Path",
        description: path.description || "",
    });

    feature.setStyle(new olRef.style.Style({
        stroke: new olRef.style.Stroke({
            color: path.stroke_color || "#0b5ed7",
            width: Number(path.line_width || 4),
        }),
    }));

    return feature;
}

function fitViewToFeatures(olRef, vectorSource, view, payload, featureCount) {
    if (!payload.view?.fit_to_features || featureCount === 0) {
        return;
    }

    const extent = vectorSource.getExtent();
    const extentIsEmpty = typeof olRef.extent?.isEmpty === "function"
        ? olRef.extent.isEmpty(extent)
        : false;
    if (extentIsEmpty) {
        return;
    }

    view.fit(extent, {
        padding: [48, 48, 48, 48],
        maxZoom: payload.view?.max_zoom || 15,
        duration: 0,
    });
}

function initializeOpenLayersMap(mapElement, popupElement, payload) {
    const olRef = window.ol;
    if (!olRef?.Map || !olRef?.layer?.Tile || !olRef?.source?.XYZ) {
        throw new Error("OpenLayers is not available.");
    }

    const tileLayer = new olRef.layer.Tile({
        source: new olRef.source.XYZ({
            url: payload.tile_url_template,
            attributions: payload.tile_attribution || "",
            crossOrigin: "anonymous",
            maxZoom: payload.view?.max_zoom || 15,
        }),
    });

    const vectorSource = new olRef.source.Vector();
    const features = [];

    (payload.markers || []).forEach((marker) => {
        features.push(createMarkerFeature(olRef, marker));
    });

    (payload.paths || []).forEach((path) => {
        features.push(createPathFeature(olRef, path));
    });

    (payload.areas || []).forEach((area) => {
        features.push(createAreaFeature(olRef, area));
    });

    vectorSource.addFeatures(features);

    const vectorLayer = new olRef.layer.Vector({
        source: vectorSource,
    });

    const overlay = new olRef.Overlay({
        element: popupElement,
        positioning: "bottom-center",
        stopEvent: false,
        offset: [0, -14],
    });

    const view = new olRef.View({
        center: olRef.proj.fromLonLat(payload.view?.center || [0, 20]),
        zoom: payload.view?.zoom || 10,
        maxZoom: payload.view?.max_zoom || 15,
    });

    const map = new olRef.Map({
        target: mapElement,
        layers: [tileLayer, vectorLayer],
        overlays: [overlay],
        view,
        controls: typeof olRef.control?.defaults === "function"
            ? olRef.control.defaults({ attributionOptions: { collapsible: true } })
            : undefined,
    });

    map.on("click", (event) => {
        const feature = map.forEachFeatureAtPixel(event.pixel, (selectedFeature) => selectedFeature);
        if (!feature) {
            popupElement.classList.remove("is-visible");
            overlay.setPosition(undefined);
            return;
        }

        popupElement.innerHTML = buildPopupHtml(feature.getProperties());
        popupElement.classList.add("is-visible");
        overlay.setPosition(event.coordinate);
    });

    map.on("pointermove", (event) => {
        map.getTargetElement().style.cursor = map.hasFeatureAtPixel(event.pixel) ? "pointer" : "";
    });

    requestAnimationFrame(() => {
        map.updateSize();
        fitViewToFeatures(olRef, vectorSource, view, payload, features.length);
        requestAnimationFrame(() => {
            map.updateSize();
            fitViewToFeatures(olRef, vectorSource, view, payload, features.length);
        });
    });
}

function createFallbackNotice(message) {
    const fallback = document.createElement("div");
    fallback.className = "inline-map-fallback";
    fallback.textContent = message;
    return fallback;
}

function createMapCard(result, messageId, index) {
    const payload = result.map_payload || {};
    const card = document.createElement("section");
    card.className = "inline-map-card";

    const safeMessageId = String(messageId || "map").replace(/[^a-zA-Z0-9_-]/g, "-");
    const mapId = `inline-map-${safeMessageId}-${index}`;
    const markerCount = Array.isArray(payload.markers) ? payload.markers.length : 0;
    const pathCount = Array.isArray(payload.paths) ? payload.paths.length : 0;
    const areaCount = Array.isArray(payload.areas) ? payload.areas.length : 0;
    const summaryText = payload.summary || result.summary || "Interactive Azure Maps visualization.";

    card.innerHTML = `
        <div class="inline-map-card-header">
            <div class="inline-map-card-copy">
                <div class="inline-map-card-title-row">
                    <span class="inline-map-card-icon"><i class="bi bi-geo-alt-fill"></i></span>
                    <h6 class="inline-map-card-title mb-0">${escapeHtml(payload.title || "Interactive Map")}</h6>
                </div>
                <p class="inline-map-card-summary mb-0">${escapeHtml(summaryText)}</p>
            </div>
            <div class="inline-map-badges" aria-label="Map details"></div>
        </div>
        <div class="inline-map-shell">
            <div class="inline-map-canvas" id="${mapId}"></div>
            <div class="inline-map-popup"></div>
        </div>
        <div class="inline-map-footer">
            <span>${escapeHtml(payload.map_provider === "azure_maps" ? "Azure Maps" : "Map")}</span>
            <span class="inline-map-footer-separator">•</span>
            <span>${escapeHtml(payload.source_action_name || "Map action")}</span>
        </div>
    `;

    const badgesContainer = card.querySelector(".inline-map-badges");
    if (badgesContainer) {
        badgesContainer.appendChild(createBadge("Markers", markerCount));
        if (pathCount > 0) {
            badgesContainer.appendChild(createBadge("Paths", pathCount));
        }
        badgesContainer.appendChild(createBadge("Areas", areaCount));
        if (payload.tileset_id) {
            badgesContainer.appendChild(createBadge("Tiles", payload.tileset_id));
        }
    }

    return {
        card,
        mapElement: card.querySelector(".inline-map-canvas"),
        popupElement: card.querySelector(".inline-map-popup"),
        payload,
    };
}

export async function renderInlineAzureMaps(messageElement, agentCitations = [], messageId = "", conversationId = "") {
    if (!messageElement) {
        return;
    }

    const container = messageElement.querySelector(".inline-visualizations-container");
    if (!container) {
        return;
    }

    container.querySelectorAll(".inline-map-card").forEach((card) => card.remove());

    if (!Array.isArray(agentCitations) || agentCitations.length === 0) {
        container.classList.toggle("d-none", container.children.length === 0);
        return;
    }

    const pendingMaps = [];
    let renderedCount = 0;
    for (let index = 0; index < agentCitations.length; index += 1) {
        const citation = agentCitations[index];
        const result = await resolveAzureMapsVisualization(citation, conversationId);
        if (!result) {
            continue;
        }

        const { card, mapElement, popupElement, payload } = createMapCard(result, messageId, index);
        container.appendChild(card);
        pendingMaps.push({ card, mapElement, popupElement, payload });

        renderedCount += 1;
    }

    container.classList.toggle("d-none", container.children.length === 0);

    pendingMaps.forEach(({ card, mapElement, popupElement, payload }) => {
        try {
            initializeOpenLayersMap(mapElement, popupElement, payload);
        } catch (error) {
            console.warn("Failed to initialize inline Azure Maps visualization", error);
            const mapShell = card.querySelector(".inline-map-shell");
            if (mapShell) {
                mapShell.innerHTML = "";
                mapShell.appendChild(createFallbackNotice("The map data is available, but OpenLayers could not be initialized in this browser session."));
            }
        }
    });
}