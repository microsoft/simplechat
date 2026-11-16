// test_v2_inline_maps_logic.mjs
// Version: 0.261.225
// Implemented in: 0.261.223
// Marker photos and fields in: 0.261.225
// Executes the real V2 inline map helpers: which tool results become maps, how markers, paths,
// areas and the starting view are read, and that nothing in a payload can point tiles at
// another host, load a marker photo from anything but an https link, or slip markup or an
// unchecked colour through.

import assert from 'node:assert/strict';

const {
    AZURE_MAPS_RENDER_TYPE, TILE_PROXY_PATH, collectMapCitations, describeMapContents, readInlineMap, safeImageUrl,
    safeTileTemplate, stripLegacyMapBlocks,
} = await import('../application/v2_ui/src/lib/inlineMaps.ts');

const TEMPLATE = `${TILE_PROXY_PATH}?token=abc&api-version=2024-04-01&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}&tileSize=256`;

function mapResult(overrides = {}, payloadOverrides = {}) {
    return {
        success: true,
        render_type: AZURE_MAPS_RENDER_TYPE,
        summary: 'Result summary',
        map_payload: {
            title: 'Vehicle movement',
            summary: 'Documented stops',
            map_provider: 'azure_maps',
            source_action_name: 'case_map',
            tile_attribution: '\u00a9 Microsoft Corporation',
            tile_url_template: TEMPLATE,
            markers: [
                { label: 'Pickup', description: 'Rental counter', latitude: 33.6538, longitude: -84.4709, color: '#0d6efd' },
                { label: 'Toll read', lat: 34.01, lon: -84.2 },
            ],
            paths: [{ label: 'Route', coordinates: [[-84.47, 33.65], [-84.2, 34.01]], stroke_color: '#123456', line_width: 6 }],
            areas: [],
            view: { center: [-84.3, 33.8], zoom: 9, max_zoom: 15, fit_to_features: true },
            ...payloadOverrides,
        },
        ...overrides,
    };
}

const citation = (result, extra = {}) => ({
    function_name: 'create_map_visualization',
    plugin_name: 'AzureMapsOpenLayersPlugin',
    function_result: result,
    ...extra,
});

const checks = [];
const check = (name, run) => checks.push([name, run]);

check('a map result is read from an object or from JSON text', () => {
    for (const stored of [mapResult(), JSON.stringify(mapResult())]) {
        const map = readInlineMap(citation(stored));
        assert.ok(map, 'expected a map');
        assert.equal(map.title, 'Vehicle movement');
        assert.equal(map.summary, 'Documented stops');
        assert.equal(map.provider, 'Azure Maps');
        assert.equal(map.sourceActionName, 'case_map');
        assert.equal(map.attribution, '\u00a9 Microsoft Corporation');
        assert.equal(map.tileUrlTemplate, TEMPLATE);
        assert.deepEqual(map.markers.map((marker) => marker.lonLat), [[-84.4709, 33.6538], [-84.2, 34.01]]);
        assert.deepEqual(map.view, { center: [-84.3, 33.8], zoom: 9, maxZoom: 15, fitToFeatures: true });
    }
});

check('a hydrated result with the payload at the top level is read too', () => {
    assert.ok(readInlineMap(mapResult()));
});

check('failed, foreign and empty results are not maps', () => {
    assert.equal(readInlineMap(citation(mapResult({ success: false }))), null);
    assert.equal(readInlineMap(citation(mapResult({ render_type: 'chart' }))), null);
    assert.equal(readInlineMap(citation(mapResult({}, { markers: [], paths: [], areas: [] }))), null);
    assert.equal(readInlineMap(citation('not json')), null);
    assert.equal(readInlineMap(citation({ success: true })), null);
    assert.equal(readInlineMap(null), null);
    assert.equal(readInlineMap('text'), null);
});

