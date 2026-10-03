#!/usr/bin/env python3
# test_orchestration_file_render_scratch_dir.py
"""
Functional test for orchestration file rendering when the app directory is not writable.
Version: 0.261.228
Implemented in: 0.261.228

This test ensures that generated-file rendering and generated-file downloads never write
scratch files into the process working directory (the container's non-root user cannot
write /app there), that the container image creates /app with runtime-user ownership, and
that a failed render attempt logs its error class names and OS error number so a local
file-system fault can be told apart from a source-access refusal.
"""

import ast
import csv
import errno
import io
import json
import os
import tempfile
from pathlib import Path

import functions_temp_files
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
DOCKERFILE = APP / "Dockerfile"
TEMP_FACTORIES = {
    "TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "TemporaryDirectory",
    "mkstemp", "mkdtemp",
}
SKIPPED_DIRECTORIES = {"__pycache__", "node_modules", "static", ".venv", "venv"}
INSTRUCTIONS = ("COPY", "ADD", "RUN", "WORKDIR")


def _deny_working_directory_scratch(monkeypatch):
    """Fail a temp file aimed at the working directory the way the container's /app does."""
    real = tempfile.TemporaryFile
    working = os.path.realpath(os.getcwd())
    targets = []

    def guarded(*args, **kwargs):
        target = kwargs.get("dir", args[6] if len(args) > 6 else None)
        targets.append(target)
        if target is not None and os.path.realpath(target) == working:
            raise PermissionError(errno.EACCES, "Permission denied", os.path.join(working, "tmp-denied"))
        return real(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", guarded)
    return targets


def _working_directory_temp_calls():
    """Every application tempfile call whose dir argument resolves to the working directory."""
    findings = []
    for path in sorted(APP.rglob("*.py")):
        if SKIPPED_DIRECTORIES.intersection(path.relative_to(APP).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name not in TEMP_FACTORIES:
                continue
            for keyword in node.keywords:
                value = keyword.value
                relative = isinstance(value, ast.Constant) and value.value in {".", "./", ""}
                current = isinstance(value, ast.Call) and getattr(value.func, "attr", None) == "getcwd"
                if keyword.arg == "dir" and (relative or current):
                    findings.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return findings


def test_scratch_directory_is_the_dedicated_directory_or_the_platform_default(tmp_path, monkeypatch):
    print("🔍 Testing scratch files use /sc-temp-files or the platform default, never the working directory...")
    monkeypatch.setattr(functions_temp_files, "SC_TEMP_FILES_DIR", str(tmp_path / "missing"))
    missing = functions_temp_files.scratch_file_dir()
    assert missing is None

    dedicated = tmp_path / "sc-temp-files"
    dedicated.mkdir()
    monkeypatch.setattr(functions_temp_files, "SC_TEMP_FILES_DIR", str(dedicated))
    chosen = functions_temp_files.scratch_file_dir()
    assert chosen == str(dedicated)

    monkeypatch.setattr(functions_temp_files.os, "access", lambda path, mode: False)
    unwritable = functions_temp_files.scratch_file_dir()
    assert unwritable is None
    print("✅ The dedicated directory is used only when it exists and is writable.")


def test_application_code_never_creates_temp_files_in_the_working_directory():
    print("🔍 Testing no application tempfile call targets the working directory...")
    findings = _working_directory_temp_calls()
    assert findings == [], f"Temp files must not be created in the working directory: {findings}"
    print("✅ No tempfile call uses dir='.' or the current working directory.")


def test_csv_renders_and_downloads_when_the_working_directory_is_not_writable(lifecycle, monkeypatch):
    print("🔍 Testing a CSV file renders and downloads with an unwritable working directory...")
    targets = _deny_working_directory_scratch(monkeypatch)
    output = lifecycle.prepare("csv")
    facts = []
    completed = lifecycle.service.render_attempt(output["output_id"], observe=facts.append)
    assert completed["state"] == "completed", completed
    assert completed["error_code"] is None
    rows = list(csv.reader(io.StringIO(lifecycle.download(completed).decode("utf-8"))))
    assert rows[0] == ["id", "amount", "enabled"]
    assert rows[-1] == ["last", "", "false"]
    # One scratch file for the render, at least one more for the verified download stream.
    assert len(targets) >= 2
    working = os.path.realpath(os.getcwd())
    assert all(target is None or os.path.realpath(target) != working for target in targets)
    assert "error_type" not in facts[0]
    print("✅ The file rendered, committed and downloaded without writing to the working directory.")


def test_failed_render_logs_error_class_and_errno_without_details(lifecycle):
    print("🔍 Testing a failed render records its error class and OS error number only...")
    private_path = "/app/tmp-private-scratch-name"
    lifecycle.failures["csv"] = [PermissionError(errno.EACCES, "Permission denied", private_path)]
    output = lifecycle.prepare("csv")
    facts = []
    failed = lifecycle.service.render_attempt(output["output_id"], observe=facts.append)
    assert failed["state"] == "failed"
    assert len(facts) == 1
    fact = facts[0]
    # The user-facing classification is unchanged; the diagnostics now show the real cause.
    assert fact["output_code"] == "output_access_denied"
    assert fact["error_type"] == "PermissionError"
    assert fact["error_errno"] == errno.EACCES
    assert fact["error_cause_type"] is None
    text = json.dumps(fact)
    assert private_path not in text and "Permission denied" not in text
    assert all(type(value) in (int, bool, str) or value is None for value in fact.values())
    print("✅ The PermissionError and errno were logged without its message or path.")


def test_failed_render_logs_the_root_cause_class_of_a_wrapped_error(lifecycle):
    print("🔍 Testing a wrapped failure records the root cause class and its errno...")

    def wrapped():
        try:
            raise OSError(errno.ENOSPC, "No space left on device", "/sc-temp-files/tmp-private")
        except OSError as exc:
            raise RuntimeError("private render detail") from exc

    lifecycle.failures["json"] = [wrapped]
    output = lifecycle.prepare("json")
    facts = []
    failed = lifecycle.service.render_attempt(output["output_id"], observe=facts.append)
    assert failed["state"] != "completed"
    fact = facts[0]
    assert (fact["error_type"], fact["error_cause_type"], fact["error_errno"]) == (
        "RuntimeError", "OSError", errno.ENOSPC,
    )
    assert "private" not in json.dumps(fact)
    print("✅ The outer class, root cause class and errno were logged.")


def test_container_image_creates_app_directory_for_the_runtime_user():
    print("🔍 Testing the image's /app is created by the runtime user's chowned copy...")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("AS onenote-runtime\n", 1)[1].split("\nFROM ", 1)[0]
    final_stage = dockerfile.rsplit("\nFROM ", 1)[1]
    assert final_stage.startswith("onenote-runtime\n")
    for line in runtime_stage.splitlines():
        if line.startswith(INSTRUCTIONS):
            assert not line.split()[-1].startswith("/app"), f"The base stage must not create /app: {line}"
    app_copy = final_stage.index("COPY --from=builder --chown=${UID}:${GID} /app /app")
    for line in final_stage[:app_copy].splitlines():
        if line.startswith(INSTRUCTIONS):
            assert not line.split()[-1].startswith("/app"), f"/app must not exist before its chowned copy: {line}"
    code_copy = final_stage.index("COPY --chown=${UID}:${GID} application/single_app ./")
    extractor_copy = final_stage.index(
        "COPY --from=onenote-builder /build/target/release/simplechat-onenote-extractor "
        "/app/native/onenote_extractor/bin/simplechat-onenote-extractor"
    )
    assert app_copy < code_copy < extractor_copy
    print("✅ /app is created by the chowned copy and the extractor is added afterward.")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
