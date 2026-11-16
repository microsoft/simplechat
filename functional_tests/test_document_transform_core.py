# test_document_transform_core.py
"""
Functional tests for standalone document transformation contracts and guarded dispatch.
Version: 0.261.321
Implemented in: 0.261.321

In-memory OOXML fixtures and a test-only adapter verify best-effort reporting, exact
reference binding, lazy adapters, deterministic preservation/template normalization,
safe XML/relationships, cancellation and resource ceilings. No Flask, Azure, actual
Word/PowerPoint adapter, network, disk fixture or current-version equality is required.
"""

from copy import deepcopy
from dataclasses import replace
import base64
import hashlib
import io
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
import warnings
import zipfile

from lxml import etree
import pytest

# Standalone scripts share the application's flat import layout without importing config.
APP_PATH = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_PATH))

import functions_document_transform as core


CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PPT_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
HANDLE = {"kind": "document", "document_id": "authorized-document"}


def archive_bytes(files):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return result.getvalue()


def fixture_files(extension=".docx", *, hyperlink=False):
    word = core.SOURCE_FORMATS[extension] == "docx"
    main = "word/document.xml" if word else "ppt/presentation.xml"
    if word:
        document = (
            f'<w:document xmlns:w="{WORD_NS}" xmlns:r="{OFFICE_REL_NS}"><w:body>'
            '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Reference title</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Preserved introduction</w:t></w:r></w:p></w:body></w:document>'
        )
    else:
        document = f'<p:presentation xmlns:p="{PPT_NS}"><p:sldIdLst/></p:presentation>'
    files = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CT_NS}"><Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="bin" ContentType="application/octet-stream"/>'
            f'<Override PartName="/{main}" ContentType="{core._MAIN_TYPES[extension]}"/></Types>'
        ).encode(),
        "_rels/.rels": (
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="rMain" '
            f'Type="{OFFICE_REL_NS}/officeDocument" Target="{main}"/></Relationships>'
        ).encode(),
        main: document.encode(),
        "custom/preserved.xml": b'<?xml version="1.0" encoding="UTF-8"?>\n<!-- spacing matters -->\n<custom>  original  </custom>',
        "custom/data.bin": b"\x00\xffpreserved",
    }
    if hyperlink:
        files["word/_rels/document.xml.rels"] = (
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="rLink" Type="{OFFICE_REL_NS}/hyperlink" '
            'Target="https://example.invalid/original" TargetMode="External"/></Relationships>'
        ).encode()
        files[main] = files[main].replace(
            b"</w:body>", b'<w:p><w:hyperlink r:id="rLink"><w:r><w:t>Link</w:t></w:r></w:hyperlink></w:p></w:body>',
        )
    return files


def source_bytes(extension=".docx", **kwargs):
    return archive_bytes(fixture_files(extension, **kwargs))


def prepared(content, extension=".docx", *, operations=None, unresolved=None, mode="refresh"):
    return {
        "schema_version": core.DOCUMENT_TRANSFORM_SCHEMA_VERSION,
        "output_format": core.SOURCE_FORMATS[extension], "mode": mode,
        "reference": {"handle": deepcopy(HANDLE), "content_sha256": hashlib.sha256(content).hexdigest(), "extension": extension},
        "operations": operations or [], "unresolved": unresolved or [],
    }


class FakeAdapter:
    """A deliberately tiny trusted adapter; generic dispatch is independent of actual adapters."""

    def __init__(self):
        self.calls = []

    def inspect_package(self, package, *, limits, check):
        check()
        self.calls.append("inspect")
        return {
            "targets": [
                {"id": "title", "type": "paragraph", "text": "Reference title", "part": package.main_part},
                {"id": "intro", "type": "paragraph", "text": "Preserved introduction"},
            ],
            "layouts": [{"id": "body", "name": "Reference layout"}],
            "limitations": ["Charts are preserved, not refreshed."],
        }

    def transform_package(self, package, prepared, *, limits, check, image_resolver):
        check()
        self.calls.append("transform")
        report = {"applied": [], "skipped": [], "warnings": [], "metadata": {"adapter": "test-only"}}
        for index, operation in enumerate(prepared["operations"]):
            check()
            entry = {"op_index": index, "target": operation["target"]}
            if operation["target"] == "title" and operation["op"] == "replace_text":
                root = package.parse_xml(package.main_part)
                text = root.find(f".//{{{WORD_NS}}}t")
                text.text = operation["text"]
                package.write_xml(package.main_part, root)
                report["applied"].append(entry)
            elif operation["target"] == "silent":
                continue
            else:
                report["skipped"].append({**entry, "reason": "This test adapter does not support that target or operation."})
        return report


