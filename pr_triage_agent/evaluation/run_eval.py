import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    pr_id: str
    title: str
    repo: str
    pr_number: int
    ground_truth_count: int
    true_positives: list[dict] = field(default_factory=list)
    false_positives: list[dict] = field(default_factory=list)
    false_negatives: list[dict] = field(default_factory=list)
    agent_risk_rating: Optional[str] = None
    agent_confidence: Optional[float] = None
    agent_error: Optional[str] = None
    agent_iterations: int = 0
    agent_reflection_used: bool = False
    fetch_error: Optional[str] = None
    runtime_seconds: float = 0.0

    @property
    def precision(self) -> float:
        tp = len(self.true_positives)
        fp = len(self.false_positives)
        return tp / (tp + fp) if (tp + fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        tp = len(self.true_positives)
        fn = len(self.false_negatives)
        return tp / (tp + fn) if (tp + fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p = self.precision
        r = self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def load_dataset(path: Path) -> list[dict]:
    if not path.exists():
        logger.error("Dataset file not found: %s", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Loaded %d entries from dataset", len(data))
    return data


def compute_metrics(
    ground_truth: list[dict],
    agent_comments: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    true_positives: list[dict] = []
    false_positives: list[dict] = []
    false_negatives: list[dict] = []

    matched_truths: set[int] = set()
    key_token_overlap = _tokenize_keywords

    for comment in agent_comments:
        comment_file = comment.get("file", "")
        comment_text = comment.get("comment", "")
        comment_sev = comment.get("severity", "").lower()
        comment_tokens = key_token_overlap(comment_text)
        best_match_idx = -1
        best_match_score = 0.0

        for ti, truth in enumerate(ground_truth):
            if ti in matched_truths:
                continue
            truth_file = truth.get("file", "")
            truth_sev = truth.get("severity", "").lower()
            truth_desc = truth.get("description", "")
            truth_tokens = key_token_overlap(truth_desc)

            score = 0.0
            if truth_file and comment_file:
                if _paths_match(truth_file, comment_file):
                    score += 0.4
            if truth_sev and comment_sev and truth_sev == comment_sev:
                score += 0.2
            overlap = comment_tokens & truth_tokens
            if overlap:
                score += min(0.4, 0.1 * len(overlap))

            if score > best_match_score:
                best_match_score = score
                best_match_idx = ti

        if best_match_score >= 0.4 and best_match_idx != -1:
            matched_truths.add(best_match_idx)
            true_positives.append({
                "comment": comment,
                "matched_truth": ground_truth[best_match_idx],
                "match_score": round(best_match_score, 2),
            })
        else:
            false_positives.append(comment)

    for ti, truth in enumerate(ground_truth):
        if ti not in matched_truths:
            false_negatives.append(truth)

    return true_positives, false_positives, false_negatives


def _tokenize_keywords(text: str) -> set[str]:
    stopwords = {
        "the", "a", "an", "in", "on", "of", "to", "for", "and", "or",
        "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "can", "shall", "not", "no", "nor", "with",
        "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off",
        "over", "under", "again", "further", "then", "once", "here",
        "there", "when", "where", "why", "how", "all", "each", "every",
        "both", "few", "more", "most", "other", "some", "such", "only",
        "own", "same", "so", "than", "too", "very", "just", "because",
        "but", "which", "who", "whom", "what",
    }
    tokens = set()
    for word in text.lower().split():
        for part in re.split(r"[-_/]", word):
            clean = part.strip(".,;:!?\"'()[]{}\\")
            if clean and len(clean) > 2 and clean not in stopwords:
                tokens.add(clean)
    return tokens


def _paths_match(a: str, b: str) -> bool:
    a = a.replace("\\", "/").lower()
    b = b.replace("\\", "/").lower()
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def build_results_table(results: list[EvalResult], output_path: Path) -> str:
    lines = [
        "# Evaluation Results",
        "",
        "| PR ID | Repo | Title | GT Issues | TP | FP | FN | Precision | Recall | F1 | Risk | Conf | Time |",
        "|-------|------|-------|-----------|----|----|----|-----------|--------|----|------|------|------|",
    ]
    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_gt = 0

    for r in results:
        total_tp += len(r.true_positives)
        total_fp += len(r.false_positives)
        total_fn += len(r.false_negatives)
        total_gt += r.ground_truth_count

        title_short = r.title[:50] if len(r.title) > 50 else r.title
        risk = r.agent_risk_rating or "N/A"
        conf = f"{r.agent_confidence:.2f}" if r.agent_confidence is not None else "N/A"
        err_flag = " [ERR]" if r.agent_error or r.fetch_error else ""
        lines.append(
            f"| {r.pr_id}{err_flag} | {r.repo} | {title_short} "
            f"| {r.ground_truth_count} | {len(r.true_positives)} "
            f"| {len(r.false_positives)} | {len(r.false_negatives)} "
            f"| {r.precision:.2f} | {r.recall:.2f} | {r.f1:.2f} "
            f"| {risk} | {conf} | {r.runtime_seconds:.1f}s |"
        )

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0
        else 0.0
    )

    lines.extend([
        "",
        f"**Total:** {len(results)} PRs evaluated",
        f"**Overall Precision:** {overall_precision:.3f}",
        f"**Overall Recall:** {overall_recall:.3f}",
        f"**Overall F1:** {overall_f1:.3f}",
        f"**Total Ground Truth Issues:** {total_gt}",
        f"**Total True Positives:** {total_tp}",
        f"**Total False Positives:** {total_fp}",
        f"**Total False Negatives:** {total_fn}",
        "",
    ])

    table = "\n".join(lines)
    output_path.write_text(table, encoding="utf-8")
    logger.info("Results written to %s", output_path)
    return table


class EvaluationHarness:
    def __init__(
        self,
        dataset: list[dict],
        results_dir: Path,
        skip_existing: bool = True,
        limit: Optional[int] = None,
    ):
        self.dataset = dataset
        self.results_dir = results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.skip_existing = skip_existing
        self.limit = limit
        self.results: list[EvalResult] = []

    def run(self) -> list[EvalResult]:
        entries = self.dataset[:self.limit] if self.limit else self.dataset
        logger.info("Starting evaluation: %d entries", len(entries))

        for idx, entry in enumerate(entries):
            pr_id = entry["id"]
            existing_path = self.results_dir / f"{pr_id}_result.json"

            if self.skip_existing and existing_path.exists():
                logger.info("[%d/%d] %s: skipping (result exists)", idx + 1, len(entries), pr_id)
                with open(existing_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.results.append(EvalResult(**data))
                continue

            logger.info("[%d/%d] %s: evaluating...", idx + 1, len(entries), pr_id)
            result = self._evaluate_single(entry, pr_id)

            with open(existing_path, "w", encoding="utf-8") as f:
                json.dump(result.__dict__, f, indent=2, default=str)

            self.results.append(result)

        return self.results

    def _evaluate_single(self, entry: dict, pr_id: str) -> EvalResult:
        start = time.time()
        result = EvalResult(
            pr_id=pr_id,
            title=entry.get("title", ""),
            repo=entry.get("repo", ""),
            pr_number=entry.get("pr_number", 0),
            ground_truth_count=len(entry.get("ground_truth_issues", [])),
        )

        try:
            diff_text = self._fetch_diff(entry, pr_id)
            if diff_text is None:
                result.fetch_error = "Failed to fetch diff"
                result.runtime_seconds = time.time() - start
                return result
        except Exception as e:
            result.fetch_error = str(e)
            result.runtime_seconds = time.time() - start
            return result

        try:
            agent_state = self._run_agent(entry, diff_text, pr_id)
            if agent_state is None:
                result.agent_error = "Agent returned no state"
                result.runtime_seconds = time.time() - start
                return result

            result.agent_risk_rating = agent_state.risk_rating
            result.agent_confidence = agent_state.confidence
            result.agent_error = agent_state.error
            result.agent_iterations = agent_state.iteration_count
            result.agent_reflection_used = agent_state.reflection_triggered

            gt_issues = entry.get("ground_truth_issues", [])
            agent_comments = agent_state.per_file_comments or []

            tp, fp, fn = compute_metrics(gt_issues, agent_comments)
            result.true_positives = tp
            result.false_positives = fp
            result.false_negatives = fn

        except Exception as e:
            result.agent_error = f"Exception: {e}"
            logger.exception("Agent error for %s", pr_id)

        result.runtime_seconds = time.time() - start
        return result

    def _fetch_diff(self, entry: dict, pr_id: str) -> Optional[str]:
        from pr_triage_agent.github.fetch import PRFetcher
        from pr_triage_agent.agent.loop import _format_diff

        pr_url = entry["pr_url"]
        fetcher = PRFetcher()
        diff_files = fetcher.fetch_diff(pr_url)
        if diff_files is None:
            return None
        return _format_diff(diff_files)

    def _run_agent(
        self, entry: dict, diff_text: str, pr_id: str,
    ) -> Optional[object]:
        from pr_triage_agent.agent.state import AgentState
        from pr_triage_agent.llm.gemini_client import GeminiClient
        from pr_triage_agent.agent.tools import ToolSet
        from pr_triage_agent.agent.loop import (
            _build_initial_prompt,
            _try_parse_review,
            _apply_review,
            REVIEW_SYSTEM_INSTRUCTION,
            TOOL_SCHEMAS,
            MAX_ITERATIONS,
            _execute_tool_call,
            _get_function_call,
            _get_text,
        )
        from pr_triage_agent.agent.reflection import ReflectionLoop

        gemini = GeminiClient()
        toolset = ToolSet()
        reflection = ReflectionLoop()
        state = AgentState(pr_url=entry["pr_url"])

        changed_files = [issue.get("file", "unknown") for issue in entry.get("ground_truth_issues", [])]
        changed_files = list(dict.fromkeys(changed_files))

        prompt = _build_initial_prompt(changed_files, diff_text)
        contents: list[dict] = [{"role": "user", "parts": [{"text": prompt}]}]

        while state.iteration_count < MAX_ITERATIONS:
            state.iteration_count += 1
            logger.info("Iteration %d/%d for %s", state.iteration_count, MAX_ITERATIONS, pr_id)

            response = gemini.generate_with_contents(
                contents=contents,
                tools=TOOL_SCHEMAS,
                system_instruction=REVIEW_SYSTEM_INSTRUCTION,
            )

            if response is None:
                state.error = "Gemini API returned no response"
                break

            fc = _get_function_call(response)
            if fc is not None:
                result = _execute_tool_call(toolset, fc, state)
                state.tool_results[fc.name] = result
                state.add_trace(f"tool:{fc.name}", f"success={result.success}, output={result.output[:200]}")

                result_text = json.dumps({
                    "success": result.success,
                    "output": result.output[:2000],
                    "error": result.error,
                })
                contents.append({
                    "role": "model",
                    "parts": [{"function_call": {"name": fc.name, "args": fc.args}}],
                })
                contents.append({
                    "role": "user",
                    "parts": [{"function_response": {"name": fc.name, "response": {"result": result_text}}}],
                })
                continue

            text = _get_text(response)
            if text is not None:
                state.add_trace("llm_response", text[:200])
                review_data = _try_parse_review(text)
                if review_data:
                    _apply_review(state, review_data)

                    if reflection.should_reflect(state):
                        logger.info("Reflection triggered for %s", pr_id)
                        state.reflection_triggered = True
                        reflection_prompt = reflection.build_reflection_prompt(state)
                        contents.append({"role": "user", "parts": [{"text": reflection_prompt}]})
                        continue

                    break

                state.add_trace("parse_failed", "Could not parse JSON from response")
                contents.append({
                    "role": "user",
                    "parts": [{"text": "Please produce the final review as valid JSON with exactly these keys: risk_rating, confidence, summary, per_file_comments."}],
                })
                continue

            state.error = "Unexpected empty response from model"
            break

        if state.iteration_count >= MAX_ITERATIONS and state.review is None:
            state.add_trace("capped", f"Reached max {MAX_ITERATIONS} iterations")
            state.error = f"Agent did not produce a structured review within {MAX_ITERATIONS} iterations"

        state.add_trace("complete", f"risk={state.risk_rating}, confidence={state.confidence}")
        return state

    def print_summary(self) -> None:
        if not self.results:
            logger.warning("No results to summarize")
            return

        table_path = self.results_dir / "results_summary.md"
        table = build_results_table(self.results, table_path)
        print("\n" + table)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="PR Triage Agent Evaluation Harness")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).parent / "dataset.json",
        help="Path to dataset JSON file",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="Directory for per-PR result files",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip PRs that already have a result file",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-evaluate all PRs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of PRs to evaluate",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    dataset = load_dataset(args.dataset)
    harness = EvaluationHarness(
        dataset=dataset,
        results_dir=args.results_dir,
        skip_existing=args.skip_existing,
        limit=args.limit,
    )

    harness.run()
    harness.print_summary()


if __name__ == "__main__":
    main()
