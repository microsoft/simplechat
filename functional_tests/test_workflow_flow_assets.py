# test_workflow_flow_assets.py
"""
Functional tests for locally bundled read-only workflow Flow assets.
Version: 0.261.121
Implemented in: 0.261.121

Validate the approved dependency pin, retained dependency notices, static imports,
and Vite's copied notice without downloading any browser or cloud resources.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "application" / "v2_ui"
NOTICES = UI / "public" / "licenses" / "workflow-flow-notices.txt"
PACKAGES = (
    "node_modules/@xyflow/react",
    "node_modules/@xyflow/system",
    "node_modules/@xyflow/react/node_modules/zustand",
    "node_modules/classcat",
    "node_modules/use-sync-external-store",
    "node_modules/d3-drag",
    "node_modules/d3-dispatch",
    "node_modules/d3-selection",
    "node_modules/d3-interpolate",
    "node_modules/d3-color",
    "node_modules/d3-zoom",
    "node_modules/d3-transition",
    "node_modules/d3-ease",
    "node_modules/d3-timer",
    "node_modules/@types/d3-drag",
    "node_modules/@types/d3-selection",
    "node_modules/@types/d3-interpolate",
    "node_modules/@types/d3-color",
    "node_modules/@types/d3-transition",
    "node_modules/@types/d3-zoom",
)


class WorkflowFlowAssetTests(unittest.TestCase):
    def test_approved_renderer_is_exactly_pinned_and_locked(self):
        manifest = json.loads((UI / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((UI / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["dependencies"]["@xyflow/react"], "12.11.6")
        self.assertEqual(lock["packages"]["node_modules/@xyflow/react"]["version"], "12.11.6")
        self.assertTrue(lock["packages"]["node_modules/@xyflow/react"]["integrity"])

    def test_locked_dependency_notices_are_retained(self):
        lock = json.loads((UI / "package-lock.json").read_text(encoding="utf-8"))
        notices = NOTICES.read_text(encoding="utf-8")
        for package in PACKAGES:
            with self.subTest(package=package):
                name = package.split("node_modules/")[-1]
                self.assertIn(f'{name} {lock["packages"][package]["version"]}', notices)
        for owner in ("webkid GmbH", "Jorge Bucaran", "Paul Henschel", "Meta Platforms",
                      "Mike Bostock", "Robert Penner", "Microsoft Corporation"):
            self.assertIn(owner, notices)
        self.assertIn("Permission is hereby granted", notices)
        self.assertIn("Permission to use, copy, modify", notices)
        self.assertIn("Neither the name of the author", notices)

    def test_flow_uses_static_local_bundle_imports(self):
        directory = UI / "src" / "components" / "workflows"
        canvas = (directory / "WorkflowFlowCanvas.tsx").read_text(encoding="utf-8")
        self.assertIn("from '@xyflow/react'", canvas)
        self.assertIn("import '@xyflow/react/dist/style.css'", canvas)
        self.assertIn("import './WorkflowFlowView.css'", canvas)
        for path in directory.glob("WorkflowFlow*"):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotRegex(source, r"\bimport\s*\(")
                self.assertNotRegex(source, r"\bnew\s+(?:Shared)?Worker\s*\(")
                self.assertNotRegex(source, re.compile(r"url\(\s*['\"]?https?://", re.IGNORECASE))

    def test_built_notice_matches_tracked_source_when_bundle_exists(self):
        build = ROOT / "application" / "single_app" / "static" / "v2"
        if not (build / "index.html").is_file():
            self.skipTest("Build the local V2 bundle to verify copied public assets.")
        copied = build / "licenses" / NOTICES.name
        self.assertTrue(copied.is_file(), "Rebuild V2 to ship the required Flow notices.")
        self.assertEqual(copied.read_bytes(), NOTICES.read_bytes())


if __name__ == "__main__":
    unittest.main()
