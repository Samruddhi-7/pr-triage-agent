import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from pr_triage_agent.agent.loop import AgentLoop
from pr_triage_agent.agent.reflection import ReflectionLoop
from pr_triage_agent.agent.tools import ToolSet
from pr_triage_agent.github.fetch import PRFetcher

FIXTURES = Path(__file__).resolve().parent / "fixtures"

BUGGY_DIFF_PATH = FIXTURES / "buggy_pr_diff.txt"


# ── Mock response helpers ────────────────────────────────────────────────


def _make_fc_response(name: str, args: dict):
    fc = MagicMock()
    fc.name = name
    fc.args = args

    part = MagicMock()
    part.function_call = fc
    del part.text

    content = MagicMock()
    content.parts = [part]

    candidate = MagicMock()
    candidate.content = content

    resp = MagicMock()
    resp.candidates = [candidate]
    type(resp).text = PropertyMock(side_effect=ValueError("no text"))
    return resp


def _make_text_response(text: str):
    part = MagicMock()
    part.text = text
    part.function_call = None

    content = MagicMock()
    content.parts = [part]

    candidate = MagicMock()
    candidate.content = content

    resp = MagicMock()
    resp.candidates = [candidate]
    resp.text = text
    return resp


# ── Fixture helpers ──────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
    )


