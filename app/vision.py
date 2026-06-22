from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
import json
import os
import re
from typing import Any, Protocol

from pydantic import BaseModel

from app.models import ApplicationData, ExtractedLabel, LABEL_FIELD_NAMES


DEFAULT_VISION_MODEL = "gpt-5.4-mini"
DEFAULT_TIMEOUT_SECONDS = 4.25
DEFAULT_REASONING_EFFORT = ""
DEFAULT_IMAGE_DETAIL = "low"
DEFAULT_MAX_OUTPUT_TOKENS = 450
DEFAULT_MAX_IMAGE_SIDE = 1280
DEFAULT_MAX_IMAGE_BYTES = 1_000_000
MAX_RAW_IMAGE_BYTES = 12_000_000
IMAGE_DETAIL_VALUES = frozenset({"low", "high", "auto", "original"})

EXTRACTION_PROMPT = """
Extract TTB alcohol label fields from this image.

Fields: brand_name, class_type, abv, net_contents, producer,
country_of_origin, government_warning.
Return only the structured fields. Use null for any field that is not visible.
For government_warning, preserve exact capitalization, punctuation, and wording.
Do not infer values that are not visible on the label.
""".strip()

SUPPORTED_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


class VisionServiceError(RuntimeError):
    """Base error for image extraction failures."""


class VisionServiceConfigurationError(VisionServiceError):
    """Raised when the real vision service is missing required configuration."""


class VisionPreprocessingError(VisionServiceError):
    """Raised when uploaded image bytes cannot be prepared for the model."""


class VisionParsingError(VisionServiceError):
    """Raised when a model response cannot be converted into ExtractedLabel."""


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


class VisionService(Protocol):
    def extract_label_from_bytes(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        """Extract label fields from one uploaded image."""


class ImagePreprocessor:
    def __init__(
        self,
        *,
        max_side: int = DEFAULT_MAX_IMAGE_SIDE,
        max_output_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        max_raw_bytes: int = MAX_RAW_IMAGE_BYTES,
    ) -> None:
        self.max_side = max_side
        self.max_output_bytes = max_output_bytes
        self.max_raw_bytes = max_raw_bytes

    def prepare(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> PreparedImage:
        if not image_bytes:
            raise VisionPreprocessingError("Image upload is empty.")
        if len(image_bytes) > self.max_raw_bytes:
            raise VisionPreprocessingError("Image upload is too large.")

        media_type = _detect_media_type(image_bytes, filename, content_type)
        if media_type not in SUPPORTED_MEDIA_TYPES:
            raise VisionPreprocessingError(f"Unsupported image type: {media_type}.")

        try:
            return self._prepare_with_pillow(image_bytes)
        except ModuleNotFoundError:
            return PreparedImage(data=image_bytes, media_type=media_type)
        except VisionPreprocessingError:
            raise
        except Exception as exc:  # pragma: no cover - exact Pillow errors vary
            raise VisionPreprocessingError("Image could not be decoded.") from exc

    def _prepare_with_pillow(self, image_bytes: bytes) -> PreparedImage:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(image_bytes)) as image:
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((self.max_side, self.max_side))

            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGBA"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            for quality in (88, 82, 74, 66):
                output = BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                data = output.getvalue()
                if len(data) <= self.max_output_bytes:
                    return PreparedImage(data=data, media_type="image/jpeg")

        raise VisionPreprocessingError("Image remains too large after preprocessing.")


class OpenAIVisionService:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_VISION_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
        image_detail: str = DEFAULT_IMAGE_DETAIL,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        preprocessor: ImagePreprocessor | None = None,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise VisionServiceConfigurationError(
                "OPENAI_API_KEY must be set to use OpenAIVisionService."
            )
        if image_detail not in IMAGE_DETAIL_VALUES:
            raise VisionServiceConfigurationError(
                "OPENAI_IMAGE_DETAIL must be one of: auto, high, low, original."
            )

        self.model = model
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.image_detail = image_detail
        self.max_output_tokens = max_output_tokens
        self.preprocessor = preprocessor or ImagePreprocessor()
        self._client = client or self._build_client(api_key, timeout_seconds)

    @classmethod
    def from_env(cls) -> OpenAIVisionService:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise VisionServiceConfigurationError(
                "OPENAI_API_KEY must be set to use OpenAIVisionService."
            )

        model = os.getenv("OPENAI_VISION_MODEL", DEFAULT_VISION_MODEL)
        timeout_seconds = float(
            os.getenv("OPENAI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        reasoning_effort = os.getenv(
            "OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
        )
        image_detail = os.getenv("OPENAI_IMAGE_DETAIL", DEFAULT_IMAGE_DETAIL)
        max_output_tokens = int(
            os.getenv("OPENAI_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
        )
        max_image_side = int(
            os.getenv("IMAGE_MAX_SIDE", str(DEFAULT_MAX_IMAGE_SIDE))
        )
        max_image_bytes = int(
            os.getenv("IMAGE_MAX_BYTES", str(DEFAULT_MAX_IMAGE_BYTES))
        )
        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort or None,
            image_detail=image_detail,
            max_output_tokens=max_output_tokens,
            preprocessor=ImagePreprocessor(
                max_side=max_image_side,
                max_output_bytes=max_image_bytes,
            ),
        )

    def extract_label_from_bytes(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        image = self.preprocessor.prepare(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )

        request: dict[str, Any] = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": EXTRACTION_PROMPT},
                        {
                            "type": "input_image",
                            "image_url": image.data_url,
                            "detail": self.image_detail,
                        },
                    ],
                }
            ],
            "text_format": ExtractedLabel,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
            "timeout": self.timeout_seconds,
        }
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}

        try:
            response = self._client.responses.parse(**request)
        except Exception as exc:  # pragma: no cover - network/API behavior
            raise VisionServiceError("Vision extraction request failed.") from exc

        return parse_extracted_label_response(response)

    @staticmethod
    def _build_client(api_key: str, timeout_seconds: float) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise VisionServiceConfigurationError(
                "The openai package is required for OpenAIVisionService. "
                "Install project dependencies from requirements.txt."
            ) from exc

        return OpenAI(api_key=api_key, timeout=timeout_seconds)


