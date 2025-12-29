# Ruff Linter & Formatter Guide

## Overview

Ruff is an extremely fast Python linter and formatter written in Rust. It replaces multiple tools (Flake8, isort, Black, pyupgrade, etc.) with a single, fast solution.

## Quick Commands

```bash
# Run linter with auto-fix
make lint

# Run formatter
make format

# Check linting without fixing
make lint-check

# Check formatting without fixing
make format-check
```

## VS Code Integration

The `.vscode/settings.json` is configured to:

- Use Ruff as the default Python formatter
- Format on save
- Auto-fix and organize imports on save

**Note:** Install the [Ruff VS Code extension](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff) for full integration.

## Configuration

Configuration is in `pyproject.toml` under `[tool.ruff]`:

### Enabled Rules

- **E/W**: pycodestyle errors and warnings
- **F**: pyflakes (undefined names, unused imports, etc.)
- **I**: isort (import sorting)
- **UP**: pyupgrade (modern Python syntax)
- **B**: flake8-bugbear (likely bugs and design problems)
- **C4**: flake8-comprehensions (better comprehensions)
- **SIM**: flake8-simplify (simplification suggestions)
- **RUF**: Ruff-specific rules

### Project Settings

- **Line length**: 100 characters
- **Target**: Python 3.10+
- **Quote style**: Double quotes
- **Exclude**: `app/shared/` (read-only shared library)

## Common Issues & Fixes

### Import Sorting (I001)

Ruff automatically organizes imports into groups:

1. Standard library
2. Third-party packages
3. First-party (`app.*`)
4. Local imports

**Auto-fix**: `make lint`

### Trailing Whitespace (W291)

Removes unnecessary whitespace at end of lines.

**Auto-fix**: `make format`

### Undefined Names (F821)

Catches typos and missing imports.

**Manual fix required** - check your code for undefined variables.

### Mutable Default Arguments (B008)

```python
# Bad
def func(items=[]):
    ...

# Good
def func(items=None):
    items = items or []
```

### Collapsible If Statements (SIM102)

```python
# Bad
if condition1:
    if condition2:
        do_something()

# Good
if condition1 and condition2:
    do_something()
```

## CI Integration

Add to your CI pipeline:

```yaml
- name: Lint with Ruff
  run: make lint-check

- name: Check formatting
  run: make format-check
```

## Ignoring Specific Rules

### Per-file ignores

Add to `pyproject.toml`:

```toml
[tool.ruff.lint.per-file-ignores]
"specific_file.py" = ["F401", "F821"]
```

### Inline ignores

```python
# Ignore next line
x = dangerous_function()  # noqa: F841

# Ignore specific rule
import unused_module  # noqa: F401
```

## Unsafe Fixes

Some fixes are marked as "unsafe" and require explicit opt-in:

```bash
uv run ruff check . --fix --unsafe-fixes
```

Use with caution - these can change code semantics.

## Resources

- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [Rule Reference](https://docs.astral.sh/ruff/rules/)
- [Configuration Options](https://docs.astral.sh/ruff/configuration/)
