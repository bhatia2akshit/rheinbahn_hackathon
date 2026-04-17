from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ActionType(StrEnum):
    CALL_POLICE = "call_police"


class IncidentAnalyzeRequest(BaseModel):
    raw_text: str = Field(min_length=5, max_length=2000)
    postal_code: str = Field(pattern=r"^\d{5}$")


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    internal_key: str
    label_de: str
    description: str | None = None


class PoliceDepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str
    postal_code_start: int
    postal_code_end: int
    phone_number: str


class IncidentOut(BaseModel):
    id: int
    raw_text: str
    postal_code: str
    detected_categories: list[str]
    selected_action: str
    police_department: PoliceDepartmentOut | None = None
    generated_script: str
    created_at: datetime


class AnalyzeResponse(BaseModel):
    original_input: str
    postal_code: str
    selected_categories: list[str]
    selected_action: str
    police_department: PoliceDepartmentOut | None = None
    police_phone_number: str | None = None
    summary: str
    generated_script: str

