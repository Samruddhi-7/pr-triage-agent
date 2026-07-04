import json
import logging
from pathlib import Path
from typing import Any, Optional

from pr_triage_agent.agent.reflection import ReflectionLoop
from pr_triage_agent.agent.state import AgentState
from pr_triage_agent.agent.tools import ToolResult, ToolSet
from pr_triage_agent.github.fetch import DiffFile, PRFetcher
from pr_triage_agent.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6

REVIEW_SYSTEM_INSTRUCTION = """You are a code review assistant. Review the provided pull request diff.

You have access to tools that can:
- Run a linter (ruff)
- Run tests (pytest)
- Run static analysis (bandit)
- Read file contents
- Search the codebase

Use these tools to gather evidence about the code changes.

When you have enough information, produce a structured review in JSON format:
{
  "risk_rating": "low" | "medium" | "high",
  "confidence": <0.0-1.0>,
  "summary": "<overall assessment>",
  "per_file_comments": [
    {"file": "<path>", "line": <int>, "comment": "<finding>", "severity": "low" | "medium" | "high"}
  ]
}

Focus on:
- Untested code paths
- Missing error handling
- Breaking changes
- Security issues
DO NOT comment on style or formatting."""


TOOL_SCHEMAS = [
    {
        "function_declarations": [
            {
                "name": "run_linter",
                "description": "Run ruff linter on specified Python files and return issues found",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths to lint",
                        }
                    },
                    "required": ["paths"],
                },
            },
            {
                "name": "run_tests",
                "description": "Run pytest on the project and return pass/fail results",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_path": {
                            "type": "string",
                            "description": "Path to the project root",
                        },
                        "test_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific test files or directories to run (optional)",
                        },
                    },
                    "required": ["project_path"],
                },
            },
            {
                "name": "run_static_analysis",
                "description": "Run bandit security analysis on specified files and return findings",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths to analyze",
                        }
                    },
                    "required": ["paths"],
                },
            },
            {
                "name": "read_file",
                "description": "Read contents of a file, optionally restricting to a line range",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file to read",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "First line number (1-indexed, optional)",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Last line number inclusive (optional)",
                        },
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "search_codebase",
                "description": "Search the codebase for a pattern (regex) across Python files",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Regex pattern to search for",
                        },
                        "repo_path": {
                            "type": "string",
                            "description": "Path to the repository root",
                        },
                    },
                    "required": ["query", "repo_path"],
                },
            },
        ]
    }
]


def _format_diff(diff_files: list[DiffFile]) -> str:
    lines: list[str] = []
    for df in diff_files:
        lines.append(f"=== {df.filename} ({df.status.value}, +{df.additions}/-{df.deletions}) ===")
        for hunk in df.hunks:
            lines.append(
                f"@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@"
            )
            for dl in hunk.lines:
                prefix = {"added": "+", "removed": "-", "context": " "}[dl.type.value]
                lines.append(f"{prefix}{dl.content}")
    return "\n".join(lines)


def _build_initial_prompt(
    changed_files: list[str],
    diff_text: str,
) -> str:
    changed = "\n".join(f"  - {f}" for f in changed_files) or "  (none)"

    return f"""## Pull Request Review

### Changed Files
{changed}

### Diff
```diff
{diff_text[:5000]}
```

Analyze this PR using the available tools. Call the tools one at a time as needed. When you have enough evidence, produce the final structured review as JSON."""


def _execute_tool_call(
    toolset: ToolSet,
    fc: dict,
    state: AgentState,
) -> ToolResult:
    name = fc["name"]
    args = fc.get("args", {})

    logger.info("Tool call: %s args=%s", name, args)

    if name == "run_linter":
        paths = [Path(p) for p in args.get("paths", [])]
        return toolset.run_linter(paths)

    if name == "run_tests":
        project_path = Path(args.get("project_path", state.repo_path or "."))
        test_paths = args.get("test_paths")
        extra = None
        if test_paths:
            extra = list(test_paths)
        return toolset.run_tests(project_path, extra_args=extra)

    if name == "run_static_analysis":
        paths = [Path(p) for p in args.get("paths", [])]
        return toolset.run_static_analysis(paths)

    if name == "read_file":
        file_path = Path(args["file_path"])
        start = args.get("start_line")
        end = args.get("end_line")
        line_range = (start, end) if start is not None and end is not None else None
        return toolset.read_file(file_path, line_range=line_range)

    if name == "search_codebase":
        query = args["query"]
        repo_path = Path(args.get("repo_path", state.repo_path or "."))
        return toolset.search_codebase(query, repo_path)

    return ToolResult.from_error(f"Unknown tool: {name}")


