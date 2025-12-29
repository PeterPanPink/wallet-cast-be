FROM python:3.13 AS builder

# WORKDIR in builder and runtime must be the same, as venv requires the same path
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set uv environment variables
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
# --frozen: ensures that the exact versions of dependencies are installed, preventing unexpected changes
# --no-install-project: requires a README.md to install the project itself, which we don't need in the builder stage
# --no-dev: exclude development dependencies to keep the environment lean
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Not needed for runtime, but useful for local development and unit tests
# Set up virtual environment for unit tests and local development. Works like `source .venv/bin/activate`
ENV PATH="/app/.venv/bin:$PATH"

FROM python:3.13-slim AS runtime

# WORKDIR in builder and runtime must be the same, as venv requires the same path
WORKDIR /app

# Add Tini for proper signal handling
ENV TINI_VERSION=v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set up virtual environment for application runtime. Works like `source .venv/bin/activate`
ENV PATH="/app/.venv/bin:$PATH"

# Copy virtual environment and application code
# use COPY --chown instead of RUN chown to make the build faster
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser docker-entry.sh ./docker-entry.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/tini", "--"]
CMD ["/app/docker-entry.sh"]
