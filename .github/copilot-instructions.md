# FlameCast Backend - AI Agent Instructions

## 🎯 Project Overview

FlameCast Backend is a Python-based modular system using **FastAPI**, **Beanie (MongoDB)**, **Redis**, and **ARQ** for background jobs. It integrates heavily with **LiveKit** for real-time media processing.

## 🚨 Critical Rules (Zero Tolerance)

1.  **`app/cw` is Read-Only**: This is a shared library submodule. **NEVER** modify files in `app/cw/`. Only import public APIs (`app.cw.storage.*`, `app.cw.config`, etc.).
2.  **No Proactive Docs**: Do not create `*.md` files unless explicitly asked.
3.  **Prefer Editing**: Modify existing files over creating new ones.
4.  **No Raw Dicts**: Use **Pydantic** models for API schemas and **Beanie** models for MongoDB.
5.  **No Literal Strings**: Use **Enums** for status codes, types, modes, etc.
6.  **Single Responsibility**: Each class/function must have exactly one responsibility.
7.  **Only Raise FlcError**: Only `FlcError` is allowed to be raised in this project.

## 🏗️ Architecture & Patterns

### Directory Structure

- `app/api/flc`: Main application API logic (FlameCast).
- `app/cw`: **READ-ONLY** shared core library (Storage, Config, Utils).
- `app/domain`: Core business logic and domain services (e.g., Session management, Channel operations).
- `app/services`: External service integrations (LiveKit, Mux, Translator).
- `app/workers`: ARQ background workers (e.g., `caption_agent_worker.py`).
- `app/schemas`: Pydantic and Beanie models.

### Data Access

- **MongoDB**: Use **Beanie** ODMs located in `app/schemas`.
  - Example: `await Session.find_one(Session.id == session_id)`
- **Redis**: Use `app.cw.storage.redis.get_redis_manager` or `get_redis_client`.

### Service Layer

- Encapsulate external API calls in `app/services`.
- Do not put business logic in routers; delegate to services or domain helpers.

### Error Handling

- Use `app.api.flc.errors.FlcError` for business logic errors.
- Do not return raw 400/500 responses manually in routers.

## 🛠️ Developer Workflows

### Dependency Management

- **Tool**: `uv`
- **Install**: `make install-deps`
- **Add Package**: `uv add <package>` (Do NOT edit `pyproject.toml` manually).

### Testing

- **Fast Test**: `make test-fast` (skips verbose output).
- **Specific Test**: `make test-fast tests/path/to/test.py::test_function`
- **Guidelines**: When adding unit tests, refer to the docs under `docs/unit_testing`.

### Local Development

- **Start**: `make local-up` (Starts API, Workers, Mongo, Redis).
- **Logs**: `make local-logs`.
- **Restart**: `make local-rebuild`.

## 📝 Code Style & Conventions

- **Type Hints**: Mandatory for all function arguments and return values.
- **Logging**: Use `loguru.logger`.
- **Async**: Prefer `async/await` for all I/O bound operations.

## 🔍 Key Files

- `app/main.py`: Application entry point.
- `app/workers/caption_agent_worker.py`: Example of LiveKit agent worker.
- `app/api/flc/routers`: API route definitions.
