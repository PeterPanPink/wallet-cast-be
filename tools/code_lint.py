#!/usr/bin/env python3
"""Code linting tool using AST analysis.

This script performs custom code quality checks on the WalletCast demo codebase.
It's designed to be extensible with new lint rules.

Active Rules:
    FLC001: Only FlcError should be raised (not ValueError, Exception, etc.)
    FLC002: No try-except blocks allowed in app/api/flc/ directory
    FLC003: All FastAPI endpoints must return CwOut[T] or explicit response classes

Disabling Rules:
    Use inline comments to disable specific rules:
    - # noqa: FLC001           - Disable FLC001 on this line
    - # noqa: FLC001, FLC002   - Disable multiple rules
    - # noqa                   - Disable all rules on this line
    - # type: ignore           - Also disables all rules (for compatibility)

Usage:
    python tools/code_lint.py
    python tools/code_lint.py --fix  # Auto-fix issues where possible
"""

import ast
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

# Pattern to match noqa comments like: # noqa: FLC001, FLC002 or just # noqa
NOQA_PATTERN = re.compile(
    r"#\s*noqa(?::\s*(?P<codes>[A-Z0-9,\s]+))?\s*$|#\s*type:\s*ignore",
    re.IGNORECASE,
)


def parse_noqa_comments(source: str) -> dict[int, set[str] | None]:
    """Parse noqa comments from source code.

    Returns:
        Dict mapping line numbers to either:
        - None: all rules disabled on that line (# noqa or # type: ignore)
        - set of rule IDs: specific rules disabled (# noqa: FLC001, FLC002)
    """
    noqa_lines: dict[int, set[str] | None] = {}
    lines = source.splitlines()

    for line_num, line in enumerate(lines, start=1):
        match = NOQA_PATTERN.search(line)
        if match:
            codes_str = match.group("codes")
            if codes_str:
                # Specific codes: # noqa: FLC001, FLC002
                codes = {code.strip().upper() for code in codes_str.split(",") if code.strip()}
                noqa_lines[line_num] = codes
            else:
                # No specific codes: # noqa or # type: ignore - disable all
                noqa_lines[line_num] = None

    return noqa_lines


@dataclass
class LintViolation:
    """Represents a code lint violation."""

    rule_id: str
    file_path: Path
    line_number: int
    column: int
    message: str
    severity: str = "error"  # "error", "warning", "info"

    def __str__(self) -> str:
        return f"{self.file_path}:{self.line_number}:{self.column}: {self.severity}: [{self.rule_id}] {self.message}"


class LintRule(ABC):
    """Base class for lint rules."""

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this rule checks."""
        pass

    @abstractmethod
    def check_file(self, file_path: Path, tree: ast.AST) -> list[LintViolation]:
        """Check a file for violations.

        Args:
            file_path: Path to the file being checked
            tree: Parsed AST of the file

        Returns:
            List of violations found
        """
        pass


class OnlyFlcErrorRule(LintRule):
    """Ensures only FlcError is raised in the codebase."""

    @property
    def rule_id(self) -> str:
        return "FLC001"

    @property
    def description(self) -> str:
        return "Only FlcError should be raised in application code"

    def check_file(self, file_path: Path, tree: ast.AST) -> list[LintViolation]:
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                if node.exc is None:
                    # bare raise statement (re-raising)
                    continue

                exception_name = self._get_exception_name(node.exc)
                if exception_name and not self._is_allowed_exception(exception_name):
                    violations.append(
                        LintViolation(
                            rule_id=self.rule_id,
                            file_path=file_path,
                            line_number=node.lineno,
                            column=node.col_offset,
                            message=f"Raising '{exception_name}' is not allowed. Use FlcError instead.",
                            severity="error",
                        )
                    )

        return violations

    def _get_exception_name(self, exc_node: ast.expr) -> str | None:
        """Extract the exception name from a raise statement."""
        if isinstance(exc_node, ast.Name):
            return exc_node.id
        elif isinstance(exc_node, ast.Call):
            if isinstance(exc_node.func, ast.Name):
                return exc_node.func.id
            elif isinstance(exc_node.func, ast.Attribute):
                return exc_node.func.attr
        return None

    def _is_allowed_exception(self, exception_name: str) -> bool:
        """Check if an exception is allowed to be raised."""
        # Only FlcError is allowed
        return exception_name == "FlcError"


class NoTryExceptInFlcRule(LintRule):
    """Ensures no try-except blocks are used in the flc directory."""

    @property
    def rule_id(self) -> str:
        return "FLC002"

    @property
    def description(self) -> str:
        return "No try-except blocks allowed in app/api/flc/ directory"

    def check_file(self, file_path: Path, tree: ast.AST) -> list[LintViolation]:
        violations = []

        # Only check files in app/api/flc/ directory
        if "app/api/flc" not in str(file_path):
            return violations

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                violations.append(
                    LintViolation(
                        rule_id=self.rule_id,
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset,
                        message="try-except blocks are not allowed in the flc directory. Use FlcError instead.",
                        severity="error",
                    )
                )

        return violations


class CwOutReturnTypeRule(LintRule):
    """Ensures all FastAPI endpoints return CwOut[T] or explicit response classes."""

    @property
    def rule_id(self) -> str:
        return "FLC003"

    @property
    def description(self) -> str:
        return "All FastAPI endpoints must return CwOut[T] or explicit response classes"

    def check_file(self, file_path: Path, tree: ast.AST) -> list[LintViolation]:
        violations = []

        # Only check router files in app/api/flc/routers/
        if "app/api/flc/routers" not in str(file_path):
            return violations

        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                # Check if function has a router decorator
                if not self._has_router_decorator(node):
                    continue

                # Check return type annotation
                if node.returns is None:
                    violations.append(
                        LintViolation(
                            rule_id=self.rule_id,
                            file_path=file_path,
                            line_number=node.lineno,
                            column=node.col_offset,
                            message=f"Endpoint '{node.name}' must have a return type annotation (CwOut[T] or response class).",
                            severity="error",
                        )
                    )
                    continue

                # Check if return type is valid
                if not self._is_valid_return_type(node.returns):
                    violations.append(
                        LintViolation(
                            rule_id=self.rule_id,
                            file_path=file_path,
                            line_number=node.lineno,
                            column=node.col_offset,
                            message=f"Endpoint '{node.name}' must return CwOut[T] or an explicit response class (e.g., PlainTextResponse, JSONResponse).",
                            severity="error",
                        )
                    )

        return violations

    def _has_router_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if function has @router.get/post/put/delete/patch decorator."""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if (
                    isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "router"
                ):
                    return True
            elif (
                isinstance(decorator, ast.Attribute)
                and isinstance(decorator.value, ast.Name)
                and decorator.value.id == "router"
            ):
                return True
        return False

    def _is_valid_return_type(self, return_type: ast.expr) -> bool:
        """Check if return type is CwOut[T] or a valid response class."""
        # Check for CwOut[T] pattern
        if (
            isinstance(return_type, ast.Subscript)
            and isinstance(return_type.value, ast.Name)
            and return_type.value.id == "CwOut"
        ):
            return True

        # Check for explicit response classes
        if isinstance(return_type, ast.Name):
            # Allow explicit response classes
            allowed_response_classes = {
                "PlainTextResponse",
                "JSONResponse",
                "HTMLResponse",
                "Response",
                "StreamingResponse",
                "FileResponse",
                "RedirectResponse",
            }
            if return_type.id in allowed_response_classes:
                return True

        return False


