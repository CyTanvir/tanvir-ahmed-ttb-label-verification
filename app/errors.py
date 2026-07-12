class VisionServiceError(RuntimeError):
    """Base error for image extraction failures."""


class VisionServiceConfigurationError(VisionServiceError):
    """Raised when the real vision service is missing required configuration."""


class VisionPreprocessingError(VisionServiceError):
    """Raised when uploaded image bytes cannot be prepared for the model."""


class VisionParsingError(VisionServiceError):
    """Raised when a model response cannot be converted into ExtractedLabel."""
