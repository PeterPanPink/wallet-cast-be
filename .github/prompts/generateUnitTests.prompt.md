---
name: generateUnitTests
description: Generate comprehensive unit tests for the selected code following project patterns.
argument-hint: The code or module to test
---

Analyze the selected code or module to generate comprehensive unit tests.

1.  **Mandatory Documentation Check**:

    - You **MUST** read the guidelines in `docs/unit_testing/` before generating any code.
    - Key file: `docs/unit_testing/global_guidelines.md`.
    - Follow the "Real Services over Mocks" philosophy for DB/Redis.

2.  **Strategy & Implementation**:
    - Mirror the application directory structure in `tests/`.
    - Use `pytest` and `pytest-asyncio`.
    - Use existing fixtures (e.g., `beanie_db`, `clean_redis_client`) instead of mocking internal DBs.
    - Only mock external 3rd party services (LiveKit, AWS, etc.).
    - Cover happy paths, edge cases, and error handling.
