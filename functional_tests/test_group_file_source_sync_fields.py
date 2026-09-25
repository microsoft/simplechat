#!/usr/bin/env python3
# test_group_file_source_sync_fields.py
"""
Functional test for the four classic File Sync fields in the V2 group file source editor.
Version: 0.261.172
Implemented in: 0.261.171
Browsed files carry the engine's canonical remote path, and Ignore sends it: 0.261.172

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

It also pins the ignore fix. V2's Ignore used to send a browse entry's root-relative path, while the
engine keys each item by the file's canonical remote path, so the ignore never applied. Browse now
gives every file its canonical `remote_path`, built as the engine builds it -- checked against the
engine's own listing of the same tree for SMB, Azure Files, Azure Blob and OneDrive, the four
implemented source types -- and ignoring by it marks the item the engine reads. The ignore route
itself is unchanged.
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


# --------------------------------------------------------------------------
# Ignore by the canonical remote path browse gives each file (0.261.172).
# --------------------------------------------------------------------------

# One small tree, served to every source type's engine lister and browse through fakes, keyed by the
# path relative to the source root. Each value lists a folder's children as (name, kind).
BROWSE_TREE = {
    "": (("reports", "folder"), ("budget.xlsx", "file")),
    "reports": (("2024", "folder"), ("summary.pdf", "file")),
    "reports/2024": (("q1.pdf", "file"),),
}


def tree_children(relative):
    children = BROWSE_TREE.get(relative.strip("/"))
    if children is None:
        raise FileNotFoundError(relative)
    return children


class _Stat:
    st_size = 20480
    st_mtime = 1704153600


class _SmbEntry:
    def __init__(self, name, kind):
        self.name, self._kind = name, kind

    def is_dir(self):
        return self._kind == "folder"

    def is_file(self):
        return self._kind == "file"

    def stat(self):
        return _Stat()


class _TreeSmbClient:
    """An SMB session over BROWSE_TREE under the harness root, for browse and the engine alike."""

    def scandir(self, path):
        root = UNC_PATH.rstrip("\\")
        if path.lower() == root.lower():
            relative = ""
        elif path.lower().startswith(root.lower() + "\\"):
            relative = path[len(root) + 1:].replace("\\", "/")
        else:
            raise FileNotFoundError(path)
        return [_SmbEntry(name, kind) for name, kind in tree_children(relative)]


class _TreeShareClient:
    """An Azure Files share over BROWSE_TREE under the source's root directory."""

    def __init__(self, root_directory):
        self.root = root_directory.strip("/")

    def _relative(self, directory_name):
        directory = (directory_name or "").strip("/")
        if directory == self.root:
            return ""
        if not directory.startswith(self.root + "/"):
            raise FileNotFoundError(directory)
        return directory[len(self.root) + 1:]

    def list_directories_and_files(self, directory_name=None):
        return [
            {"name": name, "is_directory": kind == "folder", "size": 20480}
            for name, kind in tree_children(self._relative(directory_name))
        ]

    def get_file_client(self, file_path):
        return type("FileClient", (), {"get_file_properties": lambda _self: {"size": 20480}})()


class _TreeBlobPrefix:
    def __init__(self, name):
        self.name = name


class _TreeContainerClient:
    """An Azure Blob container over BROWSE_TREE under the source's blob prefix."""

    def __init__(self, prefix):
        self.prefix = prefix.strip("/")

    def _blob_names(self, relative=""):
        names = []
        for name, kind in tree_children(relative):
            child = f"{relative}/{name}".strip("/")
            names.extend(self._blob_names(child) if kind == "folder" else [f"{self.prefix}/{child}"])
        return names

    def walk_blobs(self, name_starts_with=None, delimiter=None):
        relative = (name_starts_with or "")[len(self.prefix):].strip("/")
        return [
            _TreeBlobPrefix(f"{self.prefix}/{relative}/{name}/".replace("//", "/")) if kind == "folder"
            else {"name": f"{self.prefix}/{relative}/{name}".replace("//", "/"), "size": 20480}
            for name, kind in tree_children(relative)
        ]

    def list_blobs(self, name_starts_with=None):
        return [{"name": name, "size": 20480} for name in self._blob_names() if name.startswith(name_starts_with or "")]


