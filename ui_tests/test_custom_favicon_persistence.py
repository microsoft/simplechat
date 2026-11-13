# test_custom_favicon_persistence.py
"""
Browser regression for versioned custom favicon delivery after instance recovery.
Version: 0.261.062
Implemented in: 0.261.062

Uses the real base-template head and app favicon hook in an offline temporary
instance, without changing any deployed branding settings. Refs #1932.
"""

from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def favicon_server(tmp_path):
    ready = tmp_path / "ready.txt"
    log_path = tmp_path / "server.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((
        str(ROOT), str(ROOT / "application" / "single_app"), str(ROOT / "functional_tests"),
    ))
    env["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-B", str(ROOT / "functional_tests" / "test_custom_favicon_persistence.py"),
             "--browser-server", str(ready)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 120
            while not ready.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail("Offline favicon server did not start:\n" + log_path.read_text(encoding="utf-8"))
                time.sleep(0.1)
            yield f"http://127.0.0.1:{ready.read_text(encoding='ascii')}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.ui
def test_versioned_favicon_survives_instance_file_loss(page, favicon_server):
    response = page.goto(favicon_server, wait_until="domcontentloaded")
    assert response is not None and response.ok
    link = page.locator('link[rel="icon"]')
    initial_url = link.get_attribute("href")
    assert initial_url == "/static/images/favicon.ico?v=2"
    initial_icon = page.request.get(favicon_server + initial_url)
    initial_bytes = initial_icon.body()
    assert initial_icon.ok
    with Image.open(BytesIO(initial_bytes)) as image:
        assert image.convert("RGB").getpixel((16, 16)) == (255, 0, 0)

    changed = page.request.post(favicon_server + "/_test/change")
    assert changed.status == 204
    response = page.reload(wait_until="domcontentloaded")
    assert response is not None and response.ok
    updated_url = link.get_attribute("href")
    assert updated_url == "/static/images/favicon.ico?v=3"
    updated_icon = page.request.get(favicon_server + updated_url)
    updated_bytes = updated_icon.body()
    assert updated_icon.ok
    assert updated_bytes != initial_bytes
    with Image.open(BytesIO(updated_bytes)) as image:
        assert image.convert("RGB").getpixel((16, 16)) == (0, 0, 255)
