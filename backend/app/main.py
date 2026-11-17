"""Application FastAPI locale. Demarrage depuis la racine avec uvicorn."""

from contextlib import asynccontextmanager
import logging
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .config import API_VERSION, Settings
from .errors import APIError
from .imaging import decode_upload
from .inference import predict
from .middleware import RequestMiddleware
from .models import ModelStore
from .schemas import (Category, ErrorResponse, HealthResponse, MetadataResponse, ModelName,
                      Prediction, UnavailableModel, VisualizedPrediction)


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, store: ModelStore | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.models = store if store is not None else ModelStore(settings)
        if store is None:
            await run_in_threadpool(app.state.models.load)
        yield
        if store is None:
            app.state.models.models.clear()

    app = FastAPI(title="ResilientInspect AI", version=API_VERSION, lifespan=lifespan,
                  description="Inference CPU par categorie avec les checkpoints et seuils figes.")
    app.add_middleware(RequestMiddleware, max_body_bytes=settings.max_file_bytes + 64 * 1024)

    def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
        error = ErrorResponse(code=code, message=message, request_id=request.state.request_id)
        return JSONResponse(status_code=status, content=error.model_dump(mode="json"))

    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError):
        return error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "invalid_input", "Verifier les champs file, category et model et leurs valeurs autorisees.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "http_error", "Requete HTTP invalide ou ressource absente.")

    @app.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
    def health(request: Request, response: Response):
        ready = len(request.app.state.models.models)
        if ready != 15:
            response.status_code = 503
        return HealthResponse(status="ok" if ready == 15 else "degraded", version=API_VERSION,
                              ready_models=ready, request_id=request.state.request_id)

    @app.get("/model/metadata", response_model=MetadataResponse)
    def metadata(request: Request, model: ModelName | None = None, category: Category | None = None):
        service = request.app.state.models
        def selected(key):
            return (model is None or key[0] == model) and (category is None or key[1] == category)
        return MetadataResponse(models=[loaded.metadata for key, loaded in service.models.items() if selected(key)],
                                unavailable=[UnavailableModel(model=key[0], category=key[1], reason=reason)
                                             for key, reason in service.unavailable.items() if selected(key)],
                                request_id=request.state.request_id)

    def infer(request: Request, file: UploadFile, category: Category, model: ModelName, visualize: bool):
        sample = decode_upload(file, settings)
        loaded = request.app.state.models.models.get((model, category))
        if loaded is None:
            raise APIError(503, "model_unavailable", "Ce modele est absent ou ses artefacts n'ont pas pu etre valides.")
        try:
            return predict(loaded, sample, request.state.request_id, visualize=visualize)
        except Exception as exc:
            logger.exception("Inference impossible pour %s/%s, requete %s", model, category, request.state.request_id)
            raise APIError(500, "inference_failed", "L'inference est impossible pour cette requete.") from exc

    errors = {status: {"model": ErrorResponse} for status in (400, 413, 415, 422, 500, 503)}

    @app.post("/predict", response_model=Prediction, responses=errors)
    def predict_route(request: Request, file: Annotated[UploadFile, File()],
                      category: Annotated[Category, Form()], model: Annotated[ModelName, Form()]):
        return infer(request, file, category, model, False)

    @app.post("/predict/visualize", response_model=VisualizedPrediction, responses=errors)
    def visualize_route(request: Request, file: Annotated[UploadFile, File()],
                        category: Annotated[Category, Form()], model: Annotated[ModelName, Form()]):
        return infer(request, file, category, model, True)

    return app


app = create_app()
