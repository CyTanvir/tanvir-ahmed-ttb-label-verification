from __future__ import annotations

from collections.abc import Mapping
import logging
import os
from typing import Any, Protocol

from app.errors import VisionServiceConfigurationError, VisionServiceError
from app.models import ApplicationData, ExtractedLabel
from app.vision_helpers import (
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_IMAGE_SIDE,
    ImagePreprocessor,
    coerce_extracted_label,
    parse_extracted_label_response,
)

DEFAULT_VISION_MODEL = "gpt-4.1-mini"
DEFAULT_TIMEOUT_SECONDS = 4.25
DEFAULT_REASONING_EFFORT = ""
DEFAULT_IMAGE_DETAIL = "low"
DEFAULT_MAX_OUTPUT_TOKENS = 300
IMAGE_DETAIL_VALUES = frozenset({"low", "high", "auto", "original"})

EXTRACTION_PROMPT = """
Extract TTB alcohol label fields from this image.

Fields: brand_name, class_type, abv, net_contents, producer,
country_of_origin, government_warning, raw_text, extraction_confidence.
Return only the structured fields. Use null for any field that is not visible.
For government_warning, preserve exact capitalization, punctuation, and wording.
For raw_text, briefly list any label text not already captured in the fields
above (do not repeat government_warning verbatim again); keep it under 200
characters.
For extraction_confidence, give your overall confidence in this extraction as a
number from 0.0 to 1.0.
Do not infer values that are not visible on the label.
""".strip()

logger = logging.getLogger(__name__)


class VisionService(Protocol):
    def extract_label_from_bytes(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        """Extract label fields from one uploaded image."""


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
            logger.exception("Vision extraction request failed.")
            raise VisionServiceError("Vision extraction request failed.") from exc

        return parse_extracted_label_response(response)

    def warm_up(self) -> None:
        """Best-effort: exercise the real responses endpoint for this model
        ahead of the first user request. A ping to /v1/models only warms the
        TCP/TLS connection, not whatever OpenAI provisions server-side for a
        model's first /v1/responses call, which is where the real first-hit
        latency lives."""
        try:
            self._client.responses.create(
                model=self.model,
                input="ping",
                max_output_tokens=16,
                store=False,
                timeout=self.timeout_seconds,
            )
        except Exception:  # pragma: no cover - best-effort only
            logger.exception("Vision service warm-up call failed.")

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
        self.label = coerce_extracted_label(label)
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
