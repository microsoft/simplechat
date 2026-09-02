#!/usr/bin/env python3
"""
Functional test for server-side Mermaid rendering in exports.
Version: 0.261.034
Implemented in: 0.261.027
Label-text regression coverage added in: 0.261.034

This test ensures diagrams are rasterized on the server, using the Playwright Chromium
already installed in the image, for exports that have no browser attached to them. It
covers the capability probe, that a rendered diagram keeps its label text, that the
server and browser renderers are configured identically, and that the export route only
renders diagrams the client did not already supply.

The rendering assertions skip themselves when Chromium is unavailable, which is the same
condition under which the feature degrades to leaving the diagram as a code block.
"""

import base64
import io
import os
import sys
import types
from typing import Any, Callable, Dict, List
from unittest import mock


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
sys.path.insert(0, APP_DIR)
sys.modules.setdefault(
    'olefile',
    types.SimpleNamespace(isOleFile=lambda *_args, **_kwargs: False, OleFileIO=None),
)

from functions_export_visuals import normalize_visual_assets  # noqa: E402
from functions_mermaid_server_render import (  # noqa: E402
    MERMAID_RENDER_SCRIPT,
    MERMAID_SERVER_RENDER_FONT_FAMILY,
    build_render_page_style,
    get_embedded_render_font_data_uri,
    get_embedded_render_font_path,
    get_mermaid_bundle_path,
    get_mermaid_server_render_capabilities,
    is_mermaid_server_rendering_available,
    render_mermaid_visual_assets,
)

RASTERIZER_PATH = os.path.join(APP_DIR, 'static', 'js', 'chat', 'chat-visual-rasterizer.js')
MERMAID_RUNTIME_PATH = os.path.join(APP_DIR, 'static', 'js', 'chat', 'chat-mermaid-runtime.js')
DOCKERFILE_PATH = os.path.join(APP_DIR, 'Dockerfile')

FLOWCHART_SOURCE = (
    'graph TD\n'
    '    A[Ingest Documents] --> B{Needs OCR?}\n'
    '    B -->|Yes| C[Document Intelligence]\n'
    '    B -->|No| D[Chunk and Embed]\n'
    '    C --> D'
)
SEQUENCE_SOURCE = 'sequenceDiagram\n    Alice->>Bob: Hello Bob\n    Bob-->>Alice: Hi Alice'
INVALID_SOURCE = 'this is definitely not valid mermaid {{{'

# The same graph with and without label text. Comparing the two is what distinguishes a
# diagram that drew its labels from one that drew only boxes and arrows: a container with no
# scalable font measures every label as zero-width, so the shapes still appear and the text
# does not.
LABELLED_SOURCE = (
    'graph TD\n'
    '    A[Microsoft Entra ID Tenant] --> B[Management Group]\n'
    '    B --> C[Subscription Production Applications]\n'
    '    B --> D[Resource Group prod-web-rg]'
)
UNLABELLED_SOURCE = (
    'graph TD\n'
    '    A[ ] --> B[ ]\n'
    '    B --> C[ ]\n'
    '    B --> D[ ]'
)


def _import_route_helpers():
    """Import the export route module, stubbing Cosmos when Azure config is absent."""
    try:
        import route_backend_conversation_export as route_module

        return route_module, None
    except Exception:
        pass

    try:
        import azure.cosmos as azure_cosmos_module

        os.environ.setdefault('AZURE_COSMOS_ENDPOINT', 'https://example.documents.azure.com:443/')
        os.environ.setdefault('AZURE_COSMOS_KEY', 'ZHVtbXkta2V5LWZvci1sb2NhbC10ZXN0aW5n')
        os.environ.setdefault('AZURE_COSMOS_AUTHENTICATION_TYPE', 'key')

        with mock.patch.object(azure_cosmos_module, 'CosmosClient', mock.MagicMock()):
            import route_backend_conversation_export as route_module

        return route_module, None
    except Exception as import_error:
        return None, import_error


ROUTE_MODULE, ROUTE_IMPORT_ERROR = _import_route_helpers()


def _route_helpers_available() -> bool:
    if ROUTE_MODULE is not None:
        return True

    print(f"Skipping route-dependent assertion: {ROUTE_IMPORT_ERROR}")
    return False


def _server_rendering_available() -> bool:
    if is_mermaid_server_rendering_available():
        return True

    capabilities = get_mermaid_server_render_capabilities()
    print(f"Skipping server rendering assertion: {capabilities.get('message')}")
    return False


