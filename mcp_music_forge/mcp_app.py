from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from core.infra.db import create_db_and_tables
from core.logging import configure_logging
from core.settings import AppSettings, get_settings


@dataclass
class LifespanContext:
    settings: AppSettings


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[LifespanContext]:
    settings = get_settings()
    # Init logging and DB
    configure_logging()
    create_db_and_tables()
    yield LifespanContext(settings=settings)


mcp = FastMCP(
    "mcp-music-forge",
    lifespan=lifespan,
    # Important when mounting under /mcp in FastAPI to avoid double prefix
    streamable_http_path="/",
    stateless_http=True,
)

# Import side-effects: tool and resource registrations
# isort: off
from .tools import probe_url as _probe_url  # noqa: F401,E402
from .tools import enqueue_download as _enqueue_download  # noqa: F401,E402
from .tools import get_job_status as _get_job_status  # noqa: F401,E402
from .resources import files as _files  # noqa: F401,E402

# isort: on


def main() -> None:  # pragma: no cover - thin runner
    """
    Run MCP server via stdio or HTTP depending on env/args
    (defaults to stdio).
    """
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - thin runner
    main()
