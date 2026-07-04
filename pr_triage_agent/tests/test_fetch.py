from pathlib import Path

import pytest

from pr_triage_agent.github.fetch import (
    FileStatus,
    LineType,
    PRFetcher,
    parse_diff,
    parse_pr_url,
)

# ── fixture diffs ──────────────────────────────────────────────────────────

SIMPLE_DIFF = """\
--- a/hello.py
+++ b/hello.py
@@ -1,3 +1,4 @@
 def greet(name):
-    return f"Hello, {name}"
+    return f"Hi, {name}"
+
 
 def goodbye():
"""

NEW_FILE_DIFF = """\
--- /dev/null
+++ b/new_module.py
@@ -0,0 +1,5 @@
+def new_func():
+    pass
+
+def another():
+    return 42
"""

DELETED_FILE_DIFF = """\
--- a/old_file.py
+++ /dev/null
@@ -1,3 +0,0 @@
-print("this")
-print("is")
-print("gone")
"""

MULTI_HUNK_DIFF = """\
--- a/example.py
+++ b/example.py
@@ -1,4 +1,5 @@
 first
 second
-third
+third_modified
 fourth
+fourth_and_half
@@ -10,6 +11,7 @@
 tenth
 eleventh
-twelfth
+twelfth_modified
 thirteenth
 fourteenth
+fifteenth
"""

BINARY_DIFF = """\
--- /dev/null
+++ b/image.png
Binary files /dev/null and b/image.png differ
"""

EMPTY_DIFF = ""


class TestParsePRUrl:
    def test_standard_url(self) -> None:
        owner, repo, num = parse_pr_url(
            "https://github.com/owner/repo/pull/42"
        )
        assert (owner, repo, num) == ("owner", "repo", 42)

    def test_with_git_suffix(self) -> None:
        owner, repo, num = parse_pr_url(
            "https://github.com/owner/repo.git/pull/42"
        )
        assert (owner, repo, num) == ("owner", "repo", 42)

    def test_trailing_slash(self) -> None:
        owner, repo, num = parse_pr_url(
            "https://github.com/owner/repo/pull/42/"
        )
        assert (owner, repo, num) == ("owner", "repo", 42)

    def test_invalid_url(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://example.com/foo")

    def test_http_url(self) -> None:
        owner, repo, num = parse_pr_url(
            "http://github.com/owner/repo/pull/7"
        )
        assert (owner, repo, num) == ("owner", "repo", 7)


class TestParseDiff:
    def test_simple_diff(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        assert len(files) == 1

        f = files[0]
        assert f.filename == "hello.py"
        assert f.status == FileStatus.MODIFIED
        assert f.additions == 2
        assert f.deletions == 1

        assert len(f.hunks) == 1
        hunk = f.hunks[0]
        assert hunk.old_start == 1
        assert hunk.old_count == 3
        assert hunk.new_start == 1
        assert hunk.new_count == 4

        assert len(hunk.lines) == 6
        assert hunk.lines[0].type == LineType.CONTEXT
        assert hunk.lines[1].type == LineType.REMOVED
        assert hunk.lines[1].content == '    return f"Hello, {name}"'
        assert hunk.lines[2].type == LineType.ADDED
        assert hunk.lines[2].content == '    return f"Hi, {name}"'
        assert hunk.lines[3].type == LineType.ADDED
        assert hunk.lines[3].content == ""
        assert hunk.lines[4].type == LineType.CONTEXT
        assert hunk.lines[4].content == ""
        assert hunk.lines[5].type == LineType.CONTEXT
        assert hunk.lines[5].content == "def goodbye():"

    def test_new_file(self) -> None:
        files = parse_diff(NEW_FILE_DIFF)
        assert len(files) == 1
        f = files[0]
        assert f.filename == "new_module.py"
        assert f.status == FileStatus.ADDED
        assert f.additions == 5
        assert f.deletions == 0

    def test_deleted_file(self) -> None:
        files = parse_diff(DELETED_FILE_DIFF)
        assert len(files) == 1
        f = files[0]
        assert f.filename == "old_file.py"
        assert f.status == FileStatus.REMOVED
        assert f.additions == 0
        assert f.deletions == 3

    def test_multi_hunk(self) -> None:
        files = parse_diff(MULTI_HUNK_DIFF)
        assert len(files) == 1
        f = files[0]
        assert len(f.hunks) == 2
        assert f.additions == 4
        assert f.deletions == 2

    def test_binary_file(self) -> None:
        files = parse_diff(BINARY_DIFF)
        assert len(files) == 1
        f = files[0]
        assert f.filename == "image.png"
        assert f.is_binary
        assert len(f.hunks) == 0

    def test_empty_diff(self) -> None:
        files = parse_diff(EMPTY_DIFF)
        assert files == []

    def test_line_numbers(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        hunk = files[0].hunks[0]

        context_line = hunk.lines[0]
        assert context_line.old_number == 1
        assert context_line.new_number == 1

        removed_line = hunk.lines[1]
        assert removed_line.old_number == 2
        assert removed_line.new_number is None

        added_line = hunk.lines[2]
        assert added_line.new_number == 2
        assert added_line.old_number is None


class TestPRFetcher:
    def test_fetch_diff_local(self, tmp_path: Path) -> None:
        repo = tmp_path / "local_repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")

        base_file = repo / "base.py"
        base_file.write_text("def old():\n    return 1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "base commit")
        _git(repo, "branch", "-M", "main")

        _git(repo, "checkout", "-b", "feature")
        base_file.write_text("def old():\n    return 2\n\n\ndef new():\n    return 3\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "feature commit")

        files = PRFetcher.fetch_diff_local(repo, "main", "feature")
        assert files is not None
        assert len(files) == 1

        f = files[0]
        assert f.filename == "base.py"
        assert f.additions == 5
        assert f.deletions == 1

    def test_fetch_diff_local_no_changes(self, tmp_path: Path) -> None:
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")

        (repo / "file.py").write_text("x = 1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        _git(repo, "branch", "-M", "main")

        _git(repo, "checkout", "-b", "feature")
        (repo / "file.py").write_text("x = 1\ny = 2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "feature")

        files = PRFetcher.fetch_diff_local(repo, "main", "feature")
        assert files is not None
        assert len(files) == 1
        assert files[0].filename == "file.py"

    def test_fetch_diff_local_not_a_repo(self, tmp_path: Path) -> None:
        not_repo = tmp_path / "not_a_repo"
        not_repo.mkdir()
        with pytest.raises(ValueError, match="Not a git repository"):
            PRFetcher.fetch_diff_local(not_repo, "main", "feature")

    def test_list_changed_files_local(self, tmp_path: Path) -> None:
        repo = tmp_path / "file_list_repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")

        (repo / "a.py").write_text("a\n")
        (repo / "b.py").write_text("b\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "base")
        _git(repo, "branch", "-M", "main")

        _git(repo, "checkout", "-b", "feature")
        (repo / "a.py").write_text("a_modified\n")
        (repo / "c.py").write_text("c\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "feature")

        files = PRFetcher.list_changed_files_local(repo, "main", "feature")
        assert "a.py" in files
        assert "c.py" in files


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
    )
