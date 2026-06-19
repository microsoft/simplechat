# probe_foundry_model_endpoints.py
"""Probe configured Foundry model endpoint URL and payload shapes without printing secrets."""

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT / ".venv" / ".env"
DEFAULT_PROMPT = "What is 2 plus 2? Reply with one short sentence."
APP_CONTEXT_MESSAGE = (
    "Application-provided context for the assistant. Use this as background only; "
    "the user's current request appears separately.\n"
    "Instruction memories:\n"
    "- When writing email or documents, avoid em dashes.\n"
    "- Use the user's durable response preferences unless overridden.\n"
    "Relevant facts:\n"
    "- User's name is Paul.\n"
    "- User lives in Alexandria.\n"
    "- User lives in a single floor house."
)


@dataclass
class ProbeCase:
    provider: str
    model_name: str
    url_label: str
    url: str
    key: str
    api_kind: str
    payload_variant: str
    stream: bool = False


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Missing env file: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def url_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def append_path(url: str, suffix: str) -> str:
    return url.rstrip("/") + "/" + suffix.lstrip("/")


def set_query_param(url: str, name: str, value: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if value:
        query[name] = value
    else:
        query.pop(name, None)
    return urlunparse(parsed._replace(query=urlencode(query)))


def redact_error_text(text: Any) -> str:
    rendered = json.dumps(text, default=str) if isinstance(text, (dict, list)) else str(text or "")
    rendered = rendered.replace("\r", " ").replace("\n", " ")
    return rendered[:600]


def response_summary(response: requests.Response) -> tuple[str, str, str, int | None, int | None]:
    try:
        payload = response.json()
    except ValueError:
        return "non_json", response.text[:240], "", None, None

    if response.ok:
        if isinstance(payload, dict) and "choices" in payload:
            choices = payload.get("choices") or []
            message = (choices[0] or {}).get("message") if choices else {}
            content = (message or {}).get("content") or ""
            finish_reason = (choices[0] or {}).get("finish_reason") if choices else ""
            usage = payload.get("usage") or {}
            return "ok", str(content)[:160], str(finish_reason or ""), usage.get("prompt_tokens"), usage.get("completion_tokens")
        if isinstance(payload, dict) and "output_text" in payload:
            usage = payload.get("usage") or {}
            return "ok", str(payload.get("output_text") or "")[:160], "", usage.get("input_tokens"), usage.get("output_tokens")
        if isinstance(payload, dict) and isinstance(payload.get("output"), list):
            text_parts = []
            for output_item in payload.get("output") or []:
                if not isinstance(output_item, dict):
                    continue
                for content_item in output_item.get("content") or []:
                    if not isinstance(content_item, dict):
                        continue
                    text_value = content_item.get("text") or content_item.get("output_text")
                    if isinstance(text_value, str):
                        text_parts.append(text_value)
            usage = payload.get("usage") or {}
            return "ok", "".join(text_parts)[:160], str(payload.get("status") or ""), usage.get("input_tokens"), usage.get("output_tokens")
        return "ok", redact_error_text(payload), "", None, None

    return "error", redact_error_text(payload), "", None, None


def iter_stream_response(response: requests.Response) -> tuple[str, str]:
    text_parts: list[str] = []
    final_error = ""
    try:
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            event_data = line[5:].strip()
            if event_data == "[DONE]":
                break
            try:
                payload = json.loads(event_data)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("error"):
                final_error = redact_error_text(payload.get("error"))
                break
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if choices:
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    text_parts.append(str(delta.get("content")))
                finish_reason = choices[0].get("finish_reason")
                if finish_reason and finish_reason != "stop":
                    final_error = f"finish_reason={finish_reason}; payload={redact_error_text(payload)}"
            if isinstance(payload, dict) and payload.get("output_text"):
                text_parts.append(str(payload.get("output_text")))
    finally:
        response.close()
    return "".join(text_parts), final_error


def build_chat_messages(prompt: str, variant: str) -> list[dict[str, str]]:
    if variant == "context_style_only":
        return [
            {"role": "user", "content": "Background note: Prefer concise replies and avoid em dashes."},
            {"role": "user", "content": prompt},
        ]
    if variant == "context_name_only":
        return [
            {"role": "user", "content": "Background note: The person's first name is Paul."},
            {"role": "user", "content": prompt},
        ]
    if variant == "context_plain_combined":
        return [
            {
                "role": "user",
                "content": (
                    "Background notes for this chat: first name Paul; location Alexandria; "
                    "home is single floor; prefer no em dashes.\n\n"
                    f"Message: {prompt}"
                ),
            }
        ]
    if variant == "context_system":
        return [
            {"role": "system", "content": APP_CONTEXT_MESSAGE},
            {"role": "user", "content": prompt},
        ]
    if variant == "context_user_separate":
        return [
            {"role": "user", "content": APP_CONTEXT_MESSAGE},
            {"role": "user", "content": prompt},
        ]
    if variant == "context_folded_user":
        return [
            {
                "role": "user",
                "content": (
                    f"{APP_CONTEXT_MESSAGE}\n\n"
                    "Current user request:\n"
                    f"{prompt}"
                ),
            }
        ]
    return [{"role": "user", "content": prompt}]


def build_chat_payload(model_name: str, prompt: str, variant: str, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": build_chat_messages(prompt, variant),
    }
    if stream:
        payload["stream"] = True
    if variant in {"max_tokens", "reasoning_low"}:
        payload["max_tokens"] = 32
    if variant == "reasoning_low":
        payload["reasoning_effort"] = "low"
    return payload


def build_response_payload(model_name: str, prompt: str, variant: str, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_name,
        "input": prompt,
    }
    if stream:
        payload["stream"] = True
    if variant in {"max_tokens", "reasoning_low"}:
        payload["max_output_tokens"] = 64
    if variant == "reasoning_low":
        payload["reasoning"] = {"effort": "low"}
    return payload


def run_case(case: ProbeCase, prompt: str, timeout: int) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "api-key": case.key,
    }
    payload = (
        build_response_payload(case.model_name, prompt, case.payload_variant, case.stream)
        if case.api_kind == "responses"
        else build_chat_payload(case.model_name, prompt, case.payload_variant, case.stream)
    )
    started = time.perf_counter()
    try:
        response = requests.post(case.url, headers=headers, json=payload, timeout=timeout, stream=case.stream)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if case.stream and response.ok:
            content, stream_error = iter_stream_response(response)
            status = "ok" if content and not stream_error else "empty_or_error"
            return {
                "provider": case.provider,
                "model": case.model_name,
                "url_shape": case.url_label,
                "api": case.api_kind,
                "variant": case.payload_variant,
                "stream": case.stream,
                "http": response.status_code,
                "status": status,
                "content": content[:160],
                "finish": stream_error,
                "elapsed_ms": elapsed_ms,
            }
        status, content, finish, prompt_tokens, completion_tokens = response_summary(response)
        return {
            "provider": case.provider,
            "model": case.model_name,
            "url_shape": case.url_label,
            "api": case.api_kind,
            "variant": case.payload_variant,
            "stream": case.stream,
            "http": response.status_code,
            "status": status,
            "content": content,
            "finish": finish,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "provider": case.provider,
            "model": case.model_name,
            "url_shape": case.url_label,
            "api": case.api_kind,
            "variant": case.payload_variant,
            "stream": case.stream,
            "http": None,
            "status": "exception",
            "content": redact_error_text(exc),
            "finish": "",
            "elapsed_ms": elapsed_ms,
        }


