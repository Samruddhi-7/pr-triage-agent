from typing import Optional


class PRFetcher:
    def __init__(self, token: Optional[str] = None):
        self.token = token

    def fetch_diff(self, pr_url: str) -> Optional[str]:
        raise NotImplementedError("Phase 1")

    def fetch_changed_files(self, pr_url: str) -> list[str]:
        raise NotImplementedError("Phase 1")