def _painted_pixel_ratio(data_uri: str):
    from PIL import Image

    image_bytes = base64.b64decode(data_uri.split(',', 1)[1])
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb_image = image.convert('RGB')
        width, height = rgb_image.size
        colors = rgb_image.getcolors(maxcolors=1_000_000) or []

    painted = sum(count for count, color in colors if color != (255, 255, 255))
    return width, height, painted / float(width * height)


def _dark_pixel_count(data_uri: str) -> int:
    """Count near-black pixels, which is what label glyphs are made of.

    Node fills and edges in the neutral theme are much lighter than text, so this separates
    "the diagram has writing in it" from "the diagram has boxes in it".
    """
    from PIL import Image

    image_bytes = base64.b64decode(data_uri.split(',', 1)[1])
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb_image = image.convert('RGB')
        colors = rgb_image.getcolors(maxcolors=1_000_000) or []

    return sum(count for count, color in colors if sum(color) < 300)


def _asset_for_source(assets: List[Dict[str, Any]], source: str) -> Dict[str, Any]:
    for asset in assets:
        if asset.get('normalized_source') == source.strip():
            return asset
    raise AssertionError(f'no rendered asset for source: {source[:40]}')


def _build_png_data_uri() -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (12, 12), (7, 8, 9)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def test_capability_probe_reports_a_complete_shape():
    """The probe must always answer, whether or not Chromium is present."""
    print("Testing server render capability probe...")

    capabilities = get_mermaid_server_render_capabilities()
    for key in (
        'server_rendering_available',
        'playwright_available',
        'chromium_launch_available',
        'bundle_available',
        'message',
    ):
        assert key in capabilities, capabilities

    assert capabilities['bundle_available'] is True, capabilities
    assert os.path.exists(get_mermaid_bundle_path()), get_mermaid_bundle_path()
    assert isinstance(capabilities['message'], str) and capabilities['message'], capabilities

    print("Server render capability probe passed!")


def test_server_and_browser_renderers_share_configuration():
    """Both renderers must disable htmlLabels, or labels vanish when drawn to canvas.

    The browser-side configuration lives in the shared Mermaid runtime, because inline chat
    rendering and export rendering drive the same global Mermaid instance and would otherwise
    overwrite each other's settings. The rasterizer must ask that runtime for the export
    preset, which is what keeps the neutral theme and fixed sizing this parity depends on.
    """
    print("Testing renderer configuration parity...")

    with open(RASTERIZER_PATH, 'r', encoding='utf-8') as handle:
        client_source = handle.read()

    with open(MERMAID_RUNTIME_PATH, 'r', encoding='utf-8') as handle:
        runtime_source = handle.read()

    assert 'MERMAID_PRESET_EXPORT' in client_source, 'rasterizer must request the export preset'
    assert "theme: 'neutral'" in runtime_source, 'export preset must keep the neutral theme'

    for required in (
        'htmlLabels: false',
        "securityLevel: 'strict'",
        'suppressErrorRendering: true',
    ):
        assert required in runtime_source, f'missing from browser Mermaid runtime: {required}'
        assert required in MERMAID_RENDER_SCRIPT, f'missing from server renderer: {required}'

    print("Renderer configuration parity passed!")


def test_server_renders_diagrams_with_visible_labels():
    """A server-rendered diagram must contain its label text, not just shapes.

    Painted-pixel coverage alone cannot show this: boxes and arrows paint plenty of pixels
    on their own, which is how a build that rendered every label invisibly still passed.
    The labelled graph is therefore compared against the identical graph with its labels
    removed, on two measures that only writing can move.
    """
    print("Testing server diagram rendering...")

    if not _server_rendering_available():
        return

    assets = render_mermaid_visual_assets([
        {'source': FLOWCHART_SOURCE, 'alt': 'Flowchart diagram', 'caption': ''},
        {'source': SEQUENCE_SOURCE, 'alt': 'Sequence diagram', 'caption': ''},
    ])

    assert len(assets) == 2, assets
    for asset in assets:
        assert asset['kind'] == 'diagram', asset
        assert asset['data_uri'].startswith('data:image/png;base64,'), asset['data_uri'][:48]
        width, height, painted_ratio = _painted_pixel_ratio(asset['data_uri'])
        assert width >= 100 and height >= 50, (width, height)
        assert painted_ratio > 0.01, painted_ratio

    label_comparison = render_mermaid_visual_assets([
        {'source': LABELLED_SOURCE},
        {'source': UNLABELLED_SOURCE},
    ])
    assert len(label_comparison) == 2, label_comparison
    labelled = _asset_for_source(label_comparison, LABELLED_SOURCE)
    unlabelled = _asset_for_source(label_comparison, UNLABELLED_SOURCE)

    labelled_dark = _dark_pixel_count(labelled['data_uri'])
    unlabelled_dark = _dark_pixel_count(unlabelled['data_uri'])
    assert labelled_dark > unlabelled_dark + 500, (
        'the labelled diagram drew no more dark pixels than the same diagram with empty '
        f'labels, so its text is missing: {labelled_dark} vs {unlabelled_dark}'
    )

    # Node width follows the width of its label. Uniform, minimum-width boxes are the
    # signature of a runtime that measured every label as zero-width.
    labelled_width, _, _ = _painted_pixel_ratio(labelled['data_uri'])
    unlabelled_width, _, _ = _painted_pixel_ratio(unlabelled['data_uri'])
    assert labelled_width > unlabelled_width, (
        'labelled and unlabelled diagrams came out the same width, so label text was never '
        f'measured: {labelled_width} vs {unlabelled_width}'
    )

    print("Server diagram rendering passed!")


