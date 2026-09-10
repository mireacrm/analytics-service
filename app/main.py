import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mireacrm_common import identity, observability, tracing
from mireacrm_common.errors import (
    ConflictError,
    ForbiddenError,
    InvalidArgumentError,
    NotFoundError,
    UnavailableError,
)
from mireacrm_common.health import check_readiness
from mireacrm_common.lifespan import AppContext, build_context
from sqlalchemy.exc import IntegrityError

from app.api import reports
from app.infra.config import Settings, get_settings

log = logging.getLogger("analytics")

QUEUE = "analytics-service.events"

_HTTP_CODES: dict[type[Exception], int] = {
    NotFoundError: 404,
    ForbiddenError: 403,
    ConflictError: 409,
    InvalidArgumentError: 422,
    IntegrityError: 409,
    UnavailableError: 503,
}


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="Analytics Service", version="0.1.0")
    app.state.context = context
    observability.install(app, context.settings.service_name)

    app.include_router(reports.router)

    for exc_type, status_code in _HTTP_CODES.items():
        app.add_exception_handler(exc_type, _make_handler(status_code))

    @app.middleware("http")
    async def trace_context(request: Request, call_next):
        traceparent = tracing.parse(request.headers.get(tracing.HEADER))
        tracing.set_current(traceparent)
        identity.set_current(identity.parse(request.headers))
        response = await call_next(request)
        response.headers[tracing.HEADER] = traceparent
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness: процесс отвечает. Зависимости намеренно не проверяются."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        """Readiness: зависимости доступны."""
        report = await check_readiness(context)
        return JSONResponse(
            status_code=200 if report.ready else 503,
            content={"status": "ok" if report.ready else "degraded", "checks": report.checks},
        )

    return app


def _make_handler(status_code: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        detail = "конфликт при записи в базу" if isinstance(exc, IntegrityError) else str(exc)
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return handler


async def serve(settings: Settings | None = None) -> None:
    """REST и gRPC в одном event loop: один процесс, один контейнер."""
    import uvicorn

    settings = settings or get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    # gRPC инструментируется до создания каналов: инструментация подменяет
    # фабрики, а уже открытые каналы её не подхватят.
    traced = observability.setup_tracing(settings.service_name, settings.otlp_endpoint)
    if traced:
        observability.instrument_grpc()

    from mireacrm_common.consumer import Consumer

    from app import handlers
    from app.clients import CoreClient

    async with build_context(settings, CoreClient(settings.core_addr)) as context:
        consumer = Consumer(settings.amqp_url, QUEUE, settings.service_name)
        # Аналитика слушает весь поток: биндинг `#` объявлен в definitions.json.
        consumer.handle_all(handlers.build(context))
        await consumer.start()

        app = create_app(context)
        if traced:
            observability.instrument_app(app)
            observability.instrument_database(context.engine)

        http = uvicorn.Server(
            uvicorn.Config(app, host="0.0.0.0", port=settings.http_port, log_level="info")
        )

        try:
            await http.serve()
        finally:
            await consumer.stop()


def run() -> None:
    asyncio.run(serve())