class CodeLinter:
    """Main code linter that runs all lint rules."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.rules: list[LintRule] = [
            OnlyFlcErrorRule(),
            NoTryExceptInFlcRule(),
            CwOutReturnTypeRule(),
        ]

    def get_python_files(self) -> list[Path]:
        """Get all Python files in the project, excluding ignored paths."""
        app_dir = self.project_root / "app"
        ignored_dirs = {
            "__pycache__",
            ".pytest_cache",
            ".git",
            "cw",  # Ignore the cw library
        }

        python_files = []
        for py_file in app_dir.rglob("*.py"):
            # Check if any parent directory is in ignored_dirs
            if any(part in ignored_dirs for part in py_file.parts):
                continue
            python_files.append(py_file)

        return sorted(python_files)

    def lint_file(self, file_path: Path) -> list[LintViolation]:
        """Lint a single file with all rules."""
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            return [
                LintViolation(
                    rule_id="SYNTAX",
                    file_path=file_path,
                    line_number=e.lineno or 0,
                    column=e.offset or 0,
                    message=f"Syntax error: {e.msg}",
                    severity="error",
                )
            ]
        except Exception as e:
            return [
                LintViolation(
                    rule_id="PARSE",
                    file_path=file_path,
                    line_number=0,
                    column=0,
                    message=f"Failed to parse file: {e}",
                    severity="error",
                )
            ]

        # Parse noqa comments
        noqa_lines = parse_noqa_comments(content)

        violations = []
        for rule in self.rules:
            for violation in rule.check_file(file_path, tree):
                # Check if this violation should be suppressed
                if self._is_suppressed(violation, noqa_lines):
                    continue
                violations.append(violation)

        return violations

    def _is_suppressed(
        self,
        violation: LintViolation,
        noqa_lines: dict[int, set[str] | None],
    ) -> bool:
        """Check if a violation is suppressed by a noqa comment."""
        line_num = violation.line_number
        if line_num not in noqa_lines:
            return False

        suppressed_codes = noqa_lines[line_num]
        # None means all rules are suppressed (# noqa or # type: ignore)
        if suppressed_codes is None:
            return True

        # Check if the specific rule is suppressed
        return violation.rule_id.upper() in suppressed_codes

    def lint_all(self) -> list[LintViolation]:
        """Lint all Python files in the project."""
        all_violations = []
        python_files = self.get_python_files()

        print(f"🔍 Linting {len(python_files)} Python files...")
        print(f"📋 Active rules: {', '.join(rule.rule_id for rule in self.rules)}\n")

        for file_path in python_files:
            violations = self.lint_file(file_path)
            all_violations.extend(violations)

        return all_violations

    def print_summary(self, violations: list[LintViolation]) -> None:
        """Print a summary of violations."""
        if not violations:
            print("✅ No violations found!\n")
            return

        print(f"\n❌ Found {len(violations)} violation(s):\n")

        # Group by severity
        errors = [v for v in violations if v.severity == "error"]
        warnings = [v for v in violations if v.severity == "warning"]
        infos = [v for v in violations if v.severity == "info"]

        for violation in violations:
            print(violation)

        print("\n📊 Summary:")
        if errors:
            print(f"   Errors: {len(errors)}")
        if warnings:
            print(f"   Warnings: {len(warnings)}")
        if infos:
            print(f"   Info: {len(infos)}")
        print()


def main() -> int:
    """Main entry point."""
    project_root = Path(__file__).parent.parent
    linter = CodeLinter(project_root)

    violations = linter.lint_all()
    linter.print_summary(violations)

    # Return exit code: 0 if no errors, 1 if errors found
    has_errors = any(v.severity == "error" for v in violations)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
