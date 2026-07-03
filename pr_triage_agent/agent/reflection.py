from pr_triage_agent.agent.state import AgentState


class ReflectionLoop:
    def __init__(self, max_steps: int = 3):
        self.max_steps = max_steps

    def should_reflect(self, state: AgentState) -> bool:
        raise NotImplementedError("Phase 4")

    def plan_next_action(self, state: AgentState) -> str:
        raise NotImplementedError("Phase 4")
