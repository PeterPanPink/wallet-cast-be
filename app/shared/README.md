# Shared Library (Sanitized Demo)

A comprehensive Python library providing API utilities and storage management for backend services.

## Overview

Shared Library is designed to be embedded as a submodule in other projects, providing essential backend functionality including:

- **API Utilities**: Admin functions, health checks, error handling, and utility functions
- **Storage Management**: Redis and MongoDB client management with connection pooling
- **Environment Configuration**: Automatic loading from environment variables and demo env files

## Project Structure

```
shared-lib/
├── src/                   # Source code directory
│   ├── __init__.py        # Package initialization
│   ├── api/               # API utilities
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── errors.py
│   │   ├── health.py
│   │   └── utils.py
│   └── storage/           # Storage management
│       ├── __init__.py
│       ├── mongo.py
│       └── redis.py
├── tests/                 # Test files
├── docs/                  # Documentation
├── tools/                 # Development tools
│   ├── create-release-branch.sh
│   ├── test-release-script.sh
│   └── usage-example.md
├── pyproject.toml
└── README.md
```

## Development

### Prerequisites

- Python 3.10+
- Poetry (for dependency management)

### Setup

```bash
# Install dependencies
make install-deps

# Run tests
make test

# Run tests with coverage
make test-cov

# Quick test run
make test-fast
```

### Available Commands

```bash
make help                 # Show all available commands
make install-deps         # Install dependencies and configure git hooks
make test                 # Run all tests (verbose)
make test-cov             # Run tests with coverage report
make test-fast            # Run tests without verbose output
make test-verbose         # Run tests with verbose output
make clean                # Clean cache files
```

## Release Branches

The project uses versioned release branches to provide stable, embeddable versions for other projects.

### Release Branch Strategy

- **Versioned Branches**: Each release is a separate branch named `release-v<version>` (e.g., `release-v0.1.0`)main
- **Full Content**: Release branches contain the complete project content from 
- **Source Focus**: Target projects only use the `src/` directory content
- **Version Control**: Prevents conflicts by requiring unique version numbers

### Release Branch Structure

Each release branch contains the full project structure:

```
release-v0.1.0/
├── src/                    # Source code (used by target projects)
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── errors.py
│   │   ├── health.py
│   │   └── utils.py
│   └── storage/
│       ├── __init__.py
│       ├── mongo.py
│       └── redis.py
├── tests/                  # Test files (for reference)
├── docs/                   # Documentation (for reference)
├── tools/                  # Development tools (for reference)
├── pyproject.toml          # Configuration (for reference)
└── README.md               # Documentation (for reference)
```

### Creating Release Branches

```bash
# Create a new release branch with version
./tools/create-release-branch.sh 0.1.0

# Create another version
./tools/create-release-branch.sh 0.2.0

# List all available release branches
./tools/list-release-branches.sh

# Test script logic (without creating branch)
./tools/test-release-script.sh
```

**Prerequisites**:
- Must be on the `main` branch
- main branch must have no uncommitted changes
- main branch must be up to date with remote

**Note**: The script will fail if:
- You're not on the main branch
- main has uncommitted changes
- main is not up to date with remote
- A branch with the same version already exists

### Branch Strategy

The script creates **TWO branches** for each version:

1. **`release-v<version>`** - Full project content:
   - `src/` (source code)
   - `tests/` (test files)
   - `docs/` (documentation)
   - `tools/` (development tools)
   - Configuration files

2. **`library-v<version>`** - Source code only (for external projects):
   - `api/` (moved from `src/api/`)
   - `storage/` (moved from `src/storage/`)
   - `config.py` (moved from `src/config.py`)
   - `__init__.py` (moved from `src/__init__.py`)
   - `README.md` (documentation)
   - (Development files removed)

### Available Tools

- `create-release-branch.sh <version>`: Create both release and library branches
- `list-release-branches.sh`: List all available release and library branches
- `test-release-script.sh`: Test the release script logic without creating branches

## Usage in Target Projects

### Step 1: Add a Specific Release Branch

In your target project root directory, add a specific version:

```bash
# Navigate to your project root directory first
cd /path/to/your/project

# Add a specific library version as subtree (recommended - source code only)
git subtree add --prefix=app/shared <redacted-remote-url> library-v0.1.0 --squash
```

**Note**: Make sure to execute this command in your project's root directory.

### Step 2: Directory Structure

After adding the subtree, your project structure will look like:

```
your-project/
├── app/
│   └── shared/
│       ├── __init__.py
│       ├── api/                # API modules (moved from src/api/)
│       │   ├── __init__.py
│       │   ├── admin.py
│       │   ├── errors.py
│       │   ├── health.py
│       │   └── utils.py
│       ├── storage/            # Storage modules (moved from src/storage/)
│       │   ├── __init__.py
│       │   ├── mongo.py
│       │   └── redis.py
│       ├── config.py           # Configuration module (moved from src/config.py)
│       └── README.md           # Documentation (for reference)
├── your-main-code/
└── other-files...
```