def test_render_font_is_embedded_rather_than_borrowed_from_the_host():
    """The renderer must carry its own font.

    The application image installs no scalable Latin typeface, so a diagram asking for
    Arial or a generic sans-serif resolves to nothing there: Chromium measures every label
    as zero-width, Mermaid falls back to its minimum node size, and the export is a set of
    uniform empty boxes. Embedding the font removes the dependency on the host entirely.
    """
    print("Testing embedded render font...")

    font_path = get_embedded_render_font_path()
    assert font_path and os.path.exists(font_path), (
        'no embeddable font was found; matplotlib supplies DejaVu Sans and is already a '
        f'requirement, so this should not happen: {font_path}'
    )

    data_uri = get_embedded_render_font_data_uri()
    assert data_uri and data_uri.startswith('data:font/ttf;base64,'), (data_uri or '')[:48]

    page_style = build_render_page_style()
    assert '@font-face' in page_style, page_style[:200]
    assert MERMAID_SERVER_RENDER_FONT_FAMILY in page_style, page_style[:200]
    assert data_uri in page_style, 'the font data URI must reach the render page'

    # The render script has to ask for the family that was embedded, or the embedding is
    # decorative and Mermaid still measures against whatever the host provides.
    assert 'options.fontFamily' in MERMAID_RENDER_SCRIPT, MERMAID_RENDER_SCRIPT[:400]

    capabilities = get_mermaid_server_render_capabilities()
    assert capabilities.get('embedded_font_available') is True, capabilities

    print("Embedded render font passed!")


def test_container_image_installs_scalable_fonts():
    """The image should still carry real fonts for everything else that renders in it.

    Source Review and Deep Research screenshot pages in the same Chromium, and they have no
    embedded font of their own. The legacy X11 Type1 and bitmap packages that used to be the
    only font install provide no scalable Latin face.
    """
    print("Testing container font packages...")

    with open(DOCKERFILE_PATH, 'r', encoding='utf-8') as handle:
        dockerfile = handle.read()

    assert 'dejavu' in dockerfile.lower(), 'no scalable font family is installed in the image'
    assert 'fc-cache' in dockerfile, 'the font cache is never rebuilt after installing fonts'

    print("Container font packages passed!")


def test_server_renderer_captures_the_live_page():
    """Diagrams must be screenshotted where they are drawn, not repainted onto a canvas.

    Serializing an SVG and reloading it through an <img> silently drops whatever that
    isolated context will not honour, fonts included, and it is not needed here: this
    renderer already has a real browser page open.
    """
    print("Testing live-page capture...")

    assert 'document.importNode' in MERMAID_RENDER_SCRIPT, MERMAID_RENDER_SCRIPT[:400]
    assert 'document.fonts.ready' in MERMAID_RENDER_SCRIPT, MERMAID_RENDER_SCRIPT[:400]
    for canvas_artifact in ("getContext('2d')", 'drawImage', 'toDataURL', 'new Image()'):
        assert canvas_artifact not in MERMAID_RENDER_SCRIPT, (
            f'the server renderer still rasterizes through a canvas: {canvas_artifact}'
        )

    print("Live-page capture passed!")


def test_server_skips_a_diagram_it_cannot_render():
    """One bad diagram must not lose the good ones."""
    print("Testing server render error isolation...")

    if not _server_rendering_available():
        return

    assets = render_mermaid_visual_assets([
        {'source': INVALID_SOURCE},
        {'source': FLOWCHART_SOURCE},
    ])

    assert len(assets) == 1, assets
    assert assets[0]['normalized_source'] == FLOWCHART_SOURCE, assets[0]['normalized_source']

    print("Server render error isolation passed!")