def build_cases(env: dict[str, str], include_stream: bool) -> list[ProbeCase]:
    cases: list[ProbeCase] = []
    variants = ["basic", "max_tokens", "reasoning_low"]
    stream_options = [False, True] if include_stream else [False]

    def add_chat_cases(provider: str, key: str, url_shapes: dict[str, str], model_names: list[str]) -> None:
        for model_name in model_names:
            if not model_name:
                continue
            for label, url in url_shapes.items():
                if not url:
                    continue
                for variant in variants:
                    for stream in stream_options:
                        cases.append(ProbeCase(provider, model_name, label, url, key, "chat", variant, stream))

    new_endpoint = env.get("NEW_FOUNDRY_ENDPOINT", "")
    new_origin = url_origin(new_endpoint) if new_endpoint else ""
    new_key = env.get("NEW_FOUNDRY_KEY", "")
    add_chat_cases(
        "new_foundry",
        new_key,
        {
            "env_openai_v1": env.get("NEW_FOUNDRY_COMPLETIONS_URI", ""),
            "app_project_openai_v1": append_path(new_endpoint, "openai/v1/chat/completions") if new_endpoint else "",
            "origin_openai_v1": append_path(new_origin, "openai/v1/chat/completions") if new_origin else "",
        },
        [
            env.get("NEW_FOUNDRY_DEEPSEEK_MODEL_NAME", ""),
            env.get("NEW_FOUNDRY_GROK_MODEL_NAME", ""),
            env.get("NEW_FOUNDRY_LLAMA_MODEL_NAME", ""),
        ],
    )
    if env.get("NEW_FOUNDRY_RESPONSE_URI") and env.get("NEW_FOUNDRY_OPENAI_MODEL_NAME"):
        add_chat_cases(
            "new_foundry",
            new_key,
            {
                "env_openai_v1_for_response_model": env.get("NEW_FOUNDRY_COMPLETIONS_URI", ""),
                "app_project_openai_v1_for_response_model": append_path(new_endpoint, "openai/v1/chat/completions") if new_endpoint else "",
            },
            [env.get("NEW_FOUNDRY_OPENAI_MODEL_NAME", "")],
        )
        for variant in variants:
            for stream in stream_options:
                cases.append(
                    ProbeCase(
                        "new_foundry",
                        env["NEW_FOUNDRY_OPENAI_MODEL_NAME"],
                        "env_responses",
                        env["NEW_FOUNDRY_RESPONSE_URI"],
                        new_key,
                        "responses",
                        variant,
                        stream,
                    )
                )

    classic_endpoint = env.get("CLASSIC_FOUNDRY_ENDPOINT", "")
    classic_origin = url_origin(classic_endpoint) if classic_endpoint else ""
    classic_key = env.get("CLASSIC_FOUNDRY_KEY", "")
    classic_models_url = append_path(classic_origin, "models/chat/completions") if classic_origin else ""
    if classic_models_url:
        classic_models_url = set_query_param(classic_models_url, "api-version", "2024-05-01-preview")
    add_chat_cases(
        "classic_foundry",
        classic_key,
        {
            "env_models_api_version": env.get("CLASSIC_FOUNDRY_COMPLETIONS_URI", ""),
            "app_project_openai_v1": append_path(classic_endpoint, "openai/v1/chat/completions") if classic_endpoint else "",
            "origin_models_api_version": classic_models_url,
        },
        [
            env.get("CLASSIC_FOUNDRY_DEEPSEEK_MODEL_NAME", ""),
            env.get("CLASSIC_FOUNDRY_GROK_MODEL_NAME", ""),
            env.get("CLASSIC_FOUNDRY_LLAMA_MODEL_NAME", ""),
        ],
    )
    if env.get("CLASSIC_FOUNDRY_RESPONSE_URI") and env.get("CLASSIC_FOUNDRY_OPENAI_MODEL_NAME"):
        add_chat_cases(
            "classic_foundry",
            classic_key,
            {
                "env_models_api_version_for_response_model": env.get("CLASSIC_FOUNDRY_COMPLETIONS_URI", ""),
                "app_project_openai_v1_for_response_model": append_path(classic_endpoint, "openai/v1/chat/completions") if classic_endpoint else "",
            },
            [env.get("CLASSIC_FOUNDRY_OPENAI_MODEL_NAME", "")],
        )
        for variant in variants:
            for stream in stream_options:
                cases.append(
                    ProbeCase(
                        "classic_foundry",
                        env["CLASSIC_FOUNDRY_OPENAI_MODEL_NAME"],
                        "env_responses",
                        env["CLASSIC_FOUNDRY_RESPONSE_URI"],
                        classic_key,
                        "responses",
                        variant,
                        stream,
                    )
                )
    return [case for case in cases if case.key and case.url]