def azure_files_source(env):
    return create_source(env, {
        "name": "Quarterly Azure Files", "source_type": "azure_files",
        "connection": {"account_url": "https://contoso.file.core.windows.net", "share_name": "reports",
                       "directory_path": "quarterly"},
        "credentials": {"auth_type": "managed_identity", "managed_identity_client_id": ""},
    })


def azure_blob_source(env):
    return create_source(env, {
        "name": "Team blob container", "source_type": "azure_blob",
        "connection": {"account_url": "https://contoso.blob.core.windows.net", "container_name": "finance",
                       "blob_prefix": "team"},
        "credentials": {"auth_type": "managed_identity", "managed_identity_client_id": ""},
    })


def serve_tree(environment, monkeypatch, source_type):
    """Create a source of the type and point both browse and the engine at the same tree."""
    filesync = environment.filesync
    if source_type == "azure_files":
        created = azure_files_source(environment)
        monkeypatch.setattr(filesync, "_get_azure_files_share_client", lambda _source: _TreeShareClient("quarterly"))
    elif source_type == "azure_blob":
        created = azure_blob_source(environment)
        monkeypatch.setattr(filesync, "_get_azure_blob_container_client", lambda _source: _TreeContainerClient("team"))
    else:
        created = create_source(environment)
        monkeypatch.setattr(filesync, "_register_smb_session", lambda _source: _TreeSmbClient())
    return created


def browsed_entries(environment, source_id):
    """Every entry browse lists, over every folder of the tree, keyed by its root-relative path."""
    entries = {}
    for folder in BROWSE_TREE:
        response = environment.client.post(f"{LIST_PATH}/{source_id}/browse", json={"browse_path": folder})
        assert response.status_code == 200, response.get_data(as_text=True)
        for entry in response.get_json()["browse"]["entries"]:
            entries[entry["path"]] = entry
    return entries


def engine_remote_paths(environment, source_id):
    """What the sync engine itself lists for the stored source: root-relative path -> remote_path."""
    filesync = environment.filesync
    stored = environment.sources_container.get(GROUP, source_id)
    return {
        str(remote_file["relative_path"]).replace("\\", "/"): remote_file["remote_path"]
        for remote_file in filesync._list_remote_files(stored, filesync.get_file_sync_config())
    }


@pytest.mark.parametrize("source_type", ["smb", "azure_files", "azure_blob"])
def test_every_browsed_file_carries_the_path_the_engine_keys_it_by(environment, monkeypatch, source_type):
    """Over the same tree, each browsed file's `remote_path` is the one the engine lists for that file,
    so it names the same item; folders carry none, since the engine keeps items only for files."""
    created = serve_tree(environment, monkeypatch, source_type)
    as_user(environment, "owner")
    entries = browsed_entries(environment, created["id"])
    engine = engine_remote_paths(environment, created["id"])
    files = {path: entry for path, entry in entries.items() if entry["type"] == "file"}
    assert sorted(files) == sorted(engine) == ["budget.xlsx", "reports/2024/q1.pdf", "reports/summary.pdf"]
    item_id = environment.filesync._item_id_for_path
    for path, entry in files.items():
        assert entry["remote_path"] == engine[path], f"{source_type} {path}: browse and the engine disagree"
        assert item_id(created["id"], entry["remote_path"]) == item_id(created["id"], engine[path])
    assert all("remote_path" not in entry for entry in entries.values() if entry["type"] == "folder")


