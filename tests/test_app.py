import json

from fastapi.testclient import TestClient

from app.main import app, get_vision_service_factory
from app.models import ExtractedLabel
from app.vision import FakeVisionService, VisionPreprocessingError


client = TestClient(app)

GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

APPLICATION_DATA = {
    "brand_name": "Example Estate",
    "class_type": "Cabernet Sauvignon",
    "abv": "13.5% alc/vol",
    "net_contents": "750 mL",
    "producer": "Example Wine Co.",
    "country_of_origin": "USA",
    "government_warning": GOVERNMENT_WARNING,
}


def override_vision_service(service):
    app.dependency_overrides[get_vision_service_factory] = lambda: lambda: service


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ttb-label-verification",
        "version": "0.1.0",
    }


def test_frontend_loads_health_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "TTB Label Verification" in response.text
    assert 'fetch("/health"' in response.text


def test_verify_label_returns_full_verification_result() -> None:
    service = FakeVisionService(ExtractedLabel(**APPLICATION_DATA))
    override_vision_service(service)

    try:
        response = client.post(
            "/verify",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files={"label_image": ("label.png", b"image bytes", "image/png")},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"results", "overall_verdict", "latency_ms"}
    assert data["overall_verdict"] == "APPROVED"
    assert data["latency_ms"] >= 0
    assert len(data["results"]) == 7
    assert all(result["status"] == "PASS" for result in data["results"])
    assert data["results"][0] == {
        "field": "brand_name",
        "match_type": "fuzzy",
        "expected": "Example Estate",
        "found": "Example Estate",
        "status": "PASS",
    }
    assert service.calls[0]["filename"] == "label.png"
    assert service.calls[0]["content_type"] == "image/png"


def test_verify_label_rejects_malformed_application_data() -> None:
    service = FakeVisionService(ExtractedLabel(**APPLICATION_DATA))
    override_vision_service(service)

    try:
        response = client.post(
            "/verify",
            data={"application_data": "{not json"},
            files={"label_image": ("label.png", b"image bytes", "image/png")},
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert response.json() == {"detail": "application_data must be valid JSON."}
    assert service.calls == []


def test_verify_label_rejects_empty_image_upload() -> None:
    service = FakeVisionService(ExtractedLabel(**APPLICATION_DATA))
    override_vision_service(service)

    try:
        response = client.post(
            "/verify",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files={"label_image": ("empty.png", b"", "image/png")},
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert response.json() == {"detail": "label_image must not be empty."}
    assert service.calls == []


def test_verify_label_returns_readable_image_error() -> None:
    class FailingVisionService:
        def extract_label_from_bytes(self, *args, **kwargs):
            raise VisionPreprocessingError("Unsupported image type: application/octet-stream.")

    override_vision_service(FailingVisionService())

    try:
        response = client.post(
            "/verify",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files={"label_image": ("label.txt", b"not an image", "text/plain")},
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported image type: application/octet-stream."
    }