def build_context_cases(env: dict[str, str], include_stream: bool) -> list[ProbeCase]:
    cases: list[ProbeCase] = []
    variants = [
        "context_style_only",
        "context_name_only",
        "context_plain_combined",
        "context_system",
        "context_user_separate",
        "context_folded_user",
    ]
    stream_options = [False, True] if include_stream else [False]

    def add_context_chat_cases(provider: str, key: str, url: str, model_names: list[str]) -> None:
        for model_name in model_names:
            if not model_name or not key or not url:
                continue
            for variant in variants:
                for stream in stream_options:
                    cases.append(ProbeCase(provider, model_name, "app_context_probe", url, key, "chat", variant, stream))

    add_context_chat_cases(
        "new_foundry",
        env.get("NEW_FOUNDRY_KEY", ""),
        env.get("NEW_FOUNDRY_COMPLETIONS_URI", ""),
        [
            env.get("NEW_FOUNDRY_DEEPSEEK_MODEL_NAME", ""),
            env.get("NEW_FOUNDRY_GROK_MODEL_NAME", ""),
            env.get("NEW_FOUNDRY_LLAMA_MODEL_NAME", ""),
        ],
    )
    add_context_chat_cases(
        "classic_foundry",
        env.get("CLASSIC_FOUNDRY_KEY", ""),
        env.get("CLASSIC_FOUNDRY_COMPLETIONS_URI", ""),
        [
            env.get("CLASSIC_FOUNDRY_DEEPSEEK_MODEL_NAME", ""),
            env.get("CLASSIC_FOUNDRY_GROK_MODEL_NAME", ""),
            env.get("CLASSIC_FOUNDRY_LLAMA_MODEL_NAME", ""),
        ],
    )
    return cases


