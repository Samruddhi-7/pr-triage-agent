from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentState:
    pr_url: str
    diff: Optional[str] = None
    changed_files: list[str] = field(default_factory=list)
    lint_output: Optional[str] = None
    test_output: Optional[str] = None
    static_analysis_output: Optional[str] = None
    review: Optional[str] = None
    risk_rating: Optional[str] = None
    confidence: Optional[float] = None
    reflection_steps: int = 0
    error: Optional[str] = None
