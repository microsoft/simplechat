# test_model_catalog_token_evidence.py
"""
Offline functional tests for the complete, evidence-backed model token catalog.
Version: 0.261.122
Implemented in: 0.261.035
React V2 catalog integration: 0.261.122

Refs #1493 and PR #1497. The 2026-09-19 primary-source audit accounts for every
one of the 75 original IDs. Expected limits are explicit per ID, not inferred
from a family or calculated by adding/subtracting other limits. Additional
operation/reasoning records have separate, strict metadata-only contracts; their
historical source reviews are not new token audits. No test fetches provider
documentation, initializes application services, or calls a model.
"""

import copy
import json
import re
import unittest
from collections import Counter
from dataclasses import FrozenInstanceError
from itertools import combinations, product
from urllib.parse import urlparse

from jsonschema import ValidationError

import test_model_capability_catalog_resolution as catalog_resolution
from test_model_capability_catalog_resolution import (
    CATALOG_PATH,
    load_catalog_schema_validator,
)
from functions_embedding_policy import _catalog_policy


VERIFIED_AT = "2026-09-19"
CAPACITY_FIELDS = ("contextWindow", "inputTokenLimit", "outputTokenLimit")
PROFILE_FIELDS = (
    *CAPACITY_FIELDS, "effectiveContextWindow", "outputTokenAccounting",
    "toolReasoningEfforts",
)
AZURE_CHAT_TOOL_EFFORT_MODELS = {
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
}
TOKEN_METADATA_FIELDS = frozenset((
    *PROFILE_FIELDS, "verifiedAliases", "tokenLimitsApplicability",
    "tokenLimitEvidence", "tokenLimitProfiles",
))

AUDITED_SOURCE_IDS = {
    "openai-gpt5", "openai-gpt5-1", "openai-gpt5-6",
    "azure-openai-gpt5", "anthropic-models", "anthropic-deprecations",
    "meta-llama4", "meta-llama33", "meta-llama32-vision",
    "meta-codellama", "xai-models", "xai-grok45",
    "xai-imagine-image", "xai-imagine-video", "xai-voice",
    "microsoft-phi4-multimodal", "microsoft-phi4-mini", "microsoft-phi4-reasoning",
    "microsoft-phi35-vision", "microsoft-mai-ds-r1", "openai-reasoning",
    "azure-reasoning", "anthropic-context-windows", "anthropic-extended-thinking",
    "anthropic-batch-processing", "anthropic-models-2025-09-02", "anthropic-models-2025-05-19",
    "meta-llama-registry", "meta-codellama-config-pinned", "meta-codellama-card-pinned",
    "xai-responses-api", "xai-chat-completions-api", "xai-image-generation",
    "xai-video-generation", "xai-release-notes", "google-gemini-api",
    "google-model-metadata", "google-token-counting", "google-thinking",
    "google-deprecations", "azure-spec-gpt-5", "azure-spec-gpt-51",
    "azure-spec-gpt-52", "azure-spec-gpt-53", "azure-spec-gpt-54",
    "azure-spec-gpt-55", "azure-spec-gpt-56", "azure-spec-gpt-chat-latest",
    "anthropic-spec-fable-5", "anthropic-spec-mythos-5", "anthropic-spec-opus-5",
    "anthropic-spec-sonnet-5", "anthropic-spec-opus-4-8", "anthropic-spec-opus-4-7",
    "anthropic-spec-opus-4-6", "anthropic-spec-opus-4-5", "anthropic-spec-sonnet-4-6",
    "anthropic-spec-sonnet-4-5", "anthropic-spec-haiku-4-5", "microsoft-phi4-multimodal-config",
    "microsoft-phi4-mini-config", "microsoft-phi4-reasoning-config", "microsoft-phi4-mini-reasoning",
    "microsoft-phi4-mini-reasoning-config", "microsoft-phi35-vision-config", "microsoft-mai-ds-r1-config",
    "vertex-spec-gemini-3.8-flash", "vertex-spec-gemini-3.7-flash", "vertex-spec-gemini-3.6-flash",
    "vertex-spec-gemini-3.5-flash", "vertex-spec-gemini-3.5-flash-lite", "vertex-spec-gemini-3.1-pro-preview",
    "vertex-spec-gemini-2.5-pro", "vertex-spec-gemini-2.5-flash", "vertex-spec-gemini-2.5-flash-lite",
    "openai-spec-gpt-5.6-sol", "openai-spec-gpt-5.6-terra", "openai-spec-gpt-5.6-luna",
    "openai-spec-gpt-5.5", "openai-spec-gpt-chat-latest", "openai-spec-gpt-5.4",
    "openai-spec-gpt-5.4-pro", "openai-spec-gpt-5.4-mini", "openai-spec-gpt-5.4-nano",
    "openai-spec-gpt-5.3-codex", "openai-spec-gpt-5.2-codex", "openai-spec-gpt-5.2",
    "openai-spec-gpt-5.1", "openai-spec-gpt-5.1-codex", "openai-spec-gpt-5.1-codex-mini",
    "openai-spec-gpt-5.1-codex-max", "openai-spec-gpt-5", "openai-spec-gpt-5-pro",
    "openai-spec-gpt-5-codex", "openai-spec-gpt-5-mini", "openai-spec-gpt-5-nano",
    "xai-spec-grok-4.5", "xai-spec-grok-4.3", "xai-spec-grok-4.20-0309-reasoning",
    "xai-spec-grok-4.20-0309-non-reasoning", "xai-spec-grok-build-0.1", "xai-spec-grok-4.20-multi-agent-0309",
    "xai-spec-grok-imagine-image-quality", "xai-spec-grok-imagine-image", "xai-spec-grok-imagine-video-1.5",
    "xai-spec-grok-imagine-video", "google-spec-gemini-3.8-flash", "google-spec-gemini-3.7-flash",
    "google-spec-gemini-3.6-flash", "google-spec-gemini-3.5-flash", "google-spec-gemini-3.5-flash-lite",
    "google-spec-gemini-3.1-pro-preview", "google-spec-gemini-2.5-pro", "google-spec-gemini-2.5-flash",
    "google-spec-gemini-2.5-flash-lite", "google-spec-gemini-2.0-flash", "anthropic-model-ids",
    "anthropic-context-windows-2025-08-29", "anthropic-extended-thinking-2025-09-03", "google-generate-content",
    "google-openai-compatibility", "google-openai-cookbook", "google-generate-content-thinking-2026-02-03",
    "vertex-generation-reference", "vertex-generation-parameters", "vertex-thinking-prompting",
    "vertex-openai-compatibility",
}

# Provider, shared context, independent input, maximum generation; None is explicit.
AUDITED_NATIVE_LIMITS = {
    "gpt-5.6-sol": ("openai", 1050000, 922000, 128000),
    "gpt-5.6-terra": ("openai", 1050000, 922000, 128000),
    "gpt-5.6-luna": ("openai", 1050000, 922000, 128000),
    "gpt-5.5": ("openai", 1050000, None, 128000),
    "gpt-chat-latest": ("openai", 400000, 272000, 128000),
    "gpt-5.4": ("openai", 1050000, None, 128000),
    "gpt-5.4-pro": ("openai", 1050000, None, 128000),
    "gpt-5.4-mini": ("openai", 400000, 272000, 128000),
    "gpt-5.4-nano": ("openai", 400000, 272000, 128000),
    "gpt-5.3-codex": ("openai", 400000, 272000, 128000),
    "gpt-5.3-chat": ("openai", None, None, None),
    "gpt-5.2-codex": ("openai", 400000, 272000, 128000),
    "gpt-5.2": ("openai", 400000, None, 128000),
    "gpt-5.2-chat": ("openai", None, None, None),
    "gpt-5.1": ("openai", 400000, None, 128000),
    "gpt-5.1-chat": ("openai", None, None, None),
    "gpt-5.1-codex": ("openai", 400000, None, 128000),
    "gpt-5.1-codex-mini": ("openai", 400000, None, 128000),
    "gpt-5.1-codex-max": ("openai", 400000, None, 128000),
    "gpt-5": ("openai", 400000, 272000, 128000),
    "gpt-5-pro": ("openai", 400000, None, 272000),
    "gpt-5-codex": ("openai", 400000, 272000, 128000),
    "gpt-5-mini": ("openai", 400000, 272000, 128000),
    "gpt-5-nano": ("openai", 400000, 272000, 128000),
    "gpt-5-chat": ("openai", None, None, None),
    "claude-fable-5": ("anthropic", 1000000, None, 128000),
    "claude-mythos-5": ("anthropic", 1000000, None, 128000),
    "claude-opus-5": ("anthropic", 1000000, None, 128000),
    "claude-sonnet-5": ("anthropic", 1000000, None, 128000),
    "claude-opus-4-8": ("anthropic", 1000000, None, 128000),
    "claude-opus-4-7": ("anthropic", 1000000, None, 128000),
    "claude-opus-4-6": ("anthropic", 1000000, None, 128000),
    "claude-opus-4-5-20251101": ("anthropic", 200000, None, 64000),
    "claude-sonnet-4-6": ("anthropic", 1000000, None, 128000),
    "claude-sonnet-4-5-20250929": ("anthropic", 200000, None, 64000),
    "claude-haiku-4-5-20251001": ("anthropic", 200000, None, 64000),
    "claude-opus-4-1-20250805": ("anthropic", 200000, None, 32000),
    "claude-opus-4-20250514": ("anthropic", 200000, None, 32000),
    "claude-sonnet-4-20250514": ("anthropic", 200000, None, 64000),
    "claude-3-7-sonnet-20250219": ("anthropic", 200000, None, 64000),
    "claude-3-5-sonnet-20241022": ("anthropic", 200000, None, 8192),
    "claude-3-5-haiku-20241022": ("anthropic", 200000, None, 8192),
    "llama-4-scout-17b-16e-instruct": ("meta", 10485760, None, None),
    "llama-4-maverick-17b-128e-instruct": ("meta", 1048576, None, None),
    "llama-3.3-70b-instruct": ("meta", 131072, None, None),
    "llama-3.2-90b-vision-instruct": ("meta", 131072, None, None),
    "llama-3.2-11b-vision-instruct": ("meta", 131072, None, None),
    "codellama-70b-instruct": ("meta", None, None, None),
    "grok-4.5": ("xai", 500000, None, None),
    "grok-4.3": ("xai", 1000000, None, None),
    "grok-4.20-0309-reasoning": ("xai", 1000000, None, None),
    "grok-4.20-0309-non-reasoning": ("xai", 1000000, None, None),
    "grok-build-0.1": ("xai", 256000, None, None),
    "grok-4.20-multi-agent-0309": ("xai", 1000000, None, None),
    "grok-imagine-image-quality": ("xai", None, None, None),
    "grok-imagine-image": ("xai", None, None, None),
    "grok-imagine-video-1.5": ("xai", None, None, None),
    "grok-imagine-video": ("xai", None, None, None),
    "grok-voice-latest": ("xai", None, None, None),
    "phi-4-multimodal-instruct": ("microsoft", 131072, None, None),
    "phi-4-mini-instruct": ("microsoft", 131072, None, None),
    "phi-4-reasoning": ("microsoft", 32768, None, None),
    "phi-4-mini-reasoning": ("microsoft", 131072, None, None),
    "phi-3.5-vision-instruct": ("microsoft", 131072, None, None),
    "mai-ds-r1": ("microsoft", None, None, None),
    "gemini-3.8-flash": ("google", None, 1048576, 65536),
    "gemini-3.7-flash": ("google", None, 1048576, 65536),
    "gemini-3.6-flash": ("google", None, 1048576, 65536),
    "gemini-3.5-flash": ("google", None, 1048576, 65536),
    "gemini-3.5-flash-lite": ("google", None, 1048576, 65536),
    "gemini-3.1-pro-preview": ("google", None, 1048576, 65536),
    "gemini-2.5-pro": ("google", None, 1048576, 65536),
    "gemini-2.5-flash": ("google", None, 1048576, 65536),
    "gemini-2.5-flash-lite": ("google", None, 1048576, 65536),
    "gemini-2.0-flash": ("google", None, 1048576, 8192),
}

