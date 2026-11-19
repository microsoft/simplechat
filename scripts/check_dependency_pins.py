# check_dependency_pins.py
"""Audit active dependency inputs without treating direct pins as a full lock.

This static audit does not replace clean installs, image builds, or upstream
release verification. Unresolved dependency surfaces deliberately fail the audit.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z")
IMAGE_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\Z")
EXACT_REQUIREMENT = re.compile(r"[A-Za-z0-9_.-]+(?:\[[^\]]+\])?==[^*; ]+(?:\s*;.*)?\Z")


def finding(path, rule, detail):
    return {"path": str(path), "rule": rule, "detail": detail}


def release_age_error(released_at, selected_at):
    released = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
    selected = datetime.fromisoformat(selected_at.replace("Z", "+00:00"))
    if released.tzinfo is None or selected.tzinfo is None:
        return "Release and selection timestamps must include a timezone."
    if selected - released < timedelta(days=14):
        return "New selections must be at least 14 full days old."
    return None


def audit_requirements(path, source, root):
    errors = []
    requirements = [
        line.strip() for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for line in requirements:
        if line.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            continue
        if not EXACT_REQUIREMENT.fullmatch(line):
            errors.append(finding(path, "python-direct-pin", f"Requirement is not exact-pinned: {line}"))
    # A constraints file pins resolution only when the installer actually reads it.
    # A nearby unused lockfile is not evidence that transitive versions are fixed.
    constraints = [
        line.split(maxsplit=1)[1]
        for line in requirements if line.startswith(("-c ", "--constraint "))
    ]
    if not constraints:
        errors.append(finding(path, "python-transitive-lock", "No consumed transitive constraints/lock file."))
    for constraint in constraints:
        lock = root / Path(path).parent / constraint
        if not lock.is_file():
            errors.append(finding(path, "missing-python-lock", f"Missing constraints file: {constraint}"))
    return errors


def audit_package(path, source, root):
    manifest = json.loads(source)
    errors = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, version in manifest.get(section, {}).items():
            if not EXACT_VERSION.fullmatch(version):
                errors.append(finding(path, "npm-direct-pin", f"{name} must use an exact version."))
    lock_path = root / Path(path).parent / "package-lock.json"
    if not lock_path.is_file():
        return errors + [finding(path, "npm-lock", "Missing npm lockfile.")]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    locked_root = lock.get("packages", {}).get("", {})
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        if manifest.get(section, {}) != locked_root.get(section, {}):
            errors.append(finding(path, "npm-lock-sync", f"Root {section} differs from package-lock.json."))
    evidence = lock_path.with_name("package-lock.evidence.json")
    if evidence.is_file():
        errors.extend(audit_lock(lock_path.relative_to(root), root, evidence))
    return errors


def audit_lock(path, root, ledger_path=None):
    errors = []
    lock = root / path
    ledger_path = ledger_path or lock.with_suffix(".json")
    if not ledger_path.is_file():
        return [finding(path, "release-evidence", "Missing release-age and input evidence.")]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if hashlib.sha256(lock.read_text(encoding="utf-8-sig").encode()).hexdigest() != ledger["lock_sha256"]:
        errors.append(finding(path, "lock-evidence-sync", "Lock content differs from its reviewed release evidence."))
    for name, digest in ledger["inputs"].items():
        source = root / name
        if not source.is_file() or hashlib.sha256(source.read_text(encoding="utf-8-sig").encode()).hexdigest() != digest:
            errors.append(finding(path, "python-lock-input", f"Regenerate lock after changing {name}."))
    for name, evidence in ledger["packages"].items():
        if not evidence["grandfathered_pin"]:
            error = release_age_error(evidence["released_at"], ledger["selected_at"])
            if error:
                errors.append(finding(path, "release-age", f"{name}: {error}"))
    return errors


def audit_cargo(path, source, root):
    manifest = tomllib.loads(source)
    errors = []
    tables = [manifest, *manifest.get("target", {}).values()]
    for table in tables:
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, value in table.get(section, {}).items():
                if isinstance(value, dict) and "path" in value:
                    continue
                if isinstance(value, dict) and "git" in value:
                    exact = bool(re.fullmatch(r"[a-f0-9]{40}", value.get("rev", "")))
                else:
                    version = value if isinstance(value, str) else value.get("version", "")
                    exact = version.startswith("=") and bool(EXACT_VERSION.fullmatch(version[1:]))
                if not exact:
                    errors.append(finding(path, "cargo-direct-pin", f"{name} must have an exact version or commit."))
    lock = root / Path(path).with_name("Cargo.lock")
    if not lock.is_file():
        return errors + [finding(path, "cargo-lock", "Missing Cargo.lock.")]
    for package in tomllib.loads(lock.read_text(encoding="utf-8"))["package"]:
        origin = package.get("source", "")
        if origin.startswith("registry+") and not re.fullmatch(r"[a-f0-9]{64}", package.get("checksum", "")):
            errors.append(finding(path, "cargo-integrity", f"{package['name']} has no registry checksum."))
        if origin.startswith("git+") and not re.search(r"#[a-f0-9]{40}$", origin):
            errors.append(finding(path, "cargo-git-lock", f"{package['name']} has no resolved commit."))
    return errors


def audit_gemfile(path, source, root):
    lock = root / Path(path).with_name("Gemfile.lock")
    if not lock.is_file():
        return [finding(path, "ruby-lock", "Missing Gemfile.lock.")]
    locked = lock.read_text(encoding="utf-8")
    errors = []
    for line in source.splitlines():
        if not re.match(r"\s*gem\s", line):
            continue
        match = re.match(r"""\s*gem\s+["']([^"']+)["'],\s*["'](?:=\s*)?(\d+(?:\.[0-9A-Za-z]+)*)["']""", line)
        if not match:
            errors.append(finding(path, "ruby-direct-pin", "Gem declarations must specify an exact version."))
        elif not re.search(rf"^    {re.escape(match[1])} \({re.escape(match[2])}(?:-[^)]+)?\)", locked, re.MULTILINE):
            errors.append(finding(path, "ruby-lock-sync", f"{match[1]} does not match Gemfile.lock."))
    if not re.search(r"BUNDLED WITH\s+\d+\.\d+\.\d+", locked):
        errors.append(finding(path, "bundler-version", "Gemfile.lock must pin Bundler."))
    return errors


def audit_terraform(path, source, root):
    errors = []
    if not re.search(r'required_version\s*=\s*"=\s*\d+\.\d+\.\d+"', source):
        errors.append(finding(path, "terraform-version", "Terraform CLI must have an exact required version."))
    lock = root / Path(path).with_name(".terraform.lock.hcl")
    if not lock.is_file():
        return errors + [finding(path, "terraform-lock", "Missing Terraform provider lockfile.")]
    locked = lock.read_text(encoding="utf-8")
    providers = re.findall(r'source\s*=\s*"([^"]+)"\s+version\s*=\s*"([^"]+)"', source)
    for name, version in providers:
        if not re.fullmatch(r"=\s*\d+\.\d+\.\d+", version):
            errors.append(finding(path, "terraform-provider-pin", f"{name} needs an exact provider constraint."))
            continue
        origin = re.escape("registry.terraform.io/" + name.lower())
        exact = re.escape(version.lstrip("= "))
        if not re.search(rf'provider "{origin}"\s*\{{\s*version\s*=\s*"{exact}"', locked):
            errors.append(finding(path, "terraform-lock-sync", f"{name} differs from its provider lock."))
    return errors


def audit_dockerfile(path, source):
    errors = []
    for line in source.splitlines():
        if line.startswith("FROM "):
            image = line.split()[1]
            if image != "scratch" and not IMAGE_DIGEST.search(image):
                errors.append(finding(path, "image-digest", f"Base image needs an immutable digest: {image}"))
            if ":latest" in image:
                errors.append(finding(path, "third-party-latest", "Third-party base images must not use latest, even with a digest."))
        if re.search(r"\b(?:tdnf|apt-get)\s+install\b", line):
            configured = source[:source.index(line)]
            snapshots = re.findall(
                r"snapshot\.(?:ubuntu\.com/ubuntu|debian\.org/archive/debian(?:-security)?)/(\d{8}T\d{6}Z)/",
                configured,
            )
            frozen_apt = (
                "apt-get" in line and snapshots and "Check-Valid-Until: no" in configured
                and "/etc/apt/sources.list.d/" in configured
                and all(
                    datetime.now(timezone.utc) - datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    >= timedelta(days=14) for value in snapshots
                )
            )
            if not frozen_apt:
                errors.append(finding(
                    path, "os-package-lock",
                    "OS dependency closure needs a verified frozen repository snapshot or checksum-locked artifacts.",
                ))
        if re.search(r"\bpip install (?:pyodbc|wheel)(?:\s|$)", line):
            errors.append(finding(path, "python-inline-pin", "Inline build packages must have exact versions."))
    return errors


def audit_selections(root):
    path = root / "scripts" / "dependency-selections.json"
    if not path.is_file():
        return [finding(path.relative_to(root), "release-evidence", "Missing explicit release selection evidence.")]
    evidence = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    for selection in evidence["selections"]:
        source = root / selection["file"]
        if not source.is_file() or selection["reference"] not in source.read_text(encoding="utf-8"):
            errors.append(finding(selection["file"], "selection-sync", "Selection evidence no longer matches its input."))
        inherited = selection.get("inherited_from")
        if inherited:
            if (
                not re.fullmatch(r"[a-f0-9]{40}", inherited["commit"])
                or selection["reference"].split("@sha256:", 1)[0] != inherited["reference"]
            ):
                errors.append(finding(selection["file"], "inherited-pin", "Inherited evidence must identify the same exact pin and a full commit SHA."))
                continue
            baseline = subprocess.run(
                ["git", "show", f"{inherited['commit']}:{selection['file']}"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            if baseline.returncode or inherited["reference"] not in baseline.stdout:
                errors.append(finding(selection["file"], "inherited-pin", "Existing pin is not present in the recorded baseline."))
            continue
        error = release_age_error(selection["released_at"], evidence["selected_at"])
        if error:
            errors.append(finding(selection["file"], "release-age", error))
    return errors


def audit_rpm_lock(root):
    path = Path("docker-customization/azurelinux-packages.lock.json")
    manifest = json.loads((root / path).read_text(encoding="utf-8"))
    errors = []
    dockerfile = (root / "application/single_app/Dockerfile").read_text(encoding="utf-8")
    if manifest["base_image"] not in dockerfile:
        errors.append(finding(path, "rpm-base-image", "Regenerate the RPM closure for the selected builder image."))
    for profile in ("common", "chromium"):
        records = manifest["profiles"][profile]
        if not records:
            errors.append(finding(path, "rpm-closure", f"The {profile} closure must not be empty."))
        for record in records:
            origin = urlparse(record["url"])
            if (
                origin.scheme != "https" or origin.hostname != "packages.microsoft.com"
                or not origin.path.endswith(".rpm") or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
            ):
                errors.append(finding(path, "rpm-integrity", f"Invalid artifact identity in {profile}."))
            released = datetime.fromtimestamp(record["published_at"], timezone.utc).isoformat()
            error = release_age_error(released, manifest["selected_at"])
            if error:
                errors.append(finding(path, "release-age", f"{profile}: {error}"))
    return errors


def audit_workflow(path, source):
    errors = []
    for number, line in enumerate(source.splitlines(), 1):
        if re.match(r"\s*#", line):
            continue
        if ":latest" in line and any(word in line for word in ("docker ", "image:", "container:")):
            application_image = re.search(
                r"(?:\$\{REGISTRY(?:_LOGIN_SERVER)?\}|\$\{\{\s*secrets\.ACR_LOGIN_SERVER(?:_NADOYLE)?\s*\}\})/simple-chat(?:-dev)?:latest",
                line,
            )
            if not application_image:
                errors.append(finding(path, "third-party-latest", f"Line {number}: latest is reserved for the SimpleChat ACR image."))
        if re.search(r"\bruns-on:.*(?:ubuntu|windows|macos)-latest", line):
            errors.append(finding(path, "runner-version", f"Line {number}: floating runner selector."))
        runtime = re.match(r"""\s*(?:python|node|ruby|dotnet)-version:\s*['"]?([^'"\s#]+)""", line)
        if runtime and not EXACT_VERSION.fullmatch(runtime[1]):
            errors.append(finding(path, "runtime-version", f"Line {number}: runtime version is not exact."))
        action = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
        if action and not action[1].startswith("./"):
            reference = action[1].split("@", 1)
            if len(reference) != 2 or not re.fullmatch(r"[0-9a-f]{40}", reference[1]):
                errors.append(finding(path, "action-sha", f"Line {number}: action is not commit-pinned."))
        if re.search(r"\bpip install --upgrade pip\s*$", line):
            errors.append(finding(path, "installer-version", f"Line {number}: unpinned pip upgrade."))
        if "npm install " in line and "--no-save" in line and not (
            "python scripts/prepare_model_catalog_sdk.py" in source
            and "npm ci --ignore-scripts --no-audit --no-fund" in source
            and 'NPM_CONFIG_OFFLINE=true' in source[:source.index(line)]
        ):
            errors.append(finding(path, "npm-transitive-lock", f"Line {number}: generated npm installation has no consumed lockfile."))
    return errors


def audit_repository(root=ROOT):
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, capture_output=True,
    )
    paths = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    errors = []
    inspected = []
    for name in paths:
        path = Path(name)
        relevant = (
            (path.name.startswith("requirements") and path.suffix == ".txt" and ".lock." not in path.name)
            or path.name in {"package.json", "Dockerfile", "devcontainer.json", "Cargo.toml", "Gemfile"}
            or (path.suffix == ".tf" and "required_providers" in (root / path).read_text(encoding="utf-8"))
            or (name.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"})
        )
        if not relevant:
            continue
        inspected.append(name)
        source = (root / path).read_text(encoding="utf-8-sig")
        if path.name.startswith("requirements"):
            errors.extend(audit_requirements(name, source, root))
        elif path.name == "package.json":
            errors.extend(audit_package(name, source, root))
        elif path.name == "Dockerfile":
            errors.extend(audit_dockerfile(name, source))
        elif path.name == "Cargo.toml":
            errors.extend(audit_cargo(name, source, root))
        elif path.name == "Gemfile":
            errors.extend(audit_gemfile(name, source, root))
        elif path.suffix == ".tf":
            errors.extend(audit_terraform(name, source, root))
        elif path.name == "devcontainer.json":
            errors.append(finding(
                name, "devcontainer-lock",
                "Feature artifacts, installed tools, and editor extensions need verified exact pins and a regenerated devcontainer lock.",
            ))
        else:
            errors.extend(audit_workflow(name, source))
    for name in paths:
        if Path(name).name.startswith("requirements") and name.endswith(".lock.txt"):
            inspected.append(name)
            errors.extend(audit_lock(Path(name), root))
    errors.extend(audit_selections(root))
    errors.extend(audit_rpm_lock(root))
    return {"inspected": inspected, "findings": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable findings.")
    args = parser.parse_args()
    report = audit_repository()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for item in report["findings"]:
            print(f"{item['path']}: [{item['rule']}] {item['detail']}")
        print(f"Inspected {len(report['inspected'])} dependency surfaces; {len(report['findings'])} unresolved findings.")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
