from types import SimpleNamespace

import pytest

from app.errors import (
    VisionParsingError,
    VisionPreprocessingError,
    VisionServiceConfigurationError,
)
from app.models import ExtractedLabel
from app.vision import FakeVisionService, OpenAIVisionService
from app.vision_helpers import ImagePreprocessor, parse_extracted_label_response


SAMPLE_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfeA\x0c\xb2\x00\x00\x00\x00IEND\xaeB`\x82"
)


def populated_label() -> ExtractedLabel:
    return ExtractedLabel(
        brand_name="Example Estate",
        class_type="Cabernet Sauvignon",
        abv="13.5% alc/vol",
        net_contents="750 mL",
        producer="Example Wine Co.",
        country_of_origin="USA",
        government_warning="GOVERNMENT WARNING: Example exact warning.",
    )


def test_fake_vision_service_returns_configured_label_and_records_call() -> None:
    service = FakeVisionService(populated_label())

    result = service.extract_label_from_bytes(
        SAMPLE_PNG_BYTES,
        filename="sample.png",
        content_type="image/png",
    )

    assert result.brand_name == "Example Estate"
    assert result.government_warning == "GOVERNMENT WARNING: Example exact warning."
    assert service.calls[0]["filename"] == "sample.png"


def test_preprocessor_returns_data_url_for_supported_image() -> None:
    preprocessor = ImagePreprocessor()

    image = preprocessor.prepare(
        SAMPLE_PNG_BYTES,
        filename="sample.png",
        content_type="image/png",
    )

    assert image.media_type in {"image/png", "image/jpeg"}
    assert image.data_url.startswith(f"data:{image.media_type};base64,")


def test_preprocessor_rejects_unknown_image_bytes() -> None:
    preprocessor = ImagePreprocessor()

    with pytest.raises(VisionPreprocessingError):
        preprocessor.prepare(
            b"not an image",
            filename="sample.png",
            content_type="image/png",
        )


def test_parse_structured_output_parsed_response() -> None:
    response = SimpleNamespace(output_parsed=populated_label())

    result = parse_extracted_label_response(response)

    assert result.brand_name == "Example Estate"


def test_parse_fenced_json_with_friendly_keys() -> None:
    response = SimpleNamespace(
        output_text="""
        ```json
        {
          "brand name": "Example Estate",
          "Class Type": "Red Wine",
          "ABV": "13.5% alc/vol",
          "Net Contents": "750 mL",
          "Producer": "Example Wine Co.",
          "Country of Origin": "United States",
          "Government Warning": "GOVERNMENT WARNING: Example exact warning."
        }
        ```
        """
    )

    result = parse_extracted_label_response(response)

    assert result.class_type == "Red Wine"
    assert result.net_contents == "750 mL"
    assert result.country_of_origin == "United States"


def test_empty_response_raises_parsing_error() -> None:
    response = SimpleNamespace(output_text='{"brand_name": null}')

    with pytest.raises(VisionParsingError):
        parse_extracted_label_response(response)


def test_openai_service_from_env_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(VisionServiceConfigurationError):
        OpenAIVisionService.from_env()


def test_openai_service_uses_tuned_stateless_request() -> None:
    class RecordingResponses:
        def __init__(self) -> None:
            self.request = {}

        def parse(self, **request):
            self.request = request
            return SimpleNamespace(output_parsed=populated_label())

    class RecordingClient:
        def __init__(self) -> None:
            self.responses = RecordingResponses()

    client = RecordingClient()
    service = OpenAIVisionService(
        api_key="test-key",
        client=client,
        timeout_seconds=3.5,
        reasoning_effort=None,
        image_detail="low",
        max_output_tokens=321,
    )

    result = service.extract_label_from_bytes(
        SAMPLE_PNG_BYTES,
        filename="sample.png",
        content_type="image/png",
    )

    request = client.responses.request
    image_part = request["input"][0]["content"][1]
    assert result.brand_name == "Example Estate"
    assert image_part["type"] == "input_image"
    assert image_part["detail"] == "low"
    assert image_part["image_url"].startswith("data:image/")
    assert request["max_output_tokens"] == 321
    assert request["store"] is False
    assert request["timeout"] == 3.5
    assert "reasoning" not in request


def test_openai_service_disables_sdk_retries() -> None:
    service = OpenAIVisionService(api_key="test-key")

    assert service._client.max_retries == 0


def test_openai_service_rejects_invalid_image_detail() -> None:
    with pytest.raises(VisionServiceConfigurationError):
        OpenAIVisionService(
            api_key="test-key",
            client=SimpleNamespace(),
            image_detail="tiny",
        )
