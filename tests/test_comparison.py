from app.comparison import compare_labels
from app.models import LABEL_FIELD_NAMES, LabelData


GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)


def field_by_name(result, name: str):
    return next(field for field in result.fields if field.name == name)


def test_label_data_exposes_phase_one_fields() -> None:
    label = LabelData(
        brand_name="Example Estate",
        product_type="Red Wine",
        alcohol_content="13.5% alc/vol",
        net_contents="750 mL",
        sulfite_statement="Contains Sulfites",
        government_warning=GOVERNMENT_WARNING,
    )

    assert tuple(LABEL_FIELD_NAMES) == (
        "brand_name",
        "product_type",
        "alcohol_content",
        "net_contents",
        "sulfite_statement",
        "government_warning",
    )
    assert label.brand_name == "Example Estate"
    assert label.government_warning == GOVERNMENT_WARNING


def test_non_warning_fields_are_normalized_and_fuzzy_matched() -> None:
    expected = LabelData(
        brand_name="Example Estate",
        product_type="Cabernet Sauvignon",
        alcohol_content="13.5% alc/vol",
        net_contents="750 mL",
        sulfite_statement="Contains Sulfites",
        government_warning=GOVERNMENT_WARNING,
    )
    extracted = LabelData(
        brand_name="  example    estate  ",
        product_type="cabernet sauvignn",
        alcohol_content="13.5 alc vol",
        net_contents="750 ml",
        sulfite_statement="contains sulfites",
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, extracted)

    assert result.matched is True
    assert field_by_name(result, "brand_name").comparison == "fuzzy_normalized"
    assert field_by_name(result, "product_type").matched is True
    assert field_by_name(result, "product_type").score >= 0.85


def test_missing_non_warning_field_fails_comparison() -> None:
    expected = LabelData(
        brand_name="Example Estate",
        government_warning=GOVERNMENT_WARNING,
    )
    extracted = LabelData(
        brand_name=None,
        government_warning=GOVERNMENT_WARNING,
    )

    result = compare_labels(expected, extracted)

    assert result.matched is False
    assert field_by_name(result, "brand_name").matched is False
    assert field_by_name(result, "brand_name").score == 0.0


def test_government_warning_is_strict_case_sensitive_match() -> None:
    expected = LabelData(
        brand_name="Example Estate",
        government_warning=GOVERNMENT_WARNING,
    )
    extracted = LabelData(
        brand_name="example estate",
        government_warning=GOVERNMENT_WARNING.replace(
            "GOVERNMENT WARNING", "Government Warning"
        ),
    )

    result = compare_labels(expected, extracted)
    warning = field_by_name(result, "government_warning")

    assert result.matched is False
    assert warning.comparison == "strict_case_sensitive"
    assert warning.matched is False
    assert warning.score == 0.0