class FakeVisionService:
    def __init__(
        self,
        label: ExtractedLabel | ApplicationData | Mapping[str, Any],
    ) -> None:
        self.label = _coerce_extracted_label(label)
        self.calls: list[dict[str, Any]] = []

    def extract_label_from_bytes(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        self.calls.append(
            {
                "image_bytes": image_bytes,
                "filename": filename,
                "content_type": content_type,
            }
        )
        return self.label.model_copy()


def parse_extracted_label_response(response: Any) -> ExtractedLabel:
    for candidate in _response_candidates(response):
        try:
            label = _coerce_extracted_label(candidate)
        except VisionParsingError:
            continue
        if _has_any_populated_field(label):
            return label

    raise VisionParsingError("Model response did not contain a populated label.")


def _response_candidates(response: Any) -> list[Any]:
    candidates: list[Any] = []

    direct = getattr(response, "output_parsed", None)
    if direct is not None:
        candidates.append(direct)

    if isinstance(response, Mapping):
        for key in ("output_parsed", "parsed", "label", "extracted_label"):
            if response.get(key) is not None:
                candidates.append(response[key])

    output = getattr(response, "output", None)
    if output is None and isinstance(response, Mapping):
        output = response.get("output")

    if output:
        for item in output:
            candidates.extend(_output_item_candidates(item))

    output_text = getattr(response, "output_text", None)
    if output_text:
        candidates.append(output_text)
    if isinstance(response, Mapping) and response.get("output_text"):
        candidates.append(response["output_text"])

    candidates.append(response)
    return candidates


def _output_item_candidates(item: Any) -> list[Any]:
    candidates: list[Any] = []
    content = getattr(item, "content", None)
    if content is None and isinstance(item, Mapping):
        content = item.get("content")

    if content is None:
        return candidates

    for part in content:
        part_type = getattr(part, "type", None)
        if part_type is None and isinstance(part, Mapping):
            part_type = part.get("type")
        if part_type == "refusal":
            refusal = getattr(part, "refusal", None)
            if refusal is None and isinstance(part, Mapping):
                refusal = part.get("refusal")
            raise VisionParsingError(f"Model refused extraction: {refusal}")

        parsed = getattr(part, "parsed", None)
        if parsed is None and isinstance(part, Mapping):
            parsed = part.get("parsed")
        if parsed is not None:
            candidates.append(parsed)

        text = getattr(part, "text", None)
        if text is None and isinstance(part, Mapping):
            text = part.get("text")
        if text:
            candidates.append(text)

    return candidates


def _coerce_extracted_label(value: Any) -> ExtractedLabel:
    if isinstance(value, ExtractedLabel):
        return value

    if isinstance(value, ApplicationData):
        return ExtractedLabel.model_validate(value.model_dump())

    if isinstance(value, BaseModel):
        value = value.model_dump()

    if isinstance(value, str):
        value = _loads_json_object(value)

    if isinstance(value, Mapping):
        value = _unwrap_label_payload(value)
        return ExtractedLabel.model_validate(_normalize_label_keys(value))

    raise VisionParsingError("Response candidate is not a label payload.")


def _unwrap_label_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("label", "extracted_label", "data"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            return nested
    return value


def _normalize_label_keys(value: Mapping[str, Any]) -> dict[str, Any]:
    canonical_keys = {_canonical_key(name): name for name in LABEL_FIELD_NAMES}
    normalized: dict[str, Any] = {}

    for key, field_value in value.items():
        canonical = canonical_keys.get(_canonical_key(str(key)))
        if canonical is not None:
            normalized[canonical] = field_value

    return normalized


def _canonical_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _loads_json_object(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise VisionParsingError("Text response does not contain a JSON object.")

    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisionParsingError("Text response contains invalid JSON.") from exc

    if not isinstance(parsed, Mapping):
        raise VisionParsingError("Text response JSON is not an object.")
    return parsed


def _has_any_populated_field(label: ExtractedLabel) -> bool:
    return any(getattr(label, name) for name in LABEL_FIELD_NAMES)


def _detect_media_type(
    image_bytes: bytes,
    filename: str | None,
    content_type: str | None,
) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    return "application/octet-stream"
