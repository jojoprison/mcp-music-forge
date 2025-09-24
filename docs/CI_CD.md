# CI/CD

Этот документ описывает как мы проверяем качество кода и собираем проект.

## Локальные проверки (pre-commit)

У нас настроены хуки pre-commit:

- Black (форматирование, 80 символов в строке)
- Ruff (линтер, isort-группировка импортов)
- MyPy (статическая типизация)
- pyupgrade (миграция синтаксиса под целевую версию Python)

Команды:

- Установка хуков: `pre-commit install`
- Запустить все проверки на всём репозитории: `pre-commit run -a`

## Ручные проверки

- Формат: `black --check .`
- Линт: `ruff check .`
- Типы: `mypy .`
- Тесты: `pytest -q`

Рекомендация: перед коммитом запустить `pre-commit run -a`.

## GitHub Actions

Файл workflow: `.github/workflows/ci.yml`

Что делает:

1. Устанавливает Python 3.12 и `uv`
2. Ставит зависимости: `uv pip install -e .[dev]`
3. Проверяет формат: `black --check .`
4. Линтит: `ruff check .`
5. Прогоняет `mypy .`
6. Запускает `pytest -q --cov`
7. (Отдельная job) Сборка Docker-образа API: `docker/build-push-action`

## Политика форматирования

- Источник правды — Black; длина строки 80. Ruff не форматирует код, только линтит.
- В PyCharm рекомендуется включить «Reformat with Black», чтобы Option+Cmd+L запускал Black.

## Замечания по типам

- SQLModel/SQLAlchemy иногда конфликтуют с сигнатурами MyPy. Мы используем точечные решения:
    - `sa_column=Column(SAJSON)` для полей с dict → JSON
    - В `enqueue_download` применяем `Session.query(...).filter_by(...)` для совместимости с MyPy.
    - В админке SQLAdmin используем `model = Job` как атрибут класса `JobAdmin`.
