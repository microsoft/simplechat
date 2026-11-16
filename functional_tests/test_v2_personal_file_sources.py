# test_v2_personal_file_sources.py
"""
Execute the real native personal adapter and shared file-source field rules.
Version: 0.261.310
Implemented in: 0.261.310
"""

import subprocess
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "application" / "v2_ui"


def test_native_personal_transport_and_fields():
    bundle = V2 / "node_modules" / f".cache-personal-file-sources-{uuid.uuid4().hex}.mjs"
    try:
        subprocess.run([
            "node", str(V2 / "node_modules" / "esbuild" / "bin" / "esbuild"),
            str(ROOT / "functional_tests" / "test_support" / "file_source_configuration_probe.ts"),
            "--bundle", "--platform=node", "--format=esm", "--packages=external",
            "--define:import.meta.env={}", f"--outfile={bundle}", "--log-level=error",
        ], check=True, capture_output=True, text=True)
        result = subprocess.run(["node", str(bundle)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        bundle.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
