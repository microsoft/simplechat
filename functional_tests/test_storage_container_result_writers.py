# test_storage_container_result_writers.py
"""First-use storage regressions through real Analyze and native tabular owners.

Version: 0.261.396
Implemented in: 0.261.396

Only Blob transport is wrapped; analysis, native staging, lifecycle fences,
result retention and failure hydration execute through their real owners.
"""

from pathlib import Path
import sys

from azure.core.exceptions import HttpResponseError
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from test_orchestration_internal_analysis import analyze, internal  # noqa: E402,F401
from test_orchestration_native_results import bridge_runtime, execute  # noqa: E402


class MissingContainerBlobs:
    def __init__(self, base, target, *, denied=False):
        self.base = base
        self.target = target
        self.denied = denied
        self.ready = False
        self.creates = 0
        self.missing_writes = 0
        self.observe = lambda: None
        self.observed = []

    def __getattr__(self, name):
        return getattr(self.base, name)

    def get_blob_client(self, container, blob):
        original = self.base.get_blob_client(container=container, blob=blob)
        owner = self

        class Blob:
            def __getattr__(self, name):
                return getattr(original, name)

            def upload_blob(self, *args, **kwargs):
                owner.observed.append(owner.observe())
                if container == owner.target and not owner.ready:
                    owner.missing_writes += 1
                    error = HttpResponseError("PRIVATE missing checkpoint container")
                    error.error_code = "ContainerNotFound"
                    error.status_code = 404
                    raise error
                return original.upload_blob(*args, **kwargs)

        return Blob()

    def get_container_client(self, container):
        owner = self

        class Container:
            def __getattr__(self, name):
                return getattr(owner.base.get_container_client(container), name)

            def create_container(self, **kwargs):
                assert container == owner.target
                assert kwargs["public_access"] is None and kwargs["retry_total"] == 0
                owner.creates += 1
                if owner.denied:
                    error = HttpResponseError("PRIVATE storage identity")
                    error.error_code = "AuthorizationPermissionMismatch"
                    error.status_code = 403
                    raise error
                owner.ready = True

        return Container()


def test_real_analysis_checkpoint_recovers_without_repeating_model_work(internal):
    store = internal.fixture.service.store
    blobs = MissingContainerBlobs(store.blob_client, store.blob_container_name)
    blobs.observe = lambda: len(internal.model.calls)
    store.blob_client = blobs
    result = analyze(internal)
    assert result["status"] == "completed", result
    assert blobs.observed[0] == blobs.observed[1]
    assert blobs.creates == blobs.missing_writes == 1
    assert internal.hooks.call_count == 0
    findings = list(internal.fixture.service.open_result(result["task_result"].output("findings")).iter_records())
    assert len(findings) == 151


def test_analysis_creation_denial_is_storage_failure_not_generic_404(internal):
    store = internal.fixture.service.store
    blobs = MissingContainerBlobs(store.blob_client, store.blob_container_name, denied=True)
    store.blob_client = blobs
    result = analyze(internal)
    assert result["status"] == "failed"
    assert result["failure"]["code"] == "result_storage_unavailable"
    assert "storage" in result["failure"]["message"]
    assert "PRIVATE" not in str(result) and "HTTP 404" not in str(result)
    assert blobs.creates == 1 and internal.hooks.call_count == 0


@pytest.mark.parametrize("denied", [False, True])
def test_native_staging_recovery_and_persisted_failure_reach_bridge(monkeypatch, denied):
    with bridge_runtime(monkeypatch, count=4, operation="query") as runtime:
        engine = runtime.native.engine
        blobs = MissingContainerBlobs(runtime.native.blobs, "personal-chat", denied=denied)
        monkeypatch.setitem(engine.CLIENTS, "storage_account_office_docs_client", blobs)
        result = execute(runtime)
        assert blobs.creates == blobs.missing_writes == 1
        assert runtime.provider.calls == [] and runtime.native.publications == []
        jobs = list(runtime.native.jobs.items.values())
        assert len(jobs) == 1
        if denied:
            assert jobs[0]["status"] == "failed"
            assert jobs[0]["failure_code"] == "result_storage_unavailable"
            assert result["failure"]["code"] == "result_storage_unavailable", result
            assert result["failure"]["retryable"] is True
            assert "PRIVATE" not in str(result)
        else:
            assert result["status"] == "completed", (result, jobs[0].get("last_error"))
            rows = list(runtime.service.open_result(result["task_result"].output("records")).iter_records())
            assert len(rows) == 2
