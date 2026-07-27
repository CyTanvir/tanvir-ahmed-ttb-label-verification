from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

import httpx

from scripts.live_demo_check import EXPECTED_APPLICATION_DATA, normalize_base_url

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = ROOT_DIR / "scripts" / "sample_label.png"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure single-label /verify latency (p50/p95) against a "
        "running instance."
    )
    parser.add_argument(
        "base_url",
        help="Target app URL, such as https://example.onrender.com.",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=20,
        help="Number of sequential /verify requests to send. Default: 20.",
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
    args = parser.parse_args()

    base_url = normalize_base_url(args.base_url)
    image_bytes = args.image.read_bytes()

    latencies_ms: list[float] = []
    with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
        for i in range(args.requests):
            started_at = perf_counter()
            try:
                response = client.post(
                    f"{base_url}/verify",
                    data={"application_data": json.dumps(EXPECTED_APPLICATION_DATA)},
                    files={"label_image": ("sample_label.png", image_bytes, "image/png")},
                )
                response.raise_for_status()
            except Exception as exc:
                print(f"FAIL request {i + 1}/{args.requests}: {exc}", file=sys.stderr)
                continue
            elapsed_ms = (perf_counter() - started_at) * 1000
            latencies_ms.append(elapsed_ms)
            print(f"request {i + 1}/{args.requests}: {elapsed_ms:.0f} ms")

    if not latencies_ms:
        print("FAIL no successful requests", file=sys.stderr)
        return 1

    print(format_summary(latencies_ms))
    return 0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def format_summary(latencies_ms: list[float]) -> str:
    return (
        f"n={len(latencies_ms)} "
        f"min={min(latencies_ms):.0f}ms "
        f"p50={percentile(latencies_ms, 50):.0f}ms "
        f"p95={percentile(latencies_ms, 95):.0f}ms "
        f"max={max(latencies_ms):.0f}ms"
    )


if __name__ == "__main__":
    raise SystemExit(main())
