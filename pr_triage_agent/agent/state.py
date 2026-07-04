from dataclasses import dataclass, field
from typing import Optional

from pr_triage_agent.agent.tools import ToolResult


@dataclass
class AgentState:
    pr_url: str = ""
    diff: Optional[str] = None
    changed_files: list[str] = field(default_factory=list)
    repo_path: Optional[str] = None

    tool_results: dict[str, ToolResult] = field(default_factory=dict)
    reasoning_trace: list[dict] = field(default_factory=list)

    iteration_count: int = 0

    review: Optional[str] = None
    risk_rating: Optional[str] = None
    confidence: Optional[float] = None
    per_file_comments: list[dict] = field(default_factory=list)

    reflection_triggered: bool = False
    error: Optional[str] = None

    def add_trace(self, step: str, detail: str = "") -> None:
        self.reasoning_trace.append({"step": step, "detail": detail})
