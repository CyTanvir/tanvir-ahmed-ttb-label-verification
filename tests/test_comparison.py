from app.comparison import compare_labels
from app.models import LABEL_FIELD_NAMES, ApplicationData


GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)


def result_for(result, field: str):
    return next(item for item in result.results if item.field == field)


def test_application_data_exposes_phase_one_fields() -> None:
    application = ApplicationData(
        brand_name="Example Estate",
        class_type="Red Wine",
        abv="13.5% alc/vol",
        net_contents="750 mL",
        producer="Example Wine Co.",
        country_of_origin="USA",
        government_warning=GOVERNMENT_WARNING,
    )

    assert tuple(LABEL_FIELD_NAMES) == (
        "brand_name",
        "class_type",
        "abv",
        "net_contents",
        "producer",
        "country_of_origin",
        "government_warning",
    )
    assert "product_type" not in LABEL_FIELD_NAMES
    assert "sulfite_statement" not in LABEL_FIELD_NAMES
    assert application.class_type == "Red Wine"
    assert application.government_warning == GOVERNMENT_WARNING


def test_fuzzy_fields_pass_after_normalization() -> None:
    expected = ApplicationData(
        brand_name="Example Estate",
        class_type="Cabernet Sauvignon",
        abv="13.5% alc/vol",
        net_contents="750 mL",
        producer="Example Wine Co.",
        country_of_origin="USA",
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        brand_name="  example    estate  ",
        class_type="cabernet sauvignn",
        abv="13.5 alc vol",
        net_contents="750ml",
        producer="example wine company",
        country_of_origin="United States",
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, found)

    assert result.overall_verdict == "APPROVED"
    assert result.latency_ms >= 0.0
    assert result_for(result, "brand_name").match_type == "fuzzy"
    assert result_for(result, "class_type").status == "PASS"
    assert result_for(result, "producer").status == "PASS"


def test_missing_expected_field_fails_comparison() -> None:
    expected = ApplicationData(
        brand_name="Example Estate",
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        brand_name=None,
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, found)
    brand = result_for(result, "brand_name")

    assert result.overall_verdict == "NEEDS_REVIEW"
    assert brand.match_type == "fuzzy"
    assert brand.status == "FAIL"


def test_abv_numeric_extraction_accepts_proof_context() -> None:
    expected = ApplicationData(
        abv="45%",
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        abv="45% Alc./Vol. (90 Proof)",
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, found)
    abv = result_for(result, "abv")

    assert result.overall_verdict == "APPROVED"
    assert abv.match_type == "abv_numeric_tolerance"
    assert abv.status == "PASS"


def test_net_contents_unit_normalizes_to_ml() -> None:
    expected = ApplicationData(
        net_contents="750 mL",
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        net_contents="750ml",
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, found)
    net_contents = result_for(result, "net_contents")

    assert result.overall_verdict == "APPROVED"
    assert net_contents.match_type == "net_contents_ml"
    assert net_contents.status == "PASS"


def test_country_of_origin_synonyms_pass() -> None:
    expected = ApplicationData(
        country_of_origin="USA",
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        country_of_origin="United States",
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, found)
    country = result_for(result, "country_of_origin")

    assert result.overall_verdict == "APPROVED"
    assert country.match_type == "country_synonym"
    assert country.status == "PASS"


def test_government_warning_missing_colon_fails_strict_case_sensitive_match() -> None:
    expected = ApplicationData(
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        government_warning=GOVERNMENT_WARNING.replace(
            "GOVERNMENT WARNING:", "GOVERNMENT WARNING"
        ),
    )

    result = compare_labels(expected, found)
    warning = result_for(result, "government_warning")

    assert result.overall_verdict == "NEEDS_REVIEW"
    assert warning.match_type == "exact_case_sensitive"
    assert warning.status == "FAIL"


def test_government_warning_correct_all_caps_passes_strict_case_sensitive_match() -> None:
    expected = ApplicationData(
        government_warning=GOVERNMENT_WARNING,
    )
    found = ApplicationData(
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, found)
    warning = result_for(result, "government_warning")

    assert result.overall_verdict == "APPROVED"
    assert warning.match_type == "exact_case_sensitive"
    assert warning.status == "PASS"
