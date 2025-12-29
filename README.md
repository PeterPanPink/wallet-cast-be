# WalletCast Demo Backend (Sanitized Showcase)

This repository is a **public, sanitized showcase** derived from a real-world backend codebase.
It is intentionally modified for portfolio use:

- **No production secrets**
- **No private endpoints**
- **No customer data**
- **External integrations are stubbed or guarded by flags**

## What this demonstrates

- **Clean API layering**: Router → Domain Service → Storage/Integration boundary
- **Business capability (genericized)**: Channel / Session / User lifecycle, state machine patterns
- **AI capability (safe demo)**: Agent-style architecture for captions/transcripts (no real providers by default)
- **Engineering maturity**: Linting, testing, Docker build workflow, security/redaction checks

## Repository layout (high level)

- `app/api/`: HTTP API (FastAPI routers)
- `app/domain/`: business logic (Channel/Session/User)
- `app/services/`: external integrations (stubbed for demo)
- `app/schemas/`: request/response models
- `docs/`: engineering docs (edited for public release)
- `tools/`: developer tools (lint, mocks, scanning)

## Security & redaction

See `docs/SECURITY_REDACTION.md` for:
- what is removed
- what is replaced with placeholders
- how to validate no secrets leak

## CI/CD (showcase)

GitHub Actions examples include:
- lint + unit tests
- redaction scan
- Docker build
- Docker build **and push** (disabled by default)

## Code quality

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
make lint
make format
```