def _build_test_repo(tmp_path: Path) -> Path:
    """Create a repo with a base commit and a feature branch that introduces a bug."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")

    src = repo / "src"
    src.mkdir()
    tests = repo / "tests"
    tests.mkdir()

    # Base commit: original calculator with tests
    (src / "__init__.py").write_text("")
    (tests / "__init__.py").write_text("")
    (src / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    (tests / "test_calculator.py").write_text(
        "from src.calculator import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "-M", "main")

    # Feature branch: adds buggy code
    _git(repo, "checkout", "-b", "feature")
    (src / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n\n"
        "def divide(a, b):\n    return a / b\n\n\n"
        "def process_data(items):\n"
        "    result = 0\n"
        "    for i in range(len(items) + 1):\n"
        "        result += items[i]\n"
        "    return result\n"
    )
    (tests / "test_calculator.py").write_text(
        "from src.calculator import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add buggy functions")
    return repo


# ── Tests ─────────────────────────────────────────────────────────────────


class TestAgentLoop:
    def test_happy_path_with_tool_calls(self, tmp_path: Path) -> None:
        """Agent uses tools and produces a final review."""
        repo = _build_test_repo(tmp_path)

        gemini = MagicMock()
        # Call 1: request linter
        # Call 2: request test run
        # Call 3: produce text review
        review = {
            "risk_rating": "high",
            "confidence": 0.85,
            "summary": "The divide function lacks zero-division handling.",
            "per_file_comments": [
                {
                    "file": "src/calculator.py",
                    "line": 5,
                    "comment": "Missing zero-division check",
                    "severity": "high",
                }
            ],
        }
        gemini.generate_with_contents.side_effect = [
            _make_fc_response("run_linter", {"paths": [str(repo / "src/calculator.py")]}),
            _make_fc_response("run_tests", {"project_path": str(repo)}),
            _make_text_response(json.dumps(review)),
        ]

        toolset = ToolSet(timeout=30)
        pr_fetcher = PRFetcher()
        loop = AgentLoop(gemini, toolset, pr_fetcher)

        state = loop.run(
            pr_url="http://github.com/owner/repo/pull/1",
            repo_path=str(repo),
            base_ref="main",
            head_ref="feature",
        )

        assert state.error is None, state.error
        assert state.risk_rating == "high"
        assert state.confidence == 0.85
        assert "divide" in state.review.lower()
        assert len(state.per_file_comments) == 1
        assert state.iteration_count <= 3
        assert "run_linter" in state.tool_results
        assert "run_tests" in state.tool_results
        assert len(state.reasoning_trace) >= 3

    def test_reflection_triggers_on_low_confidence(
        self, tmp_path: Path
    ) -> None:
        """Agent reflects when confidence is below threshold."""
        repo = _build_test_repo(tmp_path)

        gemini = MagicMock()
        low_conf_review = {
            "risk_rating": "medium",
            "confidence": 0.4,
            "summary": "Not sure about this.",
            "per_file_comments": [],
        }
        final_review = {
            "risk_rating": "high",
            "confidence": 0.85,
            "summary": "Confirmed bug: possible IndexError in process_data.",
            "per_file_comments": [
                {
                    "file": "src/calculator.py",
                    "line": 9,
                    "comment": "IndexError risk",
                    "severity": "high",
                }
            ],
        }
        gemini.generate_with_contents.side_effect = [
            _make_fc_response("run_linter", {"paths": [str(repo / "src/calculator.py")]}),
            _make_text_response(json.dumps(low_conf_review)),
            _make_fc_response("run_tests", {"project_path": str(repo)}),
            _make_text_response(json.dumps(final_review)),
        ]

        toolset = ToolSet(timeout=30)
        pr_fetcher = PRFetcher()
        reflection = ReflectionLoop(threshold=0.6)
        loop = AgentLoop(gemini, toolset, pr_fetcher, reflection_loop=reflection)

        state = loop.run(
            pr_url="http://github.com/owner/repo/pull/1",
            repo_path=str(repo),
            base_ref="main",
            head_ref="feature",
        )

        assert state.error is None, state.error
        assert state.reflection_triggered is True
        assert state.confidence == 0.85
        assert state.risk_rating == "high"
        assert "IndexError" in state.review

    def test_max_iterations_capped(self, tmp_path: Path) -> None:
        """Agent stops after MAX_ITERATIONS tool calls without a review."""
        repo = _build_test_repo(tmp_path)

        gemini = MagicMock()
        gemini.generate_with_contents.side_effect = [
            _make_fc_response("run_linter", {"paths": [str(repo / "src/calculator.py")]})
        ] * 7  # One more than MAX_ITERATIONS = 6

        toolset = ToolSet(timeout=30)
        pr_fetcher = PRFetcher()
        loop = AgentLoop(gemini, toolset, pr_fetcher)

        state = loop.run(
            pr_url="http://github.com/owner/repo/pull/1",
            repo_path=str(repo),
            base_ref="main",
            head_ref="feature",
        )

        assert state.error is not None
        assert "6 iterations" in state.error

    def test_pr_not_found(self) -> None:
        """Handles inaccessible PR gracefully."""
        gemini = MagicMock()
        toolset = ToolSet(timeout=30)
        pr_fetcher = MagicMock(spec=PRFetcher)
        pr_fetcher.fetch_diff.return_value = None

        loop = AgentLoop(gemini, toolset, pr_fetcher)
        state = loop.run("http://github.com/owner/repo/pull/99999")

        assert state.error == "PR not found or inaccessible"

    def test_parse_review_with_markdown_code_blocks(
        self, tmp_path: Path
    ) -> None:
        """Handles reviews wrapped in ```json blocks."""
        repo = _build_test_repo(tmp_path)

        gemini = MagicMock()
        review = {
            "risk_rating": "low",
            "confidence": 0.95,
            "summary": "Looks fine.",
            "per_file_comments": [],
        }
        markdown_block = f"```json\n{json.dumps(review)}\n```"
        gemini.generate_with_contents.side_effect = [
            _make_text_response(markdown_block),
        ]

        toolset = ToolSet(timeout=30)
        pr_fetcher = PRFetcher()
        loop = AgentLoop(gemini, toolset, pr_fetcher)

        state = loop.run(
            pr_url="http://github.com/owner/repo/pull/1",
            repo_path=str(repo),
            base_ref="main",
            head_ref="feature",
        )

        assert state.risk_rating == "low"
        assert state.confidence == 0.95
