"""Guard вокруг MCP-слоя.

🛑 Этих тестов не было — и 28.08.2026 пересборка образа подтянула mcp 2.x,
где `mcp.server.fastmcp.FastMCP` больше не существует. Импорт падал только
при СТАРТЕ приложения, поэтому зелёная сюита ничего не сказала, а вместе с
api лёг телеграм-бот: он поллится внутри того же процесса. ~10 минут простоя.

Проверяем ровно то, что тогда сломалось: что модули импортируются и что
регистрация инструментов и ресурсов не потерялась по дороге.
"""

from __future__ import annotations

import pytest


def test_mcp_app_imports() -> None:
    # Ровно точка отказа инцидента: импорт исполняется на старте приложения.
    from mcp_music_forge.mcp_app import mcp

    assert type(mcp).__name__ == "MCPServer"


def test_api_main_imports() -> None:
    # api тянет mcp_app за собой — именно этот импорт и ронял прод.
    import api.main

    assert api.main.app is not None


@pytest.mark.asyncio
async def test_all_tools_stay_registered() -> None:
    # Регистрация идёт побочным эффектом импорта модулей в mcp_app. Потерять
    # её можно молча: приложение поднимется, а инструментов у клиента не
    # будет — со стороны это выглядит как «MCP не работает», без ошибок.
    from mcp_music_forge.mcp_app import mcp

    names = {t.name for t in await mcp.list_tools()}

    assert names == {"probe_url", "enqueue_download", "get_job_status"}


@pytest.mark.asyncio
async def test_file_resources_stay_registered() -> None:
    from mcp_music_forge.mcp_app import mcp

    templates = await mcp.list_resource_templates()

    assert len(templates) >= 1


def test_mcp_is_mounted_without_double_prefix() -> None:
    # 🛑 В mcp 2.x `streamable_http_path` переехал из конструктора в
    # `streamable_http_app()`. Забыть его при переносе — значит получить
    # путь `/mcp/mcp`: приложение стартует, клиенты не подключаются.
    #
    # 🛑 Проверять НАЛИЧИЕ mount'а бесполезно: он есть в обоих случаях, и
    # мутант «убрать streamable_http_path» такой тест переживал. Смотреть
    # надо путь ВНУТРИ смонтированного приложения — там `/` против `/mcp`.
    from api.main import app

    mounts = [r for r in app.routes if getattr(r, "path", "") == "/mcp"]
    assert mounts, [getattr(r, "path", "?") for r in app.routes]

    inner = [getattr(r, "path", "?") for r in mounts[0].app.routes]

    assert inner == ["/"], inner