AUDITED_AZURE_LIMITS = {
    "gpt-5.6-sol": (1050000, 922000, 128000, "gpt-56"),
    "gpt-5.6-terra": (1050000, 922000, 128000, "gpt-56"),
    "gpt-5.6-luna": (1050000, 922000, 128000, "gpt-56"),
    "gpt-5.5": (1050000, 922000, 128000, "gpt-55"),
    "gpt-5.4": (1050000, 922000, 128000, "gpt-54"),
    "gpt-5.4-pro": (1050000, 922000, 128000, "gpt-54"),
    "gpt-5.4-mini": (400000, 272000, 128000, "gpt-54"),
    "gpt-5.4-nano": (400000, 272000, 128000, "gpt-54"),
    "gpt-5.3-codex": (400000, 272000, 128000, "gpt-53"),
    "gpt-5.3-chat": (128000, 111616, 16384, "gpt-53"),
    "gpt-5.2-codex": (400000, 272000, 128000, "gpt-52"),
    "gpt-5.2": (400000, 272000, 128000, "gpt-52"),
    "gpt-5.2-chat": (128000, 111616, 16384, "gpt-52"),
    "gpt-5.1": (400000, 272000, 128000, "gpt-51"),
    "gpt-5.1-chat": (128000, 111616, 16384, "gpt-51"),
    "gpt-5.1-codex": (400000, 272000, 128000, "gpt-51"),
    "gpt-5.1-codex-mini": (400000, 272000, 128000, "gpt-51"),
    "gpt-5.1-codex-max": (400000, 272000, 128000, "gpt-51"),
    "gpt-5": (400000, 272000, 128000, "gpt-5"),
    "gpt-5-pro": (400000, 272000, 128000, "gpt-5"),
    "gpt-5-codex": (400000, 272000, 128000, "gpt-5"),
    "gpt-5-mini": (400000, 272000, 128000, "gpt-5"),
    "gpt-5-nano": (400000, 272000, 128000, "gpt-5"),
    "gpt-5-chat": (128000, None, 16384, "gpt-5"),
}

AZURE_ONLY_CHAT_IDS = {
    "gpt-5.3-chat", "gpt-5.2-chat", "gpt-5.1-chat", "gpt-5-chat",
}
LATEST_CHAT_OLD_VERSIONS = ["2026-05-05", "2026-05-28", "2026-06-24"]
NON_TEXT_IDS = {
    "grok-imagine-image-quality", "grok-imagine-image",
    "grok-imagine-video-1.5", "grok-imagine-video",
}
CONFIGURATION_ONLY_CONTEXT = {
    "codellama-70b-instruct": 4096,
    "mai-ds-r1": 163840,
}

ANTHROPIC_SPEC_PAGES = {
    "claude-fable-5": "fable-5",
    "claude-mythos-5": "mythos-5",
    "claude-opus-5": "opus-5",
    "claude-sonnet-5": "sonnet-5",
    "claude-opus-4-8": "opus-4-8",
    "claude-opus-4-7": "opus-4-7",
    "claude-opus-4-6": "opus-4-6",
    "claude-opus-4-5-20251101": "opus-4-5",
    "claude-sonnet-4-6": "sonnet-4-6",
    "claude-sonnet-4-5-20250929": "sonnet-4-5",
    "claude-haiku-4-5-20251001": "haiku-4-5",
}
ANTHROPIC_HISTORICAL_SOURCES = {
    "claude-opus-4-1-20250805": ("anthropic-models-2025-09-02", "2026-08-05"),
    "claude-opus-4-20250514": ("anthropic-models-2025-09-02", "2026-06-15"),
    "claude-sonnet-4-20250514": ("anthropic-models-2025-09-02", "2026-06-15"),
    "claude-3-7-sonnet-20250219": ("anthropic-models-2025-05-19", "2026-02-19"),
    "claude-3-5-sonnet-20241022": ("anthropic-models-2025-05-19", "2025-10-28"),
    "claude-3-5-haiku-20241022": ("anthropic-models-2025-09-02", "2026-02-19"),
}

# These are publisher checkpoints, not an invented service-wide serving promise.
MICROSOFT_PUBLISHER_SPECS = {
    "phi-4-multimodal-instruct": (
        "Phi-4-multimodal-instruct", "microsoft-phi4-multimodal",
        "93f923e1a7727d1c4f446756212d9d3e8fcc5d81",
    ),
    "phi-4-mini-instruct": (
        "Phi-4-mini-instruct", "microsoft-phi4-mini",
        "cfbefacb99257ffa30c83adab238a50856ac3083",
    ),
    "phi-4-reasoning": (
        "Phi-4-reasoning", "microsoft-phi4-reasoning",
        "1de18ec97600877ce63dbf60c73b998da99f0195",
    ),
    "phi-4-mini-reasoning": (
        "Phi-4-mini-reasoning", "microsoft-phi4-mini-reasoning",
        "0e3b1e2d02ee478a3743abe3f629e9c0cb722e0a",
    ),
    "phi-3.5-vision-instruct": (
        "Phi-3.5-vision-instruct", "microsoft-phi35-vision",
        "12b77fb40b63a2c73c68243d3f767aab688a1b2a",
    ),
    "mai-ds-r1": (
        "MAI-DS-R1", "microsoft-mai-ds-r1",
        "a96d011a7111dcde61096468ebeeda8068735809",
    ),
}
META_REGISTRY_REVISION = "0e0b8c519242d5833d8c11bffc1232b77ad7f301"
CODELLAMA_REVISION = "397cae981dffaf5d5c9c90e89a0a75a850528b70"

VERTEX_SPEC_PAGES = {
    "gemini-3.8-flash": "3-8-flash",
    "gemini-3.7-flash": "3-7-flash",
    "gemini-3.6-flash": "3-6-flash",
    "gemini-3.5-flash": "3-5-flash",
    "gemini-3.5-flash-lite": "3-5-flash-lite",
    "gemini-3.1-pro-preview": "3-1-pro",
    "gemini-2.5-pro": "2-5-pro",
    "gemini-2.5-flash": "2-5-flash",
    "gemini-2.5-flash-lite": "2-5-flash-lite",
}
VERTEX_SOURCE_BASE = "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini"
GOOGLE_OPENAI_COOKBOOK_REVISION = "9cefb19b06ef5a7d476649bdc13bc70dea3e3c8e"
GOOGLE_ACCOUNTING_REVIEW_SOURCES = (
    "google-thinking", "google-model-metadata", "google-generate-content",
    "google-openai-compatibility", "google-openai-cookbook",
    "google-generate-content-thinking-2026-02-03",
    "vertex-generation-reference", "vertex-generation-parameters",
    "vertex-thinking-prompting", "vertex-openai-compatibility",
)
GOOGLE_ACCOUNTING_EVIDENCE = {
    "status": "unknown",
    "sourceIds": list(GOOGLE_ACCOUNTING_REVIEW_SOURCES),
    "verifiedAt": VERIFIED_AT,
    "note": (
        "The exact GenerateContent maxOutputTokens reference bounds response candidates "
        "without explicitly identifying whether hidden thoughts consume that cap. "
        "Separate candidatesTokenCount/thoughtsTokenCount usage fields do not prove "
        "inclusion or exclusion. The Google OpenAI-compatibility guide and pinned "
        "quickstart supply no explicit cap/thinking contract. Current and historical "
        "thinking guidance is qualitative; Vertex-specific parameter aliases do not "
        "prove another host's semantics. Only Interactions max_output_tokens is "
        "explicitly verified as total generation for the checked 2.5/3-series models."
    ),
}
GOOGLE_HISTORICAL_ACCOUNTING_EVIDENCE = {
    "status": "unknown",
    "sourceIds": ["google-spec-gemini-2.0-flash", *GOOGLE_ACCOUNTING_REVIEW_SOURCES],
    "verifiedAt": VERIFIED_AT,
    "note": (
        "The surviving Gemini 2.0 specification verifies a numeric output maximum, "
        "not independently verified total-generation accounting. Neither the checked "
        "parameter/compatibility references nor the historical GenerateContent thinking "
        "guide establish this retired model's exact cap/thinking contract. The later "
        "Interactions statement for 2.5/3-series models must not be backported."
    ),
}
VERTEX_ACCOUNTING_NOTE = (
    "The Vertex inference and generation-parameter references describe maximum "
    "response tokens without explicitly binding hidden thinking to maxOutputTokens. "
    "Thinking-as-Token-Output guidance is qualitative, not an exact cap contract. "
    "Compatibility parameter aliases and Interactions-only evidence must not be "
    "broadened to this protocol. Unknown does not assert exclusion of thinking."
)

