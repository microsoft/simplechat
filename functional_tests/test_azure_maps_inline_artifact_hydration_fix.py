#!/usr/bin/env python3
# test_azure_maps_inline_artifact_hydration_fix.py
"""
Functional test for the Azure Maps inline artifact hydration fix.
Version: 0.241.053
Implemented in: 0.241.053

This test ensures the inline Azure Maps renderer prefers hydrated artifact
payloads when compact citations were externalized and normalizes coordinates
before OpenLayers initialization, including ordered path overlays and
fit-after-visibility behavior.
"""

import os
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_INLINE_MAPS = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-inline-maps.js",
)


def _read(path):
    with open(path, encoding="utf-8") as file_handle:
        return file_handle.read()


def test_inline_maps_prefers_hydrated_artifacts():
    """The renderer must hydrate externalized map artifacts before using compact payloads."""
    print("Testing Azure Maps inline renderer artifact hydration preference...")
    content = _read(CHAT_INLINE_MAPS)
    errors = []

    required_fragments = [
        "citation?.raw_payload_externalized",
        "hydrateAzureMapsCitation(conversationId, citation.artifact_id)",
        "normalizeAzureMapsResult(getCitationResult(citation))",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"Missing renderer artifact-hydration fragment: {fragment}")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        raise AssertionError("Artifact hydration preference checks failed.")

    print("  Artifact hydration preference checks passed.")


def test_inline_maps_normalizes_coordinate_shapes():
    """The renderer must normalize coordinates before calling OpenLayers."""
    print("Testing Azure Maps inline renderer coordinate normalization...")
    content = _read(CHAT_INLINE_MAPS)
    errors = []

    required_fragments = [
        "function normalizeCoordinatePair(rawCoordinate)",
        "function normalizeMarkers(rawMarkers = [])",
        "function normalizePaths(rawPaths = [])",
        "function normalizeAreas(rawAreas = [])",
        "function createPathFeature(olRef, path)",
        "view: normalizeView(payload.view || {}, markers, areas, paths)",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"Missing coordinate-normalization fragment: {fragment}")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        raise AssertionError("Coordinate normalization checks failed.")

    print("  Coordinate normalization checks passed.")


def test_inline_maps_shows_container_before_initialization():
    """The renderer must reveal the visualization container before initializing OpenLayers."""
    print("Testing Azure Maps inline renderer visibility before initialization...")
    content = _read(CHAT_INLINE_MAPS)

    remove_fragment = 'container.classList.remove("d-none")'
    initialize_fragment = 'initializeOpenLayersMap(mapElement, popupElement, payload);'
    fit_fragment = 'fitViewToFeatures(olRef, vectorSource, view, payload, features.length);'

    if remove_fragment not in content:
        print(f"  FAIL: Missing visibility fragment: {remove_fragment}")
        raise AssertionError("Visibility fragment missing.")

    if initialize_fragment not in content:
        print(f"  FAIL: Missing initialization fragment: {initialize_fragment}")
        raise AssertionError("Initialization fragment missing.")

    if fit_fragment not in content:
        print(f"  FAIL: Missing fit fragment: {fit_fragment}")
        raise AssertionError("Fit fragment missing.")

    if content.index(remove_fragment) > content.index(initialize_fragment):
        print("  FAIL: Map initialization occurs before the container is shown.")
        raise AssertionError("Map initialization occurs before the container is shown.")

    print("  Visibility-before-initialization checks passed.")


if __name__ == "__main__":
    tests = [
        test_inline_maps_prefers_hydrated_artifacts,
        test_inline_maps_normalizes_coordinate_shapes,
        test_inline_maps_shows_container_before_initialization,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print('=' * 60)
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    print('=' * 60)
    sys.exit(0 if all(results) else 1)