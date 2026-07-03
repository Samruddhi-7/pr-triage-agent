import subprocess
from pathlib import Path
from typing import Optional


class ToolResult:
    def __init__(self, stdout: str, stderr: str, return_code: int):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code

    @property
    def success(self) -> bool:
        return self.return_code == 0


class ToolSet:
    def run_linter(self, filepath: Path) -> ToolResult:
        raise NotImplementedError("Phase 3")

    def run_tests(self, project_path: Path) -> ToolResult:
        raise NotImplementedError("Phase 3")

    def run_static_analysis(self, filepath: Path) -> ToolResult:
        raise NotImplementedError("Phase 3")
