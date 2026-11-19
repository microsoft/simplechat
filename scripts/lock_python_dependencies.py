# lock_python_dependencies.py
"""Generate consumed Python 3.12 constraints and verify new release ages."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "application": (
        ("application/single_app/requirements.txt", "requirements-dev.txt", "ui_tests/requirements.txt"),
        "application/single_app/requirements.lock.txt",
    ),
    "catalog": (
        ("scripts/requirements-model-catalog-tests.txt",),
        "scripts/requirements-model-catalog.lock.txt",
    ),
    "deployer": (("deployers/bicep/requirements.txt",), "deployers/bicep/requirements.lock.txt"),
    "external": (
        ("application/external_apps/bulkloader/requirements.txt",
         "application/external_apps/databaseseeder/requirements.txt"),
        "application/external_apps/requirements.lock.txt",
    ),
    "tools": (("scripts/requirements-dependency-locks.txt",), "scripts/requirements-dependency-locks.lock.txt"),
    "build": (("scripts/requirements-build.txt",), "docker-customization/requirements-build.lock.txt"),
}
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)$")


def canonical_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_inputs(paths, visited=None):
    if visited is None:
        visited = set()
    requirements = set()
    for path in paths:
        path = path.resolve()
        if path in visited:
            continue
        visited.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-c ", "--constraint ")):
                continue
            if line.startswith("-r "):
                requirements.update(read_inputs([path.parent / line[3:]], visited))
            elif REQUIREMENT.fullmatch(line):
                requirements.add(line)
            else:
                raise ValueError(f"{path}: unsupported dependency input: {line}")
    return requirements


def release_evidence(item):
    name, version = item
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urlopen(url, timeout=60) as response:
        metadata = json.load(response)
    timestamps = [entry["upload_time_iso_8601"] for entry in metadata["urls"]]
    if not timestamps:
        raise ValueError(f"No authoritative publication timestamp for {name}=={version}")
    return f"{name}=={version}", {"released_at": min(timestamps), "source": url}


def combine_platforms(resolutions):
    packages = {}
    for target, source in resolutions.items():
        for line in source.splitlines():
            if not line or line.startswith("#"):
                continue
            match = REQUIREMENT.fullmatch(line)
            if not match:
                raise ValueError(f"Unexpected resolver output: {line}")
            key = canonical_name(match[1]), match[2]
            packages.setdefault(key, set()).add(target)
    lines = []
    for (name, version), platforms in sorted(packages.items()):
        marker = ""
        if len(platforms) != len(resolutions):
            conditions = [
                f'(python_version == "{version}" and sys_platform == "{platform}")'
                for version, platform in sorted(platforms)
            ]
            marker = "; " + " or ".join(conditions)
        lines.append(f"{name}=={version}{marker}")
    return "\n".join(lines) + "\n", packages


def generate(profile, args, selected):
    input_names, output_name = PROFILES[profile]
    output = ROOT / output_name
    visited = set()
    inputs = read_inputs([ROOT / name for name in input_names], visited)
    existing = set()
    for path in [*visited, output]:
        relative = path.relative_to(ROOT).as_posix()
        result = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            continue
        for line in result.stdout.splitlines():
            match = REQUIREMENT.fullmatch(line.split(";", 1)[0].strip())
            if match:
                existing.add((canonical_name(match[1]), match[2]))
    cutoff = selected - timedelta(days=14)
    resolutions = {}
    with tempfile.TemporaryDirectory(prefix="simplechat-lock-") as directory:
        directory = Path(directory)
        source = directory / "requirements.in"
        source.write_text("\n".join(sorted(inputs)) + "\n", encoding="utf-8")
        versions = ("3.11", "3.12") if profile in {"catalog", "build"} else ("3.12",)
        targets = [
            (version, platform, target) for version in versions
            for platform, target in (("linux", "linux"), ("win32", "windows"))
        ]
        for version, platform, target in targets:
            destination = directory / f"{version}-{platform}.txt"
            command = [
                args.uv, "pip", "compile", str(source), "--python-version", version,
                "--python-platform", target, "--exclude-newer", cutoff.isoformat(),
                "--no-header", "--no-annotate", "--quiet", "--output-file", str(destination),
            ]
            for name, _ in sorted(existing):
                command.extend(("--exclude-newer-package", f"{name}={selected.isoformat()}"))
            if output.is_file() and not args.upgrade:
                command.extend(("--constraint", str(output)))
            if args.index_url:
                command.extend(("--index-url", args.index_url))
            if args.find_links:
                command.extend(("--find-links", args.find_links))
            subprocess.run(command, cwd=ROOT, check=True)
            resolutions[(version, platform)] = destination.read_text(encoding="utf-8")
    combined, packages = combine_platforms(resolutions)
    with ThreadPoolExecutor(max_workers=8) as executor:
        evidence = dict(executor.map(release_evidence, packages))
    for (name, version) in packages:
        record = evidence[f"{name}=={version}"]
        record["grandfathered_pin"] = (name, version) in existing
        published = datetime.fromisoformat(record["released_at"].replace("Z", "+00:00"))
        if not record["grandfathered_pin"] and published > cutoff:
            raise ValueError(f"{name}=={version} has not been published for 14 full days")
    content = (
        "# Generated by scripts/lock_python_dependencies.py; do not edit.\n"
        f"# Python {', '.join(versions)}; supported installation platforms: Linux and Windows.\n"
        f"# Selected at: {selected.isoformat()}\n"
        + combined
    )
    ledger = {
        "selected_at": selected.isoformat(), "minimum_age_days": 14,
        "inputs": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_text(encoding="utf-8-sig").encode()).hexdigest()
            for path in sorted(visited)
        },
        "lock_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "packages": dict(sorted(evidence.items())),
    }
    output.write_text(content, encoding="utf-8", newline="\n")
    output.with_suffix(".json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["all", *PROFILES], default="all")
    parser.add_argument("--uv", default=shutil.which("uv"))
    parser.add_argument("--index-url", help="Optional trusted index; never saved in committed locks.")
    parser.add_argument("--find-links", help="Optional local wheel cache.")
    parser.add_argument("--upgrade", action="store_true", help="Explicitly allow replacing existing transitive selections.")
    args = parser.parse_args()
    if not args.uv:
        parser.error("Install scripts/requirements-dependency-locks.txt in a tooling environment first.")
    selected = datetime.now(timezone.utc)
    for profile in PROFILES if args.profile == "all" else (args.profile,):
        generate(profile, args, selected)


if __name__ == "__main__":
    main()