VERIFIED_ALIASES = {
    "gpt-5.6-sol": ["gpt-5.6"],
    "gpt-5.5": ["gpt-5.5-2026-04-23"],
    "gpt-chat-latest": ["chat-latest"],
    "gpt-5.4": ["gpt-5.4-2026-03-05"],
    "claude-opus-4-5-20251101": ["claude-opus-4-5"],
    "claude-sonnet-4-5-20250929": ["claude-sonnet-4-5"],
    "claude-haiku-4-5-20251001": ["claude-haiku-4-5"],
    "claude-opus-4-1-20250805": ["claude-opus-4-1"],
    "claude-opus-4-20250514": ["claude-opus-4-0"],
    "claude-sonnet-4-20250514": ["claude-sonnet-4-0"],
    "claude-3-7-sonnet-20250219": ["claude-3-7-sonnet-latest"],
    "claude-3-5-sonnet-20241022": ["claude-3-5-sonnet-latest"],
    "claude-3-5-haiku-20241022": ["claude-3-5-haiku-latest"],
    "llama-4-scout-17b-16e-instruct": ["meta-llama/Llama-4-Scout-17B-16E-Instruct"],
    "llama-4-maverick-17b-128e-instruct": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct"],
    "llama-3.3-70b-instruct": ["meta-llama/Llama-3.3-70B-Instruct"],
    "llama-3.2-90b-vision-instruct": ["meta-llama/Llama-3.2-90B-Vision-Instruct"],
    "llama-3.2-11b-vision-instruct": ["meta-llama/Llama-3.2-11B-Vision-Instruct"],
    "codellama-70b-instruct": ["codellama/CodeLlama-70b-Instruct-hf"],
    "grok-4.5": ["grok-4.5-latest", "grok-build-latest"],
    "grok-4.3": ["grok-4.3-latest"],
    "grok-4.20-0309-reasoning": [
        "grok-4.20-reasoning-latest", "grok-4.20", "grok-4.20-reasoning",
        "grok-4.20-0309", "grok-4.20-beta-0309-reasoning", "grok-4.20-beta",
        "grok-4.20-beta-0309", "grok-4.20-beta-latest",
        "grok-4.20-beta-latest-reasoning", "grok-4.20-beta-reasoning",
        "grok-4.20-experimental-beta-0304-reasoning",
        "grok-4.20-experimental-beta-0304",
        "grok-4.20-experimental-beta-reasoning-latest",
        "grok-4.20-experimental-beta-latest", "grok-4.20-reasoning-gv2",
    ],
    "grok-4.20-0309-non-reasoning": [
        "grok-4.20-non-reasoning", "grok-4.20-non-reasoning-latest",
        "grok-4.20-beta-non-reasoning", "grok-4.20-beta-latest-non-reasoning",
        "grok-4.20-experimental-beta-0304-non-reasoning",
        "grok-4.20-experimental-beta-non-reasoning-latest",
        "grok-4.20-beta-0309-non-reasoning", "grok-4.20-non-reasoning-gv2",
    ],
    "grok-build-0.1": ["grok-code-fast-1", "grok-code-fast", "grok-code-fast-1-0825"],
    "grok-4.20-multi-agent-0309": [
        "grok-4.20-multi-agent", "grok-4.20-multi-agent-latest",
        "grok-4.20-multi-agent-beta-latest",
        "grok-4.20-multi-agent-experimental-beta-0304",
        "grok-4.20-multi-agent-experimental-beta-latest",
        "grok-4.20-multi-agent-beta-0309",
    ],
    "grok-imagine-image-quality": [
        "grok-imagine-image-quality-20260403", "grok-imagine-image-quality-latest",
        "grok-imagine-image-pro",
    ],
    "grok-imagine-image": ["grok-imagine-image-2026-03-02"],
    "grok-imagine-video-1.5": [
        "grok-imagine-video-1.5-preview", "grok-imagine-video-1.5-2026-05-30",
    ],
    "grok-voice-latest": ["grok-voice-think-fast-2.0"],
    "phi-4-multimodal-instruct": ["microsoft/Phi-4-multimodal-instruct"],
    "phi-4-mini-instruct": ["microsoft/Phi-4-mini-instruct"],
    "phi-4-reasoning": ["microsoft/Phi-4-reasoning"],
    "phi-4-mini-reasoning": ["microsoft/Phi-4-mini-reasoning"],
    "phi-3.5-vision-instruct": ["microsoft/Phi-3.5-vision-instruct"],
    "mai-ds-r1": ["microsoft/MAI-DS-R1"],
}

SOURCE_ADDITIONS = {
    "openai-reasoning": (
        "openai", "OpenAI reasoning and output token accounting",
        "https://developers.openai.com/api/docs/guides/reasoning",
    ),
    "azure-reasoning": (
        "azure", "Azure OpenAI reasoning models and request constraints",
        "https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning",
    ),
    "anthropic-context-windows": (
        "anthropic", "Claude shared context windows",
        "https://platform.claude.com/docs/en/build-with-claude/context-windows",
    ),
    "anthropic-extended-thinking": (
        "anthropic", "Claude thinking consumes the total max_tokens allowance",
        "https://platform.claude.com/docs/en/build-with-claude/extended-thinking",
    ),
    "anthropic-model-ids": (
        "anthropic", "Claude canonical snapshot IDs and aliases",
        "https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions",
    ),
    "anthropic-context-windows-2025-08-29": (
        "anthropic", "Archived Anthropic context and thinking accounting, 2025-08-29",
        "https://web.archive.org/web/20250829234850id_/https://docs.anthropic.com/en/docs/build-with-claude/context-windows",
    ),
    "anthropic-extended-thinking-2025-09-03": (
        "anthropic", "Archived Anthropic total-output accounting, 2025-09-03",
        "https://web.archive.org/web/20250903160242id_/https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking",
    ),
    "anthropic-batch-processing": (
        "anthropic", "Claude extended-output Message Batches beta conditions",
        "https://platform.claude.com/docs/en/build-with-claude/batch-processing#extended-output-beta",
    ),
    "anthropic-models-2025-09-02": (
        "anthropic", "Archived Anthropic-authored model overview, 2025-09-02",
        "https://web.archive.org/web/20250902222036id_/https://docs.anthropic.com/en/docs/about-claude/models/overview",
    ),
    "anthropic-models-2025-05-19": (
        "anthropic", "Archived Anthropic-authored model overview, 2025-05-19",
        "https://web.archive.org/web/20250519172951id_/https://docs.anthropic.com/en/docs/about-claude/models/overview",
    ),
    "meta-llama-registry": (
        "meta", "Meta's exact instructed-checkpoint context registry",
        "https://github.com/meta-llama/llama-models/blob/0e0b8c519242d5833d8c11bffc1232b77ad7f301/models/sku_types.py",
    ),
    "meta-codellama-config-pinned": (
        "meta", "CodeLlama 70B Instruct checkpoint configuration",
        "https://huggingface.co/codellama/CodeLlama-70b-Instruct-hf/blob/397cae981dffaf5d5c9c90e89a0a75a850528b70/config.json",
    ),
    "meta-codellama-card-pinned": (
        "meta", "CodeLlama 70B Instruct publisher card at the same revision",
        "https://huggingface.co/codellama/CodeLlama-70b-Instruct-hf/blob/397cae981dffaf5d5c9c90e89a0a75a850528b70/README.md",
    ),
    "xai-responses-api": (
        "xai", "xAI Responses total-generation cap and adjustable default",
        "https://docs.x.ai/developers/rest-api-reference/inference/responses",
    ),
    "xai-chat-completions-api": (
        "xai", "xAI Chat Completions visible-output cap and adjustable default",
        "https://docs.x.ai/developers/rest-api-reference/inference/chat-completions",
    ),
    "xai-image-generation": (
        "xai", "xAI image generation native constraints",
        "https://docs.x.ai/developers/model-capabilities/images/generation",
    ),
    "xai-video-generation": (
        "xai", "xAI video generation native constraints",
        "https://docs.x.ai/developers/model-capabilities/video/generation",
    ),
    "xai-release-notes": (
        "xai", "xAI release notes and dated voice model transitions",
        "https://docs.x.ai/developers/release-notes",
    ),
    "google-gemini-api": (
        "google", "Gemini API model documentation",
        "https://ai.google.dev/gemini-api/docs/models",
    ),
    "google-model-metadata": (
        "google", "Gemini Models API independent input/output limit semantics",
        "https://ai.google.dev/api/models",
    ),
    "google-token-counting": (
        "google", "Gemini token counting and shared context semantics",
        "https://ai.google.dev/gemini-api/docs/tokens#context-window",
    ),
    "google-thinking": (
        "google", "Gemini Interactions thinking and total-generation token limits",
        "https://ai.google.dev/gemini-api/docs/thinking#token-limits-and-max_output_tokens",
    ),
    "google-generate-content": (
        "google", "GenerateContent GenerationConfig and UsageMetadata definitions",
        "https://ai.google.dev/api/generate-content",
    ),
    "google-openai-compatibility": (
        "google", "Gemini OpenAI-compatible endpoint and reasoning configuration",
        "https://ai.google.dev/gemini-api/docs/openai",
    ),
    "google-openai-cookbook": (
        "google", "Pinned first-party OpenAI compatibility quickstart",
        "https://github.com/google-gemini/cookbook/blob/9cefb19b06ef5a7d476649bdc13bc70dea3e3c8e/quickstarts/Get_started_OpenAI_Compatibility.ipynb",
    ),
    "google-generate-content-thinking-2026-02-03": (
        "google", "Archived Google GenerateContent thinking guide, 2026-02-03",
        "https://web.archive.org/web/20260203152611id_/https://ai.google.dev/gemini-api/docs/thinking",
    ),
    "vertex-generation-reference": (
        "vertex", "Vertex generateContent and streamGenerateContent reference",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/inference",
    ),
    "vertex-generation-parameters": (
        "vertex", "Vertex maximum-output-token parameter definition",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/content-generation-parameters#maximum-output-tokens",
    ),
    "vertex-thinking-prompting": (
        "vertex", "Vertex qualitative thinking and token-output guidance",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking/prompting-guide",
    ),
    "vertex-openai-compatibility": (
        "vertex", "Vertex OpenAI compatibility and output-parameter aliases",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/migrate/openai/overview",
    ),
    "google-deprecations": (
        "google", "Gemini API model lifecycle and shutdown notices",
        "https://ai.google.dev/gemini-api/docs/deprecations",
    ),
}

