import logging
from typing import Any, Optional

from pr_triage_agent.agent.state import AgentState

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.6


class ReflectionLoop:
    def __init__(self, threshold: float = CONFIDENCE_THRESHOLD):
        self.threshold = threshold

    def should_reflect(self, state: AgentState) -> bool:
        if state.reflection_triggered:
            return False
        if state.confidence is None:
            return False
        return state.confidence < self.threshold

    def build_reflection_prompt(self, state: AgentState) -> str:
        trace_summary = "\n".join(
            f"  {t['step']}: {t['detail'][:200]}"
            for t in state.reasoning_trace[-3:]
        )

        recent_tool_results = "\n".join(
            f"  {k}: {v.output[:200]}"
            for k, v in state.tool_results.items()
        )

        return f"""Your confidence is {state.confidence:.2f} (below {self.threshold}) for the review of this PR.

Review draft so far:
{state.review or "No draft yet"}

Tools already run:
{recent_tool_results or "  None"}

Recent reasoning trace:
{trace_summary or "  No steps"}

Consider: is there a related file you should read, a test you should run, or a code search you should do before finalizing?
Pick ONE additional tool that would raise your confidence, call it, and then produce the final structured review."""

    def plan_next_action(self, state: AgentState) -> str:
        return self.build_reflection_prompt(state)