check('tiles only ever come from the SimpleChat tile proxy', () => {
    assert.equal(safeTileTemplate(TEMPLATE), TEMPLATE);
    assert.equal(safeTileTemplate(`  ${TEMPLATE}  `), TEMPLATE);
    assert.equal(safeTileTemplate('https://tiles.example.test/{z}/{x}/{y}.png'), null);
    assert.equal(safeTileTemplate('//tiles.example.test/api/azure-maps/tile?{z}{x}{y}'), null);
    assert.equal(safeTileTemplate('/api/azure-maps/tiles?{z}{x}{y}'), null);
    assert.equal(safeTileTemplate('/api/azure-maps/tile?token=abc&zoom={z}&x={x}'), null);
    assert.equal(safeTileTemplate('/api/azure-maps/tile?token="><img src=x>&{z}{x}{y}'), null);
    assert.equal(safeTileTemplate(undefined), null);
    assert.equal(readInlineMap(citation(mapResult({}, { tile_url_template: 'https://tiles.example.test/{z}/{x}/{y}' }))), null);
});

check('points must be real longitudes and latitudes', () => {
    const map = readInlineMap(citation(mapResult({}, {
        markers: [
            { label: 'Kept', latitude: '40.7', longitude: '-74.0' },
            { label: 'Latitude too large', latitude: 95, longitude: 10 },
            { label: 'Longitude too large', latitude: 10, longitude: 200 },
            { label: 'Missing', latitude: 10 },
            { label: 'Not a number', latitude: 'north', longitude: 3 },
            { label: 'Boolean', latitude: true, longitude: 3 },
            'not an object',
        ],
    })));
    assert.deepEqual(map.markers.map((marker) => marker.label), ['Kept']);
    assert.deepEqual(map.markers[0].lonLat, [-74, 40.7]);
});

check('labels default, and text is kept exactly as written for React to render as text', () => {
    const map = readInlineMap(citation(mapResult({}, {
        markers: [
            { latitude: 1, longitude: 1 },
            { label: '<img src=x onerror=alert(1)>', description: '<b>bold</b>', latitude: 2, longitude: 2 },
        ],
        paths: [{ coordinates: [[0, 0], [1, 1]] }],
        areas: [{ coordinates: [[0, 0], [1, 0], [1, 1]] }],
    })));
    assert.equal(map.markers[0].label, 'Location');
    assert.equal(map.markers[1].label, '<img src=x onerror=alert(1)>');
    assert.equal(map.markers[1].description, '<b>bold</b>');
    assert.equal(map.paths[0].label, 'Path');
    assert.equal(map.areas[0].label, 'Area');
});

check('only values that look like colours are passed to the map', () => {
    const map = readInlineMap(citation(mapResult({}, {
        markers: [
            { label: 'hex', color: '#ff000080', latitude: 1, longitude: 1 },
            { label: 'rgba', color: 'rgba(1, 2, 3, 0.5)', latitude: 1, longitude: 1 },
            { label: 'keyword', color: 'crimson', latitude: 1, longitude: 1 },
            { label: 'injection', color: 'red; background:url(https://x)', latitude: 1, longitude: 1 },
            { label: 'url', color: 'url(https://x)', latitude: 1, longitude: 1 },
            { label: 'object', color: { r: 1 }, latitude: 1, longitude: 1 },
        ],
    })));
    assert.deepEqual(map.markers.map((marker) => marker.color), [
        '#ff000080', 'rgba(1, 2, 3, 0.5)', 'crimson', '#0d6efd', '#0d6efd', '#0d6efd',
    ]);
});

check('a marker keeps an https photo and its caption, and any other link is dropped', () => {
    const photo = 'https://media.example.test/tlpr/media/tlpr-scene-TR-1.png?exp=1791043200&sig=0a1b2c';
    const at = { latitude: 1, longitude: 1 };
    const map = readInlineMap(citation(mapResult({}, {
        markers: [
            { label: 'kept', image_url: photo, image_caption: '  Overview MD-T01  ', ...at },
            { label: 'no caption', image_url: photo, ...at },
            { label: 'none', ...at },
            { label: 'http', image_url: 'http://media.example.test/a.png', ...at },
            { label: 'relative', image_url: '/api/image/abc', ...at },
            { label: 'protocol relative', image_url: '//media.example.test/a.png', ...at },
            { label: 'script', image_url: 'javascript:alert(1)', ...at },
            { label: 'data', image_url: 'data:image/png;base64,AAAA', ...at },
            { label: 'quote', image_url: 'https://media.example.test/a.png"onerror="x', ...at },
            { label: 'space', image_url: 'https://media.example.test/a b.png', ...at },
            { label: 'too long', image_url: `https://media.example.test/${'a'.repeat(2100)}.png`, ...at },
            { label: 'object', image_url: { url: photo }, ...at },
        ],
    })));
    assert.deepEqual(map.markers[0].image, { url: photo, caption: 'Overview MD-T01' });
    assert.deepEqual(map.markers[1].image, { url: photo, caption: '' });
    assert.deepEqual(map.markers.slice(2).map((marker) => marker.image), Array(10).fill(null));
    assert.equal(safeImageUrl(`  ${photo}  `), photo);
    assert.equal(safeImageUrl('https:'), null);
    assert.equal(safeImageUrl(42), null);

    const longCaption = readInlineMap(citation(mapResult({}, {
        markers: [{ image_url: photo, image_caption: 'c'.repeat(250), ...at }],
    })));
    assert.equal(longCaption.markers[0].image.caption.length, 200);
});