### Step 3: Import and Use

In your Python code, you can now import and use the shared library:

```python
# Import API utilities
from app.shared.api.admin import some_admin_function
from app.shared.api.health import health_check
from app.shared.api.utils import some_utility_function

# Import storage managers
from app.shared.storage.redis import RedisManager, get_cache_client
from app.shared.storage.mongo import MongoManager, get_mongo_client

# Use the managers
redis_manager = RedisManager()
cache_client = get_cache_client("default")

mongo_manager = MongoManager()
mongo_client = get_mongo_client("default")
```

### Step 4: Update to a New Version

To update the shared library to a newer version:

```bash
# Update to a specific new version
git subtree pull --prefix=app/shared <redacted-remote-url> library-v0.2.0 --squash
```

### Step 5: Configuration

shared-lib supports application-level configuration via an optional `shared-lib.yml` file (and still supports demo env files).

#### Required environment variables

1. **`INTERNAL_API_KEY`**
   - Used for internal API authentication (`verify_api_key`).

#### Optional YAML file (shared-lib.yml)

Place `shared-lib.yml` in the project root or a parent directory (CustomConfig searches upward):

```yaml
# Redis service root (used for worker data, etc.)
service_key: shared-lib

# DynamicConfig root key and refresh interval
dynamic_config_root_key: shared-lib:config
dynamic_config_refresh_interval: 10

# Redis client labels (major and queue)
redis_major_label: default
redis_queue_label: default
```

Enable the example configuration:

- When using the library branch (recommended via git subtree to `app/shared`): the example is at `app/shared/shared-lib-example.yml`. Copy it to the same level as `shared` and rename to `shared-lib.yml` (i.e., `app/shared-lib.yml`).

- When using the release branch (full project): the example is at `src/shared-lib-example.yml`. Copy it to the same level as `shared` and rename to `shared-lib.yml` (for example, if `shared` is at `app/shared`, copy to `app/shared-lib.yml`).

`env.example` example (optional):

```bash
# API Authentication (placeholder)
INTERNAL_API_KEY=PLACEHOLDER_INTERNAL_API_KEY

# Redis Configuration (optional)
REDIS_URL=redis://localhost:6379
REDIS_URL_DEFAULT=redis://localhost:6379

# MongoDB Configuration (optional)
MONGO_URL=mongodb://localhost:27017
MONGO_URL_DEFAULT=mongodb://localhost:27017
MONGO_MAX_POOL_SIZE=5
```

## Features

### Storage Management

#### Redis Manager
- Singleton pattern with thread safety
- Support for both standalone and cluster modes
- Automatic connection string loading from environment variables
- Connection pooling and cleanup
- Queue client support (with ARQ integration)

#### MongoDB Manager
- Singleton pattern with thread safety
- Connection string loading from environment variables
- Configurable connection pool sizes
- Automatic client cleanup

### API Utilities
- Admin functions for system management
- Health check endpoints
- Error handling utilities
- Common utility functions

### Environment Configuration
- Automatic loading from `env.example` and `env.local` files (demo-safe)
- Support for multiple environment configurations
- Password hiding in logs for security
- Fallback to default configurations

## Benefits

1. **Clean Import Path**: `from app.shared.api import ...` provides an explicit, public-safe namespace
2. **Namespace Isolation**: The `shared` namespace prevents conflicts with other libraries
3. **Easy Updates**: Simple git subtree commands to update the library
4. **No Dependencies**: The release branch contains only source code, no build artifacts
5. **Thread Safe**: All managers use singleton pattern with proper locking
6. **Environment Aware**: Automatic configuration from environment variables

## Configuration

### Environment Variables

#### Redis Configuration
- `REDIS_URL`: Default Redis connection string
- `REDIS_URL_<LABEL>`: Named Redis connection strings
- `REDIS_URL_DEFAULT`: Explicit default connection string

#### MongoDB Configuration
- `MONGO_URL`: Default MongoDB connection string
- `MONGO_URL_<LABEL>`: Named MongoDB connection strings
- `MONGO_URL_DEFAULT`: Explicit default connection string
- `MONGO_MAX_POOL_SIZE`: Maximum connection pool size (1-100)

### Example Environment Variables

```bash
# Redis
REDIS_URL=redis://localhost:6379
REDIS_URL_PROD=redis://<redacted-host>:6379/0?mode=cluster
REDIS_URL_TEST=redis://<redacted-host>:6379/1?mode=standalone

# MongoDB
MONGO_URL=mongodb://localhost:27017
MONGO_URL_PROD=mongodb://<redacted-host>:27017
MONGO_MAX_POOL_SIZE=10
```

## Testing

The project includes comprehensive tests for all functionality:

- Unit tests for all managers and utilities
- Environment variable handling tests
- Connection string parsing tests
- Error handling tests
- Thread safety tests

Run tests with:
```bash
make test              # Full test suite
make test-cov          # With coverage report
make test-fast         # Quick test run
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

Private - Redacted

## Version

Current version: 0.7.0
