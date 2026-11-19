# test_azure_maps_connection_no_content.py
"""
Functional tests for Azure Maps connection checks after HTTP 204.
Version: 0.261.453
Implemented in: 0.261.453

Validate the bounded alternate-tile probe, accurate failures, and secret safety
without cloud credentials or network access.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_action_connection_test_secret_redaction import _load_tester_module


def _response(status, content_type=""):
    return SimpleNamespace(status_code=status, headers={"Content-Type": content_type})


class AzureMapsConnectionTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_tester_module()
        self.manifest = {
            "endpoint": "https://atlas.microsoft.com/",
            "auth": {"key": "synthetic-maps-subscription-key"},
        }

    def test_image_succeeds_without_retry(self):
        with patch.object(self.module, "guarded_probe_request", return_value=_response(200, "image/png")) as probe:
            result = self.module.test_azure_maps_connection(self.manifest)

        self.assertTrue(result["success"])
        self.assertEqual(result["details"]["http_status"], 200)
        self.assertEqual(probe.call_count, 1)

    def test_no_content_retries_distinct_tile_with_remaining_budget(self):
        with (
            patch.object(self.module, "monotonic", side_effect=[100, 100, 106]),
            patch.object(self.module, "guarded_probe_request", side_effect=[
                _response(204), _response(200, "image/png"),
            ]) as probe,
        ):
            result = self.module.test_azure_maps_connection(self.manifest)

        self.assertTrue(result["success"])
        self.assertEqual(probe.call_count, 2)
        first, second = probe.call_args_list
        self.assertEqual(first.args, ("GET", "https://atlas.microsoft.com/map/tile"))
        self.assertEqual(second.args, first.args)
        self.assertEqual(first.kwargs["timeout"], 15)
        self.assertEqual(second.kwargs["timeout"], 9)
        first_params = first.kwargs["params"]
        second_params = second.kwargs["params"]
        self.assertEqual(tuple(first_params[key] for key in ("zoom", "x", "y")), (0, 0, 0))
        self.assertNotEqual(
            tuple(first_params[key] for key in ("zoom", "x", "y")),
            tuple(second_params[key] for key in ("zoom", "x", "y")),
        )
        for key in ("x", "y"):
            self.assertGreaterEqual(second_params[key], 0)
            self.assertLess(second_params[key], 2 ** second_params["zoom"])
        for key in ("api-version", "tilesetId", "tileSize", "language", "view", "subscription-key"):
            self.assertEqual(second_params[key], first_params[key])
        self.assertEqual(second_params["subscription-key"], self.manifest["auth"]["key"])
        self.assertEqual(first.kwargs["max_bytes"], 0)
        self.assertEqual(second.kwargs["max_bytes"], 0)

    def test_repeated_no_content_is_not_success_or_key_rejection(self):
        with (
            patch.object(self.module, "guarded_probe_request", return_value=_response(204)) as probe,
            patch.object(self.module, "log_event") as log,
        ):
            result = self.module.test_azure_maps_connection(self.manifest)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["details"]["http_status"], 204)
        self.assertIn("no tile content", result["error"])
        self.assertIn("could not be verified", result["error"])
        self.assertNotIn("rejected the subscription key", result["error"])
        self.assertEqual(probe.call_count, 2)
        self.assertNotIn(self.manifest["auth"]["key"], str(result))
        self.assertNotIn(self.manifest["auth"]["key"], str(log.call_args_list))

    def test_other_statuses_and_non_images_never_trigger_retry(self):
        for status, content_type, expected_status in [
            (401, "", 403), (403, "", 403), (404, "", 404),
            (500, "", 400), (201, "", 400), (200, "text/html", 400),
        ]:
            with self.subTest(status=status), patch.object(
                self.module, "guarded_probe_request", return_value=_response(status, content_type),
            ) as probe:
                result = self.module.test_azure_maps_connection(self.manifest)

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], expected_status)
            self.assertEqual(probe.call_count, 1)

    def test_retry_failure_is_not_hidden(self):
        for status, content_type, expected_status in [
            (401, "", 403), (403, "", 403), (404, "", 404),
            (500, "", 400), (200, "application/json", 400),
        ]:
            with self.subTest(status=status), patch.object(
                self.module, "guarded_probe_request",
                side_effect=[_response(204), _response(status, content_type)],
            ) as probe:
                result = self.module.test_azure_maps_connection(self.manifest)

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], expected_status)
            self.assertEqual(probe.call_count, 2)
            if status != 200:
                self.assertEqual(result["details"]["http_status"], status)

    def test_retry_timeout_redacts_credentials(self):
        secret = self.manifest["auth"]["key"]
        with patch.object(self.module, "guarded_probe_request", side_effect=[
            _response(204), self.module.requests.Timeout(f"Request failed with subscription-key={secret}"),
        ]) as probe:
            result = self.module.test_azure_maps_connection(self.manifest)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 502)
        self.assertEqual(probe.call_count, 2)
        self.assertNotIn(secret, str(result))

    def test_exhausted_budget_prevents_retry(self):
        with (
            patch.object(self.module, "monotonic", side_effect=[100, 100, 115]),
            patch.object(self.module, "guarded_probe_request", return_value=_response(204)) as probe,
        ):
            result = self.module.test_azure_maps_connection(self.manifest)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 502)
        self.assertIn("timed out", result["error"])
        self.assertEqual(probe.call_count, 1)

    def test_missing_key_never_makes_a_request(self):
        with patch.object(self.module, "guarded_probe_request") as probe:
            result = self.module.test_azure_maps_connection({})

        self.assertFalse(result["success"])
        self.assertIn("subscription key is required", result["error"])
        probe.assert_not_called()

    def test_destination_policy_blocks_alternate_probe(self):
        error = self.module.OutboundDestinationError("The action destination is not allowed.")
        with patch.object(self.module, "guarded_probe_request", side_effect=[
            _response(204), error,
        ]) as probe:
            result = self.module.test_azure_maps_connection(self.manifest)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], error.public_message)
        self.assertEqual(probe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
