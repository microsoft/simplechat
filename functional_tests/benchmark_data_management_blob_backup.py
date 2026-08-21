#!/usr/bin/env python3
# benchmark_data_management_blob_backup.py
"""
Azure benchmark harness for source-blob backup transport candidates.
Version: 0.250.102
Implemented in: 0.250.102

This operator-run harness compares a serial SDK baseline, bounded parallel SDK
block transfer, Blob server-side copy, and AzCopy without printing or persisting
credentials, SAS query strings, endpoints, or source content.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

from azure.core import MatchConditions
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobBlock, ContainerClient, ContentSettings
from cryptography.fernet import Fernet


MIB = 1024 * 1024
DEFAULT_EXPECTED_BYTES = 50 * 1024 * 1024 * 1024
ENCRYPTED_MAGIC = b"SCBF1\n"
ENCRYPTED_HEADER_SIZE = 49
SERVICE_TIMEOUT_SECONDS = 120


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark SimpleChat-compatible source-blob backup transports.",
    )
    parser.add_argument(
        "--candidate",
        choices=("all", "sdk", "server-copy", "azcopy"),
        default="all",
    )
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--chunk-size-mib", type=int, default=8)
    parser.add_argument("--expected-bytes", type=int, default=DEFAULT_EXPECTED_BYTES)
    parser.add_argument("--allow-smaller", action="store_true")
    parser.add_argument("--encrypted", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def require_environment(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required benchmark environment variable is missing: {name}")
    return value


def build_container_client(url, authentication_type):
    credential = (
        DefaultAzureCredential()
        if authentication_type == "managed_identity" else
        None
    )
    return ContainerClient.from_container_url(url, credential=credential)


def append_url_path(url, suffix):
    parsed = urlsplit(url)
    path = f"{parsed.path.rstrip('/')}/{suffix.strip('/')}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def block_id(run_id, block_index):
    raw = f"{run_id[:24]}:{int(block_index):08d}".encode("ascii")
    return base64.b64encode(raw).decode("ascii")


def encode_chunk(chunk, fernet, chunk_index, total_chunks, source_version):
    if fernet is None:
        return chunk
    source_digest = hashlib.sha256(source_version.encode("utf-8")).digest()
    authenticated = (
        source_digest +
        struct.pack(
            ">QQ?",
            chunk_index,
            total_chunks,
            chunk_index == total_chunks - 1,
        ) +
        chunk
    )
    token = fernet.encrypt(authenticated)
    prefix = ENCRYPTED_MAGIC if chunk_index == 0 else b""
    return prefix + struct.pack(">I", len(token)) + token


def source_version(properties):
    payload = {
        "etag": str(getattr(properties, "etag", "") or ""),
        "last_modified": str(getattr(properties, "last_modified", "") or ""),
        "size": int(getattr(properties, "size", 0) or 0),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_range(source_blob, offset, length, etag):
    kwargs = {
        "offset": offset,
        "length": length,
        "max_concurrency": 1,
        "timeout": SERVICE_TIMEOUT_SECONDS,
    }
    if etag:
        kwargs.update({
            "etag": etag,
            "match_condition": MatchConditions.IfNotModified,
        })
    buffer = io.BytesIO()
    written = source_blob.download_blob(**kwargs).readinto(buffer)
    if written != length:
        raise RuntimeError("Source range length changed during benchmark transfer.")
    return buffer.getvalue()


def copy_blob_with_sdk(
    source_container,
    target_container,
    properties,
    target_prefix,
    chunk_size,
    fernet,
    run_id,
):
    blob_name = properties.name
    source_blob = source_container.get_blob_client(blob_name)
    target_blob = target_container.get_blob_client(f"{target_prefix}/{blob_name}")
    source_size = int(properties.size or 0)
    etag = str(properties.etag or "")
    version = source_version(properties)
    total_chunks = max(1, math.ceil(source_size / chunk_size))
    blocks = []
    artifact_bytes = 0

    if source_size == 0:
        payload = encode_chunk(b"", fernet, 0, 1, version)
        target_blob.upload_blob(
            payload,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/octet-stream"),
            timeout=SERVICE_TIMEOUT_SECONDS,
        )
        artifact_bytes = len(payload)
    else:
        for chunk_index, offset in enumerate(range(0, source_size, chunk_size)):
            length = min(chunk_size, source_size - offset)
            chunk = read_range(source_blob, offset, length, etag)
            payload = encode_chunk(
                chunk,
                fernet,
                chunk_index,
                total_chunks,
                version,
            )
            current_block_id = block_id(run_id, chunk_index)
            target_blob.stage_block(
                block_id=current_block_id,
                data=payload,
                timeout=SERVICE_TIMEOUT_SECONDS,
            )
            blocks.append(BlobBlock(block_id=current_block_id))
            artifact_bytes += len(payload)
        target_blob.commit_block_list(
            blocks,
            content_settings=ContentSettings(content_type="application/octet-stream"),
            timeout=SERVICE_TIMEOUT_SECONDS,
        )

    target_properties = target_blob.get_blob_properties()
    if int(target_properties.size or 0) != artifact_bytes:
        raise RuntimeError("Committed benchmark artifact length did not verify.")
    current_source = source_blob.get_blob_properties()
    if etag and str(current_source.etag or "") != etag:
        raise RuntimeError("Source blob changed during benchmark transfer.")
    return source_size, artifact_bytes


def run_sdk_candidate(
    source_container,
    target_container,
    properties,
    target_prefix,
    parallelism,
    chunk_size,
    fernet,
):
    run_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    source_bytes = 0
    artifact_bytes = 0
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures = [
            executor.submit(
                copy_blob_with_sdk,
                source_container,
                target_container,
                item,
                target_prefix,
                chunk_size,
                fernet,
                run_id,
            )
            for item in properties
        ]
        for future in as_completed(futures):
            copied_source_bytes, copied_artifact_bytes = future.result()
            source_bytes += copied_source_bytes
            artifact_bytes += copied_artifact_bytes
    elapsed_seconds = max(0.001, time.perf_counter() - started_at)
    return {
        "status": "completed",
        "blob_count": len(properties),
        "source_bytes": source_bytes,
        "artifact_bytes": artifact_bytes,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "bytes_per_second": round(source_bytes / elapsed_seconds, 3),
        "parallelism": parallelism,
        "chunk_size_mib": chunk_size // MIB,
    }


def copy_blob_server_side(source_container, target_container, properties, target_prefix):
    source_blob = source_container.get_blob_client(properties.name)
    target_blob = target_container.get_blob_client(f"{target_prefix}/{properties.name}")
    response = target_blob.start_copy_from_url(source_blob.url)
    copy_id = response.get("copy_id") if isinstance(response, dict) else None
    while True:
        target_properties = target_blob.get_blob_properties()
        copy = getattr(target_properties, "copy", None)
        status = str(getattr(copy, "status", "") or "").lower()
        if status == "success":
            break
        if status in {"failed", "aborted"}:
            raise RuntimeError("Blob server-side copy did not complete successfully.")
        time.sleep(0.5)
    if copy_id and str(getattr(copy, "id", "") or "") != str(copy_id):
        raise RuntimeError("Blob server-side copy identity changed before verification.")
    if int(target_properties.size or 0) != int(properties.size or 0):
        raise RuntimeError("Blob server-side copy length did not verify.")
    return int(properties.size or 0)


def run_server_copy_candidate(
    source_container,
    target_container,
    properties,
    target_prefix,
    parallelism,
):
    started_at = time.perf_counter()
    copied_bytes = 0
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures = [
            executor.submit(
                copy_blob_server_side,
                source_container,
                target_container,
                item,
                target_prefix,
            )
            for item in properties
        ]
        for future in as_completed(futures):
            copied_bytes += future.result()
    elapsed_seconds = max(0.001, time.perf_counter() - started_at)
    return {
        "status": "completed",
        "blob_count": len(properties),
        "source_bytes": copied_bytes,
        "artifact_bytes": copied_bytes,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "bytes_per_second": round(copied_bytes / elapsed_seconds, 3),
        "parallelism": parallelism,
    }


def run_azcopy_candidate(
    source_url,
    target_url,
    target_prefix,
    target_container=None,
    source_properties=None,
):
    if urlsplit(source_url).query or urlsplit(target_url).query:
        return {
            "status": "skipped",
            "reason": "AzCopy SAS URLs are disabled because command arguments are process-visible.",
        }
    executable = os.getenv("SIMPLECHAT_BLOB_BENCHMARK_AZCOPY") or shutil.which("azcopy")
    if not executable:
        return {
            "status": "skipped",
            "reason": "AzCopy executable was not configured.",
        }
    started_at = time.perf_counter()
    completed = subprocess.run(
        [
            executable,
            "copy",
            source_url,
            append_url_path(target_url, target_prefix),
            "--recursive=true",
            "--log-level=ERROR",
            "--output-type=json",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    elapsed_seconds = max(0.001, time.perf_counter() - started_at)
    if completed.returncode != 0:
        return {
            "status": "failed",
            "reason": f"AzCopy exited with code {completed.returncode}.",
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
    if target_container is None or source_properties is None:
        return {
            "status": "failed",
            "reason": "AzCopy verification inputs were not supplied.",
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
    expected_blob_count = len(source_properties)
    expected_bytes = sum(int(item.size or 0) for item in source_properties)
    copied_properties = list(
        target_container.list_blobs(name_starts_with=f"{target_prefix.strip('/')}/")
    )
    copied_blob_count = len(copied_properties)
    copied_bytes = sum(int(item.size or 0) for item in copied_properties)
    if copied_blob_count != expected_blob_count or copied_bytes != expected_bytes:
        return {
            "status": "failed",
            "reason": "AzCopy target count or length verification failed.",
            "blob_count": copied_blob_count,
            "source_bytes": expected_bytes,
            "artifact_bytes": copied_bytes,
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
    return {
        "status": "completed",
        "blob_count": copied_blob_count,
        "source_bytes": expected_bytes,
        "artifact_bytes": copied_bytes,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "bytes_per_second": round(expected_bytes / elapsed_seconds, 3),
    }


def candidate_result(name, operation):
    try:
        result = operation()
        return {"candidate": name, **result}
    except Exception as exc:
        return {
            "candidate": name,
            "status": "failed",
            "error_type": type(exc).__name__,
        }


def main():
    args = parse_args()
    parallelism = max(1, min(8, args.parallelism))
    chunk_size_mib = max(1, min(16, args.chunk_size_mib))
    chunk_size = chunk_size_mib * MIB
    authentication_type = os.getenv(
        "SIMPLECHAT_BLOB_BENCHMARK_AUTHENTICATION",
        "managed_identity",
    ).strip().lower()
    if authentication_type not in {"managed_identity", "sas"}:
        raise RuntimeError("Benchmark authentication must be managed_identity or sas.")

    source_url = require_environment("SIMPLECHAT_BLOB_BENCHMARK_SOURCE_CONTAINER_URL")
    target_url = require_environment("SIMPLECHAT_BLOB_BENCHMARK_TARGET_CONTAINER_URL")
    source_container = build_container_client(source_url, authentication_type)
    target_container = build_container_client(target_url, authentication_type)
    properties = list(source_container.list_blobs())
    source_bytes = sum(int(item.size or 0) for item in properties)
    if source_bytes < max(0, args.expected_bytes) and not args.allow_smaller:
        raise RuntimeError(
            "Benchmark source set is smaller than --expected-bytes; use --allow-smaller "
            "only for harness validation."
        )

    run_prefix = (
        f"simplechat-blob-benchmark/"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    )
    fernet = Fernet(Fernet.generate_key()) if args.encrypted else None
    results = []
    if args.candidate in {"all", "sdk"}:
        results.append(candidate_result(
            "sdk-serial-encrypted" if fernet else "sdk-serial",
            lambda: run_sdk_candidate(
                source_container,
                target_container,
                properties,
                f"{run_prefix}/sdk-serial",
                1,
                chunk_size,
                fernet,
            ),
        ))
        results.append(candidate_result(
            "sdk-bounded-encrypted" if fernet else "sdk-bounded",
            lambda: run_sdk_candidate(
                source_container,
                target_container,
                properties,
                f"{run_prefix}/sdk-bounded",
                parallelism,
                chunk_size,
                fernet,
            ),
        ))
    if args.candidate in {"all", "server-copy"}:
        if fernet:
            results.append({
                "candidate": "server-copy",
                "status": "skipped",
                "reason": "Server-side copy cannot apply SimpleChat backup encryption.",
            })
        elif authentication_type != "sas":
            results.append({
                "candidate": "server-copy",
                "status": "skipped",
                "reason": "Server-side copy requires a source URL the storage service can authorize.",
            })
        else:
            results.append(candidate_result(
                "server-copy",
                lambda: run_server_copy_candidate(
                    source_container,
                    target_container,
                    properties,
                    f"{run_prefix}/server-copy",
                    parallelism,
                ),
            ))
    if args.candidate in {"all", "azcopy"}:
        if fernet:
            results.append({
                "candidate": "azcopy",
                "status": "skipped",
                "reason": "AzCopy cannot apply SimpleChat backup encryption.",
            })
        elif authentication_type != "managed_identity":
            results.append({
                "candidate": "azcopy",
                "status": "skipped",
                "reason": "AzCopy requires managed identity so credentials are not placed in process arguments.",
            })
        else:
            results.append(candidate_result(
                "azcopy",
                lambda: run_azcopy_candidate(
                    source_url,
                    target_url,
                    f"{run_prefix}/azcopy",
                    target_container,
                    properties,
                ),
            ))

    report = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "environment": os.getenv(
            "SIMPLECHAT_BLOB_BENCHMARK_ENVIRONMENT",
            "operator-supplied",
        )[:100],
        "authentication_type": authentication_type,
        "encrypted": bool(fernet),
        "source_blob_count": len(properties),
        "source_bytes": source_bytes,
        "expected_bytes": max(0, args.expected_bytes),
        "parallelism": parallelism,
        "chunk_size_mib": chunk_size_mib,
        "results": results,
    }
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if all(result.get("status") != "failed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
