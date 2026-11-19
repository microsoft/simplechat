# lock_npm_tooling.py
"""Lock repository tooling to releases published at least fourteen days ago."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "catalog": ".github/dependencies/model-catalog",
    "devcontainer": ".devcontainer",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["all", *PROFILES], default="all")
    args = parser.parse_args()
    npm = shutil.which("npm")
    if not npm:
        parser.error("npm must be available from the selected Node.js runtime.")
    selected = datetime.now(timezone.utc)
    cutoff = selected - timedelta(days=14)
    for profile in PROFILES if args.profile == "all" else (args.profile,):
        directory = ROOT / PROFILES[profile]
        subprocess.run(
            [npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund",
             f"--before={cutoff.isoformat()}", "--omit-lockfile-registry-resolved"],
            cwd=directory, check=True,
        )
        lock_path = directory / "package-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        packages = {
            (path.rsplit("node_modules/", 1)[-1], entry["version"])
            for path, entry in lock["packages"].items() if path
        }

        def verify(item):
            name, version = item
            result = subprocess.run(
                [npm, "view", name, "time", "--json"], cwd=ROOT, check=True,
                capture_output=True, text=True,
            )
            timestamps = json.loads(result.stdout)
            released = timestamps[version]
            if datetime.fromisoformat(released.replace("Z", "+00:00")) > cutoff:
                raise ValueError(f"{name}@{version} has not been published for 14 full days.")
            return f"{name}@{version}", {
                "released_at": released, "grandfathered_pin": False,
                "source": f"https://registry.npmjs.org/{quote(name, safe='@')}",
            }

        with ThreadPoolExecutor(max_workers=4) as executor:
            evidence = dict(executor.map(verify, sorted(packages)))
        manifest_path = directory / "package.json"
        ledger = {
            "selected_at": selected.isoformat(), "minimum_age_days": 14,
            "inputs": {
                manifest_path.relative_to(ROOT).as_posix(): hashlib.sha256(
                    manifest_path.read_text(encoding="utf-8-sig").encode()
                ).hexdigest(),
            },
            "lock_sha256": hashlib.sha256(lock_path.read_text(encoding="utf-8-sig").encode()).hexdigest(),
            "packages": dict(sorted(evidence.items())),
        }
        (directory / "package-lock.evidence.json").write_text(
            json.dumps(ledger, indent=2) + "\n", encoding="utf-8", newline="\n",
        )


if __name__ == "__main__":
    main()
