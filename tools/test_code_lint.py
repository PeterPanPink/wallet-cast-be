"""Tests for code linting rules."""

import ast

# Add tools directory to path
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from code_lint import (
    CwOutReturnTypeRule,
    NoTryExceptInFlcRule,
    OnlyFlcErrorRule,
    parse_noqa_comments,
)


class TestNoTryExceptInFlcRule:
    """Test FLC002: No try-except blocks in flc directory."""

    def test_detects_try_except_in_flc_directory(self):
        """Should detect try-except blocks in flc directory."""
        code = """
try:
    result = some_function()
except Exception as e:
    print(e)
"""
        tree = ast.parse(code)
        rule = NoTryExceptInFlcRule()

        # Create a path that includes app/api/flc/
        file_path = Path("/home/user/project/app/api/flc/routers/session.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 1
        assert violations[0].rule_id == "FLC002"
        assert "try-except" in violations[0].message

    def test_ignores_try_except_outside_flc_directory(self):
        """Should not detect try-except blocks outside flc directory."""
        code = """
try:
    result = some_function()
except Exception as e:
    print(e)
"""
        tree = ast.parse(code)
        rule = NoTryExceptInFlcRule()

        # Create a path outside flc directory
        file_path = Path("/home/user/project/app/services/some_service.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0

    def test_detects_nested_try_except(self):
        """Should detect nested try-except blocks."""
        code = """
def handler():
    try:
        outer()
        try:
            inner()
        except ValueError:
            pass
    except Exception:
        pass
"""
        tree = ast.parse(code)
        rule = NoTryExceptInFlcRule()

        file_path = Path("/home/user/project/app/api/flc/handlers.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 2


class TestCwOutReturnTypeRule:
    """Test FLC003: All endpoints must return CwOut[T] or response classes."""

    def test_detects_missing_return_type_on_endpoint(self):
        """Should detect endpoints without return type annotation."""
        code = """
from fastapi import APIRouter

router = APIRouter()

@router.get("/test")
async def test_endpoint():
    return {"message": "test"}
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/routers/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 1
        assert violations[0].rule_id == "FLC003"
        assert "must have a return type annotation" in violations[0].message

    def test_accepts_cwout_return_type(self):
        """Should accept CwOut[T] return type."""
        code = """
from fastapi import APIRouter
from app.api.flc.schemas.base import CwOut

router = APIRouter()

@router.get("/test")
async def test_endpoint() -> CwOut[dict]:
    return CwOut(results={})
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/routers/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0

    def test_accepts_response_class_return_type(self):
        """Should accept explicit response classes like PlainTextResponse."""
        code = """
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()

@router.get("/test")
async def test_endpoint() -> PlainTextResponse:
    return PlainTextResponse(content="test")
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/routers/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0

    def test_detects_invalid_return_type(self):
        """Should detect endpoints with invalid return types."""
        code = """
from fastapi import APIRouter

router = APIRouter()

@router.get("/test")
async def test_endpoint() -> dict:
    return {"message": "test"}
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/routers/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 1
        assert violations[0].rule_id == "FLC003"
        assert "must return CwOut[T]" in violations[0].message

    def test_ignores_non_endpoint_functions(self):
        """Should ignore functions without router decorator."""
        code = """
def helper_function() -> dict:
    return {"message": "test"}
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/routers/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0

    def test_ignores_files_outside_routers_directory(self):
        """Should only check files in routers directory."""
        code = """
from fastapi import APIRouter

router = APIRouter()

@router.get("/test")
async def test_endpoint():
    return {"message": "test"}
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/schemas/base.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0

    def test_checks_post_put_delete_patch_decorators(self):
        """Should check all HTTP method decorators."""
        code = """
from fastapi import APIRouter

router = APIRouter()

@router.post("/test")
async def post_endpoint():
    return {}

@router.put("/test")
async def put_endpoint():
    return {}

@router.delete("/test")
async def delete_endpoint():
    return {}

@router.patch("/test")
async def patch_endpoint():
    return {}
"""
        tree = ast.parse(code)
        rule = CwOutReturnTypeRule()

        file_path = Path("/home/user/project/app/api/flc/routers/test.py")
        violations = rule.check_file(file_path, tree)

        # Should detect all 4 endpoints without return types
        assert len(violations) == 4


class TestOnlyFlcErrorRule:
    """Test FLC001: Only FlcError should be raised."""

    def test_detects_value_error(self):
        """Should detect ValueError being raised."""
        code = """
def function():
    raise ValueError("error message")
"""
        tree = ast.parse(code)
        rule = OnlyFlcErrorRule()

        file_path = Path("/home/user/project/app/services/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 1
        assert violations[0].rule_id == "FLC001"
        assert "ValueError" in violations[0].message

    def test_accepts_flc_error(self):
        """Should accept FlcError being raised."""
        code = """
def function():
    raise FlcError(errcode="ERR001", errmesg="error")
"""
        tree = ast.parse(code)
        rule = OnlyFlcErrorRule()

        file_path = Path("/home/user/project/app/services/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0

    def test_accepts_bare_raise(self):
        """Should accept bare raise statements (re-raising)."""
        code = """
def function():
    try:
        pass
    except:
        raise
"""
        tree = ast.parse(code)
        rule = OnlyFlcErrorRule()

        file_path = Path("/home/user/project/app/services/test.py")
        violations = rule.check_file(file_path, tree)

        assert len(violations) == 0


class TestNoqaComments:
    """Test noqa comment parsing and suppression."""

    def test_parse_noqa_with_specific_code(self):
        """Should parse noqa comments with specific rule codes."""
        code = """x = 1  # noqa: FLC001"""
        result = parse_noqa_comments(code)
        assert result == {1: {"FLC001"}}

    def test_parse_noqa_with_multiple_codes(self):
        """Should parse noqa comments with multiple rule codes."""
        code = """x = 1  # noqa: FLC001, FLC002"""
        result = parse_noqa_comments(code)
        assert result == {1: {"FLC001", "FLC002"}}

    def test_parse_noqa_without_codes(self):
        """Should parse bare noqa comments (disable all rules)."""
        code = """x = 1  # noqa"""
        result = parse_noqa_comments(code)
        assert result == {1: None}

    def test_parse_type_ignore(self):
        """Should parse type: ignore comments (disable all rules)."""
        code = """x = 1  # type: ignore"""
        result = parse_noqa_comments(code)
        assert result == {1: None}

    def test_parse_noqa_case_insensitive(self):
        """Should parse noqa comments case-insensitively."""
        code = """x = 1  # NOQA: flc001"""
        result = parse_noqa_comments(code)
        assert result == {1: {"FLC001"}}

    def test_parse_multiple_lines(self):
        """Should parse noqa comments on multiple lines."""
        code = """line1
x = 1  # noqa: FLC001
y = 2
z = 3  # noqa: FLC002, FLC003"""
        result = parse_noqa_comments(code)
        assert result == {2: {"FLC001"}, 4: {"FLC002", "FLC003"}}

    def test_no_noqa_comments(self):
        """Should return empty dict when no noqa comments present."""
        code = """x = 1
y = 2  # normal comment"""
        result = parse_noqa_comments(code)
        assert result == {}
