from collections.abc import Callable, Mapping
import json
from pathlib import Path
from time import perf_counter
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.comparison import compare_labels
from app.models import ApplicationData, VerificationResult
from app.vision import (
    OpenAIVisionService,
    VisionParsingError,
    VisionPreprocessingError,
    VisionService,
    VisionServiceConfigurationError,
    VisionServiceError,
)

APP_VERSION = "0.1.0"
SERVICE_NAME = "ttb-label-verification"

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"
VisionServiceFactory = Callable[[], VisionService]

app = FastAPI(
    title="TTB Label Verification",
    version=APP_VERSION,
)


def get_vision_service_factory() -> VisionServiceFactory:
    return OpenAIVisionService.from_env


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": APP_VERSION,
    }


@app.post("/verify", response_model=VerificationResult)
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
    started_at = perf_counter()
    expected = _parse_application_data(application_data)
    image_bytes = await label_image.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="label_image must not be empty.",
        )

    try:
        vision_service = vision_service_factory()
        found = vision_service.extract_label_from_bytes(
            image_bytes,
            filename=label_image.filename,
            content_type=label_image.content_type,
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

    result = compare_labels(expected, found)
    latency_ms = round((perf_counter() - started_at) * 1000, 3)
    return result.model_copy(update={"latency_ms": latency_ms})


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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(INDEX_FILE)
