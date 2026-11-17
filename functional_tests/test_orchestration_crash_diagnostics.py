#!/usr/bin/env python3
# test_orchestration_crash_diagnostics.py
"""
Functional test for orchestration crash diagnostics.
Version: 0.261.454
Implemented in: 0.261.451

This test ensures that an unexpected orchestration failure reaches telemetry with its
exception class and application code location, and without the exception message.
"""

import importlib
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
APPLICATION = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APPLICATION) not in sys.path:
    sys.path.insert(0, str(APPLICATION))

telemetry = importlib.import_module("functions_appinsights")


def _raise_private():
    raise KeyError("PRIVATE_COLUMN_NAME")


def _caught():
    try:
        _raise_private()
    except KeyError as exc:
        return exc


def test_exception_fields_name_class_and_code_location_only(monkeypatch):
    monkeypatch.setattr(telemetry, "_APPLICATION_ROOT", os.path.dirname(os.path.abspath(__file__)))
    fields = telemetry.exception_log_fields(_caught())
    assert fields["error_type"] == "KeyError"
    innermost, outer = fields["error_site"].split(" < ")
    name = os.path.basename(__file__)
    assert innermost.startswith(f"{name}:_raise_private:")
    assert outer.startswith(f"{name}:_caught:")
    assert innermost.rsplit(":", 1)[1].isdigit()
    assert "PRIVATE" not in repr(fields)


def test_frames_outside_the_application_are_not_recorded():
    fields = telemetry.exception_log_fields(_caught())
    assert fields == {"error_type": "KeyError"}


def test_frame_limit_keeps_the_innermost_frames(monkeypatch):
    monkeypatch.setattr(telemetry, "_APPLICATION_ROOT", os.path.dirname(os.path.abspath(__file__)))
    fields = telemetry.exception_log_fields(_caught(), frames=1)
    assert " < " not in fields["error_site"]
    assert ":_raise_private:" in fields["error_site"]


def test_logger_keeps_crash_identity_and_drops_other_text():
    properties = telemetry._build_logger_extra("[ORCHESTRATION] Planning failed.", {
        "exception_type": "KeyError",
        "error_type": "KeyError",
        "error_site": "functions_orchestration_schema.py:validate_plan:10",
    })
    assert properties["sc_exception_type"] == "KeyError"
    assert properties["sc_error_type"] == "KeyError"
    assert properties["sc_error_site"] == "functions_orchestration_schema.py:validate_plan:10"

    unsafe = telemetry._build_logger_extra("message", {"exception_type": "PRIVATE text, not a class"})
    assert "sc_exception_type" not in unsafe
    assert unsafe["sc_exception_type_length"] == len("PRIVATE text, not a class")


def test_planning_catch_all_reports_crash_identity_and_conversation():
    source = (APPLICATION / "route_backend_orchestration.py").read_text(encoding="utf-8")
    start = source.index("'[ORCHESTRATION] Planning failed.'")
    handler = source[start:start + 400]
    assert "exception_log_fields(exc)" in handler
    assert "workflow_log_context(conversation_id=resolved_conversation_id)" in handler


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
