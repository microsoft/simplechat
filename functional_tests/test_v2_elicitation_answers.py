# test_v2_elicitation_answers.py
"""
Functional tests for primitive inline answers and composer reference context.
Version: 0.261.096
Implemented in: 0.261.096

Run the real TypeScript answer builders using the existing V2 esbuild toolchain.
No browser, signed-in account, or Azure service is required.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "application" / "v2_ui"


class ElicitationAnswersTest(unittest.TestCase):
    def test_implementation_version(self):
        assert_app_version_at_least("0.261.096")

    def test_typescript_answer_builders(self):
        npx = shutil.which("npx")
        self.assertIsNotNone(npx, "The existing V2 Node toolchain is required.")
        self.assertTrue(
            (V2 / "node_modules").is_dir(),
            "Restore the existing V2 dependencies before running this test.",
        )
        environment = dict(os.environ)
        environment["NODE_PATH"] = str(V2 / "node_modules")
        with tempfile.TemporaryDirectory(prefix="simplechat-elicitation-") as directory:
            bundle = Path(directory) / "answers.cjs"
            built = subprocess.run(
                [
                    npx, "--no-install", "esbuild",
                    str(Path(__file__).with_suffix(".ts")),
                    "--bundle", "--platform=node", "--format=cjs",
                    "--define:import.meta.env={}", "--log-level=warning",
                    f"--outfile={bundle}",
                ],
                cwd=V2, env=environment, capture_output=True, text=True,
                shell=sys.platform == "win32",
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run(
                ["node", str(bundle)],
                cwd=V2, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