@pytest.fixture
def fake_adapter(monkeypatch):
    adapter = FakeAdapter()
    monkeypatch.setitem(core._ADAPTERS, "docx", adapter)
    monkeypatch.setitem(core._ADAPTERS, "pptx", adapter)
    return adapter


def test_schema_is_bounded_detached_and_valid():
    schema = core.get_document_transform_schema()
    core.Draft202012Validator.check_schema(schema)
    schema["properties"].clear()
    intact = core.get_document_transform_schema()
    assert intact["additionalProperties"] is False
    assert intact["properties"]["operations"]["maxItems"] == 500
    assert intact["properties"]["unresolved"]["maxItems"] == 500
    content = source_bytes()
    value = prepared(content, operations=[
        {"op": "replace_text", "target": "title", "text": "<script>literal text</script>"},
        {"op": "replace_image", "target": "picture:1", "source": "asset:1"},
        {"op": "clone", "target": "title", "clone_id": "copy:1"},
        {"op": "remove", "target": "intro"},
        {"op": "append_text", "target": "title", "text": "More\ntext"},
    ])
    validated = core.validate_document_transform(value)
    validated["operations"][0]["text"] = "Detached"
    assert value["operations"][0]["text"] != "Detached"


@pytest.mark.parametrize("edit", [
    lambda value: value.update(schema_version="unversioned"),
    lambda value: value.update(code="exec('model code')"),
    lambda value: value.update(mode="overwrite"),
    lambda value: value.update(output_format="pdf"),
    lambda value: value.update(operations=[{"op": "eval", "target": "title"}]),
    lambda value: value.update(operations=[{"op": "remove", "target": "title", "text": "extra"}]),
    lambda value: value.update(operations=[{"op": "replace_text", "target": "title"}]),
    lambda value: value.update(operations=[{"op": "replace_text", "target": "title", "text": False}]),
    lambda value: value.update(operations=[{"op": "replace_image", "target": "picture", "source": "https://blob.invalid/a"}]),
    lambda value: value.update(operations=[{"op": "remove", "target": "../word/document.xml"}]),
    lambda value: value.update(operations=[{"op": "remove", "target": "title\n"}]),
    lambda value: value.update(operations=[{"op": "clone", "target": "a", "clone_id": "copy"}] * 2),
    lambda value: value["reference"].update(content_sha256="A" * 64),
    lambda value: value["reference"].update(extension=".docm"),
    lambda value: value["reference"]["handle"].update(path="C:\\secret.docx"),
    lambda value: value["reference"]["handle"].update(document_id="folder/document"),
    lambda value: value.update(unresolved=[{"target": "title", "reason": ""}]),
])
def test_malformed_contracts_are_safe_errors(edit):
    value = prepared(source_bytes())
    edit(value)
    with pytest.raises(core.DocumentTransformError) as error:
        core.validate_document_transform(value)
    assert error.value.code == "invalid_transform"
    assert "secret" not in error.value.message


def test_format_and_json_limits():
    value = prepared(source_bytes())
    value["output_format"] = "pptx"
    with pytest.raises(core.DocumentTransformError, match="Invalid"):
        core.validate_document_transform(value)
    for malformed in ({"data": float("nan")}, {"data": object()}, {"data": "\ud800"}, {"data": "\x00"}):
        with pytest.raises(core.DocumentTransformError):
            core.validate_document_transform(malformed)
    recursive = []
    recursive.append(recursive)
    with pytest.raises(core.DocumentTransformError) as error:
        core.validate_document_transform(recursive)
    assert error.value.code == "resource_limit"
    value = prepared(source_bytes(), operations=[{"op": "remove", "target": "x"}] * 2)
    with pytest.raises(core.DocumentTransformError):
        core.validate_document_transform(value, limits=replace(core.DocumentTransformLimits(), max_operations=1))
    with pytest.raises(core.DocumentTransformError) as error:
        core.validate_document_transform(prepared(source_bytes()), limits=replace(core.DocumentTransformLimits(), max_json_bytes=64))
    assert error.value.code == "resource_limit"
    with pytest.raises(ValueError):
        core.DocumentTransformLimits(max_operations=True)


