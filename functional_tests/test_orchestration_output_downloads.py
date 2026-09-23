# test_orchestration_output_downloads.py
"""Committed retained-output media types at the actual download response boundary.

Version: 0.261.127
Implemented in: 0.261.127

The real renderer, retained readers, private uploader, output store, authorization,
and download handler run with only external storage doubled.
"""

from dataclasses import replace

import pytest
import yaml

from functions_orchestration_output_store import OutputError, OutputUnavailableError
from functions_orchestration_results import NamedOutput
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_support.orchestration_results import ROWS, complete


@pytest.mark.parametrize("file_name", ["data.yml", "data.yaml", "Data.YML"])
def test_yaml_download_uses_committed_media_type_not_host_inference(lifecycle, monkeypatch, file_name):
    output = lifecycle.prepare("yaml", file_name=file_name)
    completed = lifecycle.run(output)
    monkeypatch.setattr(lifecycle.modules.routes.mimetypes, "guess_type", lambda name: ("text/html", None))
    with lifecycle.app.test_request_context():
        response = lifecycle.modules.routes._serve_chat_artifact_download(
            "owner", "conversation-1", completed["artifact_message_id"],
        )
        try:
            content = b"".join(response.response)
            headers = dict(response.headers)
        finally:
            response.close()
    rows = yaml.safe_load(content)
    assert headers["Content-Type"] == "application/yaml"
    assert int(headers["Content-Length"]) == len(content)
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "private, no-store"
    assert f'filename="{file_name}"' in headers["Content-Disposition"]
    assert rows == ROWS and rows[-1] == ROWS[-1]
    assert lifecycle.blobs.uploads == 1


@pytest.mark.parametrize("kind,output_format,extension,media_type", [
    ("markdown-v1", "md", "markdown", "text/markdown; charset=utf-8"),
    ("text-v1", "txt", "text", "text/plain; charset=utf-8"),
])
def test_prepared_text_alias_download_keeps_authorized_type(
    lifecycle, monkeypatch, kind, output_format, extension, media_type,
):
    content = "Complete prepared content.\n"
    producer = replace(lifecycle.results.producer, step_id="prepared_text")
    lifecycle.results.add_producer(producer)
    task = lifecycle.results.save(
        producer=producer, grounded=False,
        outputs=[NamedOutput("prepared", kind, content, complete(1))],
    )
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"].append({
        "step_id": producer.step_id, "enabled": True, "capability_id": producer.capability_id,
    })
    lifecycle.runs.upsert_item(run)
    output = lifecycle.prepare(
        output_format, reference=task.output("prepared"), file_name=f"Prepared.{extension}",
    )
    completed = lifecycle.run(output)
    monkeypatch.setattr(lifecycle.modules.routes.mimetypes, "guess_type", lambda name: (None, None))
    with lifecycle.app.test_request_context():
        response = lifecycle.modules.routes._serve_chat_artifact_download(
            "owner", "conversation-1", completed["artifact_message_id"],
        )
        try:
            downloaded = b"".join(response.response)
            content_type = response.content_type
        finally:
            response.close()
    assert content_type == media_type
    assert downloaded == content.encode("utf-8")


def test_tampered_committed_media_type_is_not_trusted(lifecycle):
    output = lifecycle.prepare("yaml")
    completed = lifecycle.run(output)
    record = lifecycle.raw(completed)
    record["committed_intent"]["media_type"] = "text/html"
    lifecycle.runs.upsert_item(record)
    with lifecycle.app.test_request_context():
        with pytest.raises((OutputError, OutputUnavailableError)):
            lifecycle.modules.routes._serve_chat_artifact_download(
                "owner", "conversation-1", completed["artifact_message_id"],
            )
