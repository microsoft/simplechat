#!/usr/bin/env python3
# test_group_file_source_sync_fields.py
"""
Functional test for the four classic File Sync fields in the V2 group file source editor.
Version: 0.261.171
Implemented in: 0.261.171

The classic editor sets four fields the V2 editor never showed: the folders and files to sync under
the source root (`connection.selected_paths`), the tags every synced file gets (`filters.fixed_tags`),
the tags taken from each file's folders (`filters.folder_tag_mode`), and what a sync does with the
SimpleChat copy when its source file is deleted (`remote_delete_policy`). V2 now edits all four.

This test runs the editor's real field rules -- `lib/fileSourceFields.ts`, bundled with the V2 app's
own esbuild and run under node -- against the real native group file source routes and the real
`functions_file_sync`, through `test_support/group_file_source_harness.py`. It pins:
- the editor's path and tag normalizers give exactly the server's answer for every input, including
  the paths the server refuses, so what the editor shows is what the server stores;
- an untouched V2 save of a real projection sends every one of the four fields back unchanged, for a
  source that set them and for one on the server's defaults;
- a V2 edit stores exactly the values the editor showed, with nothing rewritten by the server;
- a source stored without the fields, or with an unrecognised choice, opens with the value any save
  will store.

It also records one product finding, as a strict xfail with a positive control: V2's Ignore sends a
browse entry's root-relative path, but the engine keys items by the absolute remote path, so the
ignore never applies.
"""

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_support.group_file_source_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    UNC_PATH,
    as_user,
    create_source,
    environment,
    smb_payload,
)


V2_DIR = ROOT / "application" / "v2_ui"
PROBE_TS = Path(__file__).resolve().parent / "test_support" / "file_source_field_rules_probe.ts"
GROUP = "group-a"

# Paths the editor may be given: typed, browsed or stored. Each exercises one rule of
# `_normalize_selected_path` -- the separators, the trimming, the 2,048-character cut, the refused
# folder names, and Python's own idea of whitespace rather than JavaScript's.
PATH_CASES = [
    "", "   ", "/", "Reports", "Reports/2024", "Reports\\2024\\", "/Reports/2024/", " Reports / 2024 ",
    "a//b", "./a", "a/./b", "a/..", "..", "Ünïcode/Földer", "\u00a0spaced\u00a0", "tab\tname/x",
    "\ufeffbom/x", "\u001cfs/x", "x/\u0085nel", "𝔘nicode/𝔣older", "C:\\share\\x", "a" * 2100,
    "a" * 2047 + "/b", "\\\\server\\share\\folder",
]
# Tags the editor may be given, each exercising one rule of `_safe_tag_from_text`.
TAG_CASES = [
    "", "!!", "Q1 Reports", "q1-reports", "Legal/Contracts", "  spaced  ", "UPPER_case-ok", "a" * 60,
    "-lead-", "é", "İstanbul", "\u00a0nbsp", "\ufeffbom", "\u001cfs", "\u0085nel", "tab\ttab",
    "x" * 49 + "-y", "ẞtraße", "ΣΑΣ", "𝔘nicode", "k\u212a",
]


