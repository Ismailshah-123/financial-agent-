from __future__ import annotations

from pydantic import Field

from app.schemas.common import APIModel


class AgentInputField(APIModel):
    name: str
    label: str
    kind: str = Field(description="UI input type: uuid, date, number, select, or text.")
    required: bool
    description: str | None = None
    options: list[str] = Field(default_factory=list)


class AgentCatalogEntry(APIModel):
    key: str
    name: str
    description: str
    method: str = "POST"
    endpoint: str
    input_fields: list[AgentInputField] = Field(default_factory=list)
