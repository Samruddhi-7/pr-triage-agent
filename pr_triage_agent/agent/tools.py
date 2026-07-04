import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TRUNCATE_LENGTH = 3000
DEFAULT_TIMEOUT = 60


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: Optional[str] = None
    raw_output: Optional[str] = None
    duration_ms: Optional[float] = None
    truncated: bool = False

    @classmethod
    def ok(
        cls, output: str, raw_output: Optional[str] = None
    ) -> "ToolResult":
        truncated = len(output) > TRUNCATE_LENGTH
        return cls(
            success=True,
            output=output[:TRUNCATE_LENGTH]
            + ("\n... (truncated)" if truncated else ""),
            raw_output=raw_output,
            truncated=truncated,
        )

    @classmethod
    def from_error(cls, error: str, duration_ms: Optional[float] = None) -> "ToolResult":
        return cls(
            success=False,
            output=error,
            error=error,
            duration_ms=duration_ms,
        )


class ToolSet:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    # ── Linter ─────────────────────────────────────────────────────────────

    def run_linter(self, paths: list[Path]) -> ToolResult:
        if not paths:
            return ToolResult.from_error("No files provided to lint")
        start = time.monotonic()
        try:
            cmd = ["ruff", "check"] + [str(p) for p in paths]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            elapsed = (time.monotonic() - start) * 1000
            if result.returncode == 0:
                return ToolResult.ok(
                    "No lint issues found.", raw_output=result.stdout
                )
            output = self._truncate_output(result.stdout)
            return ToolResult(
                success=True,
                output=output,
                error=result.stderr or None,
                duration_ms=elapsed,
            )
        except FileNotFoundError:
            return ToolResult.from_error(
                "ruff is not installed or not on PATH. "
                "Install with: pip install ruff"
            )
        except subprocess.TimeoutExpired:
            return ToolResult.from_error(
                f"Linter timed out after {self.timeout}s"
            )
        except Exception as e:
            return ToolResult.from_error(f"Linter failed: {e}")

    # ── Test runner ────────────────────────────────────────────────────────

    def run_tests(
        self,
        project_path: Path,
        extra_args: Optional[list[str]] = None,
    ) -> ToolResult:
        start = time.monotonic()
        try:
            cmd = [
                "python", "-m", "pytest",
                str(project_path),
                "--tb=short",
                "--no-header",
                "-q",
            ]
            if extra_args:
                cmd.extend(extra_args)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(project_path) if project_path.is_dir() else None,
            )
            elapsed = (time.monotonic() - start) * 1000
            combined = result.stdout + result.stderr
            output = self._truncate_output(combined)
            return ToolResult(
                success=result.returncode == 0,
                output=output,
                error=result.stderr if result.returncode != 0 else None,
                raw_output=combined,
                duration_ms=elapsed,
            )
        except FileNotFoundError:
            return ToolResult.from_error(
                "pytest is not installed. Install with: pip install pytest"
            )
        except subprocess.TimeoutExpired:
            return ToolResult.from_error(
                f"Test suite timed out after {self.timeout}s"
            )
        except Exception as e:
            return ToolResult.from_error(f"Test runner failed: {e}")

    # ── Static analysis (bandit) ───────────────────────────────────────────

    def run_static_analysis(self, paths: list[Path]) -> ToolResult:
        if not paths:
            return ToolResult.from_error("No files provided for analysis")
        start = time.monotonic()
        try:
            cmd = ["bandit", "-r"] + [str(p) for p in paths] + ["-f", "txt"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            elapsed = (time.monotonic() - start) * 1000
            combined = result.stdout + result.stderr
            output = self._truncate_output(combined)
            return ToolResult(
                success=result.returncode == 0,
                output=output,
                error=result.stderr or None,
                raw_output=combined,
                duration_ms=elapsed,
            )
        except FileNotFoundError:
            return ToolResult.from_error(
                "bandit is not installed. Install with: pip install bandit"
            )
        except subprocess.TimeoutExpired:
            return ToolResult.from_error(
                f"Static analysis timed out after {self.timeout}s"
            )
        except Exception as e:
            return ToolResult.from_error(
                f"Static analysis failed: {e}"
            )

    # ── Read file ──────────────────────────────────────────────────────────

    def read_file(
        self,
        file_path: Path,
        line_range: Optional[tuple[int, int]] = None,
    ) -> ToolResult:
        start = time.monotonic()
        try:
            resolved = file_path.resolve(strict=True)
            if not resolved.is_file():
                return ToolResult.from_error(
                    f"Not a file: {file_path}"
                )

            with open(resolved, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            if line_range:
                start_line, end_line = line_range
                selected = lines[start_line - 1 : end_line]
                excerpt = "".join(selected)
                header = f"--- {file_path} lines {start_line}-{end_line} ---\n"
                output = header + excerpt
            else:
                output = "".join(lines)

            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                output=output[:TRUNCATE_LENGTH]
                + ("\n... (truncated)" if len(output) > TRUNCATE_LENGTH else ""),
                raw_output=output,
                duration_ms=elapsed,
            )
        except FileNotFoundError:
            return ToolResult.from_error(f"File not found: {file_path}")
        except PermissionError:
            return ToolResult.from_error(
                f"Permission denied: {file_path}"
            )
        except Exception as e:
            return ToolResult.from_error(f"Failed to read file: {e}")

    # ── Search codebase ────────────────────────────────────────────────────

    def search_codebase(
        self,
        query: str,
        repo_path: Path,
        include: Optional[str] = None,
    ) -> ToolResult:
        start = time.monotonic()
        try:
            resolved = repo_path.resolve(strict=True)
            if not resolved.is_dir():
                return ToolResult.from_error(
                    f"Not a directory: {repo_path}"
                )

            pattern = re.compile(query, re.IGNORECASE)
            matches: list[str] = []
            max_matches = 50
            skipped_dirs = {
                ".git", "__pycache__", "venv", ".venv",
                ".egg-info", "node_modules", ".pytest_cache",
            }

            for fpath in resolved.rglob("*"):
                if (
                    not fpath.is_file()
                    or any(p in fpath.parts for p in skipped_dirs)
                    or fpath.suffix not in {".py", ".md", ".txt", ".cfg",
                                             ".ini", ".toml", ".yaml",
                                             ".yml", ".json", ".cfg"}
                ):
                    continue
                if include and not fpath.match(include):
                    continue
                try:
                    text = fpath.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        rel = fpath.relative_to(resolved)
                        matches.append(
                            f"{rel}:{i}: {line.strip()}"
                        )
                        if len(matches) >= max_matches:
                            break
                if len(matches) >= max_matches:
                    break

            elapsed = (time.monotonic() - start) * 1000
            if not matches:
                return ToolResult(
                    success=True,
                    output=f"No matches found for '{query}'.",
                    duration_ms=elapsed,
                )

            output = "\n".join(matches)
            if len(matches) >= max_matches:
                output += "\n... (results truncated at 50 matches)"

            return ToolResult(
                success=True,
                output=output,
                raw_output=output,
                duration_ms=elapsed,
            )
        except Exception as e:
            return ToolResult.from_error(
                f"Search failed: {e}"
            )

    @staticmethod
    def _truncate_output(text: str, limit: int = TRUNCATE_LENGTH) -> str:
        if len(text) > limit:
            return text[:limit] + "\n... (truncated)"
        return text
