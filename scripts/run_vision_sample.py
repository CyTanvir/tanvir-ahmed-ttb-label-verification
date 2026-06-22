from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models import ExtractedLabel
from app.vision import FakeVisionService, OpenAIVisionService, VisionService


GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

SAMPLE_LABEL = ExtractedLabel(
    brand_name="Example Estate",
    class_type="Cabernet Sauvignon",
    abv="13.5% alc/vol",
    net_contents="750 mL",
    producer="Example Wine Co.",
    country_of_origin="USA",
    government_warning=GOVERNMENT_WARNING,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run VisionService against one label sample image."
    )
    parser.add_argument(
        "image_path",
        nargs="?",
        type=Path,
        default=ROOT_DIR / "scripts" / "sample_label.png",
        help="Path to an image. Defaults to scripts/sample_label.png.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use FakeVisionService so the script can run without an API key.",
    )
    parser.add_argument(
        "--regenerate-sample",
        action="store_true",
        help="Overwrite the default sample label image before running.",
    )
    args = parser.parse_args()

    image_path = ensure_sample_image(
        args.image_path,
        overwrite=args.regenerate_sample,
    )
    service: VisionService
    if args.mock:
        service = FakeVisionService(SAMPLE_LABEL)
    else:
        service = OpenAIVisionService.from_env()

    result = service.extract_label_from_bytes(
        image_path.read_bytes(),
        filename=image_path.name,
    )
    print(result.model_dump_json(indent=2))
    return 0


def ensure_sample_image(path: Path, *, overwrite: bool = False) -> Path:
    if path.exists() and not overwrite:
        return path

    if path.name != "sample_label.png":
        raise FileNotFoundError(f"Image not found: {path}")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Pillow is required to generate the default sample image. "
            "Install requirements.txt or pass an existing image path."
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=32)
    small_font = ImageFont.load_default(size=20)

    draw.rectangle((40, 40, 1360, 860), outline="black", width=4)
    draw.text((90, 95), "EXAMPLE ESTATE", fill="black", font=font)
    draw.text((90, 155), "Cabernet Sauvignon", fill="black", font=font)
    draw.text((90, 235), "ALC. 13.5% BY VOL.", fill="black", font=font)
    draw.text((90, 295), "750 mL", fill="black", font=font)
    draw.text((90, 355), "Produced By", fill="black", font=small_font)
    draw.text((90, 385), "Example Wine Co.", fill="black", font=font)
    draw.text((90, 445), "Product of", fill="black", font=small_font)
    draw.text((90, 475), "USA", fill="black", font=font)
    draw.multiline_text(
        (90, 585),
        wrap_text(draw, GOVERNMENT_WARNING, small_font, max_width=1220),
        fill="black",
        font=small_font,
        spacing=8,
    )
    image.save(path)
    return path


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    *,
    max_width: int,
) -> str:
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word

    if current:
        lines.append(current)

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
