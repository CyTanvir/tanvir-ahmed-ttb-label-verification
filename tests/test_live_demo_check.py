import httpx

from scripts.live_demo_check import (
    GOVERNMENT_WARNING,
    check_warning_exact_match,
    make_imperfect_image_bytes,
    normalize_base_url,
)
from tests.test_vision import SAMPLE_PNG_BYTES


def test_normalize_base_url_adds_https_and_removes_trailing_slash() -> None:
    assert normalize_base_url("demo.example.com/") == "https://demo.example.com"
    assert normalize_base_url("http://localhost:8000/") == "http://localhost:8000"


def test_make_imperfect_image_bytes_returns_jpeg() -> None:
    result = make_imperfect_image_bytes(SAMPLE_PNG_BYTES)

    assert result.startswith(b"\xff\xd8\xff")
    assert len(result) > 100


def test_warning_exact_match_check_requires_case_sensitive_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "overall_verdict": "NEEDS_REVIEW",
                "latency_ms": 10,
                "results": [
                    {
                        "field": "government_warning",
                        "match_type": "exact_case_sensitive",
                        "expected": GOVERNMENT_WARNING.replace(
                            "GOVERNMENT WARNING:",
                            "Government WARNING:",
                            1,
                        ),
                        "found": GOVERNMENT_WARNING,
                        "status": "FAIL",
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = check_warning_exact_match(client, "https://demo.example.com", b"image")

    assert result.passed is True
    assert "warning_status=FAIL" in result.detail
