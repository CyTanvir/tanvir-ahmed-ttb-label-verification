from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LABEL_FIELD_NAMES: tuple[str, ...] = (
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "country_of_origin",
    "government_warning",
)

MatchStatus = Literal["PASS", "FAIL"]
OverallVerdict = Literal["APPROVED", "NEEDS_REVIEW"]
BatchLabelStatus = Literal["APPROVED", "NEEDS_REVIEW", "ERROR"]
MatchType = Literal[
    "fuzzy",
    "abv_numeric_tolerance",
    "net_contents_ml",
    "country_synonym",
    "exact_case_sensitive",
]


class ApplicationData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brand_name: str | None = None
    class_type: str | None = None
    abv: str | None = None
    net_contents: str | None = None
    producer: str | None = None
    country_of_origin: str | None = None
    government_warning: str | None = None


class ExtractedLabel(ApplicationData):
    brand_name: str | None = Field(
        default=None,
        description="Brand name exactly as it appears on the label.",
    )
    class_type: str | None = Field(
        default=None,
        description="Wine, beer, spirits, or other class/type shown on the label.",
    )
    abv: str | None = Field(
        default=None,
        description="Alcohol by volume statement shown on the label.",
    )
    net_contents: str | None = Field(
        default=None,
        description="Net contents statement shown on the label.",
    )
    producer: str | None = Field(
        default=None,
        description="Producer, bottler, importer, or responsible company shown on the label.",
    )
    country_of_origin: str | None = Field(
        default=None,
        description="Country of origin shown on the label.",
    )
    government_warning: str | None = Field(
        default=None,
        description=(
            "Government warning text. Preserve exact capitalization, punctuation, "
            "and wording when visible."
        ),
    )


class FieldResult(BaseModel):
    field: str
    match_type: MatchType
    expected: str | None = None
    found: str | None = None
    status: MatchStatus


class VerificationResult(BaseModel):
    results: list[FieldResult]
    overall_verdict: OverallVerdict
    latency_ms: float = Field(ge=0.0)


class BatchSummary(BaseModel):
    total: int = Field(ge=0)
    approved: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    errors: int = Field(ge=0)


class BatchLabelResult(BaseModel):
    index: int = Field(ge=0)
    filename: str | None = None
    status: BatchLabelStatus
    result: VerificationResult | None = None
    error: str | None = None
    latency_ms: float = Field(ge=0.0)


class BatchVerificationResult(BaseModel):
    summary: BatchSummary
    labels: list[BatchLabelResult]
    latency_ms: float = Field(ge=0.0)
