from collections.abc import Mapping
from difflib import SequenceMatcher
import re
import unicodedata

from app.models import (
    LABEL_FIELD_NAMES,
    FieldComparison,
    LabelComparisonResult,
    LabelData,
)


GOVERNMENT_WARNING_FIELD = "government_warning"
DEFAULT_FUZZY_THRESHOLD = 0.85


def compare_labels(
    expected: LabelData | Mapping[str, object],
    extracted: LabelData | Mapping[str, object],
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> LabelComparisonResult:
    expected_label = _coerce_label(expected)
    extracted_label = _coerce_label(extracted)

    fields = [
        _compare_field(
            name,
            getattr(expected_label, name),
            getattr(extracted_label, name),
            fuzzy_threshold,
        )
        for name in LABEL_FIELD_NAMES
    ]

    return LabelComparisonResult(
        matched=all(field.matched for field in fields),
        fields=fields,
    )


def normalize_value(value: str | None) -> str:
    if value is None:
        return ""

    text = unicodedata.normalize("NFKC", value)
    text = text.replace("&", " and ")
    text = text.casefold()
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _coerce_label(label: LabelData | Mapping[str, object]) -> LabelData:
    if isinstance(label, LabelData):
        return label
    return LabelData(**label)


def _compare_field(
    name: str,
    expected: str | None,
    extracted: str | None,
    fuzzy_threshold: float,
) -> FieldComparison:
    if name == GOVERNMENT_WARNING_FIELD:
        matched = expected == extracted
        return FieldComparison(
            name=name,
            expected=expected,
            extracted=extracted,
            comparison="strict_case_sensitive",
            matched=matched,
            score=1.0 if matched else 0.0,
        )

    expected_normalized = normalize_value(expected)
    extracted_normalized = normalize_value(extracted)
    score = _similarity_score(expected_normalized, extracted_normalized)

    return FieldComparison(
        name=name,
        expected=expected,
        extracted=extracted,
        comparison="fuzzy_normalized",
        matched=score >= fuzzy_threshold,
        score=score,
        expected_normalized=expected_normalized,
        extracted_normalized=extracted_normalized,
    )


def _similarity_score(expected: str, extracted: str) -> float:
    if not expected and not extracted:
        return 1.0
    if not expected or not extracted:
        return 0.0
    if expected == extracted:
        return 1.0
    return SequenceMatcher(None, expected, extracted).ratio()
