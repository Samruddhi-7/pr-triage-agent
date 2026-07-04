import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import requests


class LineType(Enum):
    CONTEXT = "context"
    ADDED = "added"
    REMOVED = "removed"


class FileStatus(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    UNKNOWN = "unknown"


@dataclass
class DiffLine:
    type: LineType
    content: str
    old_number: Optional[int] = None
    new_number: Optional[int] = None


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str = ""
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class DiffFile:
    filename: str
    status: FileStatus = FileStatus.MODIFIED
    old_path: Optional[str] = None
    hunks: list[Hunk] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    @property
    def is_binary(self) -> bool:
        return not self.hunks


_PR_URL_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/pull/(\d+)/?$"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = _PR_URL_RE.match(url)
    if not m:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    owner, repo, number = m.group(1), m.group(2), int(m.group(3))
    return owner, repo, number


_CHUNK_HEADER_RE = re.compile(
    r"^@@\s+-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@\s*(.*)"
)


def parse_diff(raw: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    current_file: Optional[DiffFile] = None
    current_hunk: Optional[Hunk] = None

    old_line = 0
    new_line = 0

    for line in raw.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")

        # File header: --- a/old_path
        if stripped.startswith("--- "):
            old_path = _strip_prefix(stripped[4:])
            if current_file is not None:
                files.append(current_file)

            current_file = DiffFile(
                filename="",
                old_path=old_path,
            )
            current_hunk = None

        # File header: +++ b/new_path
        elif stripped.startswith("+++ ") and current_file is not None:
            new_path = _strip_prefix(stripped[4:])
            if new_path == "/dev/null":
                current_file.filename = current_file.old_path or "/dev/null"
            else:
                current_file.filename = new_path

            if current_file.old_path == "/dev/null":
                current_file.status = FileStatus.ADDED
            elif new_path == "/dev/null":
                current_file.status = FileStatus.REMOVED

        # Hunk header: @@ -old,count +new,count @@
        elif stripped.startswith("@@"):
            m = _CHUNK_HEADER_RE.match(stripped)
            if m and current_file is not None:
                old_start = int(m.group(1))
                old_cnt = int(m.group(2)) if m.group(2) else 1
                new_start = int(m.group(3))
                new_cnt = int(m.group(4)) if m.group(4) else 1
                header = m.group(5).strip()

                current_hunk = Hunk(
                    old_start=old_start,
                    old_count=old_cnt,
                    new_start=new_start,
                    new_count=new_cnt,
                    header=header,
                )
                current_file.hunks.append(current_hunk)
                old_line = old_start
                new_line = new_start

        # Binary file indicator
        elif stripped.startswith("Binary files") and current_file is not None:
            files.append(current_file)
            current_file = None
            current_hunk = None

        # File content lines (only within hunks)
        elif current_hunk is not None:
            if stripped.startswith("+") and not stripped.startswith("+++"):
                content = stripped[1:]
                diff_line = DiffLine(
                    type=LineType.ADDED,
                    content=content,
                    new_number=new_line,
                )
                current_hunk.lines.append(diff_line)
                current_file.additions += 1
                new_line += 1
            elif stripped.startswith("-") and not stripped.startswith("---"):
                content = stripped[1:]
                diff_line = DiffLine(
                    type=LineType.REMOVED,
                    content=content,
                    old_number=old_line,
                )
                current_hunk.lines.append(diff_line)
                current_file.deletions += 1
                old_line += 1
            elif stripped.startswith(" "):
                content = stripped[1:]
                diff_line = DiffLine(
                    type=LineType.CONTEXT,
                    content=content,
                    old_number=old_line,
                    new_number=new_line,
                )
                current_hunk.lines.append(diff_line)
                old_line += 1
                new_line += 1
            elif stripped.startswith("\\ "):
                pass

        # Rename/copy headers from git diff
        elif stripped.startswith("rename from ") and current_file is not None:
            current_file.status = FileStatus.RENAMED
        elif stripped.startswith("rename to ") and current_file is not None:
            current_file.status = FileStatus.RENAMED

        # New file mode
        elif stripped.startswith("new file mode") and current_file is not None:
            current_file.status = FileStatus.ADDED
        elif (
            stripped.startswith("deleted file mode")
            and current_file is not None
        ):
            current_file.status = FileStatus.REMOVED

    if current_file is not None:
        files.append(current_file)

    return files


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


class PRFetcher:
    def __init__(self, token: Optional[str] = None):
        if token is None:
            token = os.environ.get("GITHUB_TOKEN")
        self.token = token
        self._session = requests.Session()
        if self.token:
            self._session.headers.update(
                {"Authorization": f"Bearer {self.token}"}
            )

    def fetch_diff(self, pr_url: str) -> Optional[list[DiffFile]]:
        owner, repo, number = parse_pr_url(pr_url)
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
        )
        headers = {"Accept": "application/vnd.github.v3.diff"}
        resp = self._session.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw_diff = resp.text
        return parse_diff(raw_diff)

    def fetch_changed_files(self, pr_url: str) -> Optional[list[str]]:
        owner, repo, number = parse_pr_url(pr_url)
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/files"
        )
        resp = self._session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return [f["filename"] for f in resp.json()]

    @staticmethod
    def fetch_diff_local(
        repo_path: str | Path,
        base_ref: str,
        head_ref: str,
    ) -> Optional[list[DiffFile]]:
        repo = Path(repo_path).resolve()
        try:
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--git-dir"],
                capture_output=True,
                check=True,
                timeout=10,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise ValueError(f"Not a git repository: {repo}")

        cmd = [
            "git",
            "-C",
            str(repo),
            "diff",
            f"{base_ref}...{head_ref}",
            "--unified=3",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git diff failed: {result.stderr.strip()}"
            )
        if not result.stdout.strip():
            return []
        return parse_diff(result.stdout)

    @staticmethod
    def list_changed_files_local(
        repo_path: str | Path,
        base_ref: str,
        head_ref: str,
    ) -> list[str]:
        repo = Path(repo_path).resolve()
        cmd = [
            "git",
            "-C",
            str(repo),
            "diff",
            f"{base_ref}...{head_ref}",
            "--name-only",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git diff --name-only failed: {result.stderr.strip()}"
            )
        return [f for f in result.stdout.strip().split("\n") if f]