check('fields are label and value text, capped as the action caps them', () => {
    const map = readInlineMap(citation(mapResult({}, {
        markers: [{
            label: 'Toll read', latitude: 1, longitude: 1,
            fields: [
                { label: 'Transponder', value: 'GA-PP-4471023' },
                { label: 'Toll', value: 4.5 },
                { label: '  ', value: 'no label' },
                { label: 'No value', value: '' },
                { label: 'Object', value: { nested: true } },
                { label: '<b>Lane</b>', value: '<img src=x>' },
                'not a field',
                { label: 'L'.repeat(80), value: 'V'.repeat(400) },
            ],
        }],
    })));
    const [marker] = map.markers;
    assert.deepEqual(marker.fields.slice(0, 3), [
        { label: 'Transponder', value: 'GA-PP-4471023' },
        { label: 'Toll', value: '4.5' },
        { label: '<b>Lane</b>', value: '<img src=x>' },
    ]);
    assert.equal(marker.fields[3].label.length, 60);
    assert.equal(marker.fields[3].value.length, 300);
    assert.equal(marker.fields.length, 4);

    const many = readInlineMap(citation(mapResult({}, {
        markers: [{ latitude: 1, longitude: 1, fields: Array.from({ length: 20 }, (_, index) => ({ label: `F${index}`, value: 'v' })) }],
    })));
    assert.equal(many.markers[0].fields.length, 12);
    // The action always stores a list; anything else is not read as fields.
    const notAList = readInlineMap(citation(mapResult({}, { markers: [{ latitude: 1, longitude: 1, fields: { Tag: 'x' } }] })));
    assert.deepEqual(notAList.markers[0].fields, []);
});

