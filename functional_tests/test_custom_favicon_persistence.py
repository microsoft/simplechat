# test_custom_favicon_persistence.py
"""
Regression coverage for custom favicon restoration and cross-instance updates.
Version: 0.261.062
Implemented in: 0.261.062

Real application modules run in fresh processes with external I/O blocked.
Temporary instance roots isolate generated files from the repository. Refs #1932.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import importlib
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask, render_template_string
from PIL import Image
import pytest

from test_support.offline_bootstrap import offline_app_imports
from test_app_settings_store_consistency import FakeRedis


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"


def check(condition, message):
    """Keep probe checks active in optimized Python."""
    if not condition:
        raise AssertionError(message)


def icon_bytes(color):
    buffer = BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="ICO")
    return buffer.getvalue()


def make_worker(app_module, root):
    worker = Flask(__name__, root_path=str(root), static_folder=str(root / "static"))
    worker.secret_key = "offline-favicon-test"
    worker.before_request(app_module.ensure_application_initialized)
    source = (APP_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    head = source[source.index("<head>"):source.index("<!-- Bootstrap CSS -->")]

    @worker.route("/")
    def page():
        settings = app_module.get_request_settings()
        return render_template_string(
            head + "</head><body><h1>Favicon fixture</h1></body>",
            app_settings=app_module.sanitize_settings_for_user(settings),
        )

    return worker


def save_icon(settings_module, data, version):
    saved = settings_module.update_settings({
        "custom_favicon_base64": base64.b64encode(data).decode("ascii"),
        "favicon_version": version,
    })
    check(saved, "Offline favicon settings save failed.")


def initialize_worker(app_module, worker):
    # Keep real initialization/settings wiring, replacing only cloud and session effects.
    with patch.object(app_module, "app", worker), patch.multiple(
        app_module,
        initialize_clients=lambda _settings: None,
        setup_appinsights_logging=lambda _settings: None,
        ensure_default_global_agent_exists=lambda: None,
        configure_sessions=lambda _settings: None,
    ):
        app_module.initialize_application(force=True)


def offline_probe(first_module, browser_ready=None):
    # Imports must execute inside the external-I/O seam, not behind fake app modules.
    with offline_app_imports():
        importlib.import_module(first_module)
        config = importlib.import_module("config")
        app_module = importlib.import_module("app")
        settings_module = importlib.import_module("functions_settings")
        settings_module.get_settings(use_cosmos=True)

        first, second = icon_bytes("red"), icon_bytes("blue")
        save_icon(settings_module, first, 2)
        with TemporaryDirectory() as directory:
            roots = [Path(directory) / name for name in ("one", "two")]
            workers = [make_worker(app_module, root) for root in roots]
            paths = [root / "static" / "images" / "favicon.ico" for root in roots]
            initialize_worker(app_module, workers[0])
            restored = paths[0].read_bytes()
            check(restored == first, "Startup did not restore the saved custom favicon.")

            if browser_ready is not None:
                browser_server(app_module, settings_module, workers[0], paths[0], second, browser_ready)
                return

            # A fresh second instance and a later upload both use the real settings path.
            initialize_worker(app_module, workers[1])
            check(paths[1].read_bytes() == first, "Second instance did not restore the icon.")
            store = app_module.app_settings_cache.get_settings_store()
            for mode, data, version in (("redis", second, 3), ("redis-failed", first, 4), ("cosmos", second, 5)):
                store.redis = FakeRedis()
                store.redis_required = mode != "cosmos"
                save_icon(settings_module, data, version)
                store.redis.failed = mode == "redis-failed"
                for worker, path in zip(workers, paths):
                    with patch.object(app_module, "app", worker):
                        with worker.test_client() as client:
                            response = client.get(f"/static/images/favicon.ico?v={version}")
                            payload = response.get_data()
                            status = response.status_code
                            response.close()
                    check(status == 200 and payload == data, f"Instance served a stale favicon with {mode}.")
                    check(path.read_bytes() == data, f"Instance file did not converge with {mode}.")

            # Other static requests must not trigger settings lookup or favicon regeneration.
            with patch.object(app_module, "app", workers[0]), patch.object(
                app_module, "get_request_settings", side_effect=AssertionError("Unrelated asset read settings")
            ):
                with workers[0].test_client() as client:
                    response = client.get("/static/missing.css")
                    response.close()

            stored = settings_module.get_settings()
            with patch.object(config.os, "replace", side_effect=AssertionError("Unchanged icon rewritten")):
                config.ensure_custom_favicon_file_exists(workers[0], stored)
            paths[0].unlink()
            with patch.object(app_module, "app", workers[0]):
                with workers[0].test_client() as client:
                    response = client.get("/static/images/favicon.ico?v=3")
                    payload = response.get_data()
                    response.close()
            check(payload == second, "A deleted local icon was not regenerated.")

            events = []
            for invalid in ("not base64!", base64.b64encode(b"not an image").decode("ascii"), True):
                with patch.object(config, "log_event", side_effect=lambda *args, **kwargs: events.append((args, kwargs))):
                    config.ensure_custom_favicon_file_exists(workers[0], {"custom_favicon_base64": invalid})
                check(paths[0].read_bytes() == second, "Invalid data replaced a usable icon.")
            check(len(events) == 3, "Invalid stored data was not explicitly logged.")

            with patch.object(config.os, "replace", side_effect=PermissionError("test failure")), patch.object(
                config, "log_event", side_effect=lambda *args, **kwargs: events.append((args, kwargs))
            ):
                config.ensure_custom_favicon_file_exists(
                    workers[0], {"custom_favicon_base64": base64.b64encode(first).decode("ascii")}
                )
            check(len(events) == 4, "A failed replacement was not logged.")
            check(paths[0].read_bytes() == second, "Failed replacement truncated the icon.")
            check(not list(paths[0].parent.glob(".favicon-*")), "Temporary replacement file leaked.")
            config.ensure_custom_favicon_file_exists(workers[0], {})
            check(paths[0].read_bytes() == second, "Empty settings changed the existing icon.")

            def write_icon(data):
                config.ensure_custom_favicon_file_exists(
                    workers[0], {"custom_favicon_base64": base64.b64encode(data).decode("ascii")}
                )

            # Observe real concurrent file replacements, not merely a mock of os.replace.
            observations = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                writes = [pool.submit(write_icon, data) for data in (first, second) * 8]
                for _ in range(64):
                    try:
                        observed = paths[0].read_bytes()
                    except PermissionError:
                        # Windows can deny a concurrent open during an atomic replacement.
                        if os.name != "nt":
                            raise
                        continue
                    observations += 1
                    check(observed in (first, second), "A reader observed partial ICO bytes.")
                for future in writes:
                    future.result()
            check(observations > 0, "No concurrent reads were observed.")
            check(not list(paths[0].parent.glob(".favicon-*")), "Concurrent replacements leaked files.")
        print("PASS: favicon startup, independent instances, requests, and atomic failure paths")


def browser_server(app_module, settings_module, worker, path, replacement, ready_path):
    # This fixture only exists in the offline subprocess, never in production routes.
    from werkzeug.serving import make_server

    @worker.post("/_test/change")
    def change():
        save_icon(settings_module, replacement, 3)
        path.unlink()
        return "", 204

    server = make_server("127.0.0.1", 0, worker)
    Path(ready_path).write_text(str(server.server_port), encoding="ascii")
    with patch.object(app_module, "app", worker):
        server.serve_forever()


@pytest.mark.parametrize("first_module", ("app", "config"))
@pytest.mark.parametrize("optimized", (False, True))
def test_favicon_real_bootstrap_and_instance_persistence(first_module, optimized):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(APP_DIR), str(ROOT / "functional_tests")))
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + [str(Path(__file__).resolve()), "--offline-probe", first_module],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: favicon startup" in result.stdout


if __name__ == "__main__":
    sys.path.insert(0, str(APP_DIR))
    if "--browser-server" in sys.argv:
        offline_probe("config", sys.argv[-1])
    elif "--offline-probe" in sys.argv:
        offline_probe(sys.argv[-1])
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
