# test_government_speech.py
"""
Offline regression coverage for Government Speech routing and chat failures.
Version: 0.261.450
Implemented in: 0.261.450

Real modules load in fresh processes with external bootstrap I/O blocked.
SpeechConfig uses the installed native SDK; recognizer events are simulated.
Probe-local imports intentionally occur inside the offline bootstrap context.
"""

import io
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ID = (
    "/subscriptions/12345678-1234-1234-1234-123456789abc"
    "/resourceGroups/offline/providers/Microsoft.CognitiveServices/accounts/offline"
)


def _run_probe(name):
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((
            str(ROOT / "application" / "single_app"),
            str(ROOT / "functional_tests"),
            os.environ.get("PYTHONPATH", ""),
        )),
    }
    result = subprocess.run(
        [sys.executable, "-c", (
            "import runpy; "
            f"runpy.run_path({str(Path(__file__).resolve())!r})[{name!r}]()"
        )],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_synthesis_cloud_and_auth_compatibility():
    _run_probe("_probe_synthesis")


def test_chat_recognition_failure_and_cleanup():
    _run_probe("_probe_recognition")


def _probe_synthesis():
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports():
        import functions_documents as documents
        import azure.cognitiveservices.speech as sdk

        credentials = Mock()
        credentials.get_token.return_value = SimpleNamespace(token="offline-token")
        settings = {
            "speech_service_authentication_type": "managed_identity",
            "speech_service_resource_id": RESOURCE_ID,
        }
        with patch.object(documents, "DefaultAzureCredential", return_value=credentials):
            for cloud, endpoint in (
                ("usgovernment", "https://offline.cognitiveservices.azure.us"),
                ("custom", "https://offline.cognitiveservices.azure.cn"),
            ):
                with patch.object(documents, "AZURE_ENVIRONMENT", cloud):
                    config = documents.get_speech_synthesis_config(settings, endpoint, "usgovvirginia")
                    assert config.get_property(sdk.PropertyId.SpeechServiceConnection_Endpoint) == endpoint
                    assert config.authorization_token == f"aad#{RESOURCE_ID}#offline-token"
                    credentials.get_token.assert_called_with(documents.cognitive_services_scope)
                    with pytest.raises(ValueError, match="endpoint is required"):
                        documents.get_speech_synthesis_config(settings, "", "usgovvirginia")

            with patch.object(documents, "AZURE_ENVIRONMENT", "public"):
                config = documents.get_speech_synthesis_config(settings, "", "eastus")
                assert config.get_property(sdk.PropertyId.SpeechServiceConnection_Region) == "eastus"
                assert config.get_property(sdk.PropertyId.SpeechServiceConnection_Endpoint) == ""
                assert config.authorization_token == f"aad#{RESOURCE_ID}#offline-token"

            for cloud, endpoint in (
                ("public", "https://offline.cognitiveservices.azure.com"),
                ("usgovernment", "https://offline.cognitiveservices.azure.us"),
            ):
                with patch.object(documents, "AZURE_ENVIRONMENT", cloud):
                    config = documents.get_speech_synthesis_config({
                        "speech_service_authentication_type": "key",
                        "speech_service_key": " offline-key ",
                    }, endpoint, "")
                    assert config.get_property(sdk.PropertyId.SpeechServiceConnection_Endpoint) == endpoint
                    assert config.get_property(sdk.PropertyId.SpeechServiceConnection_Key) == "offline-key"

            with pytest.raises(ValueError, match="location is required"):
                documents.get_speech_synthesis_config(settings, "", "")
            with pytest.raises(ValueError, match="resource ID is required"):
                documents.get_speech_synthesis_config({
                    "speech_service_authentication_type": "managed_identity",
                }, "", "eastus")


class _Signal:
    def __init__(self):
        self.handlers = []
        self.disconnected = False

    def connect(self, handler):
        self.handlers.append(handler)

    def emit(self, value):
        for handler in self.handlers:
            handler(value)

    def disconnect_all(self):
        self.disconnected = True
        self.handlers.clear()


class _Completion:
    def __init__(self):
        self.complete = False

    def set(self):
        self.complete = True

    def is_set(self):
        return self.complete

    def wait(self, timeout):
        assert timeout == 120
        return self.complete


def _probe_recognition():
    from flask import Blueprint, Flask
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports(), TemporaryDirectory() as directory:
        import route_backend_speech as speech
        from functions_appinsights import _build_logger_extra

        audio_path = Path(directory) / "offline.wav"
        audio_path.write_bytes(b"offline-audio")
        active = {}
        instances = []
        sdk = speech.speechsdk
        provider_secret = "provider-secret-must-not-leak"
        transcript = "private transcript"

        class Recognizer:
            def __init__(self, **kwargs):
                self.recognized = _Signal()
                self.canceled = _Signal()
                self.session_stopped = _Signal()
                self.stopped = False
                instances.append(self)

            def start_continuous_recognition(self):
                if active.get("start_error"):
                    raise RuntimeError(provider_secret)
                if active.get("partial"):
                    self.recognized.emit(SimpleNamespace(result=SimpleNamespace(
                        reason=sdk.ResultReason.RecognizedSpeech, text=f" {transcript} ",
                    )))
                if active.get("no_match"):
                    self.recognized.emit(SimpleNamespace(result=SimpleNamespace(
                        reason=sdk.ResultReason.NoMatch, text="",
                    )))
                if active.get("cancel") is not None:
                    self.canceled.emit(SimpleNamespace(
                        reason=active["cancel"], error_details=provider_secret,
                    ))
                if active.get("session_stopped"):
                    self.session_stopped.emit(SimpleNamespace())

            def stop_continuous_recognition(self):
                self.stopped = True
                if active.get("late_error"):
                    self.canceled.emit(SimpleNamespace(
                        reason=sdk.CancellationReason.Error, error_details=provider_secret,
                    ))

        logs = Mock()
        debug = Mock()
        with (
            patch.object(speech, "_get_speech_config", return_value=object()),
            patch.object(sdk, "AudioConfig", return_value=object()) as audio_config,
            patch.object(sdk, "SpeechRecognizer", Recognizer),
            patch.object(speech, "threading", SimpleNamespace(Event=_Completion)),
            patch.object(speech.time, "sleep"),
            patch.object(speech, "log_event", logs),
            patch.object(speech, "debug_print", debug),
        ):
            scenarios = (
                ({"partial": True, "session_stopped": True}, None, [transcript]),
                ({"no_match": True, "session_stopped": True}, None, []),
                ({"cancel": sdk.CancellationReason.EndOfStream}, None, []),
                ({"partial": True, "cancel": sdk.CancellationReason.EndOfStream}, None, [transcript]),
                ({"cancel": sdk.CancellationReason.Error}, RuntimeError, None),
                ({"partial": True, "cancel": sdk.CancellationReason.Error}, RuntimeError, None),
                ({"partial": True, "cancel": sdk.CancellationReason.CancelledByUser}, RuntimeError, None),
                ({}, TimeoutError, None),
                ({"partial": True}, TimeoutError, None),
                ({"partial": True, "session_stopped": True, "late_error": True}, RuntimeError, None),
                ({"start_error": True}, RuntimeError, None),
            )
            for scenario, error, expected in scenarios:
                active.clear()
                active.update(scenario)
                if error:
                    with pytest.raises(error):
                        speech._transcribe_wav_with_speech_sdk(str(audio_path), {}, "", "en-US")
                else:
                    result = speech._transcribe_wav_with_speech_sdk(str(audio_path), {}, "", "en-US")
                    assert result == expected, scenario
                recognizer = instances[-1]
                assert recognizer.stopped, scenario
                assert all(signal.disconnected for signal in (
                    recognizer.recognized, recognizer.canceled, recognizer.session_stopped,
                )), scenario

            app = Flask("offline-speech")
            app.config.update(TESTING=True, SECRET_KEY="offline-only")
            bp = Blueprint("speech", __name__)
            speech.register_route_backend_speech(bp)
            app.register_blueprint(bp)
            client = app.test_client()
            with client.session_transaction() as session:
                session["user"] = {"oid": "offline-user", "roles": ["Admin"]}
            settings = {
                "enable_speech_to_text_input": True,
                "speech_service_endpoint": "https://offline.cognitiveservices.azure.us",
            }
            with patch.object(speech, "get_settings", return_value=settings), patch.object(
                speech, "AZURE_ENVIRONMENT", "usgovernment",
            ):
                for scenario in (
                    {"cancel": sdk.CancellationReason.Error},
                    {"partial": True, "cancel": sdk.CancellationReason.Error},
                    {"partial": True}, {"start_error": True},
                    {"session_stopped": True}, {"partial": True, "session_stopped": True},
                ):
                    active.clear()
                    active.update(scenario)
                    response = client.post("/api/speech/transcribe-chat", data={
                        "audio": (io.BytesIO(b"offline-audio"), "recording.wav"),
                    })
                    body = response.get_json()
                    uploaded_path = audio_config.call_args.kwargs["filename"]
                    assert not Path(uploaded_path).exists()
                    if scenario.get("session_stopped"):
                        assert response.status_code == 200, body
                        assert body["success"] == bool(scenario.get("partial")), body
                    else:
                        assert response.status_code == 500, body
                        assert body == {
                            "success": False, "error": "Failed to transcribe audio. Please try again.",
                        }

            for cloud in ("usgovernment", "custom", "public"):
                with (
                    patch.object(speech, "AZURE_ENVIRONMENT", cloud),
                    patch.object(speech, "_transcribe_audio_with_fast_api", return_value=["fast"]) as fast,
                    patch.object(speech, "_transcribe_wav_with_speech_sdk", return_value=["sdk"]) as fallback,
                ):
                    result = speech._transcribe_chat_wav(str(audio_path), {}, "https://offline/", "en-US")
                    assert result == (["fast"] if cloud == "public" else ["sdk"])
                    assert fast.call_count == (1 if cloud == "public" else 0)
                    assert fallback.call_count == (0 if cloud == "public" else 1)

        recorded = str(logs.call_args_list) + str(debug.call_args_list)
        assert provider_secret not in recorded
        assert transcript not in recorded
        codes = {
            call.kwargs.get("extra", {}).get("failure_code") for call in logs.call_args_list
        }
        assert {"speech_sdk_canceled", "speech_sdk_interrupted", "speech_sdk_timeout"} <= codes
        for code in codes - {None}:
            safe = _build_logger_extra("[SPEECH] Recognition failed.", {"failure_code": code})
            assert safe["sc_failure_code"] == code