@pytest.mark.parametrize("handle", [
    HANDLE, {"kind": "artifact", "conversation_id": "same-conversation", "message_id": "generated-message"},
])
def test_inspection_binds_exact_bytes_and_opaque_handle(fake_adapter, handle):
    content = source_bytes()
    manifest = core.inspect_document(content, "REFERENCE.DOCX", handle)
    assert manifest["version"] == "document-inspection-v1"
    assert manifest["reference"] == {
        "handle": handle, "content_sha256": hashlib.sha256(content).hexdigest(), "extension": ".docx",
    }
    assert manifest["output_format"] == "docx"
    assert manifest["targets"][0]["id"] == "title"
    assert fake_adapter.calls == ["inspect"]


def test_reference_digest_mismatch_precedes_adapter_dispatch(fake_adapter):
    content = source_bytes()
    value = prepared(content)
    with pytest.raises(core.DocumentTransformError) as error:
        core.transform_document(content + b"changed", value)
    assert error.value.code == "reference_changed"
    assert fake_adapter.calls == []


def test_best_effort_applied_skipped_unresolved_and_preservation(fake_adapter):
    files = fixture_files(hyperlink=True)
    content = archive_bytes(files)
    value = prepared(content, operations=[
        {"op": "replace_text", "target": "title", "text": "New & useful <literal> draft"},
        {"op": "replace_text", "target": "chart:unknown", "text": "Unsupported"},
        {"op": "remove", "target": "silent"},
    ], unresolved=[{"target": "revenue", "reason": "A revenue figure is not available."}])
    with core.transform_document(content, value) as result:
        output = result.file_content.read()
        assert result.size_bytes == len(output)
        assert result.content_sha256 == hashlib.sha256(output).hexdigest()
        assert result.media_type == core.MEDIA_TYPES["docx"]
        assert result.file_extension == ".docx"
        report = result.metadata["transformation_report"]
        assert result.metadata["adapter"] == "test-only"
        assert report["applied"] == [{"op_index": 0, "target": "title", "op": "replace_text"}]
        assert [entry["op_index"] for entry in report["skipped"]] == [1, 2]
        assert report["unresolved"] == value["unresolved"]
        assert report["status"] == "draft"
        assert report["output"]["content_sha256"] == result.content_sha256
        assert {"target": "intro", "reason": "No operation requested."} in report["unchanged"]
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
            assert root.find(f".//{{{WORD_NS}}}t").text == "New & useful <literal> draft"
            assert root.find(f".//{{{WORD_NS}}}b") is not None
            for name in files:
                if name != "word/document.xml":
                    assert archive.read(name) == files[name]
    assert result.file_content.closed
    assert fake_adapter.calls == ["inspect", "transform"]
    assert archive_bytes(files) == content


def test_no_changes_are_prominent_and_reference_content_is_not_new_evidence(fake_adapter):
    content = source_bytes()
    value = prepared(content, mode="create_from_reference")
    with core.transform_document(content, value) as result:
        report = result.metadata["transformation_report"]
        assert report["status"] == "draft"
        assert any("No changes applied" in message for message in report["warnings"])
        assert any("not newly verified" in message for message in report["warnings"])
        with zipfile.ZipFile(result.file_content) as archive:
            assert archive.read("word/document.xml") == fixture_files()["word/document.xml"]


