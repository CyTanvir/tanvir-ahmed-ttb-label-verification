from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.vision import DEFAULT_VISION_MODEL


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Confirm the configured OPENAI_VISION_MODEL is present on the "
            "current OpenAI model list. Requires OPENAI_API_KEY."
        )
    )
    parser.add_argument(
        "model",
        nargs="?",
        default=os.getenv("OPENAI_VISION_MODEL", DEFAULT_VISION_MODEL),
        help="Model id to check. Defaults to OPENAI_VISION_MODEL, then the app default.",
    )
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY must be set to check the live model list.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        print(
            "The openai package is required. Install requirements.txt.",
            file=sys.stderr,
        )
        return 2

    client = OpenAI(api_key=api_key)
    available_ids = {model.id for model in client.models.list().data}

    if args.model in available_ids:
        print(f"OK: '{args.model}' is on the current OpenAI model list.")
        return 0

    print(
        f"FAIL: '{args.model}' was not found on the current OpenAI model list.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
