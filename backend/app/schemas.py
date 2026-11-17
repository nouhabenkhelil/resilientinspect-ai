"""Contrats JSON exposes dans Swagger."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


Category = Literal["bottle", "hazelnut", "leather"]
ModelName = Literal["B0", "A1", "T0", "T1", "T2"]
MODELS = ("B0", "A1", "T0", "T1", "T2")
CATEGORIES = ("bottle", "hazelnut", "leather")


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: UUID


class Prediction(BaseModel):
    category: Category
    model: ModelName
    version: str
    anomaly_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    decision: Literal["normal", "anomaly"]
    inference_time_ms: float = Field(ge=0, allow_inf_nan=False)
    request_id: UUID


class Visualization(BaseModel):
    kind: Literal["reconstruction_error", "gradcam"]
    description: str
    width: int = 256
    height: int = 256
    coordinate_space: Literal["letterbox_256"] = "letterbox_256"
    padding_top_bottom_left_right: list[int]
    original_height_width: list[int]
    scale: str
    is_segmentation: bool = False
    image_png_base64: str
    heatmap_png_base64: str
    overlay_png_base64: str


class VisualizedPrediction(Prediction):
    visualization: Visualization


class ModelMetadata(BaseModel):
    model: ModelName
    category: Category
    version: str
    checkpoint_sha256: str
    calibration_sha256: str
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    seed: int | None = None
    input_size: list[int] = [256, 256]
    normalization: str
    score: str
    decision_rule: Literal["score > threshold"] = "score > threshold"
    explanation: Literal["reconstruction_error", "gradcam"]
    training_environment: dict[str, Any] | None = None
    serving_environment: dict[str, Any]
    compatibility_report_sha256: str | None = None


class UnavailableModel(BaseModel):
    model: ModelName
    category: Category
    reason: str


class MetadataResponse(BaseModel):
    models: list[ModelMetadata]
    unavailable: list[UnavailableModel]
    request_id: UUID


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    device: Literal["cpu"] = "cpu"
    ready_models: int
    expected_models: int = 15
    request_id: UUID
