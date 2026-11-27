# microsoft_decision_plugin.py
"""Semantic Kernel action for typed Microsoft Decision-1 judgments."""

import json
import logging
from typing import Any, Dict, List, Optional

import requests
from azure.identity import DefaultAzureCredential
from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_microsoft_decision_operations import (
    MICROSOFT_DECISION_MAX_CRITERIA_ITEMS,
    MICROSOFT_DECISION_MAX_INSTRUCTIONS_LENGTH,
    MICROSOFT_DECISION_MAX_STATE_BYTES,
    MICROSOFT_DECISION_LEGACY_PATH,
    MICROSOFT_DECISION_PLUGIN_TYPE,
    normalize_microsoft_decision_additional_fields,
    normalize_microsoft_decision_endpoint,
    validate_microsoft_decision_manifest,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class MicrosoftDecisionPlugin(BasePlugin):
    """Invoke Microsoft Decision-1 for bounded, typed decisions only."""

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._auth = self.manifest.get("auth") if isinstance(self.manifest.get("auth"), dict) else {}
        self._additional_fields = normalize_microsoft_decision_additional_fields(
            self.manifest.get("additionalFields")
        )
        self.endpoint = normalize_microsoft_decision_endpoint(
            self.manifest.get("endpoint"), self._additional_fields["url_mode"]
        )
        self.deployment_name = self._additional_fields["deployment_name"]
        self.timeout_seconds = self._additional_fields["timeout_seconds"]
        self.minimum_confidence = self._additional_fields["minimum_confidence"]
        self.api_key_header = self._additional_fields["api_key_header"]
        self._validate_configuration()

    @property
    def display_name(self) -> str:
        return "Microsoft Decision-1"

    @property
    def metadata(self) -> Dict[str, Any]:
        description = self.manifest.get(
            "description",
            "Makes bounded binary, choice, and score decisions using Microsoft Decision-1.",
        )
        return {
            "name": self.manifest.get("name", MICROSOFT_DECISION_PLUGIN_TYPE),
            "type": MICROSOFT_DECISION_PLUGIN_TYPE,
            "description": (
                f"{description}\n\nDecision-1 returns typed decisions and probabilities, "
                "not a written rationale. Use it for classification, routing, scoring, and "
                "decision support; interpret low-confidence results as requiring review."
            ),
            "methods": [
                {
                    "name": "check_condition",
                    "description": "Evaluate a binary condition and return its probability.",
                    "parameters": [
                        {"name": "state", "type": "str", "description": "Text or JSON state to evaluate.", "required": True},
                        {"name": "instructions", "type": "str", "description": "Neutral binary question.", "required": True},
                        {"name": "true_criteria", "type": "str", "description": "Optional definition of true.", "required": False},
                        {"name": "false_criteria", "type": "str", "description": "Optional definition of false.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Boolean decision, probability, and review signal."},
                },
                {
                    "name": "choose_option",
                    "description": "Choose one option from a bounded JSON object of option labels and criteria.",
                    "parameters": [
                        {"name": "state", "type": "str", "description": "Text or JSON state to classify.", "required": True},
                        {"name": "instructions", "type": "str", "description": "Neutral selection question.", "required": True},
                        {"name": "options_json", "type": "str", "description": "JSON object mapping option labels to criteria.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Choice, per-option probabilities, and review signal."},
                },
                {
                    "name": "score_state",
                    "description": "Score state against ordered levels supplied as a JSON array.",
                    "parameters": [
                        {"name": "state", "type": "str", "description": "Text or JSON state to score.", "required": True},
                        {"name": "instructions", "type": "str", "description": "Neutral scoring question.", "required": True},
                        {"name": "levels_json", "type": "str", "description": "JSON array of levels ordered lowest to highest.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Score, level probabilities, and review signal."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return ["check_condition", "choose_option", "score_state"]

    def _validate_configuration(self) -> None:
        errors = validate_microsoft_decision_manifest(self.manifest)
        if errors:
            raise ValueError("; ".join(errors))

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        auth_type = str(self._auth.get("type") or "").strip()
        if auth_type == "key":
            headers[self.api_key_header] = str(self._auth.get("key") or "")
            return headers
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default").token
        headers["Authorization"] = f"Bearer {token}"
        return headers

    def _parse_state(self, state: str) -> Any:
        normalized_state = str(state or "").strip()
        if not normalized_state:
            raise ValueError("state is required.")
        if len(normalized_state.encode("utf-8")) > MICROSOFT_DECISION_MAX_STATE_BYTES:
            raise ValueError("state exceeds the maximum supported size.")
        if normalized_state.startswith(("{", "[")):
            try:
                return json.loads(normalized_state)
            except json.JSONDecodeError:
                pass
        return normalized_state

    @staticmethod
    def _parse_json_argument(raw_value: str, expected_type: type, field_name: str) -> Any:
        try:
            parsed = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{field_name} must be valid JSON.") from exc
        if not isinstance(parsed, expected_type):
            raise ValueError(f"{field_name} must be a JSON {expected_type.__name__}.")
        return parsed

    def _validate_instructions(self, instructions: str) -> str:
        normalized = str(instructions or "").strip()
        if not normalized:
            raise ValueError("instructions are required.")
        if len(normalized) > MICROSOFT_DECISION_MAX_INSTRUCTIONS_LENGTH:
            raise ValueError("instructions exceed the maximum supported length.")
        return normalized

    def _invoke(self, question_name: str, state: str, question: Dict[str, Any]) -> Dict[str, Any]:
        try:
            parsed_state = self._parse_state(state)
            if self.endpoint.endswith(MICROSOFT_DECISION_LEGACY_PATH):
                body = {
                    "model": self.deployment_name,
                    "state": parsed_state,
                    "questions": {question_name: question},
                }
            else:
                body = {
                    "model": self.deployment_name,
                    "input": self._build_responses_input(parsed_state, question_name, question),
                }
            response = requests.post(
                self.endpoint,
                headers=self._headers(),
                json=body,
                timeout=self.timeout_seconds,
            )
        except ValueError as exc:
            return self._error_result(str(exc), "validation")
        except requests.Timeout:
            return self._error_result("Microsoft Decision did not respond before the configured timeout.", "timeout")
        except requests.RequestException:
            return self._error_result("Microsoft Decision could not be reached.", "connection")
        except Exception as exc:
            log_event(
                "[MICROSOFT_DECISION] Decision request setup failed.",
                extra={"plugin_name": self.manifest.get("name"), "exception_type": type(exc).__name__},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_result("Microsoft Decision request could not be prepared.", "authentication")

        if response.status_code >= 400:
            error_type = {
                400: "validation",
                401: "authentication",
                403: "authorization",
                404: "not_found",
                422: "validation",
                429: "throttled",
            }.get(response.status_code, "provider")
            return self._error_result(
                "Microsoft Decision rejected the request. Verify the action configuration and try again.",
                error_type,
                http_status=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            return self._error_result("Microsoft Decision returned an invalid response.", "response")
        if self.endpoint.endswith(MICROSOFT_DECISION_LEGACY_PATH):
            return self._project_answer(payload, question_name)
        return self._project_responses_answer(payload)

    @staticmethod
    def _build_responses_input(state: Any, question_name: str, question: Dict[str, Any]) -> str:
        return (
            "Return only a JSON object with the fields `answer` and `probabilities`. "
            "Do not include markdown or a rationale. The answer must satisfy the typed "
            f"question named `{question_name}`.\n"
            f"State: {json.dumps(state, ensure_ascii=False)}\n"
            f"Question: {json.dumps(question, ensure_ascii=False)}"
        )

    def _project_responses_answer(self, payload: Any) -> Dict[str, Any]:
        response_text = self._extract_response_text(payload)
        if response_text is None:
            return self._error_result("Microsoft Decision returned no answer text.", "response")
        try:
            answer = json.loads(response_text)
        except (TypeError, json.JSONDecodeError):
            return self._error_result("Microsoft Decision returned an invalid JSON answer.", "response")
        if not isinstance(answer, dict):
            return self._error_result("Microsoft Decision returned an invalid answer.", "response")
        result = {
            "success": True,
            "answer": answer,
            "model": payload.get("model") if isinstance(payload, dict) else None,
            "usage": payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else {},
        }
        confidence = self._resolve_confidence(answer)
        if confidence is not None:
            result["confidence"] = confidence
            result["requires_review"] = confidence < self.minimum_confidence
        return result

    @staticmethod
    def _extract_response_text(payload: Any) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    if content["text"].strip():
                        return content["text"].strip()
        return None

    def _project_answer(self, payload: Any, question_name: str) -> Dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            return self._error_result("Microsoft Decision returned no answers.", "response")
        answer = payload["answers"].get(question_name)
        if not isinstance(answer, dict):
            return self._error_result("Microsoft Decision returned an invalid answer.", "response")
        result = {
            "success": True,
            "answer": answer,
            "model": payload.get("model"),
            "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        }
        confidence = self._resolve_confidence(answer)
        if confidence is not None:
            result["confidence"] = confidence
            result["requires_review"] = confidence < self.minimum_confidence
        return result

    @staticmethod
    def _resolve_confidence(answer: Dict[str, Any]) -> Optional[float]:
        probability = answer.get("probability")
        if isinstance(probability, (int, float)):
            return float(probability)
        probabilities = answer.get("probabilities")
        if isinstance(probabilities, dict):
            values = [value for value in probabilities.values() if isinstance(value, (int, float))]
            return max(values) if values else None
        if isinstance(probabilities, list):
            values = [value for value in probabilities if isinstance(value, (int, float))]
            return max(values) if values else None
        return None

    @staticmethod
    def _error_result(message: str, error_type: str, **extra: Any) -> Dict[str, Any]:
        result = {"success": False, "error": message, "error_type": error_type}
        result.update(extra)
        return result

    @plugin_function_logger("MicrosoftDecisionPlugin")
    @kernel_function(description="Evaluate a binary condition and return its probability.", name="check_condition")
    def check_condition(
        self,
        state: str,
        instructions: str,
        true_criteria: str = "",
        false_criteria: str = "",
    ) -> Dict[str, Any]:
        try:
            criteria = {}
            if str(true_criteria or "").strip():
                criteria["true"] = str(true_criteria).strip()
            if str(false_criteria or "").strip():
                criteria["false"] = str(false_criteria).strip()
            question = {"type": "noul", "instructions": self._validate_instructions(instructions)}
            if criteria:
                question["criteria"] = criteria
            return self._invoke("condition", state, question)
        except ValueError as exc:
            return self._error_result(str(exc), "validation")

    @plugin_function_logger("MicrosoftDecisionPlugin")
    @kernel_function(description="Choose one option from a bounded JSON object of option labels and criteria.", name="choose_option")
    def choose_option(self, state: str, instructions: str, options_json: str) -> Dict[str, Any]:
        try:
            options = self._parse_json_argument(options_json, dict, "options_json")
            if not 2 <= len(options) <= MICROSOFT_DECISION_MAX_CRITERIA_ITEMS:
                return self._error_result("options_json must contain between two and twenty options.", "validation")
            if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip() for key, value in options.items()):
                return self._error_result("Each option must have a non-empty label and criterion.", "validation")
            return self._invoke(
                "choice",
                state,
                {"type": "choice", "instructions": self._validate_instructions(instructions), "criteria": options},
            )
        except ValueError as exc:
            return self._error_result(str(exc), "validation")

    @plugin_function_logger("MicrosoftDecisionPlugin")
    @kernel_function(description="Score state against ordered levels supplied as a JSON array.", name="score_state")
    def score_state(self, state: str, instructions: str, levels_json: str) -> Dict[str, Any]:
        try:
            levels = self._parse_json_argument(levels_json, list, "levels_json")
            if not 2 <= len(levels) <= MICROSOFT_DECISION_MAX_CRITERIA_ITEMS:
                return self._error_result("levels_json must contain between two and twenty levels.", "validation")
            if any(not isinstance(level, str) or not level.strip() for level in levels):
                return self._error_result("Each score level must be a non-empty string.", "validation")
            return self._invoke(
                "score",
                state,
                {"type": "score", "instructions": self._validate_instructions(instructions), "criteria": levels},
            )
        except ValueError as exc:
            return self._error_result(str(exc), "validation")
