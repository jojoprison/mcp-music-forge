from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from markupsafe import Markup
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
    # Ensure MCP StreamableHTTP SessionManager is running for mounted /mcp app
    # This initializes the internal task group required to handle requests
    # (avoids: RuntimeError "Task group is not initialized.
    # Make sure to use run().")
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="MCP Music Forge", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def intercept_mcp_browser_request(request: Request, call_next):
    # Check if accessing /mcp root with a browser (Accept: text/html)
    # to show a helpful page instead of JSON error
    if (
        request.url.path.rstrip("/") == "/mcp"
        and "text/html" in request.headers.get("accept", "")
    ):
        html_content = """
        <!DOCTYPE html>
        <html>
            <head>
                <title>MCP Music Forge</title>
                <style>
                    body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; color: #333; }
                    code { background: #f4f4f4; padding: 0.2em 0.4em; border-radius: 3px; }
                    .note { background: #eef; padding: 1rem; border-radius: 6px; margin-bottom: 1.5rem; }
                    a { color: #0066cc; text-decoration: none; }
                    a:hover { text-decoration: underline; }
                </style>
            </head>
            <body>
                <h1>MCP Music Forge Server</h1>
                <div class="note">
                    <p><strong>Status:</strong> Running 🟢</p>
                </div>
                <p>This endpoint provides the <strong>Model Context Protocol (MCP)</strong> interface via SSE (Server-Sent Events).</p>
                <p>It is intended for MCP clients (like Claude Desktop), not direct browser viewing.</p>

                <h2>How to connect</h2>
                <p>Configure your MCP client with:</p>
                <ul>
                    <li><strong>URL:</strong> <code>http://localhost:8033/mcp</code> (or <code>.../mcp/sse</code>)</li>
                    <li><strong>Type:</strong> SSE</li>
                </ul>

                <hr>
                <p>
                    <a href="/docs">API Documentation</a> |
                    <a href="/admin">Admin Panel</a>
                </p>
            </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "mcp-protocol-version",
        "mcp-session-id",
        "authorization",
        "content-type",
    ],
    expose_headers=["mcp-session-id"],
)

# Mount MCP Streamable HTTP under /mcp
app.mount("/mcp", mcp.streamable_http_app())


class JobAdmin(ModelView, model=Job):
    name = "Задание"
    name_plural = "Задания"
    icon = "fa-solid fa-music"

    column_list = [
        "id",
        "provider",
        "status",
        "title",
        "artist",
        "created_at",
        "audio",
    ]
    column_labels = {
        "id": "ID",
        "provider": "Провайдер",
        "status": "Статус",
        "title": "Название",
        "artist": "Исполнитель",
        "created_at": "Создано",
        "url": "Ссылка",
        "error": "Ошибка",
        "updated_at": "Обновлено",
        "fingerprint": "Отпечаток",
        "duration": "Длительность",
        "artwork_url": "Обложка",
        "options": "Опции",
        "audio": "Аудио",
    }

    def audio(self, obj: Job) -> Markup:
        if obj.status != "succeeded":
            return Markup("-")
        url = f"/jobs/{obj.id}/download"
        html = (
            f'<audio controls src="{url}" preload="none" style="height: 30px; width: 200px; vertical-align: middle;"></audio> '
            f'<a href="{url}" download style="margin-left: 10px;">📥</a>'
        )
        return Markup(html)


_admin = Admin(app=app, engine=get_engine(), title="Музыкальная Кузница")
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


@app.get("/jobs/{job_id}/download")
async def download_job_artifact(job_id: str):
    """
    Download the final artifact for a job.
    """
    settings = get_settings()
    final_dir = settings.storage_dir / "jobs" / job_id / "final"
    if not final_dir.exists():
        raise HTTPException(status_code=404, detail="Job files not found")

    # Find first file
    # Note: this is a simple implementation that takes the first file found
    files = [f for f in final_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
    if not files:
        raise HTTPException(status_code=404, detail="No artifacts found")

    return FileResponse(files[0], filename=files[0].name)
