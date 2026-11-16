# test_deployer_postconfig_sdk_contract.py
"""
Functional test for the merged deployment entrypoint's Cosmos document contract.
Version: 0.261.408
Implemented in: 0.261.408

Execute the real postconfig module with installed-SDK point responses for an
existing settings document and first-time creation. External services use the
existing deployment fixture; no Azure requests are made.
"""

from azure.cosmos._cosmos_responses import CosmosDict
import pytest

from test_app_settings_store_consistency import FakeCosmos
from test_deployment_configuration import (
    test_real_postconfig_entrypoint_writes_once_and_initializes_search as run_real_entrypoint,
    world,
)


class SdkDeploymentCosmos(FakeCosmos):
    def __init__(self):
        super().__init__()
        self.responses = []

    def _response(self, response_hook=None):
        document = super()._response(response_hook)
        response = CosmosDict(document, response_headers={"etag": document["_etag"]})
        self.responses.append(response)
        return response


@pytest.mark.parametrize("existing", [True, False])
def test_real_postconfig_module_accepts_sdk_point_documents(monkeypatch, world, existing):
    world.cosmos = SdkDeploymentCosmos()
    previous_etag = world.cosmos.document["_etag"] if existing else None
    if not existing:
        world.cosmos.document = None

    run_real_entrypoint(monkeypatch, world)

    stored = world.cosmos.read_item(item="app_settings", partition_key="app_settings")
    assert type(stored) is CosmosDict
    assert stored["id"] == "app_settings"
    assert stored["_etag"] and stored["_etag"] != previous_etag
    assert world.cosmos.writes == 1
    assert world.cosmos.responses
    assert all(type(response) is CosmosDict for response in world.cosmos.responses)
    assert all(
        response.get_response_headers()["etag"] == response["_etag"]
        for response in world.cosmos.responses
    )