def _try_parse_review(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _apply_review(state: AgentState, review_data: dict) -> None:
    state.risk_rating = review_data.get("risk_rating", "unknown")
    state.confidence = review_data.get("confidence")
    state.review = json.dumps(review_data, indent=2)
    state.per_file_comments = review_data.get("per_file_comments", [])


_call_id_counter = 0


def _next_call_id() -> str:
    global _call_id_counter
    _call_id_counter += 1
    return f"call_{_call_id_counter}"


def _get_function_call(response: Any) -> Optional[dict]:
    try:
        message = response.choices[0].message
        if message.tool_calls:
            tc = message.tool_calls[0]
            return {"name": tc.function.name, "args": json.loads(tc.function.arguments)}
    except (AttributeError, IndexError, KeyError, json.JSONDecodeError):
        pass
    return None


def _get_text(response: Any) -> Optional[str]:
    try:
        return response.choices[0].message.content
    except (AttributeError, IndexError):
        pass
    return None


class AgentLoop:
    def __init__(
        self,
        groq_client: GroqClient,
        toolset: ToolSet,
        pr_fetcher: PRFetcher,
        reflection_loop: Optional[ReflectionLoop] = None,
    ):
        self.groq = groq_client
        self.toolset = toolset
        self.pr_fetcher = pr_fetcher
        self.reflection = reflection_loop or ReflectionLoop()

    def run(
        self,
        pr_url: str,
        repo_path: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
    ) -> AgentState:
        state = AgentState(pr_url=pr_url, repo_path=repo_path)

        # ── 1. Fetch diff ──────────────────────────────────────────────
        diff_files: list[DiffFile] = []

        if repo_path and base_ref and head_ref:
            result = self.pr_fetcher.fetch_diff_local(
                repo_path, base_ref, head_ref
            )
            if result is None:
                state.error = "Local diff produced no result"
                return state
            diff_files = result
            state.diff = _format_diff(diff_files)
            state.changed_files = self.pr_fetcher.list_changed_files_local(
                repo_path, base_ref, head_ref
            )
            if not state.changed_files:
                state.changed_files = [d.filename for d in diff_files]
        else:
            result = self.pr_fetcher.fetch_diff(pr_url)
            if result is None:
                state.error = "PR not found or inaccessible"
                return state
            diff_files = result
            state.diff = _format_diff(diff_files)
            files = self.pr_fetcher.fetch_changed_files(pr_url)
            state.changed_files = files or [d.filename for d in diff_files]

        if not state.changed_files:
            state.error = "No changed files found in PR"
            return state

        state.add_trace(
            "fetched_diff",
            f"{len(state.changed_files)} files changed",
        )

        # ── 2. Build initial prompt ────────────────────────────────────
        prompt = _build_initial_prompt(state.changed_files, state.diff)
        contents: list[dict] = [
            {"role": "user", "content": prompt}
        ]

        # ── 3. Main reasoning loop ─────────────────────────────────────

        while state.iteration_count < MAX_ITERATIONS:
            state.iteration_count += 1
            logger.info(
                "Iteration %d/%d", state.iteration_count, MAX_ITERATIONS
            )

            response = self.groq.generate_with_contents(
                contents=contents,
                tools=TOOL_SCHEMAS,
                system_instruction=REVIEW_SYSTEM_INSTRUCTION,
            )

            if response is None:
                state.error = "Groq API returned no response"
                break

            fc = _get_function_call(response)
            if fc is not None:
                result = _execute_tool_call(self.toolset, fc, state)
                state.tool_results[fc["name"]] = result
                state.add_trace(
                    f"tool:{fc['name']}",
                    f"success={result.success}, "
                    f"output={result.output[:200]}",
                )
                result_text = json.dumps(
                    {
                        "success": result.success,
                        "output": result.output[:2000],
                        "error": result.error,
                    }
                )
                call_id = _next_call_id()
                contents.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc["args"]),
                        },
                    }],
                })
                contents.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_text,
                })
                continue

            text = _get_text(response)
            if text is not None:
                state.add_trace("llm_response", text[:200])
                review_data = _try_parse_review(text)
                if review_data:
                    _apply_review(state, review_data)

                    # ── 4. Reflection step ─────────────────────────
                    if self.reflection.should_reflect(state):
                        logger.info(
                            "Confidence %.2f < %.2f, triggering reflection",
                            state.confidence,
                            self.reflection.threshold,
                        )
                        state.reflection_triggered = True
                        reflection_prompt = (
                            self.reflection.build_reflection_prompt(state)
                        )
                        contents.append({
                            "role": "user",
                            "content": reflection_prompt,
                        })
                        continue

                    break

                state.add_trace(
                    "parse_failed",
                    "Could not parse JSON from response",
                )
                contents.append({
                    "role": "user",
                    "content": (
                        "Please produce the final review as "
                        "valid JSON with exactly these keys: "
                        "risk_rating, confidence, summary, "
                        "per_file_comments."
                    ),
                })
                continue

            state.error = "Unexpected empty response from model"
            break

        # ── 5. Cap reached ─────────────────────────────────────────────
        if (
            state.iteration_count >= MAX_ITERATIONS
            and state.review is None
        ):
            state.add_trace(
                "capped", f"Reached max {MAX_ITERATIONS} iterations"
            )
            state.error = (
                f"Agent did not produce a structured review "
                f"within {MAX_ITERATIONS} iterations"
            )

        state.add_trace(
            "complete",
            f"risk={state.risk_rating}, confidence={state.confidence}",
        )
        return state
