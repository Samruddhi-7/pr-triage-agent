from pathlib import Path

import pytest

from pr_triage_agent.agent.tools import ToolResult, ToolSet

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sample_project"
SRC = FIXTURES / "src"
MATH_UTILS = SRC / "math_utils.py"
UNSAFE = SRC / "unsafe.py"


# ── ToolResult ─────────────────────────────────────────────────────────────


class TestToolResult:
    def test_ok_no_truncation(self) -> None:
        short = "hello"
        r = ToolResult.ok(short)
        assert r.success is True
        assert r.output == short
        assert r.truncated is False

    def test_ok_truncation(self) -> None:
        long_text = "a" * 5000
        r = ToolResult.ok(long_text)
        assert len(r.output) < 5000
        assert r.truncated is True
        assert "... (truncated)" in r.output

    def test_from_error(self) -> None:
        r = ToolResult.from_error("something broke")
        assert r.success is False
        assert r.error == "something broke"
        assert r.output == "something broke"


# ── ToolSet ────────────────────────────────────────────────────────────────


@pytest.fixture
def tools():
    return ToolSet(timeout=30)


class TestRunLinter:
    def test_linter_clean_file(self, tools: ToolSet) -> None:
        result = tools.run_linter([MATH_UTILS])
        assert result.success
        assert "No lint issues found" in result.output

    def test_linter_reports_issues(self, tools: ToolSet) -> None:
        result = tools.run_linter([UNSAFE])
        assert result.success
        assert "json" in result.output.lower() or "unused" in result.output.lower()

    def test_linter_no_files(self, tools: ToolSet) -> None:
        result = tools.run_linter([])
        assert result.success is False
        assert "No files provided" in result.output

    def test_linter_nonexistent_file(self, tools: ToolSet) -> None:
        result = tools.run_linter([Path("/nonexistent/file.py")])
        assert result.success  # ruff returns non-zero on missing files but we still treat it as a valid result
        assert result.output


class TestRunTests:
    def test_all_tests_pass(self, tools: ToolSet) -> None:
        result = tools.run_tests(
            FIXTURES,
            extra_args=["--ignore=tests/test_failing.py", "tests/"],
        )
        assert result.success is True
        assert "passed" in result.output.lower()

    def test_failing_tests(self, tools: ToolSet) -> None:
        result = tools.run_tests(FIXTURES, extra_args=["tests/test_failing.py"])
        assert result.success is False
        assert "failed" in result.output.lower()

    def test_timeout(self) -> None:
        fast_tools = ToolSet(timeout=0.001)
        result = fast_tools.run_tests(FIXTURES)
        assert result.success is False
        assert "timed out" in result.output


class TestRunStaticAnalysis:
    def test_secure_file_passes(self, tools: ToolSet) -> None:
        result = tools.run_static_analysis([MATH_UTILS])
        assert result.success
        assert "No issues" in result.output

    def test_insecure_file_reports_findings(self, tools: ToolSet) -> None:
        result = tools.run_static_analysis([UNSAFE])
        assert result.success is False
        assert "Issue" in result.output or "subprocess" in result.output.lower()

    def test_no_files(self, tools: ToolSet) -> None:
        result = tools.run_static_analysis([])
        assert result.success is False
        assert "No files provided" in result.output

    def test_nonexistent_file(self, tools: ToolSet) -> None:
        result = tools.run_static_analysis([Path("/nonexistent")])
        assert result.success  # bandit exits 0; it skips missing files gracefully


class TestReadFile:
    def test_read_whole_file(self, tools: ToolSet) -> None:
        result = tools.read_file(MATH_UTILS)
        assert result.success
        assert "def add" in result.output
        assert "def divide" in result.output

    def test_read_line_range(self, tools: ToolSet) -> None:
        result = tools.read_file(MATH_UTILS, line_range=(1, 3))
        assert result.success
        assert "def add" in result.output
        assert "def divide" not in result.output

    def test_file_not_found(self, tools: ToolSet) -> None:
        result = tools.read_file(Path("/nonexistent/file.py"))
        assert result.success is False
        assert "File not found" in result.error

    def test_not_a_file(self, tools: ToolSet) -> None:
        result = tools.read_file(SRC)
        assert result.success is False
        assert "Not a file" in result.error


class TestSearchCodebase:
    def test_find_matches(self, tools: ToolSet) -> None:
        result = tools.search_codebase("def add", SRC)
        assert result.success
        assert "math_utils.py" in result.output

    def test_no_matches(self, tools: ToolSet) -> None:
        result = tools.search_codebase("xyznonexistent", SRC)
        assert result.success
        assert "No matches found" in result.output

    def test_not_a_directory(self, tools: ToolSet) -> None:
        result = tools.search_codebase("test", MATH_UTILS)
        assert result.success is False
        assert "Not a directory" in result.error
