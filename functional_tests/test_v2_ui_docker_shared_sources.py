#!/usr/bin/env python3
"""
Functional test for V2 UI shared source availability in the Docker build.

Version: 0.261.128
Implemented in: 0.261.128

The V2 SPA imports a small amount of source by relative path from outside
application/v2_ui (the shared model catalog module and stylesheet under
application/single_app/static). A local `npm run build` resolves those paths because the
whole repository is on disk, but the Dockerfile's v2uibuilder stage only copies
application/v2_ui, so an escaping import that is not also copied fails the image build
with TS2307 while the local build stays green.

This test proves every escaping import in the V2 source is present in that stage, and is
not excluded from the ACR build context by .dockerignore.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SOURCE_DIR = REPO_ROOT / "application" / "v2_ui"
DOCKERFILE = REPO_ROOT / "application" / "single_app" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

V2_BUILDER_STAGE = "v2uibuilder"
V2_BUILDER_WORKDIR = "/v2_ui"

SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}

# Matches the specifier of a static `import ... from '...'`, a side-effect `import '...'`,
# and a dynamic `import('...')`.
IMPORT_SPECIFIER_RE = re.compile(
    r"""(?:^|[\s;{(])import\s*(?:\(\s*)?(?:[^'";]*?\sfrom\s*)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _iter_v2_source_files():
    """Yield V2 SPA source files, skipping installed dependencies and build output."""
    skipped_dirs = {"node_modules", "dist"}
    for path in V2_SOURCE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if skipped_dirs.intersection(path.relative_to(V2_SOURCE_DIR).parts):
            continue
        yield path


def _escaping_imports():
    """Return (source_file, specifier, resolved_repo_path) for imports outside v2_ui."""
    escaping = []
    for source_file in _iter_v2_source_files():
        content = source_file.read_text(encoding="utf-8", errors="ignore")
        for specifier in IMPORT_SPECIFIER_RE.findall(content):
            if not specifier.startswith("."):
                continue
            resolved = (source_file.parent / specifier).resolve()
            if V2_SOURCE_DIR in resolved.parents or resolved == V2_SOURCE_DIR:
                continue
            escaping.append((source_file, specifier, resolved))
    return escaping


def _required_repo_files(resolved):
    """Return the repo files the builder stage needs for one escaping import.

    A `.js` specifier is type-checked through its sibling `.d.ts`, so both files have to
    reach the image for `tsc -b` to succeed.
    """
    required = [resolved]
    if resolved.suffix == ".js":
        declaration = resolved.with_suffix(".d.ts")
        if declaration.is_file():
            required.append(declaration)
    return required


def _builder_stage_text():
    """Return the Dockerfile text belonging to the v2uibuilder stage."""
    dockerfile_text = DOCKERFILE.read_text(encoding="utf-8")
    stage_start = re.search(
        rf"^FROM\s+\S+\s+AS\s+{V2_BUILDER_STAGE}\s*$", dockerfile_text, re.MULTILINE | re.IGNORECASE
    )
    assert stage_start, f"Dockerfile has no '{V2_BUILDER_STAGE}' build stage"

    remainder = dockerfile_text[stage_start.end():]
    next_stage = re.search(r"^FROM\s+", remainder, re.MULTILINE)
    return remainder[: next_stage.start()] if next_stage else remainder


def _builder_stage_copy_map():
    """Map container paths created by the stage's COPY instructions to repo paths."""
    stage_text = _builder_stage_text()
    # Join continued lines so a multi-source COPY is parsed as one instruction.
    stage_text = re.sub(r"\\\r?\n\s*", " ", stage_text)

    copy_map = {}
    for line in stage_text.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("COPY "):
            continue

        tokens = [token for token in stripped.split()[1:] if not token.startswith("--")]
        if len(tokens) < 2:
            continue

        sources, destination = tokens[:-1], tokens[-1]
        if not destination.startswith("/"):
            destination = f"{V2_BUILDER_WORKDIR}/{destination.lstrip('./')}"

        for source in sources:
            repo_path = REPO_ROOT / source.rstrip("/")
            container_path = destination.rstrip("/") + "/" + repo_path.name
            if source.endswith("/") or repo_path.is_dir():
                container_path = destination.rstrip("/")
            copy_map[container_path] = repo_path

    return copy_map


def _container_path_for(repo_path, copy_map):
    """Return the in-container path a repo file is copied to, or None when uncopied."""
    for container_path, copied_repo_path in copy_map.items():
        if copied_repo_path == repo_path:
            return container_path
        if copied_repo_path.is_dir() and copied_repo_path in repo_path.parents:
            relative = repo_path.relative_to(copied_repo_path).as_posix()
            return f"{container_path}/{relative}"
    return None


def _expected_container_path(source_file, specifier):
    """Return the path a V2 import resolves to inside the builder stage."""
    source_container_dir = (
        f"{V2_BUILDER_WORKDIR}/{source_file.parent.relative_to(V2_SOURCE_DIR).as_posix()}"
    )
    return os.path.normpath(f"{source_container_dir}/{specifier}").replace("\\", "/")


def test_escaping_imports_resolve_to_tracked_files():
    """Every V2 import that reaches outside application/v2_ui points at a real file."""
    print("Testing V2 imports that reach outside application/v2_ui...")

    escaping = _escaping_imports()
    missing = [
        f"{source_file.relative_to(REPO_ROOT)} imports '{specifier}' -> {resolved} (missing)"
        for source_file, specifier, resolved in escaping
        if not resolved.is_file()
    ]

    assert missing == [], "V2 imports point at files that do not exist:\n  " + "\n  ".join(missing)

    print(f"  Found {len(escaping)} escaping import(s); all resolve to existing files.")
    print("Escaping import resolution test passed!")
    return True


def test_escaping_imports_are_copied_into_builder_stage():
    """The v2uibuilder stage copies every file the V2 build imports from outside v2_ui."""
    print("Testing v2uibuilder stage copies shared V2 sources...")

    copy_map = _builder_stage_copy_map()
    assert copy_map, "No COPY instructions parsed from the v2uibuilder stage"

    violations = []
    for source_file, specifier, resolved in _escaping_imports():
        if not resolved.is_file():
            continue

        expected_container_path = _expected_container_path(source_file, specifier)
        for required in _required_repo_files(resolved):
            actual_container_path = _container_path_for(required, copy_map)
            if actual_container_path is None:
                violations.append(
                    f"{required.relative_to(REPO_ROOT)} (imported by "
                    f"{source_file.relative_to(REPO_ROOT)}) is not copied into the "
                    f"{V2_BUILDER_STAGE} stage; the image build cannot resolve it"
                )
            elif required == resolved and actual_container_path != expected_container_path:
                violations.append(
                    f"{required.relative_to(REPO_ROOT)} is copied to "
                    f"{actual_container_path} but '{specifier}' resolves to "
                    f"{expected_container_path}"
                )

    assert violations == [], (
        "V2 build would fail inside Docker:\n  " + "\n  ".join(violations)
    )

    print("Builder stage COPY coverage test passed!")
    return True


def test_shared_sources_stay_in_the_build_context():
    """.dockerignore keeps the shared single_app static sources in the ACR build context."""
    print("Testing .dockerignore keeps shared V2 sources in the build context...")

    assert DOCKERIGNORE.is_file(), ".dockerignore is missing from the repository root"
    dockerignore_text = DOCKERIGNORE.read_text(encoding="utf-8")

    assert "!application/single_app/**" in dockerignore_text, (
        ".dockerignore must re-include application/single_app/** so shared V2 sources "
        "reach the ACR build context"
    )

    excluded_shared_paths = [
        line.strip()
        for line in dockerignore_text.splitlines()
        if line.strip().startswith("application/single_app/static/")
        and not line.strip().startswith("application/single_app/static/v2/")
    ]
    assert excluded_shared_paths == [], (
        ".dockerignore excludes static sources the V2 build imports:\n  "
        + "\n  ".join(excluded_shared_paths)
    )

    print("Build context test passed!")
    return True


def test_fix_version_recorded():
    """The application version is at least the release that added the shared-source copy."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.128")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_escaping_imports_resolve_to_tracked_files,
        test_escaping_imports_are_copied_into_builder_stage,
        test_shared_sources_stay_in_the_build_context,
        test_fix_version_recorded,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
