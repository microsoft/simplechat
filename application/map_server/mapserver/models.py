# models.py
"""Request bodies the map server accepts. Text is trimmed to its stored limits by validation.py."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateMapRequest(_Request):
    title: str = Field(max_length=1000)
    description: str = Field(default="", max_length=10000)
    basemap: str = Field(default="", max_length=64)
    first_phase_name: str = Field(default="", max_length=1000)
    first_phase_description: str = Field(default="", max_length=10000)
    conversation_id: str = Field(default="", max_length=128)


class UpdateMapRequest(_Request):
    title: Optional[str] = Field(default=None, max_length=1000)
    description: Optional[str] = Field(default=None, max_length=10000)
    basemap: Optional[str] = Field(default=None, max_length=64)


class LinkConversationRequest(_Request):
    conversation_id: str = Field(min_length=1, max_length=128)


class StartPhaseRequest(_Request):
    name: str = Field(max_length=1000)
    description: str = Field(default="", max_length=10000)
    color: str = Field(default="", max_length=64)


class UpdatePhaseRequest(_Request):
    name: Optional[str] = Field(default=None, max_length=1000)
    description: Optional[str] = Field(default=None, max_length=10000)
    color: Optional[str] = Field(default=None, max_length=64)


class AddFeaturesRequest(_Request):
    features: List[Dict[str, Any]] = Field(min_length=1, max_length=200)
    phase_id: str = Field(default="", max_length=8)
    on_duplicate: Literal["skip", "update"] = "skip"


class UpdateFeatureRequest(_Request):
    changes: Dict[str, Any]
    expected_revision: Optional[int] = Field(default=None, ge=1)
    phase_id: str = Field(default="", max_length=8)


class RetractFeatureRequest(_Request):
    reason: str = Field(max_length=10000)
    phase_id: str = Field(default="", max_length=8)
