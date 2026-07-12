from collections.abc import Callable, Mapping
from difflib import SequenceMatcher
import re
from time import perf_counter
import unicodedata

from app.models import (
    LABEL_FIELD_NAMES,
    ApplicationData,
    FieldResult,
    MatchType,
    VerificationResult,
)


DEFAULT_FUZZY_THRESHOLD = 0.90
ABV_TOLERANCE = 0.1
NET_CONTENTS_ML_TOLERANCE = 1.0
FUZZY_FIELDS = frozenset({"brand_name", "class_type", "producer"})
GOVERNMENT_WARNING_FIELD = "government_warning"
FLUID_OUNCE_TO_ML = 29.5735
UNIT_TO_ML = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    "cl": 10.0,
    "centiliter": 10.0,
    "centiliters": 10.0,
    "floz": FLUID_OUNCE_TO_ML,
    "fluidounce": FLUID_OUNCE_TO_ML,
    "fluidounces": FLUID_OUNCE_TO_ML,
    "oz": FLUID_OUNCE_TO_ML,
    "ounce": FLUID_OUNCE_TO_ML,
    "ounces": FLUID_OUNCE_TO_ML,
}
COUNTRY_SYNONYMS = {
    "usa": "united states",
    "us": "united states",
    "unitedstates": "united states",
    "unitedstatesofamerica": "united states",
    "uk": "united kingdom",
    "gb": "united kingdom",
    "greatbritain": "united kingdom",
    "unitedkingdom": "united kingdom",
    "fr": "france",
    "france": "france",
    "it": "italy",
    "italia": "italy",
    "italy": "italy",
    "es": "spain",
    "espana": "spain",
    "espaa": "spain",
    "spain": "spain",
    "de": "germany",
    "deutschland": "germany",
    "germany": "germany",
    "pt": "portugal",
    "portugal": "portugal",
    "au": "australia",
    "aus": "australia",
    "australia": "australia",
    "nz": "new zealand",
    "newzealand": "new zealand",
    "ar": "argentina",
    "argentina": "argentina",
    "cl": "chile",
    "chile": "chile",
    "za": "south africa",
    "southafrica": "south africa",
}


