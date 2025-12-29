# Code Linting Tool

AST-based code quality checker for the WalletCast demo backend.

## Usage

```bash
# Run all lint checks
python tools/code_lint.py

# Or make it executable and run directly
chmod +x tools/code_lint.py
./tools/code_lint.py
```

## Current Rules

### FLC001: Only AppError Should Be Raised

Ensures that only `AppError` exceptions are raised in application code. This rule enforces consistent error handling across the codebase.

**Allowed:**

- `AppError` (our custom error class)

**Not allowed:**

- Built-in exceptions: `ValueError`, `TypeError`, `KeyError`, `Exception`, etc.
- FastAPI/Pydantic exceptions: `HTTPException`, `ValidationError`, `RequestValidationError`
- Any other exception types

All business logic errors should be raised as `AppError` with appropriate error codes from `AppErrorCode`.

## Adding New Rules

To add a new lint rule:

1. Create a new class that inherits from `LintRule`:

```python
class MyNewRule(LintRule):
    """Description of what this rule checks."""

    @property
    def rule_id(self) -> str:
        return "FLC002"  # Use next available ID

    @property
    def description(self) -> str:
        return "Human-readable description"

    def check_file(self, file_path: Path, tree: ast.AST) -> List[LintViolation]:
        violations = []

        # Walk the AST and check for issues
        for node in ast.walk(tree):
            if isinstance(node, ast.SomeNode):
                # Check condition
                if some_condition:
                    violations.append(
                        LintViolation(
                            rule_id=self.rule_id,
                            file_path=file_path,
                            line_number=node.lineno,
                            column=node.col_offset,
                            message="Description of the violation",
                            severity="error",  # or "warning", "info"
                        )
                    )

        return violations
```

2. Register the rule in `CodeLinter.__init__()`:

```python
self.rules: List[LintRule] = [
    OnlyFlcErrorRule(),
    MyNewRule(),  # Add your new rule here
]
```

## Configuration

### Ignored Directories

The linter automatically ignores:

- `__pycache__`
- `.pytest_cache`
- `.git`
- `app/shared` (read-only shared library)

To modify ignored directories, edit the `ignored_dirs` set in `CodeLinter.get_python_files()`.

### Severity Levels

- **error**: Must be fixed, causes non-zero exit code
- **warning**: Should be reviewed, doesn't block CI
- **info**: Informational, suggestions for improvement

## Exit Codes

- `0`: No errors found (warnings/info may exist)
- `1`: One or more errors found

## Integration with CI/CD

Add to your CI pipeline:

```yaml
- name: Run code linter
  run: python tools/code_lint.py
```

Or add to Makefile:

```makefile
lint:
	python tools/code_lint.py
```