@pytest.mark.parametrize("extension", [".docx", ".dotx", ".pptx", ".potx"])
def test_deterministic_pack_preserves_parts_and_normalizes_templates(fake_adapter, extension):
    files = fixture_files(extension)
    content = archive_bytes(files)
    manifest = core.inspect_document(content, "reference" + extension, HANDLE)
    assert manifest["reference"]["extension"] == extension
    outputs = []
    for _repeat in range(2):
        with core.transform_document(content, prepared(content, extension)) as result:
            outputs.append(result.file_content.read())
            assert result.output_format == core.SOURCE_FORMATS[extension]
    assert outputs[0] == outputs[1]
    with zipfile.ZipFile(io.BytesIO(outputs[0])) as archive:
        types = etree.fromstring(archive.read("[Content_Types].xml"))
        main = "word/document.xml" if extension in (".docx", ".dotx") else "ppt/presentation.xml"
        declared = types.find(f"{{{CT_NS}}}Override").get("ContentType")
        assert declared == core._MAIN_TYPES["." + core.SOURCE_FORMATS[extension]]
        for name, data in files.items():
            if name != "[Content_Types].xml" or extension in (".docx", ".pptx"):
                assert archive.read(name) == data
        assert archive.namelist() == sorted(files)
        assert all(info.date_time == (2000, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert archive.read(main) == files[main]


def test_registry_accepts_lazy_test_module_and_missing_adapter_is_not_import_failure(monkeypatch):
    adapter = FakeAdapter()
    module = SimpleNamespace(inspect_package=adapter.inspect_package, transform_package=adapter.transform_package)
    monkeypatch.setitem(core._ADAPTERS, "docx", core._ADAPTERS["docx"])
    monkeypatch.setitem(sys.modules, "test_only_future_adapter", module)
    previous = core.register_document_transform_adapter("docx", "test_only_future_adapter")
    assert previous is not None
    content = source_bytes()
    inspected = core.inspect_document(content, "reference.docx", HANDLE)
    assert inspected["targets"]
    with core.transform_document(content, prepared(content)) as result:
        assert result.size_bytes > 0
    core.register_document_transform_adapter("docx", "test_only_missing_adapter")
    with pytest.raises(core.DocumentTransformError) as error:
        core.inspect_document(content, "reference.docx", HANDLE)
    assert error.value.code == "adapter_unavailable"
    with pytest.raises(core.DocumentTransformError):
        core.register_document_transform_adapter("docx", object())


@pytest.mark.parametrize("edit", [
    lambda files: files.update({"../outside.xml": b"<outside/>"}),
    lambda files: files.update({"C:outside.xml": b"<outside/>"}),
    lambda files: files.update({"CUSTOM/preserved.xml": b"<outside/>"}),
    lambda files: files.update({"custom/preserved.xml": b"<broken"}),
    lambda files: files.update({"custom/preserved.xml": b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///secret">]><x>&e;</x>'}),
    lambda files: files.update({"custom/preserved.xml": '<?xml version="1.0" encoding="UTF-7"?><x/>'.encode()}),
    lambda files: files.update({"word/vbaProject.bin": b"macro"}),
])
def test_corrupt_unsafe_or_ambiguous_packages_hard_fail_before_dispatch(fake_adapter, edit):
    files = fixture_files()
    edit(files)
    content = archive_bytes(files)
    with pytest.raises(core.DocumentTransformError):
        core.transform_document(content, prepared(content))
    assert fake_adapter.calls == []


def test_duplicate_encryption_and_non_zip_inputs_fail(fake_adapter):
    files = fixture_files()
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr("custom/data.bin", b"duplicate")
    with pytest.raises(core.DocumentTransformError):
        core.GuardedPackage(buffer.getvalue(), ".docx")
    backslash_files = fixture_files()
    backslash_files["word/outside.xml"] = b"<outside/>"
    backslash_content = archive_bytes(backslash_files).replace(b"word/outside.xml", b"word\\outside.xml")
    with pytest.raises(core.DocumentTransformError):
        core.GuardedPackage(backslash_content, ".docx")
    encrypted = bytearray(source_bytes())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        location = encrypted.index(signature) + offset
        bits = struct.unpack_from("<H", encrypted, location)[0]
        struct.pack_into("<H", encrypted, location, bits | 1)
    for content in (bytes(encrypted), b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1encrypted", b"not zip", b"PK\x03\x04broken"):
        with pytest.raises(core.DocumentTransformError):
            core.GuardedPackage(content, ".docx")


@pytest.mark.parametrize("active", ["dde", "split_dde", "program", "macro", "script_link"])
def test_program_fields_actions_and_unsafe_external_relationships_fail(active):
    files = fixture_files()
    if active == "dde":
        payload = b'<w:fldSimple w:instr=" DDEAUTO cmd.exe"/>'
    elif active == "split_dde":
        payload = (
            b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>DD</w:instrText></w:r>'
            b'<w:r><w:instrText>EAUTO cmd.exe</w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
        )
    elif active in ("program", "macro"):
        payload = f'<a:hlinkHover xmlns:a="{DRAWING_NS}" action=" ppaction://{active}?name=unsafe"/>'.encode()
    else:
        relationship = "hyperlink"
        target = "javascript:unsafe()"
        files["word/_rels/document.xml.rels"] = (
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="rUnsafe" Type="{OFFICE_REL_NS}/{relationship}" '
            f'Target="{target}" TargetMode="External"/></Relationships>'
        ).encode()
        payload = b""
    files["word/document.xml"] = files["word/document.xml"].replace(b"</w:body>", payload + b"</w:body>")
    with pytest.raises(core.DocumentTransformError) as error:
        core.GuardedPackage(archive_bytes(files), ".docx")
    assert error.value.code == "active_content"


def test_external_word_template_is_detached_without_blocking_useful_output(fake_adapter):
    files = fixture_files()
    files["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rTemplate" Type="{OFFICE_REL_NS}/attachedTemplate" '
        'Target="https://example.invalid/template.dotx" TargetMode="External"/></Relationships>'
    ).encode()
    files["word/document.xml"] = files["word/document.xml"].replace(
        b"</w:body>", b'<w:attachedTemplate r:id="rTemplate"/></w:body>',
    )
    content = archive_bytes(files)
    inspection = core.inspect_document(content, "reference.docx", HANDLE)
    with core.transform_document(content, prepared(content)) as result:
        with zipfile.ZipFile(result.file_content) as archive:
            assert b"attachedTemplate" not in archive.read("word/document.xml")
            assert b"example.invalid" not in archive.read("word/_rels/document.xml.rels")
            assert archive.read("custom/preserved.xml") == files["custom/preserved.xml"]
        assert any("external Word template" in warning for warning in result.metadata["transformation_report"]["warnings"])
    assert inspection["reference"]["content_sha256"] == hashlib.sha256(content).hexdigest()
    assert any("external Word template" in item for item in inspection["limitations"])
    assert b"attachedTemplate" in files["word/document.xml"]


def test_declared_xml_disguised_as_binary_is_guarded():
    files = fixture_files()
    files["[Content_Types].xml"] = files["[Content_Types].xml"].replace(
        b"</Types>", b'<Override PartName="/custom/data.bin" ContentType="application/xml"/></Types>',
    )
    files["custom/data.bin"] = b'<!DOCTYPE x [<!ENTITY e "expansion">]><x>&e;</x>'
    with pytest.raises(core.DocumentTransformError):
        core.GuardedPackage(archive_bytes(files), ".docx")


@pytest.mark.parametrize("target", ["missing.xml", "../../outside.xml", "https://example.invalid/body.xml", "http://[malformed"])
def test_invalid_relationship_targets_have_safe_errors(target):
    files = fixture_files()
    files["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rMissing" Type="{OFFICE_REL_NS}/image" Target="{target}"/></Relationships>'
    ).encode()
    with pytest.raises(core.DocumentTransformError) as error:
        core.GuardedPackage(archive_bytes(files), ".docx")
    assert error.value.code in ("invalid_relationship", "invalid_package")
    assert target not in error.value.message


def test_dangling_changed_reference_and_modified_unsafe_xml_are_not_delivered(fake_adapter, monkeypatch):
    content = source_bytes()

    def mutate(package, value, *, limits, check, image_resolver):
        package.files["word/document.xml"] = package.files["word/document.xml"].replace(
            b"</w:body>", b'<w:hyperlink r:id="rMissing"/></w:body>',
        )
        return {}

    monkeypatch.setattr(fake_adapter, "transform_package", mutate)
    with pytest.raises(core.DocumentTransformError) as error:
        core.transform_document(content, prepared(content))
    assert error.value.code == "invalid_relationship"
    package = core.GuardedPackage(content, ".docx")
    package.files["custom/preserved.xml"] = b'<!DOCTYPE x [<!ENTITY e "unsafe">]><x>&e;</x>'
    with pytest.raises(core.DocumentTransformError) as error:
        package.pack()
    assert error.value.code == "unsafe_xml"
    package.files["custom/preserved.xml"] = b'<?xml version="1.0" encoding="ISO-8859-1"?><x>safe text</x>'
    with pytest.raises(core.DocumentTransformError):
        package.pack()


@pytest.mark.parametrize("field,maximum", [
    ("max_source_bytes", 32), ("max_package_entries", 2),
    ("max_package_uncompressed_bytes", 32), ("max_part_bytes", 32),
    ("max_xml_nodes", 2), ("max_output_bytes", 32), ("max_targets", 1),
])
def test_resource_boundaries_are_enforced(fake_adapter, field, maximum):
    content = source_bytes()
    limits = replace(core.DocumentTransformLimits(), **{field: maximum})
    with pytest.raises(core.DocumentTransformError) as error:
        core.transform_document(content, prepared(content), limits=limits)
    assert error.value.code in ("resource_limit", "source_too_large", "output_too_large")


def test_cancellation_is_paced_and_access_failures_are_never_skipped(fake_adapter):
    content = source_bytes()
    with pytest.raises(core.DocumentTransformCancelled):
        core.transform_document(content, prepared(content), check=lambda: False)
    assert fake_adapter.calls == []
    count = 0

    def cancel_during_package():
        nonlocal count
        count += 1
        if count >= 15:
            raise core.DocumentTransformCancelled()

    with pytest.raises(core.DocumentTransformCancelled):
        core.GuardedPackage(content, ".docx", check=cancel_during_package)
    assert count == 15
    for failure in (PermissionError("private access detail"), core.DocumentMergeError("denied", "private access detail")):
        count = 0

        def denied_during_zip():
            nonlocal count
            count += 1
            if count == 4:
                raise failure

        with pytest.raises(type(failure)) as error:
            core.GuardedPackage(content, ".docx", check=denied_during_zip)
        assert error.value is failure


def test_adapter_cancellation_and_injected_image_resolver(fake_adapter, monkeypatch):
    content = source_bytes()
    resolver = lambda token: b"authorized image" if token == "asset:1" else None
    seen = []

    def receive(package, value, *, limits, check, image_resolver):
        seen.append(image_resolver("asset:1"))
        check()
        raise core.DocumentTransformCancelled()

    monkeypatch.setattr(fake_adapter, "transform_package", receive)
    with pytest.raises(core.DocumentTransformCancelled):
        core.transform_document(content, prepared(content), image_resolver=resolver)
    assert seen == [b"authorized image"]


def test_failed_output_and_final_check_close_the_owned_buffer(fake_adapter, monkeypatch):
    content = source_bytes()
    buffers = []
    original = core._BoundedBuffer

    def tracked_buffer(ceiling):
        result = original(ceiling)
        buffers.append(result)
        return result

    monkeypatch.setattr(core, "_BoundedBuffer", tracked_buffer)
    with pytest.raises(core.DocumentTransformError):
        core.transform_document(content, prepared(content), limits=replace(core.DocumentTransformLimits(), max_output_bytes=32))
    assert buffers[-1].closed

    def deny_after_buffer_created():
        if buffers and not buffers[-1].closed:
            raise PermissionError("access revoked")

    with pytest.raises(PermissionError):
        core.transform_document(content, prepared(content), check=deny_after_buffer_created)
    assert buffers[-1].closed


@pytest.mark.parametrize("inspection", [
    {"targets": [{"id": "repeated", "type": "paragraph"}, {"id": "repeated", "type": "paragraph"}]},
    {"targets": [{"id": "path/to/document", "type": "paragraph"}]},
    {"targets": [{"id": "title", "type": "paragraph", "text": {"not": "plain text"}}]},
    {"targets": {}, "layouts": [], "limitations": []},
])
def test_invalid_inspection_descriptors_fail_safely(fake_adapter, monkeypatch, inspection):
    monkeypatch.setattr(fake_adapter, "inspect_package", lambda *args, **kwargs: inspection)
    content = source_bytes()
    with pytest.raises(core.DocumentTransformError) as error:
        core.inspect_document(content, "reference.docx", HANDLE)
    assert error.value.code == "invalid_inspection"


@pytest.mark.parametrize("raw", [
    {"applied": [{"op_index": 0, "target": "different"}]},
    {"applied": [{"op_index": True, "target": "title"}]},
    {"applied": [{"op_index": 0, "target": "title"}], "skipped": [{"op_index": 0, "target": "title"}]},
    {"warnings": ["okay", {"unsafe": "not text"}]},
    {"unresolved": [{"target": "title"}]},
    {"metadata": []},
])
def test_invalid_adapter_outcomes_never_masquerade_as_success(fake_adapter, monkeypatch, raw):
    content = source_bytes()
    monkeypatch.setattr(fake_adapter, "transform_package", lambda *args, **kwargs: raw)
    with pytest.raises(core.DocumentTransformError) as error:
        core.transform_document(content, prepared(content, operations=[{"op": "remove", "target": "title"}]))
    assert error.value.code == "invalid_report"


@pytest.mark.parametrize("optimized", [False, True])
def test_real_cold_import_is_network_and_bootstrap_independent(optimized):
    probe = """
import importlib.abc
import base64
import hashlib
import socket
import sys
class RejectBootstrap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'flask', 'config', 'functions_settings', 'functions_appinsights', 'azure', 'openai'}:
            raise RuntimeError('bootstrap dependency imported')
def deny(*args, **kwargs):
    raise RuntimeError('network attempted')
socket.create_connection = deny
socket.socket.connect = deny
sys.meta_path.insert(0, RejectBootstrap())
sys.path.insert(0, sys.argv[1])
import functions_document_transform as core
if any(name in sys.modules for name in ('config', 'functions_document_transform_docx', 'functions_document_transform_pptx')):
    raise RuntimeError('eager adapter/bootstrap import')
schema = core.get_document_transform_schema()
if schema['properties']['schema_version']['const'] != 'document_transform_v1':
    raise RuntimeError('schema missing')
class FakeAdapter:
    def inspect_package(self, package, *, limits, check):
        check()
        return {'targets': [{'id': 'body', 'type': 'paragraph'}], 'layouts': [], 'limitations': []}
    def transform_package(self, package, prepared, *, limits, check, image_resolver):
        check()
        return {'skipped': [{'op_index': 0, 'target': 'missing', 'reason': 'Unsupported target'}]}
core.register_document_transform_adapter('docx', FakeAdapter())
content = base64.b64decode(sys.argv[2])
handle = {'kind': 'document', 'document_id': 'authorized-document'}
manifest = core.inspect_document(content, 'source.docx', handle)
value = {
    'schema_version': 'document_transform_v1', 'output_format': 'docx', 'mode': 'refresh',
    'reference': manifest['reference'],
    'operations': [{'op': 'remove', 'target': 'missing'}], 'unresolved': []
}
validated = core.validate_document_transform(value)
if len(validated['operations']) != 1:
    raise RuntimeError('validation did not preserve operation')
with core.transform_document(content, validated) as result:
    output = result.file_content.read()
    if hashlib.sha256(output).hexdigest() != result.content_sha256 or result.size_bytes != len(output):
        raise RuntimeError('invalid serialized result')
    if result.metadata['transformation_report']['skipped'][0]['target'] != 'missing':
        raise RuntimeError('skipped target missing')
if not result.file_content.closed:
    raise RuntimeError('result not closed')
"""
    encoded = base64.b64encode(source_bytes()).decode("ascii")
    command = [sys.executable, "-B", *(["-O"] if optimized else []), "-c", probe, str(APP_PATH), encoded]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