def test_a_browsed_onedrive_file_carries_the_engine_remote_path(environment, monkeypatch):
    """OneDrive (personal only) browses the same Graph items the engine lists, and gives each file the
    engine's own `onedrive://` path; a folder carries none."""
    filesync = environment.filesync
    folder = {"id": "folder-1", "name": "reports", "folder": {"childCount": 1},
              "parentReference": {"driveId": "drive-1", "path": "/drive/root:"}}
    root_file = {"id": "file-1", "name": "budget.xlsx", "file": {"mimeType": "application/vnd.ms-excel"}, "size": 20480,
                 "parentReference": {"driveId": "drive-1", "path": "/drive/root:"}}
    nested_file = {"id": "file-2", "name": "summary.pdf", "file": {"mimeType": "application/pdf"}, "size": 20480,
                   "parentReference": {"driveId": "drive-1", "path": "/drive/root:/reports"}}

    def children(_source, item_id=None, selected_path="", max_items=1000):
        return [nested_file] if item_id == "folder-1" or selected_path == "reports" else [folder, root_file]

    monkeypatch.setattr(filesync, "_iter_onedrive_children", children)
    source = {"id": "onedrive-source", "source_type": "onedrive", "recursive": True,
              "connection": {"selected_paths": []}}
    browsed = filesync._browse_onedrive_path(source, "") + filesync._browse_onedrive_path(source, "reports")
    engine = {item["relative_path"]: item["remote_path"]
              for item in filesync._list_onedrive_files(source, filesync.get_file_sync_config())}
    files = {entry["path"]: entry["remote_path"] for entry in browsed if entry["type"] == "file"}
    assert files == engine == {"budget.xlsx": "onedrive://drive-1/file-1", "reports/summary.pdf": "onedrive://drive-1/file-2"}
    assert all("remote_path" not in entry for entry in browsed if entry["type"] == "folder")


def test_ignoring_a_browsed_file_reaches_the_item_the_engine_syncs(environment, monkeypatch):
    """Ignoring a file the way V2 does -- by the `remote_path` browse gave it -- marks the very item the
    engine checks before syncing that file (flipped from the 0.261.171 strict xfail)."""
    created = serve_tree(environment, monkeypatch, "smb")
    as_user(environment, "owner")
    browsed = browsed_entries(environment, created["id"])["budget.xlsx"]
    response = environment.client.post(
        f"{LIST_PATH}/{created['id']}/ignore-path",
        json={"remote_path": browsed["remote_path"], "ignored": True},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    # The engine's own lookup: its listing's remote_path for the file, keyed into its existing items.
    filesync = environment.filesync
    stored = environment.sources_container.get(GROUP, created["id"])
    existing = filesync._load_existing_items(stored)
    engine_path = engine_remote_paths(environment, created["id"])["budget.xlsx"]
    item = existing.get(filesync._item_id_for_path(created["id"], engine_path))
    assert item is not None and item.get("ignored") is True
    restored = environment.client.post(
        f"{LIST_PATH}/{created['id']}/ignore-path",
        json={"remote_path": browsed["remote_path"], "ignored": False},
    )
    assert restored.status_code == 200 and restored.get_json()["item"]["ignored"] is False
    existing = filesync._load_existing_items(stored)
    assert existing[filesync._item_id_for_path(created["id"], engine_path)]["ignored"] is False


def test_a_root_relative_path_still_reaches_no_engine_item(environment, monkeypatch):
    """The route itself is unchanged: it stores the path it is given, so ignoring by the root-relative
    `path` still marks an item the engine never reads. That is why the editor sends `remote_path`."""
    created = serve_tree(environment, monkeypatch, "smb")
    as_user(environment, "owner")
    response = environment.client.post(
        f"{LIST_PATH}/{created['id']}/ignore-path", json={"remote_path": "budget.xlsx", "ignored": True},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    filesync = environment.filesync
    stored = environment.sources_container.get(GROUP, created["id"])
    engine_path = engine_remote_paths(environment, created["id"])["budget.xlsx"]
    assert filesync._item_id_for_path(created["id"], engine_path) not in filesync._load_existing_items(stored)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