def test_server_render_deduplicates_and_caps_sources():
    """Repeated diagrams render once, and the batch honours its cap."""
    print("Testing server render source handling...")

    if not _server_rendering_available():
        return

    assets = render_mermaid_visual_assets(
        [{'source': FLOWCHART_SOURCE}, {'source': FLOWCHART_SOURCE}, {'source': SEQUENCE_SOURCE}],
        max_diagrams=1,
    )
    assert len(assets) == 1, assets

    print("Server render source handling passed!")


def test_export_route_fills_only_uncovered_diagrams():
    """The route renders what the client did not, and leaves what it did alone."""
    print("Testing export route asset merging...")

    if not _route_helpers_available():
        return

    content = f'Intro.\n\n```mermaid\n{FLOWCHART_SOURCE}\n```\n\n$$E = mc^2$$\n'

    client_assets = normalize_visual_assets([{
        'kind': 'diagram',
        'source': FLOWCHART_SOURCE,
        'data_uri': _build_png_data_uri(),
    }])
    assert len(client_assets) == 1, client_assets

    merged = ROUTE_MODULE._merge_server_rendered_visual_assets([content], client_assets)
    assert len(merged) == 1, merged
    assert merged[0]['data_uri'] == client_assets[0]['data_uri'], 'client asset was replaced'

    print("Export route asset merging passed!")


def test_export_route_skips_rendering_when_there_are_no_diagrams():
    """Content without a diagram must never reach the renderer."""
    print("Testing export route no-diagram short circuit...")

    if not _route_helpers_available():
        return

    with mock.patch.object(
        ROUTE_MODULE,
        'render_mermaid_visual_assets',
        side_effect=AssertionError('renderer must not be called'),
    ):
        merged = ROUTE_MODULE._merge_server_rendered_visual_assets(
            ['Plain prose with no diagram in it.'],
            [],
        )

    assert merged == [], merged

    print("Export route no-diagram short circuit passed!")


def test_export_route_degrades_when_chromium_is_unavailable():
    """With Chromium opted out, the fence survives instead of the export failing."""
    print("Testing export route degradation without Chromium...")

    if not _route_helpers_available():
        return

    content = f'```mermaid\n{FLOWCHART_SOURCE}\n```'

    with mock.patch.object(ROUTE_MODULE, 'is_mermaid_server_rendering_available', return_value=False):
        merged = ROUTE_MODULE._merge_server_rendered_visual_assets([content], [])

    assert merged == [], merged

    rendered = ROUTE_MODULE._render_message_export_content(
        {'role': 'assistant', 'content': content},
        visual_assets=merged,
    )
    assert '```mermaid' in rendered, rendered[:200]

    print("Export route degradation passed!")


def test_export_route_renderer_failure_does_not_fail_the_export():
    """A renderer that raises must not take the export down with it."""
    print("Testing export route renderer failure handling...")

    if not _route_helpers_available():
        return

    content = f'```mermaid\n{FLOWCHART_SOURCE}\n```'

    with mock.patch.object(ROUTE_MODULE, 'is_mermaid_server_rendering_available', return_value=True), \
            mock.patch.object(
                ROUTE_MODULE,
                'render_mermaid_visual_assets',
                side_effect=RuntimeError('browser exploded'),
            ):
        merged = ROUTE_MODULE._merge_server_rendered_visual_assets([content], [])

    assert merged == [], merged

    print("Export route renderer failure handling passed!")


def test_export_entry_content_collection():
    """Every body an export renders must be offered to the renderer."""
    print("Testing export entry content collection...")

    if not _route_helpers_available():
        return

    entries = [{
        'summary_intro': {'content': 'Abstract body'},
        'messages': [
            {'content_text': 'First message'},
            {'content_text': ''},
            {'content_text': 'Second message'},
        ],
    }]
    contents = ROUTE_MODULE._collect_export_entry_contents(entries)

    assert contents == ['Abstract body', 'First message', 'Second message'], contents

    print("Export entry content collection passed!")


if __name__ == "__main__":
    tests: List[Callable[[], None]] = [
        test_capability_probe_reports_a_complete_shape,
        test_server_and_browser_renderers_share_configuration,
        test_render_font_is_embedded_rather_than_borrowed_from_the_host,
        test_container_image_installs_scalable_fonts,
        test_server_renderer_captures_the_live_page,
        test_server_renders_diagrams_with_visible_labels,
        test_server_skips_a_diagram_it_cannot_render,
        test_server_render_deduplicates_and_caps_sources,
        test_export_route_fills_only_uncovered_diagrams,
        test_export_route_skips_rendering_when_there_are_no_diagrams,
        test_export_route_degrades_when_chromium_is_unavailable,
        test_export_route_renderer_failure_does_not_fail_the_export,
        test_export_entry_content_collection,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
