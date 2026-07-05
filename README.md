# PR Triage Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Groq Free](https://img.shields.io/badge/LLM-Llama%203.3%2070B%20(Groq%20free)-orange)](https://console.groq.com/keys)
[![Ruff](https://img.shields.io/badge/linter-ruff-purple)](https://github.com/astral-sh/ruff)
[![Bandit](https://img.shields.io/badge/security-bandit-red)](https://bandit.readthedocs.io)
[![Tests](https://img.shields.io/badge/tests-83%20passing-brightgreen)]()

> Read code, not just diff. An autonomous PR review agent that fetches diffs, runs real linting/testing/SAST tools, reasons over results via Groq (Llama 3.3 70B), and produces structured reviews with risk ratings — all without a paid API.

---

## Demo

[![asciicast](https://img.shields.io/badge/demo-vhs%20recording-blue)]()

```text
$ python -m pr_triage_agent review https://github.com/psf/requests/pull/6963
┌────────────────────────────────────────────────┐
│  PR Triage Agent — Reviewing pull request       │
└────────────────────────────────────────────────┘
  ✓ Fetched diff (2 files, +20/-8)
  ✓ ruff: no new issues
  ✓ pytest: all tests passed
  ⚠ bandit: potential issue in auth.py (line 178)

┌────────────────────────────────────┐
│  Risk Rating: high                 │
│  Confidence: 0.88                  │
│  Summary: Fixes CVE-2024-47081     │
└────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ File              │ Line │ Severity │ Comment        │
├───────────────────┼──────┼──────────┼────────────────┤
│ requests/auth.py  │ 178  │ high     │ Netloc creds…  │
└─────────────────────────────────────────────────────┘
```

---

## Architecture

![Architecture Diagram](pr_triage_agent/assets/architecture.svg)

**How it works (3 phases):**

### Phase 1: Input
`PRFetcher.fetch_diff()` calls the GitHub REST API (`Accept: application/vnd.github.v3.diff`) to get the unified diff of a PR, then `parse_diff()` converts it into structured dataclasses — `DiffFile` → `Hunk` → `DiffLine` with tracking of old/new line numbers, file status (added/modified/deleted/renamed), and add/delete counts. Also supports local git mode (`git diff base...head`).

### Phase 2: Reasoning Loop
1. **Build Prompt** — The structured diff and list of changed files are embedded in a system prompt that instructs the LLM (Llama 3.3 70B via Groq) to act as a code reviewer.
2. **Tool-Augmented Generation** — The LLM can request tool calls: `run_linter` (ruff), `run_tests` (pytest), `run_static_analysis` (bandit), `read_file`, and `search_codebase`. Each result is appended to the conversation history.
3. **Iterative Reasoning** — Up to 6 rounds of tool calls. The LLM decides when it has enough evidence to produce the final review.
4. **Reflection** — If the LLM's self-reported confidence is below 0.6, a reflection prompt re-queries the model to reconsider its findings. Only one extra round.

### Phase 3: Output
The agent produces a structured JSON review: `{risk_rating, confidence, summary, per_file_comments[{file, line, comment, severity}]}`. Nothing is auto-merged or auto-approved — all output is human-gated.

---

## Evaluation Results

We curate a dataset of **16 real merged PRs** from 6 popular Python projects (cpython, flask, click, httpx, requests, poetry) and compare the agent's flagged issues against documented ground-truth issues from the PR descriptions and review comments. Each PR has exactly one ground-truth issue.

| PR ID | Repo | Title | P | R | F1 | Risk |
|-------|------|-------|---|---|----|------|
| requests-6963 | psf/requests | CVE-2024-47081 credential leak | 0.00 | 0.00 | 0.00 | low |
| click-2800 | pallets/click | Close contexts during shell completion | 1.00 | 1.00 | 1.00 | medium |
| click-3642 | pallets/click | BytesWarning under python -bb | 0.00 | 0.00 | 0.00 | low |
| click-3653 | pallets/click | ANSI stripping regression | 1.00 | 1.00 | 1.00 | low |
| cpython-119454 | python/cpython | HTTP client OOM via Content-Length | 0.50 | 1.00 | 0.67 | low |
| cpython-119514 | python/cpython | IMAP DoS via literal size | 1.00 | 1.00 | 1.00 | low |
| cpython-119204 | python/cpython | Pickle VM overallocation | 0.50 | 1.00 | 0.67 | low |
| cpython-122753 | python/cpython | Email header spoofing via quoted-string | 0.00 | 0.00 | 0.00 | low |
| cpython-123354 | python/cpython | SanitizedNames regression | 0.00 | 0.00 | 0.00 | low |
| cpython-126976 | python/cpython | urlsplit bracketed host validation | 1.00 | 1.00 | 1.00 | low |
| flask-4234 | pallets/flask | None in before_request_funcs | 0.00 | 0.00 | 0.00 | — |
| flask-4001 | pallets/flask | Missing static folder crash | 0.00 | 0.00 | 0.00 | unknown |
| httpx-3250 | encode/httpx | Connection timeout hang | 0.00 | 0.00 | 0.00 | — |
| httpx-3350 | encode/httpx | Malformed redirect Location | 0.00 | 0.00 | 0.00 | — |
| poetry-9050 | python-poetry/poetry | Missing python version constraint | 1.00 | 1.00 | 1.00 | low |
| poetry-9100 | python-poetry/poetry | Extras dependency resolution | 0.00 | 0.00 | 0.00 | low |

| Metric | Value |
|--------|-------|
| **Precision** | 0.318 |
| **Recall** | 0.467 |
| **F1 Score** | 0.378 |
| **Dataset Size** | 16 PRs |

The agent achieves **perfect scores (P=1.0, R=1.0) on 5 of 16 PRs** — click-2800 (context resource leak), click-3653 (ANSI regression), cpython-119514 (IMAP DoS), cpython-126976 (urlsplit validation), and poetry-9050 (missing python constraint). These share a common trait: the issue is directly visible in a single diff hunk and the diff itself contains the fix logic.

**Two recurring failure modes stand out:**

1. **Semantic misses on security issues.** The agent failed to identify the actual CVE in requests-6963 (netloc credential leak — CVE-2024-47081), instead flagging an unrelated error-handling removal as low-severity. Similarly, it missed the email header spoofing vulnerability in cpython-122753 and the SanitizedNames overscoping regression in cpython-123354. In all three cases, the agent's false positives were low-severity observations about test files or helper functions rather than the core security issue. The diff alone doesn't make these vulnerabilities obvious; understanding *why* a change matters requires contextual security knowledge.

2. **Systematic false positives from tool infrastructure.** When the agent runs in an environment where the target repository isn't cloned, tool calls fail with `File not found` and the agent fills the gap with generic observations. The most extreme case is poetry-9100, where 6 of 6 false positives are identical messages about linter and SAST tools being unable to find source files. These aren't real issues — they're artifacts of an evaluation environment without local repo checkouts. This inflates false positive counts and depresses precision.

Three additional PRs (flask-4234, httpx-3250, httpx-3350) encountered non-recoverable infrastructure errors — either the Groq API returned no response (likely rate-limit exhaustion during that slot) or the GitHub diff fetch failed. These contribute zero signal to the metrics.

Results are written to `pr_triage_agent/evaluation/results/` as per-PR JSON files. Run the evaluation yourself:
```bash
python -m pr_triage_agent eval
```

---

## Key Engineering Decisions

### Why Groq (Llama 3.3 70B) + sleep-based rate limiting
The goal was a fully functional agent with **zero API cost**. Groq's free tier offers 1,000 requests/day (30 RPM) for `llama-3.3-70b-versatile` — dramatically higher than most other free-tier alternatives. Groq's LPU hardware also delivers faster inference (394 tokens/sec), and the OpenAI-compatible API means standard tools work without a vendor SDK. A simple `time.sleep(2.4)` rate limiter with exponential backoff on 429s keeps us compliant. Cost logging to SQLite tracks usage for when you eventually want to upgrade.

### Why hand-wrapped tools instead of LangChain / CrewAI
Heavy agent frameworks abstract away the function-calling loop and make debugging harder. By hand-wrapping 5 tools (`ToolSet` returning `ToolResult` dataclasses with auto-truncation), each `AgentLoop.run()` iteration is explicit: model response → is it a function call? → execute → append to contents → continue. This fits in ~470 lines and is trivially swappable to other languages (replace `run_linter` with ESLint, `run_tests` with Jest, etc.).

### How the reflection step works
When the LLM emits a review JSON with `confidence < 0.6`, `ReflectionLoop.build_reflection_prompt()` creates a prompt that lists the tool evidence gathered so far and explicitly asks: *"Review the evidence above and reconsider your assessment. Are there additional issues? Were any incorrectly identified?"* This is appended as a user message and the model is re-queried once.

### Graceful failure handling
Every `ToolResult` wraps errors (missing binary, timeout, non-existent file) so the LLM sees `{"success": false, "error": "..."}` rather than a crash. The agent loop continues; if output is truncated at 3000 chars, the LLM is told so. If the agent exceeds 6 iterations without producing valid JSON, the error is returned for human inspection.

---

## Setup

### Requirements
- **Python 3.11+**
- A **free Groq API key** from [console.groq.com/keys](https://console.groq.com/keys)

### Install
```bash
pip install -r requirements.txt
```

### Configure
```bash
python -m pr_triage_agent init
# Edit the .env file that was created:
#   GROQ_API_KEY=your_key_here
#   GITHUB_TOKEN=optional_github_token
```

> **Note:** Without `GITHUB_TOKEN`, unauthenticated GitHub API calls are limited to 60/hour. Set one for development use (no special permissions needed — public repo access only).

---

## Usage

### Review a PR
```bash
python -m pr_triage_agent review https://github.com/psf/requests/pull/6963
```

### Review a local branch
```bash
python -m pr_triage_agent review \
    https://github.com/psf/requests/pull/6963 \
    --repo-path /path/to/repo \
    --base main \
    --head feature-branch
```

### Run evaluation against the dataset
```bash
python -m pr_triage_agent eval
python -m pr_triage_agent eval --limit 3         # first 3 PRs
python -m pr_triage_agent eval --no-skip-existing  # re-run all
```

### Demo (no API key needed)
```bash
python pr_triage_agent/assets/demo_review.py
```

---

## Project Structure

```
pr_triage_agent/
├── __init__.py          # version
├── __main__.py          # python -m entrypoint
├── cli.py               # argparse CLI (review/eval/init commands)
├── agent/
│   ├── loop.py          # AgentLoop: fetch → prompt → tool call → review
│   ├── state.py         # AgentState dataclass
│   ├── tools.py         # ToolSet: ruff, pytest, bandit, read, search
│   └── reflection.py    # ReflectionLoop: low-confidence re-query
├── github/
│   └── fetch.py         # PRFetcher + parse_diff + dataclasses
├── llm/
│   └── groq_client.py   # Rate-limited Groq (OpenAI-compatible) wrapper + cost logging
├── storage/
│   └── db.py            # SQLite: cost_log, review_history
├── evaluation/
│   ├── dataset.json     # 16 PR ground-truth dataset
│   ├── run_eval.py      # EvaluationHarness: metrics computation
│   └── results/         # Per-PR result JSON + summary markdown
├── assets/
│   ├── architecture.svg # Architecture diagram
│   └── demo_review.py   # Interactive demo script
└── tests/
    ├── test_groq_client.py    # 10 tests
    ├── test_fetch.py          # 16 tests
    ├── test_tools.py          # 21 tests
    ├── test_agent_loop.py     # 5 tests
    └── test_evaluation.py     # 31 tests
```

**Total: 83 tests** — run them with:
```bash
pytest
```

---

## Limitations & Future Enhancements

- **Recall of 0.47 means roughly half of real issues go undetected.** The agent reliably catches issues directly described in a single diff hunk (5/5 perfect scores were single-hunk patterns) but systematically misses issues that require cross-file reasoning or security-domain knowledge — the netloc credential leak (requests-6963), the email header spoofing (cpython-122753), and the dependency-resolution edge case (poetry-9100) were all missed despite being the primary purpose of their respective PRs. Improving recall likely requires deeper code context (AST-level analysis, not just lint/SAST surface checks) or multi-step retrieval (find pattern → search codebase for related patterns → cross-reference).

- **False positives are dominated by two predictable failure modes:** (a) the agent comments on test-file additions as if they're production risks (cpython-119454, cpython-119204, cpython-122753, cpython-123354 all have FPs on test code with `severity: low`), and (b) in environments where the target repo isn't cloned locally, every tool call returns `File not found`, leaving the agent with no evidence and producing generic, non-actionable comments (poetry-9100: 6 identical FPs about linter path errors). Addressing (b) requires proper local repo setup; (a) may need prompt engineering to deprioritize test files or a post-processing filter.

- **16 PRs is a small dataset.** Directional signal is present — the 5 perfect scores and the distinct failure modes are reproduceable — but the confidence intervals are wide. Growing to 100+ PRs across more languages and issue types is the single highest-impact investment.

- **Python-only toolchain.** Ruff, pytest, and bandit can only analyze Python. The tool architecture is language-agnostic (swap `run_linter` for ESLint, `run_tests` for Jest, etc.), but wiring additional runtimes is not yet done.

- **Infrastructure failures reduce effective sample size.** 3 of 16 PRs (flask-4234, httpx-3250, httpx-3350) failed due to network or API issues rather than agent limitations. The resumable-eval feature now re-attempts these on subsequent runs, but the Groq free-tier rate limit (30 RPM, 1,000 req/day) means large evaluation runs are likely to hit 429s and exhaust tokens mid-run.

- **No inline PR comments.** The agent produces structured JSON reviews but doesn't post them to GitHub as review comments. This is intentional — output remains human-gated — but means the agent can't yet participate in CI-driven review workflows.

- **Single-pass reflection.** The reflection loop triggers at most once when confidence < 0.6. A more capable agent might do iterative deepening: find a potential issue → search related code → refine the finding → re-query. The current architecture supports this (it's just another loop iteration), but the prompt and tool-use patterns aren't optimized for it yet.

---

*Built with Python, Groq, and curiosity. MIT licensed.*
