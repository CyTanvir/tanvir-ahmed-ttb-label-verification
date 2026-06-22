import json
import threading
import time

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


def batch_files(*names: str):
    return [
        ("label_images", (name, f"image bytes for {name}".encode(), "image/png"))
        for name in names
    ]


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ttb-label-verification",
        "version": "0.1.0",
    }


def test_frontend_loads_batch_label_verification_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "TTB Label Verification" in response.text
    assert 'const BATCH_VERIFY_ENDPOINT = "/verify/batch";' in response.text
    assert 'name="label_images"' in response.text
    assert "multiple" in response.text
    assert 'payload.append("label_images"' in response.text
    assert 'payload.append("application_data"' in response.text
    for field in APPLICATION_DATA:
        assert f'name="{field}"' in response.text
    assert "overall_verdict" in response.text
    assert "summary" in response.text
    assert "Verification Error" in response.text


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


def test_verify_batch_returns_ordered_summary_and_results() -> None:
    service = FakeVisionService(ExtractedLabel(**APPLICATION_DATA))
    override_vision_service(service)

    try:
        response = client.post(
            "/verify/batch",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files=batch_files("front.png", "back.png", "neck.png"),
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"summary", "labels", "latency_ms"}
    assert data["summary"] == {
        "total": 3,
        "approved": 3,
        "needs_review": 0,
        "errors": 0,
    }
    assert [label["filename"] for label in data["labels"]] == [
        "front.png",
        "back.png",
        "neck.png",
    ]
    assert [label["status"] for label in data["labels"]] == [
        "APPROVED",
        "APPROVED",
        "APPROVED",
    ]
    assert all(label["result"]["overall_verdict"] == "APPROVED" for label in data["labels"])
    assert sorted(call["filename"] for call in service.calls) == [
        "back.png",
        "front.png",
        "neck.png",
    ]


def test_verify_batch_summarizes_approved_review_and_error_results() -> None:
    class FilenameVisionService:
        def extract_label_from_bytes(self, *args, filename=None, **kwargs):
            if filename == "error.png":
                raise VisionPreprocessingError("Unsupported image type: application/octet-stream.")
            if filename == "review.png":
                return ExtractedLabel(
                    **{
                        **APPLICATION_DATA,
                        "brand_name": "Different Estate",
                    }
                )
            return ExtractedLabel(**APPLICATION_DATA)

    override_vision_service(FilenameVisionService())

    try:
        response = client.post(
            "/verify/batch",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files=batch_files("approved.png", "review.png", "error.png"),
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {
        "total": 3,
        "approved": 1,
        "needs_review": 1,
        "errors": 1,
    }
    assert [label["status"] for label in data["labels"]] == [
        "APPROVED",
        "NEEDS_REVIEW",
        "ERROR",
    ]
    assert data["labels"][1]["result"]["overall_verdict"] == "NEEDS_REVIEW"
    assert data["labels"][2]["result"] is None
    assert data["labels"][2]["error"] == "Unsupported image type: application/octet-stream."


def test_verify_batch_reports_empty_file_as_item_error() -> None:
    service = FakeVisionService(ExtractedLabel(**APPLICATION_DATA))
    override_vision_service(service)

    try:
        response = client.post(
            "/verify/batch",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files=[
                ("label_images", ("good.png", b"image bytes", "image/png")),
                ("label_images", ("empty.png", b"", "image/png")),
            ],
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {
        "total": 2,
        "approved": 1,
        "needs_review": 0,
        "errors": 1,
    }
    assert data["labels"][1]["status"] == "ERROR"
    assert data["labels"][1]["error"] == "label_image must not be empty."
    assert len(service.calls) == 1


def test_verify_batch_runs_extractions_concurrently() -> None:
    class SlowVisionService:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def extract_label_from_bytes(self, *args, **kwargs):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)

            try:
                time.sleep(0.08)
                return ExtractedLabel(**APPLICATION_DATA)
            finally:
                with self.lock:
                    self.active -= 1

    service = SlowVisionService()
    override_vision_service(service)

    try:
        response = client.post(
            "/verify/batch",
            data={"application_data": json.dumps(APPLICATION_DATA)},
            files=batch_files("one.png", "two.png", "three.png"),
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["summary"]["approved"] == 3
    assert service.max_active >= 2
