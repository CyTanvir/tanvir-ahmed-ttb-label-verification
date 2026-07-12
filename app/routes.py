from collections.abc import Callable, Mapping
import asyncio
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.comparison import compare_labels
from app.errors import (
    VisionParsingError,
    VisionPreprocessingError,
    VisionServiceConfigurationError,
    VisionServiceError,
)
from app.models import (
    ApplicationData,
    BatchLabelResult,
    BatchSummary,
    BatchVerificationResult,
    VerificationResult,
)
from app.vision import OpenAIVisionService, VisionService

DEFAULT_MAX_BATCH_LABELS = 10
DEFAULT_MAX_BATCH_CONCURRENCY = 4
MAX_BATCH_LABELS = int(os.getenv("MAX_BATCH_LABELS", str(DEFAULT_MAX_BATCH_LABELS)))
MAX_BATCH_CONCURRENCY = int(
    os.getenv("MAX_BATCH_CONCURRENCY", str(DEFAULT_MAX_BATCH_CONCURRENCY))
)

VisionServiceFactory = Callable[[], VisionService]

router = APIRouter()


@dataclass(frozen=True)
class UploadedLabel:
    index: int
    filename: str | None
    content_type: str | None
    image_bytes: bytes


def get_vision_service_factory() -> VisionServiceFactory:
    return get_openai_vision_service


@lru_cache(maxsize=1)
def get_openai_vision_service() -> VisionService:
    return OpenAIVisionService.from_env()


@router.post("/verify", response_model=VerificationResult)
async def verify_label(
    application_data: Annotated[
        str,
        Form(description="JSON object containing the expected application fields."),
    ],
    label_image: Annotated[
        UploadFile,
        File(description="Single label image to verify."),
    ],
    vision_service_factory: Annotated[
        VisionServiceFactory,
        Depends(get_vision_service_factory),
    ],
) -> VerificationResult:
    expected = _parse_application_data(application_data)
    upload = await _read_uploaded_label(label_image, index=0)
    if not upload.image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="label_image must not be empty.",
        )

    try:
        return await asyncio.to_thread(
            _verify_uploaded_label,
            expected,
            upload,
            vision_service_factory,
        )
    except VisionPreprocessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except VisionServiceConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except VisionParsingError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except VisionServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/verify/batch", response_model=BatchVerificationResult)
async def verify_label_batch(
    application_data: Annotated[
        str,
        Form(description="JSON object containing the expected application fields."),
    ],
    label_images: Annotated[
        list[UploadFile],
        File(description="One or more label images to verify together."),
    ],
    vision_service_factory: Annotated[
        VisionServiceFactory,
        Depends(get_vision_service_factory),
    ],
) -> BatchVerificationResult:
    started_at = perf_counter()
    expected = _parse_application_data(application_data)

    if not label_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one label image is required.",
        )
    if len(label_images) > MAX_BATCH_LABELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch upload is limited to {MAX_BATCH_LABELS} label images.",
        )

    uploads = [
        await _read_uploaded_label(label_image, index=index)
        for index, label_image in enumerate(label_images)
    ]
    semaphore = asyncio.Semaphore(min(MAX_BATCH_CONCURRENCY, len(uploads)))

    async def verify_one(upload: UploadedLabel) -> BatchLabelResult:
        async with semaphore:
            return await _verify_batch_upload(
                expected,
                upload,
                vision_service_factory,
            )

    labels = await asyncio.gather(*(verify_one(upload) for upload in uploads))
    latency_ms = round((perf_counter() - started_at) * 1000, 3)
    return BatchVerificationResult(
        summary=_summarize_batch(labels),
        items=list(labels),
        latency_ms=latency_ms,
    )


async def _read_uploaded_label(label_image: UploadFile, *, index: int) -> UploadedLabel:
    return UploadedLabel(
        index=index,
        filename=label_image.filename,
        content_type=label_image.content_type,
        image_bytes=await label_image.read(),
    )


async def _verify_batch_upload(
    expected: ApplicationData,
    upload: UploadedLabel,
    vision_service_factory: VisionServiceFactory,
) -> BatchLabelResult:
    started_at = perf_counter()
    try:
        if not upload.image_bytes:
            raise VisionPreprocessingError("label_image must not be empty.")

        result = await asyncio.to_thread(
            _verify_uploaded_label,
            expected,
            upload,
            vision_service_factory,
        )
    except (
        VisionPreprocessingError,
        VisionServiceConfigurationError,
        VisionParsingError,
        VisionServiceError,
    ) as exc:
        latency_ms = round((perf_counter() - started_at) * 1000, 3)
        return BatchLabelResult(
            index=upload.index,
            filename=upload.filename,
            status="ERROR",
            error=str(exc),
            latency_ms=latency_ms,
        )

    return BatchLabelResult(
        index=upload.index,
        filename=upload.filename,
        status=result.overall_verdict,
        result=result,
        latency_ms=result.latency_ms,
    )


def _verify_uploaded_label(
    expected: ApplicationData,
    upload: UploadedLabel,
    vision_service_factory: VisionServiceFactory,
) -> VerificationResult:
    started_at = perf_counter()
    vision_service = vision_service_factory()
    found = vision_service.extract_label_from_bytes(
        upload.image_bytes,
        filename=upload.filename,
        content_type=upload.content_type,
    )
    result = compare_labels(expected, found)
    latency_ms = round((perf_counter() - started_at) * 1000, 3)
    return result.model_copy(update={"latency_ms": latency_ms})


def _summarize_batch(labels: list[BatchLabelResult]) -> BatchSummary:
    return BatchSummary(
        total=len(labels),
        passed=sum(1 for label in labels if label.status == "APPROVED"),
        needs_review=sum(1 for label in labels if label.status != "APPROVED"),
    )


def _parse_application_data(payload: str) -> ApplicationData:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="application_data must be valid JSON.",
        ) from exc

    if not isinstance(data, Mapping):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="application_data must be a JSON object.",
        )

    try:
        return ApplicationData.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "application_data contains invalid field values.",
                "errors": exc.errors(),
            },
        ) from exc
