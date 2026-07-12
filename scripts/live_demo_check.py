from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from PIL import Image, ImageEnhance, ImageFilter


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = ROOT_DIR / "scripts" / "sample_label.png"
GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
EXPECTED_APPLICATION_DATA = {
    "brand_name": "Example Estate",
    "class_type": "Cabernet Sauvignon",
    "abv": "13.5% alc/vol",
    "net_contents": "750 mL",
    "producer": "Example Wine Co.",
    "country_of_origin": "USA",
    "government_warning": GOVERNMENT_WARNING,
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the live deployed-demo verification checklist."
    )
    parser.add_argument(
        "base_url",
        help="Deployed app URL, such as https://example.up.railway.app.",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_IMAGE,
        help="Sample label image to upload. Defaults to scripts/sample_label.png.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for each request.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print compact per-field details for failed checks.",
    )
    args = parser.parse_args()

    try:
        results = run_checks(
            normalize_base_url(args.base_url),
            image_path=args.image,
            timeout_seconds=args.timeout,
            verbose=args.verbose,
        )
    except Exception as exc:  # pragma: no cover - command-line safety net
        print(f"FAIL live demo check could not run: {exc}", file=sys.stderr)
        return 1

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.name}: {result.detail}")

    return 0 if all(result.passed for result in results) else 1


def normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        raise ValueError("base_url is required.")
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"
    return base_url


def run_checks(
    base_url: str,
    *,
    image_path: Path = DEFAULT_IMAGE,
    timeout_seconds: float = 30.0,
    verbose: bool = False,
) -> list[CheckResult]:
    image_bytes = image_path.read_bytes()
    imperfect_image_bytes = make_imperfect_image_bytes(image_bytes)

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        return [
            check_health(client, base_url),
            check_single_label(client, base_url, image_bytes, verbose=verbose),
            check_batch_labels(client, base_url, image_bytes, imperfect_image_bytes),
            check_warning_exact_match(client, base_url, image_bytes),
            check_imperfect_image(client, base_url, imperfect_image_bytes),
        ]


def check_health(client: httpx.Client, base_url: str) -> CheckResult:
    try:
        response = client.get(f"{base_url}/health")
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return CheckResult("health", False, str(exc))

    passed = payload.get("status") == "ok"
    detail = json.dumps(payload, sort_keys=True)
    return CheckResult("health", passed, detail)


def check_single_label(
    client: httpx.Client,
    base_url: str,
    image_bytes: bytes,
    *,
    verbose: bool = False,
) -> CheckResult:
    started_at = perf_counter()
    try:
        payload = post_single(client, base_url, image_bytes, EXPECTED_APPLICATION_DATA)
    except Exception as exc:
        return CheckResult("single label", False, str(exc))

    elapsed_ms = round((perf_counter() - started_at) * 1000)
    verdict = payload.get("overall_verdict")
    latency_ms = payload.get("latency_ms")
    passed = verdict == "APPROVED" and elapsed_ms < 5000
    detail = f"verdict={verdict}, server_latency_ms={latency_ms}, wall_ms={elapsed_ms}"
    if verbose and not passed:
        detail = f"{detail}, fields={format_field_results(payload)}"
    return CheckResult("single label", passed, detail)


def check_batch_labels(
    client: httpx.Client,
    base_url: str,
    image_bytes: bytes,
    imperfect_image_bytes: bytes,
) -> CheckResult:
    files = [
        ("label_images", ("sample_label.png", image_bytes, "image/png")),
        ("label_images", ("imperfect_sample_label.jpg", imperfect_image_bytes, "image/jpeg")),
    ]
    try:
        response = client.post(
            f"{base_url}/verify/batch",
            data={"application_data": json.dumps(EXPECTED_APPLICATION_DATA)},
            files=files,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return CheckResult("batch labels", False, str(exc))

    summary = payload.get("summary", {})
    items = payload.get("items", [])
    total = summary.get("total")
    item_errors = sum(1 for item in items if item.get("status") == "ERROR")
    passed = total == 2 and item_errors == 0 and len(items) == 2
    detail = f"summary={json.dumps(summary, sort_keys=True)}"
    return CheckResult("batch labels", passed, detail)


def check_warning_exact_match(
    client: httpx.Client,
    base_url: str,
    image_bytes: bytes,
) -> CheckResult:
    expected = {
        **EXPECTED_APPLICATION_DATA,
        "government_warning": GOVERNMENT_WARNING.replace(
            "GOVERNMENT WARNING:",
            "Government WARNING:",
            1,
        ),
    }

    try:
        payload = post_single(client, base_url, image_bytes, expected)
    except Exception as exc:
        return CheckResult("warning exact match", False, str(exc))

    warning = find_field(payload, "government_warning")
    passed = (
        payload.get("overall_verdict") == "NEEDS_REVIEW"
        and warning.get("match_type") == "exact_case_sensitive"
        and warning.get("status") == "FAIL"
    )
    detail = (
        f"verdict={payload.get('overall_verdict')}, "
        f"warning_status={warning.get('status')}, "
        f"match_type={warning.get('match_type')}"
    )
    return CheckResult("warning exact match", passed, detail)


def check_imperfect_image(
    client: httpx.Client,
    base_url: str,
    imperfect_image_bytes: bytes,
) -> CheckResult:
    try:
        payload = post_single(
            client,
            base_url,
            imperfect_image_bytes,
            EXPECTED_APPLICATION_DATA,
            filename="imperfect_sample_label.jpg",
            content_type="image/jpeg",
        )
    except Exception as exc:
        return CheckResult("imperfect image", False, str(exc))

    verdict = payload.get("overall_verdict")
    result_count = len(payload.get("results", []))
    passed = verdict in {"APPROVED", "NEEDS_REVIEW"} and result_count == 7
    detail = f"verdict={verdict}, result_count={result_count}"
    return CheckResult("imperfect image", passed, detail)


def post_single(
    client: httpx.Client,
    base_url: str,
    image_bytes: bytes,
    expected: dict[str, str],
    *,
    filename: str = "sample_label.png",
    content_type: str = "image/png",
) -> dict[str, Any]:
    response = client.post(
        f"{base_url}/verify",
        data={"application_data": json.dumps(expected)},
        files={"label_image": (filename, image_bytes, content_type)},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Response JSON was not an object.")
    return payload


def find_field(payload: dict[str, Any], field: str) -> dict[str, Any]:
    for item in payload.get("results", []):
        if item.get("field") == field:
            return item
    return {}


def format_field_results(payload: dict[str, Any]) -> str:
    items = []
    for item in payload.get("results", []):
        field = item.get("field")
        status = item.get("status")
        expected = compact_value(item.get("expected"))
        found = compact_value(item.get("found"))
        items.append(f"{field}:{status} expected={expected} found={found}")
    return " | ".join(items)


def compact_value(value: Any) -> str:
    text = "null" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) > 90:
        return f"{text[:87]}..."
    return text


def make_imperfect_image_bytes(image_bytes: bytes) -> bytes:
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        image = image.rotate(1.4, expand=True, fillcolor="white")
        image = ImageEnhance.Contrast(image).enhance(0.82)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.45))
        image.thumbnail((1150, 850))

        output = BytesIO()
        image.save(output, format="JPEG", quality=72, optimize=True)
        return output.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