SOURCE_HOSTS = {
    "developers.openai.com", "learn.microsoft.com", "platform.claude.com",
    "docs.anthropic.com", "web.archive.org", "github.com", "huggingface.co",
    "docs.x.ai", "ai.google.dev", "cloud.google.com", "docs.cloud.google.com",
    "docs.cohere.com",
}
SOURCE_PROVIDER_HOSTS = {
    "openai": {"developers.openai.com"},
    "azure": {"learn.microsoft.com"},
    "anthropic": {"platform.claude.com", "docs.anthropic.com", "web.archive.org"},
    "google": {"ai.google.dev", "github.com", "web.archive.org"},
    "vertex": {"cloud.google.com", "docs.cloud.google.com"},
    "xai": {"docs.x.ai"},
    "meta": {"github.com", "huggingface.co"},
    "microsoft": {"learn.microsoft.com", "huggingface.co"},
    "cohere": {"docs.cohere.com"},
}
GITHUB_PUBLISHER_PREFIXES = {
    "meta": "/meta-llama/llama-models/",
    "google": "/google-gemini/cookbook/",
}
ARCHIVE_ORIGIN_PREFIXES = {
    "anthropic": "https://docs.anthropic.com/",
    "google": "https://ai.google.dev/",
}


def validate_catalog_integrity(catalog):
    """Validate cross-record invariants that JSON Schema cannot express."""
    sources = {}
    for source in catalog["sources"]:
        source_id = source["id"]
        if source_id in sources:
            raise ValueError(f"Duplicate source ID: {source_id}")
        sources[source_id] = source
        parsed = urlparse(source["url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname not in SOURCE_HOSTS
            or parsed.username
            or parsed.password
        ):
            raise ValueError(f"Not a public primary-source URL: {source_id}")
        if parsed.hostname not in SOURCE_PROVIDER_HOSTS.get(source["provider"], set()):
            raise ValueError(f"Source publisher and URL disagree: {source_id}")
        if source["verifiedAt"] > catalog["lastUpdated"]:
            raise ValueError(f"Source is newer than catalog: {source_id}")
        if parsed.hostname == "github.com":
            prefix = GITHUB_PUBLISHER_PREFIXES.get(source["provider"])
            if not prefix or not parsed.path.startswith(prefix):
                raise ValueError(f"Not the publisher's repository: {source_id}")
        if parsed.hostname == "huggingface.co":
            owner = parsed.path.split("/")[1]
            if owner not in {"meta-llama", "codellama", "microsoft"}:
                raise ValueError(f"Not a publisher-owned model card: {source_id}")
        if parsed.hostname == "web.archive.org":
            original = source.get("archivedFrom", "")
            prefix = ARCHIVE_ORIGIN_PREFIXES.get(source["provider"])
            if not prefix or not original.startswith(prefix):
                raise ValueError(f"Archive lacks first-party authorship: {source_id}")
            if not source["url"].endswith(original):
                raise ValueError(f"Archive and original disagree: {source_id}")

    embedding_identities = {}
    for model in catalog["models"]:
        if "embeddingPolicy" not in model:
            continue
        for identity in (model["id"], *model.get("aliases", [])):
            normalized = re.sub(r"[\s_.]+", "-", identity.strip().lower())
            owner = embedding_identities.setdefault(normalized, model["id"])
            if owner != model["id"]:
                raise ValueError(f"Ambiguous embedding identity: {identity}")

    model_ids = set()
    identities = {}
    for model in catalog["models"]:
        model_id = model["id"]
        if model_id in model_ids:
            raise ValueError(f"Duplicate model ID: {model_id}")
        model_ids.add(model_id)
        for identity in (model_id, *model.get("aliases", []), *model.get("verifiedAliases", [])):
            normalized = re.sub(r"[\s_.]+", "-", identity.strip().lower())
            embedding_owner = embedding_identities.get(normalized)
            if embedding_owner is not None and embedding_owner != model_id:
                raise ValueError(f"Ambiguous embedding identity: {identity}")
        for identity in (model_id, *model.get("verifiedAliases", [])):
            normalized = re.sub(r"[\s_.]+", "-", identity.strip().lower())
            owner = identities.setdefault(normalized, model_id)
            if owner != model_id:
                raise ValueError(f"Ambiguous verified identity: {identity}")
        for source_id in model.get("sourceIds", []):
            if source_id not in sources:
                raise ValueError(f"Unresolved model source: {model_id}/{source_id}")

        embeds = model.get("capabilities", {}).get("generatesEmbeddings") is True
        if embeds != ("embeddingPolicy" in model):
            raise ValueError(f"Embedding operation and policy disagree: {model_id}")
        if embeds:
            embedding_policy = _catalog_policy(model["embeddingPolicy"])
            for version_policy in embedding_policy.get("versions", {}).values():
                _catalog_policy({**embedding_policy, **version_policy})

        policy = model.get("reasoningPolicy")
        if policy is not None:
            for source_id in policy["sourceIds"]:
                if source_id not in sources:
                    raise ValueError(f"Unresolved reasoning source: {model_id}/{source_id}")
            if policy["status"] == "supported" and policy["default_effort"] not in policy["efforts"]:
                raise ValueError(f"Reasoning fallback is not a supported effort: {model_id}")

        if "tokenLimitEvidence" not in model:
            if TOKEN_METADATA_FIELDS.intersection(model):
                raise ValueError(f"Unevidenced token metadata: {model_id}")
            continue

        profiles = model.get("tokenLimitProfiles", [])
        profile_ids = [profile["id"] for profile in profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError(f"Duplicate profile ID: {model_id}")
        for scope in (model, *profiles):
            scope_id = scope["id"]
            fields = set(PROFILE_FIELDS).intersection(scope)
            evidence_fields = set(scope["tokenLimitEvidence"])
            if fields != evidence_fields:
                raise ValueError(f"Evidence does not cover exact fields: {scope_id}")
            for field, evidence in scope["tokenLimitEvidence"].items():
                for source_id in evidence["sourceIds"]:
                    if source_id not in sources or source_id not in model["sourceIds"]:
                        raise ValueError(f"Unresolved evidence source: {scope_id}/{source_id}")
                if evidence["verifiedAt"] > catalog["lastUpdated"]:
                    raise ValueError(f"Evidence is newer than catalog: {scope_id}/{field}")

            for field in (*CAPACITY_FIELDS, "effectiveContextWindow"):
                value = scope.get(field)
                if value is not None and (type(value) is not int or value <= 0):
                    raise ValueError(f"Not a positive true integer: {scope_id}/{field}")
            context = scope.get("contextWindow")
            if context is not None:
                for field in ("inputTokenLimit", "outputTokenLimit", "effectiveContextWindow"):
                    value = scope.get(field)
                    if value is not None and value > context:
                        raise ValueError(f"Capacity exceeds shared context: {scope_id}/{field}")
            if model["tokenLimitsApplicability"] == "non-text":
                if scope.get("outputTokenLimit") is not None:
                    raise ValueError(f"Non-text output became a chat budget: {scope_id}")

        for left, right in combinations(profiles, 2):
            if left["provider"] != right["provider"]:
                continue
            left_specificity = int("protocol" in left) + int("modelVersions" in left)
            right_specificity = int("protocol" in right) + int("modelVersions" in right)
            if left_specificity != right_specificity:
                continue
            protocols_overlap = (
                "protocol" not in left or "protocol" not in right
                or left["protocol"] == right["protocol"]
            )
            versions_overlap = (
                "modelVersions" not in left or "modelVersions" not in right
                or bool(set(left["modelVersions"]).intersection(right["modelVersions"]))
            )
            if protocols_overlap and versions_overlap:
                raise ValueError(f"Equally specific profiles overlap: {model_id}")


class TestModelCatalogTokenEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.models = {model["id"]: model for model in cls.catalog["models"]}
        cls.audited_models = {
            model_id: model for model_id, model in cls.models.items()
            if model_id in AUDITED_NATIVE_LIMITS
        }
        cls.sources = {source["id"]: source for source in cls.catalog["sources"]}
        cls.validator = load_catalog_schema_validator()

    def test_all_75_exact_dispositions(self):
        self.assertEqual(set(self.audited_models), set(AUDITED_NATIVE_LIMITS))
        counts = Counter(model["provider"] for model in self.audited_models.values())
        self.assertEqual(
            counts,
            {"openai": 25, "anthropic": 17, "google": 10, "meta": 6, "microsoft": 6, "xai": 11},
        )
        for model_id, expected in AUDITED_NATIVE_LIMITS.items():
            with self.subTest(model=model_id):
                model = self.models[model_id]
                actual = (model["provider"], *(model[field] for field in CAPACITY_FIELDS))
                self.assertEqual(actual, expected)
                self.assertEqual(model["verifiedAliases"], VERIFIED_ALIASES.get(model_id, []))
                expected_applicability = (
                    "non-text" if model_id in NON_TEXT_IDS
                    else "unknown" if model_id == "grok-voice-latest"
                    else "text"
                )
                self.assertEqual(model["tokenLimitsApplicability"], expected_applicability)
                for field in CAPACITY_FIELDS:
                    evidence = model["tokenLimitEvidence"][field]
                    self.assertEqual(evidence["verifiedAt"], VERIFIED_AT)
                    if model[field] is not None:
                        self.assertIs(type(model[field]), int)
                        self.assertGreater(model[field], 0)
                        self.assertEqual(evidence["status"], "verified")
                    else:
                        self.assertNotEqual(evidence["status"], "verified")

    def test_schema_and_cross_record_integrity(self):
        self.validator.validate(self.catalog)
        validate_catalog_integrity(self.catalog)
        self.assertIn("google-gemini-api", self.sources)
        self.assertTrue(AUDITED_SOURCE_IDS.issubset(self.sources))
        for source_id in AUDITED_SOURCE_IDS:
            with self.subTest(source=source_id):
                self.assertEqual(self.sources[source_id]["verifiedAt"], VERIFIED_AT)

    def test_public_source_registry_matches_the_audited_urls(self):
        for source_id, (provider, _title, url) in SOURCE_ADDITIONS.items():
            with self.subTest(source=source_id):
                self.assertEqual(self.sources[source_id]["provider"], provider)
                self.assertEqual(self.sources[source_id]["url"], url)
        for model_id, page in VERTEX_SPEC_PAGES.items():
            with self.subTest(model=model_id):
                source = self.sources[f"vertex-spec-{model_id}"]
                self.assertEqual(source["provider"], "vertex")
                self.assertEqual(source["url"], f"{VERTEX_SOURCE_BASE}/{page}")

    def test_published_native_limits_reference_the_exact_model(self):
        for model_id, model in self.audited_models.items():
            provider = model["provider"]
            source_id = None
            if provider == "openai" and model_id not in AZURE_ONLY_CHAT_IDS:
                source_id = f"openai-spec-{model_id}"
                native_id = "chat-latest" if model_id == "gpt-chat-latest" else model_id
                self.assertTrue(self.sources[source_id]["url"].endswith(f"/{native_id}"))
            elif provider == "anthropic":
                source_id = (
                    f"anthropic-spec-{ANTHROPIC_SPEC_PAGES[model_id]}"
                    if model_id in ANTHROPIC_SPEC_PAGES
                    else ANTHROPIC_HISTORICAL_SOURCES[model_id][0]
                )
            elif provider == "google":
                source_id = f"google-spec-{model_id}"
                self.assertTrue(self.sources[source_id]["url"].endswith(f"/{model_id}"))
            elif provider == "xai" and model["tokenLimitsApplicability"] == "text":
                source_id = f"xai-spec-{model_id}"
                self.assertTrue(self.sources[source_id]["url"].endswith(f"/{model_id}"))
            elif provider == "meta" and model_id not in CONFIGURATION_ONLY_CONTEXT:
                source_id = "meta-llama-registry"
            elif provider == "microsoft":
                source_id = f"{MICROSOFT_PUBLISHER_SPECS[model_id][1]}-config"
            for field in CAPACITY_FIELDS:
                if model[field] is not None:
                    with self.subTest(model=model_id, field=field):
                        self.assertIsNotNone(source_id)
                        self.assertIn(source_id, model["tokenLimitEvidence"][field]["sourceIds"])

    def test_azure_profiles_keep_native_and_host_limits_separate(self):
        for model_id, expected in AUDITED_AZURE_LIMITS.items():
            with self.subTest(model=model_id):
                profiles = self.models[model_id]["tokenLimitProfiles"]
                generic = [
                    profile for profile in profiles
                    if profile["provider"] == "azure"
                    and "protocol" not in profile and "modelVersions" not in profile
                ]
                self.assertEqual(len(generic), 1)
                profile = generic[0]
                self.assertEqual(tuple(profile[field] for field in CAPACITY_FIELDS), expected[:3])
                source_id = f"azure-spec-{expected[3]}"
                for field in CAPACITY_FIELDS:
                    self.assertIn(source_id, profile["tokenLimitEvidence"][field]["sourceIds"])
        self.assertEqual(self.models["gpt-5-pro"]["outputTokenLimit"], 272000)
        for model_id in AZURE_ONLY_CHAT_IDS:
            model = self.models[model_id]
            for field in CAPACITY_FIELDS:
                self.assertEqual(model["tokenLimitEvidence"][field]["status"], "hosting-dependent")
            self.assertTrue(any("retired" in note.lower() and "Azure" in note for note in model["notes"]))

    def test_native_openai_input_limits_require_their_own_published_evidence(self):
        for model_id in (
            "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex", "gpt-5.2-codex",
            "gpt-5", "gpt-5-codex", "gpt-5-mini", "gpt-5-nano",
        ):
            with self.subTest(model=model_id):
                model = self.models[model_id]
                evidence = model["tokenLimitEvidence"]["inputTokenLimit"]
                self.assertEqual(model["inputTokenLimit"], 272000)
                self.assertEqual(evidence["status"], "verified")
                self.assertEqual(evidence["sourceIds"], [f"openai-spec-{model_id}"])
                self.assertIn("explicitly publishes Maximum input tokens", evidence["note"])
        for model_id in (
            "gpt-5.5", "gpt-5.4", "gpt-5.4-pro", "gpt-5.2", "gpt-5.1",
            "gpt-5.1-codex", "gpt-5.1-codex-mini", "gpt-5.1-codex-max", "gpt-5-pro",
        ):
            with self.subTest(model=model_id):
                model = self.models[model_id]
                self.assertIsNone(model["inputTokenLimit"])
                self.assertEqual(model["tokenLimitEvidence"]["inputTokenLimit"]["status"], "unknown")

    def test_tool_effort_constraints_are_evidenced_and_exactly_scoped(self):
        constrained = set()
        for model_id, model in self.audited_models.items():
            self.assertNotIn("toolReasoningEfforts", model)
            for profile in model.get("tokenLimitProfiles", []):
                if "toolReasoningEfforts" not in profile:
                    continue
                with self.subTest(model=model_id, profile=profile["id"]):
                    constrained.add(model_id)
                    self.assertEqual(profile["provider"], "azure")
                    self.assertEqual(profile["protocol"], "chat_completions")
                    self.assertNotIn("modelVersions", profile)
                    self.assertEqual(profile["toolReasoningEfforts"], ["none"])
                    self.assertEqual(profile["outputTokenAccounting"], "total_generation")
                    evidence = profile["tokenLimitEvidence"]["toolReasoningEfforts"]
                    self.assertEqual(evidence["status"], "verified")
                    self.assertEqual(evidence["verifiedAt"], VERIFIED_AT)
                    self.assertEqual(
                        set(evidence["sourceIds"]),
                        {"azure-spec-gpt-56", "azure-reasoning"},
                    )
                    self.assertIn(model_id, evidence["note"])
                    self.assertIn("explicit", evidence["note"])
        self.assertEqual(constrained, AZURE_CHAT_TOOL_EFFORT_MODELS)

    def test_real_budget_exposes_tool_effort_constraints_without_family_inference(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id in AZURE_CHAT_TOOL_EFFORT_MODELS:
            for provider, protocol, expected_efforts in (
                ("azure", "chat_completions", ("none",)),
                ("azure", "responses", ()),
                ("openai", "chat_completions", ()),
            ):
                with self.subTest(model=model_id, provider=provider, protocol=protocol):
                    budget = capabilities.resolve_model_token_budget(
                        {"modelName": model_id},
                        provider=provider,
                        protocol=protocol,
                        request_output_limit=4096,
                    )
                    self.assertIsInstance(budget, capabilities.ModelTokenBudget)
                    self.assertEqual(budget.tool_reasoning_efforts, expected_efforts)
                    self.assertEqual(budget.output_accounting, "total_generation")
                    self.assertEqual(budget.context_window, 1050000)
                    self.assertEqual(budget.input_limit, 922000)
                    self.assertEqual(budget.output_limit, 128000)
                    self.assertEqual(budget.request_output_limit, 4096)
                    self.assertEqual(budget.model_id, model_id)
                    self.assertEqual(budget.provider, provider)
                    self.assertEqual(budget.protocol, protocol)
                    self.assertTrue(budget.provenance)
                    with self.assertRaises(FrozenInstanceError):
                        budget.tool_reasoning_efforts = ()
        for model_id in ("gpt-5.5", "gpt-5.6-unverified"):
            budget = capabilities.resolve_model_token_budget(
                {"modelName": model_id},
                provider="azure",
                protocol="chat_completions",
                request_output_limit=4096,
            )
            self.assertEqual(budget.tool_reasoning_efforts, ())

    def test_unversioned_azure_tiers_keep_tool_rules_and_default_capacities(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id, identifier_field, version_fields in product(
            AZURE_CHAT_TOOL_EFFORT_MODELS,
            ("modelName", "deploymentName"),
            ({}, {"modelVersion": None}, {"modelVersion": ""}),
        ):
            with self.subTest(model=model_id, identifier=identifier_field, version=version_fields):
                budget = capabilities.resolve_model_token_budget(
                    {identifier_field: model_id, **version_fields},
                    provider="azure",
                    protocol="chat_completions",
                    request_output_limit=4096,
                )
                self.assertFalse(budget.model_version)
                self.assertEqual(budget.model_id, model_id)
                self.assertEqual(budget.tool_reasoning_efforts, ("none",))
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit),
                    (1050000, 922000, 128000),
                )
                self.assertEqual(budget.output_accounting, "total_generation")

    def test_dated_azure_tool_constraints_survive_partial_capacity_overrides(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id in AZURE_CHAT_TOOL_EFFORT_MODELS:
            for override in ({"contextWindow": 1000000}, {"outputTokenLimit": 4096}):
                with self.subTest(model=model_id, override=override):
                    budget = capabilities.resolve_model_token_budget(
                        {
                            "modelName": model_id,
                            "modelVersion": "2026-07-09",
                            **override,
                        },
                        provider="azure",
                        protocol="chat_completions",
                        request_output_limit=4096,
                    )
                    self.assertEqual(budget.provider, "azure")
                    self.assertEqual(budget.protocol, "chat_completions")
                    self.assertEqual(budget.model_version, "2026-07-09")
                    self.assertEqual(budget.tool_reasoning_efforts, ("none",))
                    self.assertEqual(budget.input_limit, 922000)
                    self.assertEqual(budget.context_window, override.get("contextWindow", 1050000))
                    self.assertEqual(budget.output_limit, override.get("outputTokenLimit", 128000))
                    self.assertEqual(budget.output_accounting, "total_generation")

    def test_native_and_scoped_output_accounting_remains_distinct(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id, provider, protocol, expected in (
            ("gpt-5-pro", "openai", "responses", "total_generation"),
            ("gpt-5-pro", "azure", "responses", "total_generation"),
            ("claude-sonnet-4-6", "anthropic", "messages", "total_generation"),
            ("grok-4.5", "xai", "responses", "total_generation"),
            ("grok-4.5", "xai", "chat_completions", "visible_only"),
        ):
            with self.subTest(model=model_id, provider=provider, protocol=protocol):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": model_id}, provider=provider, protocol=protocol,
                )
                self.assertEqual(budget.output_accounting, expected)
        for provider, expected_context in (("google", None), ("vertex", 1048576)):
            budget = capabilities.resolve_model_token_budget(
                {"modelName": "gemini-2.5-pro"},
                provider=provider,
                protocol="generate_content",
            )
            self.assertEqual(budget.context_window, expected_context)
            self.assertEqual(budget.input_limit, 1048576)
            self.assertEqual(budget.output_limit, 65536)
        retired = capabilities.resolve_model_token_budget(
            {"modelName": "gemini-2.0-flash"},
            provider="google",
            protocol="generate_content",
        )
        self.assertIsNone(retired.context_window)
        self.assertEqual(retired.input_limit, 1048576)
        self.assertEqual(retired.output_limit, 8192)

    def test_latest_chat_requires_an_audited_azure_version(self):
        model = self.models["gpt-chat-latest"]
        profiles = {profile["id"]: profile for profile in model["tokenLimitProfiles"]}
        unknown = profiles["azure-version-unknown"]
        self.assertNotIn("modelVersions", unknown)
        self.assertEqual(tuple(unknown[field] for field in CAPACITY_FIELDS), (None, None, None))
        for field in CAPACITY_FIELDS:
            self.assertEqual(unknown["tokenLimitEvidence"][field]["status"], "unknown")
        older = profiles["azure-2026-05-05-through-2026-06-24"]
        self.assertEqual(older["modelVersions"], LATEST_CHAT_OLD_VERSIONS)
        self.assertEqual(tuple(older[field] for field in CAPACITY_FIELDS), (128000, 111616, 16384))
        newer = profiles["azure-2026-08-06"]
        self.assertEqual(newer["modelVersions"], ["2026-08-06"])
        self.assertEqual(tuple(newer[field] for field in CAPACITY_FIELDS), (400000, 272000, 128000))
        self.assertNotIn("gpt-5.5-instant", model["verifiedAliases"])
        self.assertIn("gpt-5.5-instant", model["aliases"])

    def test_latest_chat_documents_distinct_provider_request_ids(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        source = self.sources["openai-spec-gpt-chat-latest"]
        self.assertEqual(source["url"], "https://developers.openai.com/api/docs/models/chat-latest")
        self.assertIn("gpt-chat-latest is Azure's API name", " ".join(source["notes"]))
        self.assertIn(
            "logical cross-provider catalog record",
            " ".join(self.models["gpt-chat-latest"]["notes"]),
        )
        model = {"modelName": "chat-latest"}
        budget = capabilities.resolve_model_token_budget(
            model, provider="openai", protocol="responses",
        )
        self.assertEqual(model["modelName"], "chat-latest")
        self.assertEqual(budget.provider, "openai")
        self.assertEqual(budget.context_window, 400000)
        self.assertEqual(budget.input_limit, 272000)
        self.assertEqual(budget.output_limit, 128000)

    def test_azure_latest_chat_does_not_inherit_unversioned_tier_defaults(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        unknown_versions = (
            {}, {"modelVersion": None}, {"modelVersion": ""},
            {"modelVersion": "2026-07-09"},
        )
        for protocol, version_fields in product(
            ("chat_completions", "responses"), unknown_versions
        ):
            with self.subTest(protocol=protocol, version=version_fields):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": "gpt-chat-latest", **version_fields},
                    provider="azure",
                    protocol=protocol,
                    request_output_limit=4096,
                )
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit),
                    (None, None, None),
                )
        known_versions = [
            (version, (128000, 111616, 16384))
            for version in LATEST_CHAT_OLD_VERSIONS
        ]
        known_versions.append(("2026-08-06", (400000, 272000, 128000)))
        for protocol, (version, expected) in product(
            ("chat_completions", "responses"), known_versions
        ):
            with self.subTest(protocol=protocol, version=version):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": "gpt-chat-latest", "modelVersion": version},
                    provider="azure",
                    protocol=protocol,
                    request_output_limit=4096,
                )
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit),
                    expected,
                )

    def test_azure_responses_effective_ceiling_remains_approximate(self):
        profiles = self.models["gpt-5.5"]["tokenLimitProfiles"]
        matching = [profile for profile in profiles if "effectiveContextWindow" in profile]
        self.assertEqual(len(matching), 1)
        profile = matching[0]
        self.assertEqual(profile["provider"], "azure")
        self.assertEqual(profile["protocol"], "responses")
        self.assertEqual(profile["effectiveContextWindow"], 922000)
        note = profile["tokenLimitEvidence"]["effectiveContextWindow"]["note"].lower()
        self.assertIn("approx", note)
        self.assertIn("combined", note)
        self.assertIn("margin", note)
        self.assertEqual(self.models["gpt-5.5"]["contextWindow"], 1050000)

    def test_claude_context_and_synchronous_output_are_not_beta_limits(self):
        for model_id, model in self.audited_models.items():
            if model["provider"] != "anthropic":
                continue
            with self.subTest(model=model_id):
                self.assertIsNone(model["inputTokenLimit"])
                self.assertEqual(model["tokenLimitEvidence"]["inputTokenLimit"]["status"], "unknown")
                self.assertEqual(model["outputTokenAccounting"], "total_generation")
                self.assertLessEqual(model["outputTokenLimit"], 128000)
                if model_id in ANTHROPIC_HISTORICAL_SOURCES:
                    source_id, retired_at = ANTHROPIC_HISTORICAL_SOURCES[model_id]
                    self.assertIn(source_id, model["tokenLimitEvidence"]["contextWindow"]["sourceIds"])
                    self.assertIn(source_id, model["tokenLimitEvidence"]["outputTokenLimit"]["sourceIds"])
                    self.assertIn(retired_at, " ".join(model["notes"]))
                    self.assertIn("Claude API", " ".join(model["notes"]))
                    self.assertEqual(
                        self.sources[source_id]["archivedFrom"],
                        "https://docs.anthropic.com/en/docs/about-claude/models/overview",
                    )

    def test_historical_claude_aliases_preserve_snapshot_provenance(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id, (source_id, _retired_at) in ANTHROPIC_HISTORICAL_SOURCES.items():
            model = self.models[model_id]
            self.assertIn(source_id, model["sourceIds"])
            self.assertIn("Historical aliases", " ".join(model["notes"]))
            for alias in VERIFIED_ALIASES[model_id]:
                with self.subTest(model=model_id, alias=alias):
                    budget = capabilities.resolve_model_token_budget(
                        {"modelName": alias}, provider="anthropic", protocol="messages",
                    )
                    self.assertEqual(budget.model_id, model_id)
                    self.assertEqual(budget.context_window, model["contextWindow"])
                    self.assertEqual(budget.output_limit, model["outputTokenLimit"])
                    self.assertIsNone(budget.input_limit)
                    self.assertEqual(budget.output_accounting, "total_generation")
            accounting = model["tokenLimitEvidence"]["outputTokenAccounting"]
            self.assertIn("anthropic-context-windows-2025-08-29", accounting["sourceIds"])
            self.assertIn("anthropic-extended-thinking-2025-09-03", accounting["sourceIds"])
        for model_id in (
            "claude-fable-5", "claude-mythos-5", "claude-opus-5", "claude-sonnet-5",
            "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
        ):
            self.assertEqual(self.models[model_id]["verifiedAliases"], [])
            self.assertIn("anthropic-model-ids", self.models[model_id]["sourceIds"])

    def test_google_independent_limits_do_not_invent_shared_context(self):
        for model_id, model in self.audited_models.items():
            if model["provider"] != "google":
                continue
            with self.subTest(model=model_id):
                self.assertIsNone(model["contextWindow"])
                self.assertEqual(model["inputTokenLimit"], 1048576)
                self.assertIn("google-model-metadata", model["sourceIds"])
                self.assertIn("google-deprecations", model["sourceIds"])
                if model_id in VERTEX_SPEC_PAGES:
                    vertex = [
                        profile for profile in model["tokenLimitProfiles"]
                        if profile["provider"] == "vertex"
                    ]
                    self.assertEqual(len(vertex), 1)
                    self.assertEqual(vertex[0]["contextWindow"], 1048576)
                    self.assertEqual(vertex[0]["outputTokenLimit"], 65536)
                    self.assertEqual(vertex[0]["outputTokenAccounting"], "unknown")
                    self.assertIn(
                        f"vertex-spec-{model_id}",
                        vertex[0]["tokenLimitEvidence"]["contextWindow"]["sourceIds"],
                    )
                    self.assertIn(
                        f"vertex-spec-{model_id}",
                        vertex[0]["tokenLimitEvidence"]["outputTokenLimit"]["sourceIds"],
                    )
                    self.assertNotEqual(
                        vertex[0]["contextWindow"],
                        model["inputTokenLimit"] + model["outputTokenLimit"],
                    )
                else:
                    self.assertNotIn("tokenLimitProfiles", model)
                    self.assertEqual(model["outputTokenLimit"], 8192)
                    self.assertIn("2026-06-01", " ".join(model["notes"]))
        self.assertNotIn("gemini-3.1-pro", self.models["gemini-3.1-pro-preview"]["verifiedAliases"])
        for model_id in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"):
            notes = " ".join(self.models[model_id]["tokenLimitProfiles"][0]["notes"])
            self.assertIn("2026-10-20", notes)
            self.assertIn("Vertex", notes)
            self.assertIn("no announced shutdown", " ".join(self.models[model_id]["notes"]))

    def test_google_accounting_does_not_broaden_interactions_evidence(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id, model in self.audited_models.items():
            if model["provider"] != "google":
                continue
            expected_evidence = (
                GOOGLE_HISTORICAL_ACCOUNTING_EVIDENCE
                if model_id == "gemini-2.0-flash"
                else GOOGLE_ACCOUNTING_EVIDENCE
            )
            self.assertEqual(model["outputTokenAccounting"], "unknown")
            self.assertEqual(model["tokenLimitEvidence"]["outputTokenAccounting"], expected_evidence)
            for provider, protocol in product(
                ("google", "vertex"), ("generate_content", "chat_completions")
            ):
                with self.subTest(model=model_id, provider=provider, protocol=protocol):
                    budget = capabilities.resolve_model_token_budget(
                        {"modelName": model_id},
                        provider=provider,
                        protocol=protocol,
                        request_output_limit=4096,
                    )
                    self.assertEqual(budget.output_accounting, "unknown")
                    with self.assertRaises(capabilities.ModelTokenBudgetError) as raised:
                        budget.remaining_input()
                    self.assertEqual(raised.exception.code, "model_generation_unbounded")
            for profile in model.get("tokenLimitProfiles", []):
                self.assertEqual(profile["protocol"], "generate_content")
                accounting = profile["tokenLimitEvidence"]["outputTokenAccounting"]
                self.assertEqual(accounting["status"], "unknown")
                self.assertEqual(accounting["note"], VERTEX_ACCOUNTING_NOTE)

    def test_google_operator_accounting_does_not_change_native_evidence(self):
        """A caller-declared contract is not new verification of provider facts."""
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        records = capabilities.get_model_capability_catalog_records()
        native_record = next(record for record in records if record["id"] == "gemini-3.8-flash")
        original_record = copy.deepcopy(native_record)
        for override_scope, protocol in product(
            ("model", "endpoint"), ("generate_content", "chat_completions")
        ):
            with self.subTest(override_scope=override_scope, protocol=protocol):
                model = {"modelName": "gemini-3.8-flash"}
                endpoint = {}
                target = model if override_scope == "model" else endpoint
                target["outputTokenAccounting"] = "total_generation"
                budget = capabilities.resolve_model_token_budget(
                    model,
                    endpoint,
                    provider="google",
                    protocol=protocol,
                    request_output_limit=4096,
                )
                self.assertEqual(budget.output_accounting, "total_generation")
                self.assertIsNone(budget.context_window)
                remaining = budget.remaining_input(1000)
                self.assertEqual(remaining, 1048576 - 1000)
                self.assertEqual(native_record, original_record)
                self.assertEqual(native_record["outputTokenAccounting"], "unknown")
                self.assertEqual(
                    native_record["tokenLimitEvidence"]["outputTokenAccounting"]["status"],
                    "unknown",
                )
                unconfigured = capabilities.resolve_model_token_budget(
                    {"modelName": "gemini-3.8-flash"},
                    provider="google",
                    protocol=protocol,
                    request_output_limit=4096,
                )
                self.assertEqual(unconfigured.output_accounting, "unknown")

    def test_google_unknown_accounting_records_the_bounded_primary_source_review(self):
        cookbook = self.sources["google-openai-cookbook"]
        self.assertEqual(cookbook["revision"], GOOGLE_OPENAI_COOKBOOK_REVISION)
        self.assertIn(f"/blob/{GOOGLE_OPENAI_COOKBOOK_REVISION}/", cookbook["url"])
        historical = self.sources["google-generate-content-thinking-2026-02-03"]
        self.assertEqual(
            historical["archivedFrom"], "https://ai.google.dev/gemini-api/docs/thinking"
        )
        for model in self.audited_models.values():
            if model["provider"] == "google":
                evidence = model["tokenLimitEvidence"]["outputTokenAccounting"]
                self.assertEqual(evidence["status"], "unknown")
                self.assertTrue(set(GOOGLE_ACCOUNTING_REVIEW_SOURCES).issubset(evidence["sourceIds"]))
        for source_id in ("google-openai-cookbook", "google-generate-content-thinking-2026-02-03"):
            with self.subTest(source=source_id):
                broken = copy.deepcopy(self.catalog)
                source = next(source for source in broken["sources"] if source["id"] == source_id)
                source["provider"] = "anthropic"
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(broken)

    def test_open_weight_configuration_is_not_a_hosted_capacity(self):
        for model_id, config_value in CONFIGURATION_ONLY_CONTEXT.items():
            with self.subTest(model=model_id):
                model = self.models[model_id]
                self.assertIsNone(model["contextWindow"])
                evidence = model["tokenLimitEvidence"]["contextWindow"]
                self.assertEqual(evidence["status"], "configuration-only")
                self.assertIn(f"{config_value:,}", evidence["note"])
        for model_id, (_, source_id, revision) in MICROSOFT_PUBLISHER_SPECS.items():
            with self.subTest(model=model_id):
                source = self.sources[f"{source_id}-config"]
                self.assertEqual(source["revision"], revision)
                self.assertIn(f"/blob/{revision}/config.json", source["url"])
                self.assertIn(f"{source_id}-config", self.models[model_id]["sourceIds"])
        self.assertEqual(self.sources["meta-llama-registry"]["revision"], META_REGISTRY_REVISION)
        for source_id in ("meta-codellama-config-pinned", "meta-codellama-card-pinned"):
            self.assertEqual(self.sources[source_id]["revision"], CODELLAMA_REVISION)
        reasoning = self.models["phi-4-mini-reasoning"]
        self.assertNotIn("microsoft-phi4-mini", reasoning["sourceIds"])
        self.assertIn("microsoft-phi4-mini-reasoning", reasoning["sourceIds"])
        for model in self.audited_models.values():
            if model["provider"] in {"meta", "microsoft"}:
                self.assertIsNone(model["inputTokenLimit"])
                self.assertIsNone(model["outputTokenLimit"])
                self.assertEqual(model["outputTokenAccounting"], "unknown")

    def test_xai_default_is_not_a_maximum_and_accounting_is_protocol_scoped(self):
        for model_id, model in self.audited_models.items():
            if model["provider"] != "xai" or model["tokenLimitsApplicability"] != "text":
                continue
            with self.subTest(model=model_id):
                self.assertIsNone(model["inputTokenLimit"])
                self.assertIsNone(model["outputTokenLimit"])
                evidence = model["tokenLimitEvidence"]["outputTokenLimit"]
                self.assertEqual(evidence["status"], "unknown")
                self.assertIn("128,000", evidence["note"])
                self.assertIn("default", evidence["note"].lower())
                self.assertEqual(model["outputTokenAccounting"], "total_generation")
                profiles = {profile["protocol"]: profile for profile in model["tokenLimitProfiles"]}
                self.assertEqual(profiles["responses"]["outputTokenAccounting"], "total_generation")
                self.assertEqual(profiles["chat_completions"]["outputTokenAccounting"], "visible_only")
        self.assertIn("grok-build-latest", self.models["grok-4.5"]["verifiedAliases"])
        self.assertNotIn("grok-build-latest", self.models["grok-build-0.1"]["verifiedAliases"])

    def test_xai_verified_aliases_resolve_to_the_dated_snapshot(self):
        capabilities = catalog_resolution.capabilities
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)
        for model_id, model in self.audited_models.items():
            if model["provider"] != "xai":
                continue
            for alias in model["verifiedAliases"]:
                with self.subTest(model=model_id, alias=alias):
                    budget = capabilities.resolve_model_token_budget(
                        {"modelName": alias}, provider="xai", protocol="responses",
                    )
                    self.assertEqual(budget.model_id, model_id)
                    self.assertEqual(budget.context_window, model["contextWindow"])
                    self.assertIsNone(budget.input_limit)
                    self.assertIsNone(budget.output_limit)
                    self.assertEqual(budget.applicability, model["tokenLimitsApplicability"])
        for alias in (
            "grok-imagine-image-latest", "grok-imagine-video-latest",
            "grok-voice-think-fast-1.0",
        ):
            with self.subTest(unverified_current_alias=alias):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": alias}, provider="xai", protocol="responses",
                )
                self.assertNotIn(budget.model_id, self.models)
                self.assertIsNone(budget.context_window)
                self.assertIsNone(budget.output_limit)

    def test_non_text_and_voice_dispositions_remain_explicit(self):
        for model_id in NON_TEXT_IDS:
            model = self.models[model_id]
            self.assertEqual(model["tokenLimitEvidence"]["outputTokenLimit"]["status"], "not-applicable")
            for field in ("contextWindow", "inputTokenLimit"):
                self.assertIsNone(model[field])
                self.assertEqual(model["tokenLimitEvidence"][field]["status"], "unknown")
        voice = self.models["grok-voice-latest"]
        for field in CAPACITY_FIELDS:
            self.assertEqual(voice["tokenLimitEvidence"][field]["status"], "unknown")
        self.assertNotIn("grok-voice-think-fast-1.0", voice["verifiedAliases"])
        self.assertIn("grok-voice-think-fast-1.0", voice["aliases"])
        self.assertIn("xai-release-notes", voice["sourceIds"])
        self.assertIn("2026-08-05", " ".join(voice["notes"]))

    def test_schema_rejects_non_integer_or_nonpositive_capacities(self):
        for field in CAPACITY_FIELDS:
            for invalid in (True, False, 0, -1, 1.0, 1.25, "128000", float("nan"), float("inf")):
                with self.subTest(field=field, value=invalid):
                    broken = copy.deepcopy(self.catalog)
                    broken["models"][0][field] = invalid
                    with self.assertRaises(ValidationError):
                        self.validator.validate(broken)

    def test_schema_rejects_missing_or_contradictory_evidence(self):
        for field in CAPACITY_FIELDS:
            with self.subTest(field=field):
                broken = copy.deepcopy(self.catalog)
                del broken["models"][0]["tokenLimitEvidence"][field]
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)
                broken = copy.deepcopy(self.catalog)
                broken["models"][0]["tokenLimitEvidence"][field]["status"] = "unknown"
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)
                broken = copy.deepcopy(self.catalog)
                broken["models"][0][field] = None
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)

    def test_schema_rejects_invalid_provenance(self):
        for key, value in (
            ("status", "estimated"),
            ("status", "deployment-dependent"),
            ("note", ""),
            ("note", "   "),
            ("verifiedAt", "2026-02-30"),
            ("verifiedAt", "September 19"),
            ("sourceIds", []),
            ("sourceIds", ["same", "same"]),
        ):
            with self.subTest(key=key, value=value):
                broken = copy.deepcopy(self.catalog)
                broken["models"][0]["tokenLimitEvidence"]["contextWindow"][key] = value
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)
        for url in ("http://docs.x.ai/developers/models", "javascript:void(0)"):
            with self.subTest(url=url):
                broken = copy.deepcopy(self.catalog)
                broken["sources"][0]["url"] = url
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)

    def test_profile_values_reject_invalid_types_and_accept_explicit_unknown(self):
        for field in (*CAPACITY_FIELDS, "effectiveContextWindow"):
            for invalid in (True, 0, -1, 1.0, 1.5, "922000", float("nan"), float("inf")):
                with self.subTest(field=field, value=invalid):
                    broken = copy.deepcopy(self.catalog)
                    profile = broken["models"][0]["tokenLimitProfiles"][0]
                    profile[field] = invalid
                    profile["tokenLimitEvidence"][field] = copy.deepcopy(
                        profile["tokenLimitEvidence"]["contextWindow"]
                    )
                    with self.assertRaises(ValidationError):
                        self.validator.validate(broken)
        qualified = copy.deepcopy(self.catalog)
        profile = qualified["models"][0]["tokenLimitProfiles"][0]
        profile["outputTokenLimit"] = None
        profile["tokenLimitEvidence"]["outputTokenLimit"]["status"] = "unknown"
        self.validator.validate(qualified)
        validate_catalog_integrity(qualified)
        self.assertIsNone(profile["outputTokenLimit"])
        self.assertEqual(qualified["models"][0]["outputTokenLimit"], 128000)

    def test_schema_rejects_inconsistent_non_text_applicability(self):
        broken = copy.deepcopy(self.catalog)
        model = broken["models"][0]
        model["tokenLimitsApplicability"] = "non-text"
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)
        broken = copy.deepcopy(self.catalog)
        model = broken["models"][0]
        model["outputTokenLimit"] = None
        model["tokenLimitEvidence"]["outputTokenLimit"]["status"] = "not-applicable"
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)

    def test_schema_rejects_unknown_keys_and_profile_contract_errors(self):
        broken = copy.deepcopy(self.catalog)
        broken["models"][0]["tokenLimitProfiles"][0]["provider"] = "microsoft"
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)
        broken = copy.deepcopy(self.catalog)
        profile = broken["models"][0]["tokenLimitProfiles"][0]
        profile["protocol"] = "guessed_api"
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)
        broken = copy.deepcopy(self.catalog)
        profile = broken["models"][0]["tokenLimitProfiles"][0]
        profile["modelVersions"] = []
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)
        broken = copy.deepcopy(self.catalog)
        del broken["models"][0]["tokenLimitProfiles"][0]["tokenLimitEvidence"]["contextWindow"]
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)
        for target in ("catalog", "source", "model", "profile", "evidence", "capabilities"):
            with self.subTest(target=target):
                broken = copy.deepcopy(self.catalog)
                model = broken["models"][0]
                targets = {
                    "catalog": broken,
                    "source": broken["sources"][0],
                    "model": model,
                    "profile": model["tokenLimitProfiles"][0],
                    "evidence": model["tokenLimitEvidence"]["contextWindow"],
                    "capabilities": model["capabilities"],
                }
                targets[target]["unexpectedField"] = True
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)

    def test_schema_validates_optional_tool_effort_constraints(self):
        for invalid in (None, "none", [], [None], [True], [1], [""], ["   "], ["none", "none"]):
            with self.subTest(value=invalid):
                broken = copy.deepcopy(self.catalog)
                profile = broken["models"][0]["tokenLimitProfiles"][1]
                profile["toolReasoningEfforts"] = invalid
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)
        for missing in ("toolReasoningEfforts", "evidence"):
            with self.subTest(missing=missing):
                broken = copy.deepcopy(self.catalog)
                profile = broken["models"][0]["tokenLimitProfiles"][1]
                if missing == "evidence":
                    del profile["tokenLimitEvidence"]["toolReasoningEfforts"]
                else:
                    del profile["toolReasoningEfforts"]
                with self.assertRaises(ValidationError):
                    self.validator.validate(broken)
        broken = copy.deepcopy(self.catalog)
        evidence = broken["models"][0]["tokenLimitProfiles"][1]["tokenLimitEvidence"]
        evidence["toolReasoningEfforts"]["status"] = "unknown"
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)
        qualified = copy.deepcopy(self.catalog)
        profile = qualified["models"][0]["tokenLimitProfiles"][1]
        del profile["outputTokenAccounting"]
        del profile["tokenLimitEvidence"]["outputTokenAccounting"]
        self.validator.validate(qualified)
        validate_catalog_integrity(qualified)

    def test_integrity_rejects_missing_sources_and_ambiguous_profiles(self):
        for target in ("model", "root_evidence", "profile_evidence"):
            with self.subTest(target=target):
                broken = copy.deepcopy(self.catalog)
                model = broken["models"][0]
                source_lists = {
                    "model": model["sourceIds"],
                    "root_evidence": model["tokenLimitEvidence"]["contextWindow"]["sourceIds"],
                    "profile_evidence": model["tokenLimitProfiles"][0]["tokenLimitEvidence"]["contextWindow"]["sourceIds"],
                }
                source_lists[target].append("missing-source")
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(broken)
        broken = copy.deepcopy(self.catalog)
        duplicate = copy.deepcopy(broken["models"][0]["tokenLimitProfiles"][0])
        duplicate["id"] = "conflicting-profile"
        broken["models"][0]["tokenLimitProfiles"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "Equally specific profiles overlap"):
            validate_catalog_integrity(broken)
        broken = copy.deepcopy(self.catalog)
        broken["models"][1]["verifiedAliases"].append(broken["models"][0]["id"])
        with self.assertRaisesRegex(ValueError, "Ambiguous verified identity"):
            validate_catalog_integrity(broken)

    def test_profile_overlap_checks_protocol_and_version_dimensions(self):
        base = copy.deepcopy(self.catalog)
        left = copy.deepcopy(base["models"][0]["tokenLimitProfiles"][0])
        right = copy.deepcopy(left)
        left["id"] = "left"
        right["id"] = "right"
        left["modelVersions"] = ["2026-07-09", "2026-08-01"]
        right["modelVersions"] = ["2026-08-01"]
        base["models"][0]["tokenLimitProfiles"] = [left, right]
        with self.assertRaisesRegex(ValueError, "Equally specific profiles overlap"):
            validate_catalog_integrity(base)
        right["modelVersions"] = ["2026-09-01"]
        validate_catalog_integrity(base)
        del right["modelVersions"]
        right["protocol"] = "responses"
        with self.assertRaisesRegex(ValueError, "Equally specific profiles overlap"):
            validate_catalog_integrity(base)
        right["modelVersions"] = ["2026-08-01"]
        validate_catalog_integrity(base)

    def test_integrity_rejects_duplicate_ids_and_non_primary_sources(self):
        for target in ("source", "model", "profile"):
            with self.subTest(target=target):
                broken = copy.deepcopy(self.catalog)
                if target == "source":
                    broken["sources"].append(copy.deepcopy(broken["sources"][0]))
                elif target == "model":
                    broken["models"].append(copy.deepcopy(broken["models"][0]))
                else:
                    profiles = broken["models"][0]["tokenLimitProfiles"]
                    profiles.append(copy.deepcopy(profiles[0]))
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    validate_catalog_integrity(broken)
        for url in (
            "https://third-party.example/models",
            "https://huggingface.co/unverified-author/model",
            "https://github.com/unverified-author/model",
        ):
            with self.subTest(url=url):
                broken = copy.deepcopy(self.catalog)
                broken["sources"][0]["url"] = url
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(broken)

    def test_catalog_schema_failure_cannot_be_returned_as_false_success(self):
        probe = catalog_resolution.TestModelCapabilityCatalog("test_catalog_matches_schema")
        probe.catalog = copy.deepcopy(self.catalog)
        probe.catalog["models"][0]["contextWindow"] = True
        result = unittest.TestResult()
        probe.run(result)
        successful = result.wasSuccessful()
        self.assertFalse(successful, "A caught failure returning False must not pass.")
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors) + len(result.failures), 1)


if __name__ == "__main__":
    unittest.main()
