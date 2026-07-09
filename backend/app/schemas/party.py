from typing import List, Literal, Optional
from pydantic import BaseModel, field_validator


class Party(BaseModel):
    serial_no: int
    full_name: str = ""
    relation_type: Literal["S/O", "D/O", "W/O", "C/O", ""] = ""
    relation_name: str = ""
    age: Optional[int] = None
    address: str = ""
    state: str = ""
    country: str = "India"
    raw_text: str = ""

    @field_validator("relation_type", mode="before")
    @classmethod
    def _normalize_relation_type(cls, v):
        if v is None:
            return ""
        v = str(v).strip().upper()
        return v if v in ("S/O", "D/O", "W/O", "C/O") else ""

    @field_validator(
        "full_name", "relation_name", "address", "state", "country", "raw_text",
        mode="before",
    )
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else v


class PartyList(BaseModel):
    parties: List[Party]