def compare_labels(
    expected: ApplicationData | Mapping[str, object],
    found: ApplicationData | Mapping[str, object],
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> VerificationResult:
    started_at = perf_counter()
    expected_data = _coerce_application_data(expected)
    found_data = _coerce_application_data(found)

    results = [
        _compare_field(
            field,
            getattr(expected_data, field),
            getattr(found_data, field),
            fuzzy_threshold,
        )
        for field in LABEL_FIELD_NAMES
    ]
    verdict = (
        "APPROVED"
        if all(result.status == "PASS" for result in results)
        else "NEEDS_REVIEW"
    )
    latency_ms = round((perf_counter() - started_at) * 1000, 3)

    return VerificationResult(
        results=results,
        overall_verdict=verdict,
        latency_ms=latency_ms,
    )


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""

    text = unicodedata.normalize("NFKC", value)
    text = text.replace("&", " and ")
    text = text.casefold()
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    text = re.sub(r"\bco\b", "company", text)
    return re.sub(r"\s+", " ", text).strip()


def _coerce_application_data(
    data: ApplicationData | Mapping[str, object],
) -> ApplicationData:
    if isinstance(data, ApplicationData):
        return data
    return ApplicationData.model_validate(data)


def _compare_field(
    field: str,
    expected: str | None,
    found: str | None,
    fuzzy_threshold: float,
) -> FieldResult:
    if field == GOVERNMENT_WARNING_FIELD:
        return _field_result(
            field,
            "exact_case_sensitive",
            expected,
            found,
            _government_warning_matches(expected, found),
        )

    strategies: Mapping[str, Callable[[str | None, str | None], bool]] = {
        "abv": _abv_matches,
        "net_contents": _net_contents_matches,
        "country_of_origin": _country_matches,
    }

    if field in FUZZY_FIELDS:
        return _field_result(
            field,
            "fuzzy",
            expected,
            found,
            _fuzzy_matches(expected, found, fuzzy_threshold),
        )

    strategy = strategies[field]
    match_type = _match_type_for_field(field)
    return _field_result(field, match_type, expected, found, strategy(expected, found))


def _field_result(
    field: str,
    match_type: MatchType,
    expected: str | None,
    found: str | None,
    matched: bool,
) -> FieldResult:
    return FieldResult(
        field=field,
        match_type=match_type,
        expected=expected,
        found=found,
        status="PASS" if matched else "FAIL",
    )


def _match_type_for_field(field: str) -> MatchType:
    if field == "abv":
        return "abv_numeric_tolerance"
    if field == "net_contents":
        return "net_contents_ml"
    if field == "country_of_origin":
        return "country_synonym"
    raise ValueError(f"Unsupported comparison field: {field}")


def _government_warning_matches(expected: str | None, found: str | None) -> bool:
    if _is_missing(expected) or _is_missing(found):
        return False
    return _collapse_whitespace(expected) == _collapse_whitespace(found)


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _fuzzy_matches(
    expected: str | None,
    found: str | None,
    threshold: float,
) -> bool:
    if _is_missing(expected) and _is_missing(found):
        return True
    if _is_missing(expected) or _is_missing(found):
        return False

    expected_normalized = normalize_text(expected)
    found_normalized = normalize_text(found)
    if not expected_normalized and not found_normalized:
        return True
    if not expected_normalized or not found_normalized:
        return False
    if expected_normalized == found_normalized:
        return True

    score = SequenceMatcher(None, expected_normalized, found_normalized).ratio()
    if score >= threshold:
        return True

    sorted_expected = _token_sort(expected_normalized)
    sorted_found = _token_sort(found_normalized)
    if sorted_expected == sorted_found:
        return True
    sorted_score = SequenceMatcher(None, sorted_expected, sorted_found).ratio()
    return sorted_score >= threshold


def _token_sort(value: str) -> str:
    return " ".join(sorted(value.split()))


def _abv_matches(expected: str | None, found: str | None) -> bool:
    if _is_missing(expected) and _is_missing(found):
        return True
    expected_abv = _extract_abv_percent(expected)
    found_abv = _extract_abv_percent(found)
    if expected_abv is None or found_abv is None:
        return False
    return abs(expected_abv - found_abv) <= ABV_TOLERANCE


def _extract_abv_percent(value: str | None) -> float | None:
    if _is_missing(value):
        return None

    text = unicodedata.normalize("NFKC", value or "")
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent_match:
        return float(percent_match.group(1))

    normalized = normalize_text(text)
    context_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:alc|alcohol|abv|vol)\b",
        normalized,
    )
    if context_match:
        return float(context_match.group(1))

    proof_match = re.search(r"(\d+(?:\.\d+)?)\s*proof\b", normalized)
    if proof_match:
        return float(proof_match.group(1)) / 2

    numbers = re.findall(r"\d+(?:\.\d+)?", normalized)
    if len(numbers) == 1:
        candidate = float(numbers[0])
        if 0 <= candidate <= 100:
            return candidate

    return None


def _net_contents_matches(expected: str | None, found: str | None) -> bool:
    if _is_missing(expected) and _is_missing(found):
        return True
    expected_ml = _extract_net_contents_ml(expected)
    found_ml = _extract_net_contents_ml(found)
    if expected_ml is None or found_ml is None:
        return False
    return abs(expected_ml - found_ml) <= NET_CONTENTS_ML_TOLERANCE


def _extract_net_contents_ml(value: str | None) -> float | None:
    if _is_missing(value):
        return None

    normalized = normalize_text(value)
    normalized = re.sub(r"(?<!\d)\.(?!\d)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(fluid\s*ounces?|fl\s*oz|floz|milliliters?|ml|liters?|litres?|l|"
        r"centiliters?|cl|ounces?|oz)\b",
        normalized,
    )
    if match is None:
        return None

    amount = float(match.group(1))
    unit = re.sub(r"[^a-z]", "", match.group(2))
    return amount * UNIT_TO_ML[unit]


def _country_matches(expected: str | None, found: str | None) -> bool:
    if _is_missing(expected) and _is_missing(found):
        return True
    if _is_missing(expected) or _is_missing(found):
        return False
    return _normalize_country(expected) == _normalize_country(found)


def _normalize_country(value: str) -> str:
    normalized = normalize_text(value)
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    return COUNTRY_SYNONYMS.get(compact, normalized)


def _is_missing(value: str | None) -> bool:
    return value is None or value == ""
