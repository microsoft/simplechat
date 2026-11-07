# test_content_screening_upload_routes.py
"""
Behavioral tests for private upload staging before ordinary executor submission.
Version: 0.261.106
Implemented in: 0.261.106

Executes the real create/update/prepare/submit blocks and their error handlers.
All storage, filesystem, executor, and telemetry operations are injected fakes.
"""

import ast
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Configure the standalone import path before loading the side-effect-free contracts.
from content_screening.contracts import ScreeningError


UPLOAD_ROUTES = (
    ("route_backend_documents.py", "api_user_upload_document", {}),
    ("route_backend_group_documents.py", "api_upload_group_document", {"group_id": "group-1"}),
    ("route_backend_public_documents.py", "api_upload_public_document", {"public_workspace_id": "workspace-1"}),
    ("route_external_public_documents.py", "external_upload_public_document", {"public_workspace_id": "workspace-1"}),
)


def submission_statement(statement):
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"submit", "submit_stored"}
        and any(isinstance(argument, ast.Name) and argument.id == "process_document_upload_background" for argument in node.args)
        for node in ast.walk(statement)
    )


def load_upload_queue_block(file_name, route_name):
    path = APP_ROOT / file_name
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    route = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == route_name
    )
    block = next(
        node for node in ast.walk(route)
        if isinstance(node, ast.Try)
        and any(
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "create_document"
            for statement in node.body
        )
        and any(submission_statement(statement) for statement in node.body)
    )
    block = deepcopy(block)
    submit_index = next(index for index, statement in enumerate(block.body) if submission_statement(statement))
    block.body = block.body[:submit_index + 1]
    previous_statement = block.body[-2]
    if not (
        isinstance(previous_statement, ast.Expr)
        and isinstance(previous_statement.value, ast.Call)
        and isinstance(previous_statement.value.func, ast.Name)
        and previous_statement.value.func.id == "prepare_document_upload"
    ):
        raise AssertionError("Upload preparation must immediately precede executor submission.")
    return compile(ast.Module(body=[block], type_ignores=[]), str(path), "exec")


class UploadPreparationRouteTests(unittest.TestCase):
    def execute(self, file_name, route_name, *, preparation_result=None, failure=None):
        events = []
        prepared = []
        queued = []
        errors = []
        logs = []
        state = {"prepared": False}
        worker = object()

        def create_document(**arguments):
            events.append("create")
            self.assertEqual(arguments["document_id"], "document-1")

        def update_document(**arguments):
            events.append("update")
            self.assertFalse(state["prepared"], "No stale metadata update may follow source preparation.")
            self.assertEqual(arguments["percentage_complete"], 0)

        def prepare_document_upload(**arguments):
            events.append("prepare")
            state["prepared"] = True
            prepared.append(arguments)
            if failure is not None:
                raise failure
            return preparation_result

        def submit(*arguments, **keywords):
            events.append("submit")
            self.assertTrue(state["prepared"])
            self.assertIs(arguments[-1], worker)
            queued.append(keywords)
            return object()

        namespace = {
            "create_document": create_document,
            "update_document": update_document,
            "prepare_document_upload": prepare_document_upload,
            "process_document_upload_background": worker,
            "current_app": SimpleNamespace(extensions={"executor": SimpleNamespace(submit=submit, submit_stored=submit)}),
            "parent_document_id": "document-1", "doc_id": "document-1",
            "user_id": "user-1", "active_group_id": "group-1",
            "active_ws": "workspace-1", "active_workspace_id": "workspace-1",
            "temp_file_path": "staged-upload.csv", "tmp_path": "staged-upload.csv",
            "original_filename": "report.csv", "orig": "report.csv",
            "upload_errors": errors, "errors": errors,
            "logging": logging, "ScreeningError": ScreeningError,
            "log_event": lambda message, **arguments: logs.append({"message": message, **arguments}),
            "os": SimpleNamespace(path=SimpleNamespace(exists=lambda _path: False)),
        }
        exec(load_upload_queue_block(file_name, route_name), namespace)
        return events, prepared, queued, errors, logs

    def test_all_workspace_scopes_prepare_exact_worker_source_before_queue(self):
        for file_name, route_name, scope in UPLOAD_ROUTES:
            with self.subTest(route=route_name):
                events, prepared, queued, errors, _logs = self.execute(
                    file_name, route_name, preparation_result={"id": "scan-1"},
                )
                expected = {
                    "document_id": "document-1", "user_id": "user-1",
                    "temp_file_path": "staged-upload.csv", "original_filename": "report.csv",
                    **scope,
                }
                self.assertEqual(events, ["create", "update", "prepare", "submit"])
                self.assertEqual(prepared, [expected])
                self.assertEqual(queued, [expected])
                self.assertEqual(errors, [])

    def test_unenrolled_preparation_result_preserves_legacy_queueing(self):
        for file_name, route_name, _scope in UPLOAD_ROUTES:
            with self.subTest(route=route_name):
                events, _prepared, queued, errors, _logs = self.execute(
                    file_name, route_name, preparation_result=None,
                )
                self.assertEqual(events[-2:], ["prepare", "submit"])
                self.assertEqual(len(queued), 1)
                self.assertEqual(errors, [])

    def test_preparation_failures_never_queue_or_disclose_private_details(self):
        for file_name, route_name, _scope in UPLOAD_ROUTES:
            for error in (
                ScreeningError("PRIVATE original reference must not reach a client"),
                RuntimeError("PRIVATE provider credential or blob pointer"),
            ):
                with self.subTest(route=route_name, error=type(error).__name__):
                    events, prepared, queued, errors, logs = self.execute(
                        file_name, route_name, failure=error,
                    )
                    self.assertEqual(events, ["create", "update", "prepare"])
                    self.assertEqual(len(prepared), 1)
                    self.assertEqual(queued, [])
                    self.assertEqual(len(errors), 1)
                    self.assertNotIn("PRIVATE", json.dumps(errors))
                    self.assertNotIn("PRIVATE", json.dumps(logs))
                    self.assertEqual(logs[0]["extra"]["exception_type"], type(error).__name__)


if __name__ == "__main__":
    unittest.main()