def print_result(result: dict[str, Any]) -> None:
    content = str(result.get("content") or "").replace("|", "/")
    finish = str(result.get("finish") or "").replace("|", "/")
    print(
        " | ".join(
            [
                result.get("provider", ""),
                result.get("model", ""),
                result.get("url_shape", ""),
                result.get("api", ""),
                f"variant={result.get('variant')}",
                f"stream={result.get('stream')}",
                f"http={result.get('http')}",
                f"status={result.get('status')}",
                f"finish={finish[:220]}",
                f"content={content[:220]}",
                f"elapsed_ms={result.get('elapsed_ms')}",
            ]
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Foundry model endpoint URL and payload shapes.")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help="Path to env file with Foundry endpoints and keys.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to send to each model.")
    parser.add_argument("--timeout", type=int, default=45, help="Request timeout in seconds.")
    parser.add_argument("--include-stream", action="store_true", help="Also test streaming calls.")
    parser.add_argument("--context-shapes", action="store_true", help="Test app-provided context message shapes instead of the base matrix.")
    args = parser.parse_args()

    env = load_env_file(Path(args.env))
    cases = build_context_cases(env, include_stream=args.include_stream) if args.context_shapes else build_cases(env, include_stream=args.include_stream)
    print(f"Loaded {len(cases)} probe cases. Secrets are not printed.")
    for case in cases:
        print_result(run_case(case, args.prompt, args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())