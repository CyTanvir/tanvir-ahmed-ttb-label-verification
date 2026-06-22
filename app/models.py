from typing import Literal

from pydantic import BaseModel, Field


LABEL_FIELD_NAMES: tuple[str, ...] = (
    "brand_name",
    "product_type",
    "alcohol_content",
    "net_contents",
    "sulfite_statement",
    "government_warning",
)

ComparisonMode = Literal["fuzzy_normalized", "strict_case_sensitive"]


class LabelData(BaseModel):
    brand_name: str | None = None
    product_type: str | None = None
    alcohol_content: str | None = None
    net_contents: str | None = None
    sulfite_statement: str | None = None
    government_warning: str | None = None


class FieldComparison(BaseModel):
    name: str
    expected: str | None = None
    extracted: str | None = None
    comparison: ComparisonMode
    matched: bool
    score: float = Field(ge=0.0, le=1.0)
    expected_normalized: str | None = None
    extracted_normalized: str | None = None


class LabelComparisonResult(BaseModel):
    matched: bool
    fields: list[FieldComparison]
