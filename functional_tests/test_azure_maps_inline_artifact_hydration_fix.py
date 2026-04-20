#!/usr/bin/env python3
# test_azure_maps_inline_artifact_hydration_fix.py
"""
Functional test for the Azure Maps inline artifact hydration fix.
Version: 0.241.050
Implemented in: 0.241.050

This test ensures the inline Azure Maps renderer prefers hydrated artifact
payloads when compact citations were externalized and normalizes coordinates
before OpenLayers initialization.
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
        return False

    print("  Artifact hydration preference checks passed.")
    return True


def test_inline_maps_normalizes_coordinate_shapes():
    """The renderer must normalize coordinates before calling OpenLayers."""
    print("Testing Azure Maps inline renderer coordinate normalization...")
    content = _read(CHAT_INLINE_MAPS)
    errors = []

    required_fragments = [
        "function normalizeCoordinatePair(rawCoordinate)",
        "function normalizeMarkers(rawMarkers = [])",
        "function normalizeAreas(rawAreas = [])",
        "view: normalizeView(payload.view || {}, markers, areas)",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"Missing coordinate-normalization fragment: {fragment}")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        return False

    print("  Coordinate normalization checks passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_inline_maps_prefers_hydrated_artifacts,
        test_inline_maps_normalizes_coordinate_shapes,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print('=' * 60)
        try:
            results.append(bool(test()))
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