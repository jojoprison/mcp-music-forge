from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqladmin import Admin, ModelView

from core.domain.job import Job
from core.infra.db import create_db_and_tables, get_engine
from core.logging import configure_logging
from core.settings import get_settings
from mcp_music_forge.mcp_app import mcp
from mcp_music_forge.tools.enqueue_download import (
    EnqueueOptions,
    EnqueueResult,
    enqueue_download,
)
from mcp_music_forge.tools.get_job_status import (
    GetJobStatusResult,
    get_job_status,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(logging.INFO)
    create_db_and_tables()
    # Minimal OTEL setup if OTLP endpoint provided
    if settings.otel_endpoint:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.instrumentation.fastapi import (
                FastAPIInstrumentor,
            )
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(
                resource=Resource.create(
                    {SERVICE_NAME: settings.otel_service_name}
                )
            )
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.otel_endpoint)
                )
            )
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
        except Exception as e:
            # Observability is optional; continue without failing, but log why
            logging.getLogger(__name__).warning("OTEL setup skipped: %s", e)
    yield


app = FastAPI(title="MCP Music Forge", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount MCP Streamable HTTP under /mcp
# NOTE: This allows HTTP transport for MCP clients that support it.
app.mount("/mcp", mcp.streamable_http_app())


class JobAdmin(ModelView, model=Job):  # type: ignore[call-arg]
    column_list = [
        "id",
        "provider",
        "status",
        "title",
        "artist",
        "created_at",
    ]
    name_plural = "Jobs"


_admin = Admin(app=app, engine=get_engine())
_admin.add_view(JobAdmin)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/download", response_model=EnqueueResult)
async def api_enqueue(
    url: str, options: EnqueueOptions | None = None
) -> EnqueueResult:
    try:
        return await enqueue_download(url, options)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/jobs/{job_id}", response_model=GetJobStatusResult)
async def api_job(job_id: str) -> GetJobStatusResult:
    try:
        return await get_job_status(job_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