check('paths need two points and areas three, and an area ring is closed', () => {
    const map = readInlineMap(citation(mapResult({}, {
        paths: [
            { label: 'one point', coordinates: [[0, 0]] },
            { label: 'nested', coordinates: [[[0, 0], [1, 1], [2, 2]]], line_width: 99 },
            { label: 'thin', coordinates: [[0, 0], [1, 1]], lineWidth: 0 },
        ],
        areas: [
            { label: 'two points', coordinates: [[0, 0], [1, 1]] },
            { label: 'open', coordinates: [[0, 0], [1, 0], [1, 1]], fill_color: 'rgba(0, 0, 0, 0.2)' },
            { label: 'closed', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
        ],
    })));
    assert.deepEqual(map.paths.map((path) => path.label), ['nested', 'thin']);
    assert.equal(map.paths[0].coordinates.length, 3);
    assert.equal(map.paths[0].width, 12);
    assert.equal(map.paths[1].width, 1);
    assert.deepEqual(map.areas.map((area) => area.label), ['open', 'closed']);
    assert.deepEqual(map.areas[0].coordinates, [[0, 0], [1, 0], [1, 1], [0, 0]]);
    assert.equal(map.areas[0].fillColor, 'rgba(0, 0, 0, 0.2)');
    assert.equal(map.areas[1].coordinates.length, 4);
    assert.equal(map.areas[1].strokeColor, '#b02a37');
});

check('the starting view falls back sensibly and is clamped', () => {
    const single = readInlineMap(citation(mapResult({}, {
        markers: [{ label: 'Only', latitude: 10, longitude: 20 }], paths: [], view: undefined,
    })));
    assert.deepEqual(single.view, { center: [20, 10], zoom: 14, maxZoom: 15, fitToFeatures: true });

    const several = readInlineMap(citation(mapResult({}, { view: { center: 'nowhere', zoom: 40, max_zoom: 0, fit_to_features: false } })));
    assert.deepEqual(several.view, { center: [-84.4709, 33.6538], zoom: 22, maxZoom: 1, fitToFeatures: false });

    const pathOnly = readInlineMap(citation(mapResult({}, { markers: [], view: {} })));
    assert.deepEqual(pathOnly.view.center, [-84.47, 33.65]);
    assert.equal(pathOnly.view.zoom, 10);
});

check('every map on a message is found in order, and a repeated map is drawn once', () => {
    const first = mapResult();
    const repeated = mapResult({}, { tile_url_template: TEMPLATE.replace('token=abc', 'token=def') });
    const second = mapResult({}, { title: 'Second map' });
    const found = collectMapCitations([
        { tool_name: 'lookup', function_result: { success: true } },
        citation(first),
        citation(JSON.stringify(repeated)),
        citation(second),
    ]);
    assert.deepEqual(found.map((entry) => [entry.key, entry.map?.title]), [
        ['map-1', 'Vehicle movement'],
        ['map-3', 'Second map'],
    ]);
});

check('a compact map citation is fetched by artifact; other compact citations are not', () => {
    const found = collectMapCitations([
        { function_name: 'create_map_visualization', artifact_id: 'art-map', function_result: 'Map: 23 markers' },
        { plugin_name: 'AzureMapsOpenLayersPlugin', artifact_id: 'art-plugin', function_result: '{"truncated": true' },
        { function_name: 'getRead', plugin_name: 'tlpr', artifact_id: 'art-other', function_result: 'Read summary' },
        { function_name: 'create_map_visualization', artifact_id: 'art-failed', success: false },
        { function_name: 'create_map_visualization', artifact_id: '   ' },
    ]);
    assert.deepEqual(found, [
        { key: 'map-0', artifactId: 'art-map' },
        { key: 'map-1', artifactId: 'art-plugin' },
    ]);
    assert.deepEqual(collectMapCitations(undefined), []);
    assert.deepEqual(collectMapCitations({ not: 'a list' }), []);
});

check('the card summarises what the map holds', () => {
    assert.deepEqual(describeMapContents(readInlineMap(citation(mapResult()))), ['2 markers', '1 path']);
    const withArea = readInlineMap(citation(mapResult({}, {
        markers: [{ latitude: 1, longitude: 1 }], paths: [], areas: [{ coordinates: [[0, 0], [1, 0], [1, 1]] }],
    })));
    assert.deepEqual(describeMapContents(withArea), ['1 marker', '1 area']);
    const areaOnly = readInlineMap(citation(mapResult({}, {
        markers: [], paths: [], areas: [{ coordinates: [[0, 0], [1, 0], [1, 1]] }, { coordinates: [[2, 2], [3, 2], [3, 3]] }],
    })));
    assert.deepEqual(describeMapContents(areaOnly), ['2 areas']);
});

check('legacy map blocks are removed from the text, braces in strings included', () => {
    const block = '{{map:{"title":"Route {east}","view":{"zoom":9},"note":"a \\" quote }}"}}';
    assert.equal(stripLegacyMapBlocks(`Before\n\n${block}\n\n\nAfter`), 'Before\n\nAfter');
    assert.equal(stripLegacyMapBlocks(`${block}${block}Only text`), 'Only text');
    assert.equal(stripLegacyMapBlocks(`A {{map:not json}} B ${block} C`), 'A {{map:not json}} B  C');
    assert.equal(stripLegacyMapBlocks('Unclosed {{map:{"title":"x"}'), 'Unclosed {{map:{"title":"x"}');
    const plain = '  Indented code\n\n\n\nno blocks here  ';
    assert.equal(stripLegacyMapBlocks(plain), plain);
    assert.equal(stripLegacyMapBlocks(''), '');
});

let failed = 0;
for (const [name, run] of checks) {
    try {
        run();
        console.log(`PASS ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`FAIL ${name}\n${error.stack}`);
    }
}
console.log(`\n${checks.length - failed}/${checks.length} inline map checks passed`);
process.exit(failed ? 1 : 0);
