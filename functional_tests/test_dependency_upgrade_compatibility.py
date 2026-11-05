# test_dependency_upgrade_compatibility.py
"""
Functional tests for consolidated Dependabot dependency compatibility.
Version: 0.261.402
Implemented in: 0.261.402

Exercise real upgraded packages without Azure or Snowflake credentials. Fresh
processes isolate the simulated App Service typing_extensions shadowing from
other tests and exercise the asyncio backend in normal and optimized Python.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"


def run_probe(source, *, optimized=False):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["-c", textwrap.dedent(source)])
    result = subprocess.run(
        command,
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("optimized", [False, True])
def test_anyio_backend_without_typing_extensions_sentinel(optimized):
    run_probe(
        """
        import asyncio
        import socket
        import typing_extensions

        # Windows creates a loopback wakeup socketpair when constructing its event loop.
        loop = asyncio.new_event_loop()

        def block_network(*args, **kwargs):
            raise AssertionError("This compatibility probe must not access the network")

        socket.create_connection = block_network
        socket.getaddrinfo = block_network
        socket.socket.connect = block_network
        socket.socket.connect_ex = block_network
        if hasattr(typing_extensions, "sentinel"):
            del typing_extensions.sentinel

        import anyio
        import httpx
        from openai import AsyncOpenAI
        from mcp import ClientSession
        from semantic_kernel.connectors.mcp import MCPStreamableHttpPlugin

        async def exercise_backend():
            values = []

            async def append_from_thread():
                value = await anyio.to_thread.run_sync(lambda: 42)
                values.append(value)

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(append_from_thread)
            if values != [42]:
                raise AssertionError("AnyIO thread/task behavior changed")

            def respond(request):
                return httpx.Response(200, json={
                    "id": "offline-completion", "object": "chat.completion",
                    "created": 0, "model": "offline-test",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "ok"}}],
                })

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
                async with AsyncOpenAI(api_key="offline-test", http_client=http) as client:
                    response = await client.chat.completions.create(
                        model="offline-test",
                        messages=[{"role": "user", "content": "hello"}],
                    )
                    if response.choices[0].message.content != "ok":
                        raise AssertionError("OpenAI/HTTPX response handling changed")

        anyio.run(exercise_backend, backend_options={"loop_factory": lambda: loop})
        """,
        optimized=optimized,
    )


def test_pyjwt_and_redis_entra_dependency_compatibility():
    run_probe(
        """
        from importlib.metadata import requires, version
        import jwt
        from packaging.requirements import Requirement
        from redis_entraid.cred_provider import EntraIdCredentialsProvider
        from functions_redis_client import RedisManagedIdentityCredentialProvider

        constraints = [
            Requirement(item) for item in requires("redis-entraid")
            if Requirement(item).name.lower() == "pyjwt"
        ]
        if not constraints or not all(
            version("PyJWT") in item.specifier for item in constraints
        ):
            raise AssertionError("Installed redis-entraid rejects the installed PyJWT")

        key = "offline-test-signing-key-at-least-32-bytes"
        claims = {"sub": "offline-user", "oid": "offline-object", "aud": "simplechat"}
        token = jwt.encode(claims, key, algorithm="HS256")
        decoded = jwt.decode(token, key, algorithms=["HS256"], audience="simplechat")
        if decoded != claims:
            raise AssertionError("Signed JWT round-trip changed")
        try:
            jwt.decode(token, key, algorithms=["HS256"], audience="another-service")
        except jwt.InvalidAudienceError:
            pass
        else:
            raise AssertionError("JWT audience validation did not reject another service")

        class Credential:
            def get_token(self, scope):
                from types import SimpleNamespace
                return SimpleNamespace(token=token, expires_on=4102444800)

        provider = RedisManagedIdentityCredentialProvider(
            credential=Credential(), scope="https://redis.azure.com/.default"
        )
        credentials = provider.get_credentials()
        if credentials != ("offline-object", token):
            raise AssertionError("Redis Entra object-id/token extraction changed")
        """,
    )


def test_pillow_branding_conversion_with_upgraded_decoder():
    run_probe(
        """
        from io import BytesIO
        from PIL import Image, UnidentifiedImageError
        from functions_branding_images import (
            prepare_favicon_image_for_storage, prepare_logo_image_for_storage,
        )

        for image_format in ("PNG", "JPEG"):
            source = BytesIO()
            Image.new("RGB", (200, 1000), "blue").save(source, format=image_format)
            logo = prepare_logo_image_for_storage(source.getvalue(), "logo.png")
            with Image.open(BytesIO(logo["png_data"])) as result:
                result.load()
                if result.format != "PNG" or result.size != (100, 500):
                    raise AssertionError("Logo conversion or aspect ratio changed")
            favicon = prepare_favicon_image_for_storage(source.getvalue(), "favicon.png")
            with Image.open(BytesIO(favicon["ico_data"])) as result:
                result.load()
                if result.format != "ICO" or result.size != (32, 32):
                    raise AssertionError("Favicon conversion changed")

        disguised = BytesIO()
        Image.new("RGB", (32, 32)).save(disguised, format="GIF")
        for prepare in (prepare_logo_image_for_storage, prepare_favicon_image_for_storage):
            try:
                prepare(disguised.getvalue(), "renamed.png")
            except UnidentifiedImageError:
                pass
            else:
                raise AssertionError("A renamed non-PNG/JPEG bypassed the decoding allowlist")
        """,
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