def run_probe(request):
    """Run the editor's real field rules under node on one request and return the answer."""
    assert (V2_DIR / "node_modules").is_dir(), (
        "application/v2_ui/node_modules is missing; restore the frontend dependencies first"
    )
    esbuild = V2_DIR / "node_modules" / "esbuild" / "bin" / "esbuild"
    assert esbuild.exists(), "application/v2_ui/node_modules/esbuild is missing"
    token = uuid.uuid4().hex
    # The bundle sits under node_modules (a shared junction here) so its external imports resolve,
    # and carries a unique name; both it and the request file are removed afterwards.
    bundle = V2_DIR / "node_modules" / f".cache-file-source-field-rules-{token}.mjs"
    request_file = V2_DIR / "node_modules" / f".cache-file-source-field-rules-{token}.json"
    try:
        request_file.write_text(json.dumps(request), encoding="utf-8")
        subprocess.run(
            [
                "node", str(esbuild), str(PROBE_TS), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", "--define:import.meta.env={}", f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["node", str(bundle), str(request_file)], cwd=str(V2_DIR), capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        for path in (bundle, request_file):
            if path.exists():
                path.unlink()
    assert result.returncode == 0, f"the field rules probe failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def server_path(filesync, raw):
    try:
        return {"path": filesync._normalize_selected_path(raw)}
    except ValueError:
        return {"error": True}


def read(env, source_id):
    response = env.client.get(f"{LIST_PATH}/{source_id}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def patch(env, source_id, body):
    response = env.client.patch(f"{LIST_PATH}/{source_id}", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def sync_fields(source):
    return {
        "selected_paths": source["connection"].get("selected_paths"),
        "fixed_tags": source["filters"].get("fixed_tags"),
        "folder_tag_mode": source["filters"].get("folder_tag_mode"),
        "remote_delete_policy": source.get("remote_delete_policy"),
    }


def configured_source(env):
    """A source with every one of the four fields set away from its default."""
    payload = smb_payload(name="Contracts with a selection")
    payload["connection"]["selected_paths"] = ["Reports/2024", "budget.xlsx"]
    payload["filters"] = {"fixed_tags": ["finance", "q1-reports"], "folder_tag_mode": "full_path"}
    payload["remote_delete_policy"] = "hard_delete"
    return create_source(env, payload)


def test_the_editor_normalizes_paths_and_tags_exactly_as_the_server(environment):
    """For every input the editor's normalizers give the server's own answer, refusals included."""
    filesync = environment.filesync
    answer = run_probe({"paths": PATH_CASES, "tags": TAG_CASES})
    for raw, editor in zip(PATH_CASES, answer["paths"]):
        server = server_path(filesync, raw)
        if "error" in server:
            assert "error" in editor, f"The server refuses {raw!r} but the editor accepts it as {editor}"
        else:
            assert editor == server, f"Path {raw!r}: the editor shows {editor}, the server stores {server}"
    for raw, editor in zip(TAG_CASES, answer["tags"]):
        assert editor == filesync._safe_tag_from_text(raw), (
            f"Tag {raw!r}: the editor shows {editor!r}, the server stores {filesync._safe_tag_from_text(raw)!r}"
        )


def test_the_editor_deduplicates_a_selection_and_tags_as_the_server_does(environment):
    """Paths added one by one keep the server's first-seen order and ignore-case duplicates, and tags
    keep the first of each duplicate, so the editor's list is the stored list."""
    filesync = environment.filesync
    paths = ["Reports\\2024\\", "reports/2024", "Budget.xlsx", "budget.xlsx", "Archive"]
    tags = ["Q1 Reports", "q1-reports", "Legal/Contracts", "LEGAL contracts", "finance"]
    projection = read(environment, create_source(environment)["id"])
    answer = run_probe({"edits": [{"source": projection, "add_paths": paths, "add_tags": tags}]})
    write = answer["edits"][0]["write"]
    assert answer["edits"][0]["errors"] == []
    assert write["connection"]["selected_paths"] == filesync._normalize_selected_paths(paths)
    assert write["filters"]["fixed_tags"] == filesync._normalize_tags(tags)


@pytest.mark.parametrize("kind", ["configured", "defaults"])
def test_an_untouched_v2_save_keeps_every_sync_field(environment, kind):
    """Opening a source and saving it with only a rename sends the four fields back unchanged."""
    created = configured_source(environment) if kind == "configured" else create_source(environment)
    projection = read(environment, created["id"])
    before = sync_fields(projection)
    write = run_probe({"sources": [projection]})["writes"][0]
    # The editor sends each field -- it does not rely on the server keeping an omitted one.
    assert write["connection"]["selected_paths"] == before["selected_paths"]
    assert write["filters"]["fixed_tags"] == before["fixed_tags"]
    assert write["filters"]["folder_tag_mode"] == before["folder_tag_mode"]
    assert write["remote_delete_policy"] == before["remote_delete_policy"]
    saved = patch(environment, created["id"], {
        **write, "name": "Renamed in V2", "expected_config_revision": projection["config_revision"],
    })
    assert saved["name"] == "Renamed in V2"
    assert sync_fields(saved) == before
    stored = environment.sources_container.get(GROUP, created["id"])
    assert sync_fields(stored) == before


def test_a_v2_edit_stores_exactly_what_the_editor_showed(environment):
    """The paths, tags and choices a manager enters are stored as the editor displayed them."""
    created = create_source(environment)
    projection = read(environment, created["id"])
    edit = run_probe({"edits": [{
        "source": projection,
        "add_paths": ["Reports\\2024\\", "reports/2024", " Budget.xlsx "],
        "add_tags": ["Q1 Reports", "Legal/Contracts"],
        "folder_tag_mode": "none",
        "remote_delete_policy": "hard_delete",
    }]})["edits"][0]
    assert edit["errors"] == []
    shown = edit["write"]
    assert shown["connection"]["selected_paths"] == ["Reports/2024", "Budget.xlsx"]
    assert shown["filters"]["fixed_tags"] == ["q1-reports", "legal-contracts"]
    saved = patch(environment, created["id"], {**shown, "expected_config_revision": projection["config_revision"]})
    assert sync_fields(saved) == {
        "selected_paths": shown["connection"]["selected_paths"],
        "fixed_tags": shown["filters"]["fixed_tags"],
        "folder_tag_mode": "none",
        "remote_delete_policy": "hard_delete",
    }


def test_a_path_the_server_refuses_is_refused_before_it_is_sent(environment):
    """A path leaving the root fails the whole save with a message that can't name it, so the
    editor refuses it itself and never puts it in the write."""
    created = create_source(environment)
    projection = read(environment, created["id"])
    edit = run_probe({"edits": [{"source": projection, "add_paths": ["reports/../secrets", "reports"]}]})["edits"][0]
    assert len(edit["errors"]) == 1
    assert edit["write"]["connection"]["selected_paths"] == ["reports"]
    refused = environment.client.patch(f"{LIST_PATH}/{created['id']}", json={
        "expected_config_revision": projection["config_revision"],
        "connection": {"unc_path": UNC_PATH, "selected_paths": ["reports/../secrets"]},
    })
    assert refused.status_code == 400
    assert refused.get_json() == {
        "error": "The File Sync request could not be completed. Verify the source configuration and try again.",
    }


@pytest.mark.parametrize("stored,expected", [
    ({}, {"folder_tag_mode": "parent", "remote_delete_policy": "ignore"}),
    ({"folder_tag_mode": "Sideways", "remote_delete_policy": "Shred"},
     {"folder_tag_mode": "parent", "remote_delete_policy": "ignore"}),
    ({"folder_tag_mode": " FULL_PATH ", "remote_delete_policy": "Hard_Delete"},
     {"folder_tag_mode": "full_path", "remote_delete_policy": "hard_delete"}),
])
def test_a_missing_or_unrecognised_choice_opens_as_any_save_stores_it(environment, stored, expected):
    """A source stored without a choice, or with one the server doesn't recognise, opens with the
    value any save stores, so the editor never shows a choice the server would change."""
    created = create_source(environment)
    record = environment.sources_container.get(GROUP, created["id"])
    record["filters"].pop("folder_tag_mode", None)
    record.pop("remote_delete_policy", None)
    if "folder_tag_mode" in stored:
        record["filters"]["folder_tag_mode"] = stored["folder_tag_mode"]
    if "remote_delete_policy" in stored:
        record["remote_delete_policy"] = stored["remote_delete_policy"]
    environment.sources_container.seed(record)
    projection = read(environment, created["id"])
    write = run_probe({"sources": [projection]})["writes"][0]
    assert write["filters"]["folder_tag_mode"] == expected["folder_tag_mode"]
    assert write["remote_delete_policy"] == expected["remote_delete_policy"]
    # A save that leaves them out entirely stores the same values, so the editor showed the truth.
    omitted = patch(environment, created["id"], {
        "expected_config_revision": projection["config_revision"], "name": "Untouched choices",
    })
    assert omitted["filters"]["folder_tag_mode"] == expected["folder_tag_mode"]
    assert omitted["remote_delete_policy"] == expected["remote_delete_policy"]


@pytest.mark.xfail(strict=True, reason=(
    "Product finding (M5B, 0.261.171): the V2 editor ignores a browsed file by the entry's path, "
    "which browse returns relative to the source root, but the sync engine keys each item by the "
    "file's absolute remote path (_item_id_for_path over remote_file['remote_path']), so the ignore "
    "is stored on an item the engine never reads and the file keeps syncing."
))
def test_ignoring_a_browsed_file_reaches_the_item_the_engine_syncs(environment):
    """Ignoring a file the way V2 does -- with the path browse returned -- marks the item the engine
    checks before syncing that file."""
    created = create_source(environment)
    as_user(environment, "owner")
    browsed_path = "reports/budget.xlsx"  # a browse entry's `path`, relative to the root
    response = environment.client.post(
        f"{LIST_PATH}/{created['id']}/ignore-path", json={"remote_path": browsed_path, "ignored": True},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    # The SMB engine lists this file with its absolute remote path under the root, and skips it only
    # when the item keyed by that path is ignored.
    engine_path = f"{UNC_PATH}\\reports\\budget.xlsx"
    item = environment.items_container.get(
        created["id"], environment.filesync._item_id_for_path(created["id"], engine_path),
    )
    assert item is not None and item.get("ignored") is True


def test_ignoring_the_engine_path_marks_the_item_the_engine_syncs(environment):
    """The positive control for the finding above: ignoring the file's absolute remote path marks the
    very item the engine reads, so the lookup the finding relies on is sound."""
    created = create_source(environment)
    as_user(environment, "owner")
    engine_path = f"{UNC_PATH}\\reports\\budget.xlsx"
    response = environment.client.post(
        f"{LIST_PATH}/{created['id']}/ignore-path", json={"remote_path": engine_path, "ignored": True},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    item = environment.items_container.get(
        created["id"], environment.filesync._item_id_for_path(created["id"], engine_path),
    )
    assert item is not None and item.get("ignored") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
