# test_admin_support_export_logging.py
"""
Real logging entry-point correlation and debug-forwarding regressions.
Version: 0.261.428
Implemented in: 0.261.428
"""

import hashlib
import logging
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

import functions_appinsights as insights


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def capture(monkeypatch):
    logger = logging.getLogger("support-export-test-" + uuid.uuid4().hex)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = Capture()
    logger.addHandler(handler)
    monkeypatch.setattr(insights, "_azure_monitor_configured", True)
    monkeypatch.setattr(insights, "_appinsights_logger", logger)
    monkeypatch.setattr(insights, "_diagnostic_context_provider", None)
    monkeypatch.setattr(insights.app_settings_cache, "get_settings_cache", lambda: {"enable_debug_logging": True})
    yield handler
    logger.removeHandler(handler)


def test_debug_only_forwards_once_without_widening_levels(capture, capsys):
    insights.log_event("A debug checkpoint", debug_only=True, category="TEST")
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.levelno == logging.DEBUG
    assert record.sc_message == "[debug] [TEST] A debug checkpoint"
    assert insights._appinsights_logger.level == logging.INFO
    assert "[DEBUG][Log]" not in capsys.readouterr().out


def test_debug_off_stays_silent(capture, monkeypatch, capsys):
    monkeypatch.setattr(insights.app_settings_cache, "get_settings_cache", lambda: {"enable_debug_logging": False})
    insights.log_event("Not recorded", debug_only=True)
    insights.debug_print("Not recorded either")
    assert not capture.records and capsys.readouterr().out == ""


def test_context_isolated_and_authoritative_over_caller_dimensions(capture):
    def emit(user):
        with insights.diagnostic_log_context(user_id=user, conversation_id="conversation-" + user):
            insights.log_event("A checkpoint", extra={"user_id_hash": "f" * 64})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(emit, ["one", "two"]))
    expected = {hashlib.sha256(value.encode()).hexdigest() for value in ("one", "two")}
    assert {record.sc_user_id_hash for record in capture.records} == expected
    insights.log_event("Outside context")
    assert not hasattr(capture.records[-1], "sc_user_id_hash")
