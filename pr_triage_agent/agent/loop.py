from pr_triage_agent.agent.state import AgentState
from pr_triage_agent.agent.tools import ToolSet
from pr_triage_agent.agent.reflection import ReflectionLoop
from pr_triage_agent.llm.gemini_client import GeminiClient
from pr_triage_agent.github.fetch import PRFetcher


class AgentLoop:
    def __init__(self, gemini_client: GeminiClient, toolset: ToolSet, pr_fetcher: PRFetcher):
        self.gemini = gemini_client
        self.toolset = toolset
        self.pr_fetcher = pr_fetcher

    def run(self, pr_url: str) -> AgentState:
        raise NotImplementedError("Phase 2")
