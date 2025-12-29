.PHONY: install-deps clean help test test-cov test-fast test-verbose test-integration test-integration-build test-integration-clean test-integration-logs local-up local-down local-init local-logs local-rebuild local-scale local-clean _setup-hooks lint format lint-check format-check

# Internal target to configure Git hooks (runs before other commands)
_setup-hooks:
	@git config core.hooksPath .githooks 2>/dev/null || true
	@chmod +x .githooks/pre-push 2>/dev/null || true
	@echo "✅ Git hooks configured"

# Default target
help:
	@echo "Available commands:"
	@echo "  make install-deps              - Install dependency packages"
	@echo "  make clean                     - Clean cache files"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint                      - Run Ruff linter (auto-fix)"
	@echo "  make format                    - Run Ruff formatter"
	@echo "  make lint-check                - Check linting without fixing"
	@echo "  make format-check              - Check formatting without fixing"
	@echo ""
	@echo "Testing:"
	@echo "  make test-build                - Build test container"
	@echo "  make test                      - Run all tests"
	@echo "  make test-cov                  - Run tests with coverage report"
	@echo "  make test-fast [path]          - Run tests without verbose output"
	@echo "                                   Examples:"
	@echo "                                     make test-fast"
	@echo "                                     make test-fast tests/services/worker_batches/"
	@echo "                                     make test-fast tests/services/worker_batches/test_batches.py"
	@echo "                                     make test-fast tests/services/worker_batches/test_batches.py::test_upsert_batches_single"
	@echo "                                   Alternative (no extra messages):"
	@echo "                                     make test-fast ARGS=\"tests/services/worker_batches/\""
	@echo "  make test-verbose              - Run tests with verbose output"
	@echo ""
	@echo "Local Development:"
	@echo "  make local-up                  - Start all local services"
	@echo "  make local-down                - Stop all local services"
	@echo "  make local-init                - Initialize database tables"
	@echo "  make local-logs                - View logs from all services"
	@echo "  make local-rebuild             - Rebuild and restart services"
	@echo "  make local-scale N=3           - Scale executor workers (default: 2)"
	@echo "  make local-clean               - Clean environment (remove volumes)"
	@echo "  make console                   - Start admin console (http://localhost:8998)"
	@echo ""
	@echo "Integration Tests:"
	@echo "  make test-integration          - Run integration tests for workers"
	@echo "  make test-integration-build    - Run integration tests with rebuild"
	@echo "  make test-integration-clean    - Clean integration test environment"
	@echo "  make test-integration-logs     - Show worker logs during tests"

# Install dependencies
install-deps: _setup-hooks
	@echo "📦 Installing Python dependencies..."
	@uv sync
	@echo "✅ Dependencies installed"

# Clean cache files
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -f .coverage
	docker compose -f docker-compose.test.yml down -v

# ============================================================================
# Code Quality Commands
# ============================================================================

# Run Ruff linter with auto-fix
lint: _setup-hooks
	@echo "🔍 Running Ruff linter..."
	@uv run ruff check . --fix
	@echo "✅ Linting complete"

# Run Ruff formatter
format: _setup-hooks
	@echo "✨ Running Ruff formatter..."
	@uv run ruff format .
	@echo "✅ Formatting complete"

# Check linting without fixing
lint-check: _setup-hooks
	@echo "🔍 Checking code with Ruff linter..."
	@uv run ruff check .

# Check formatting without fixing
format-check: _setup-hooks
	@echo "🔍 Checking code formatting..."
	@uv run ruff format --check .

# ============================================================================
# Testing Commands
# ============================================================================

# Build test container
test-build: _setup-hooks
	@echo "🔨 Building test container..."
	docker compose -f docker-compose.test.yml build
	@echo "✅ Test container built"

# Run tests
test: _setup-hooks
	docker compose -f docker-compose.test.yml up --attach test --abort-on-container-exit --no-log-prefix

# Run tests with coverage
test-cov: _setup-hooks
	UNIT_TEST_MODE=coverage docker compose -f docker-compose.test.yml up --attach test --abort-on-container-exit --no-log-prefix

# Run tests without verbose output
# Usage: 
#   make test-fast                                    - Run all tests
#   make test-fast ARGS="tests/services/worker_batches/"  - Run specific directory/file
#   Or just pass as argument: All non-makefile targets are treated as test paths
test-fast: _setup-hooks
	@TEST_PATH="$(filter-out $@,$(MAKECMDGOALS))";	\
	if [ -n "$$TEST_PATH" ]; then \
		echo "# Running tests: $$TEST_PATH"; \
		docker compose up -d redis mongo; \
		docker compose -f docker-compose.test.yml run --rm test uv run pytest $$TEST_PATH -q --maxfail=1 --disable-warnings; \
	else \
		UNIT_TEST_MODE=fast docker compose -f docker-compose.test.yml up --attach test --abort-on-container-exit --no-log-prefix; \
	fi


# Run tests with verbose output
test-verbose: _setup-hooks
	uv run pytest tests/ -v

# ============================================================================
# Local Development Commands
# ============================================================================

# Start all local services
local-up:
	@echo "🚀 Starting local development environment..."
	docker compose -f docker-compose.local.yml up -d
	@echo "✅ Services started"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Initialize database: make local-init"
	@echo "  2. View logs: make local-logs"
	@echo "  3. Check status: docker compose -f docker-compose.local.yml ps"

# Stop all local services
local-down:
	@echo "🛑 Stopping local development environment..."
	docker compose -f docker-compose.local.yml down
	@echo "✅ Services stopped"

# Initialize database tables
local-init:
	@echo "🗄️  Initializing database tables..."
	docker compose -f docker-compose.local.yml run --rm database-initializer
	@echo "✅ Database initialized"

# View logs from all services
local-logs:
	@echo "📋 Viewing logs (Ctrl+C to exit)..."
	docker compose -f docker-compose.local.yml logs -f

# Rebuild and restart services
local-rebuild:
	@echo "🔨 Rebuilding and restarting services..."
	docker compose -f docker-compose.local.yml up -d --build
	@echo "✅ Services rebuilt and restarted"

# Scale executor workers
local-scale:
	@echo "⚖️  Scaling executor workers to $(N) instances..."
	docker compose -f docker-compose.local.yml up -d --scale coin-fetch-executor=$(N)
	@echo "✅ Executor workers scaled to $(N)"

# Clean local environment (including volumes)
local-clean:
	@echo "🧹 Cleaning local development environment..."
	docker compose -f docker-compose.local.yml down -v
	@echo "✅ Local environment cleaned (including data)"

# ============================================================================
# Developer Console
# ============================================================================

# Start admin console
console:
	@echo "🖥️  Developer console is not included in this public demo repository."
	@echo "Start the API locally with:"
	@echo "  make local-up"
