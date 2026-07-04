"""Command-line entrypoint for PR Triage Agent."""

import argparse
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import box

from pr_triage_agent import __version__
from pr_triage_agent.agent.loop import AgentLoop
from pr_triage_agent.agent.reflection import ReflectionLoop
from pr_triage_agent.agent.tools import ToolSet
from pr_triage_agent.github.fetch import PRFetcher
from pr_triage_agent.llm.groq_client import GroqClient

console = Console()
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-triage-agent",
        description="Autonomous PR review agent that analyzes GitHub pull requests "
                    "using real linting, testing, static analysis, and LLM reasoning.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── review ────────────────────────────────────────────────────────
    review = sub.add_parser("review", help="Review a GitHub pull request")
    review.add_argument("pr_url", help="GitHub PR URL (e.g. https://github.com/owner/repo/pull/123)")
    review.add_argument("--repo-path", help="Local repo path for offline review")
    review.add_argument("--base", help="Base ref for local diff (requires --repo-path)")
    review.add_argument("--head", help="Head ref for local diff (requires --repo-path)")

    # ── eval ──────────────────────────────────────────────────────────
    eval_ = sub.add_parser("eval", help="Run evaluation against PR dataset")
    eval_.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).parent / "evaluation" / "dataset.json",
        help="Path to dataset JSON",
    )
    eval_.add_argument(
        "--results-dir",
        type=Path,
        default=Path(__file__).parent / "evaluation" / "results",
        help="Directory for per-PR result files",
    )
    eval_.add_argument(
        "--limit", type=int, default=None, help="Limit number of PRs to evaluate"
    )
    eval_.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        default=True,
        help="Re-evaluate all PRs even if results exist",
    )

    # ── init ──────────────────────────────────────────────────────────
    init_ = sub.add_parser("init", help="Initialize .env file from template")
    init_.add_argument(
        "--force", action="store_true", help="Overwrite existing .env"
    )

    return parser


def cmd_review(args: argparse.Namespace) -> None:
    _check_api_key()

    console.print(Panel.fit(
        "[bold blue]PR Triage Agent[/] - Reviewing pull request",
        border_style="blue",
    ))

    pr_fetcher = PRFetcher()
    groq = GroqClient()
    toolset = ToolSet()
    reflection = ReflectionLoop()
    agent = AgentLoop(groq, toolset, pr_fetcher, reflection)

    start = time.time()
    with console.status("[bold yellow]Analyzing PR..."):
        state = agent.run(
            pr_url=args.pr_url,
            repo_path=args.repo_path,
            base_ref=args.base,
            head_ref=args.head,
        )
    elapsed = time.time() - start

    if state.error:
        console.print(f"[bold red]Error:[/] {state.error}")
        sys.exit(1)

    _print_review(state, elapsed)


def _print_review(state, elapsed: float) -> None:
    risk_colors = {"high": "red", "medium": "yellow", "low": "green"}
    color = risk_colors.get(state.risk_rating or "unknown", "white")

    console.print()
    console.print(Panel(
        f"[bold {color}]Risk Rating: {state.risk_rating or 'N/A'}[/]\n"
        f"[bold]Confidence:[/] {state.confidence:.2f}" if state.confidence is not None else "N/A",
        title="Review Result",
        border_style=color,
        box=box.ROUNDED,
    ))

    if state.per_file_comments:
        table = Table(
            title="Per-File Comments",
            box=box.SIMPLE,
            header_style="bold cyan",
        )
        table.add_column("File", style="cyan")
        table.add_column("Line", justify="right")
        table.add_column("Severity")
        table.add_column("Comment")

        for c in state.per_file_comments:
            sev_color = {
                "high": "red",
                "medium": "yellow",
                "low": "green",
            }.get(c.get("severity", ""), "white")
            table.add_row(
                c.get("file", ""),
                str(c.get("line", "")) if c.get("line") else "-",
                f"[{sev_color}]{c.get('severity', '')}[/]",
                c.get("comment", ""),
            )
        console.print(table)

    if state.reasoning_trace:
        trace_lines = []
        for t in state.reasoning_trace:
            detail = t.get("detail", "")
            if len(detail) > 120:
                detail = detail[:120] + "..."
            trace_lines.append(f"  [dim]\\[{t['step']}][/] {detail}")
        console.print(Panel(
            "\n".join(trace_lines),
            title="Reasoning Trace",
            border_style="dim",
            box=box.SIMPLE,
        ))

    review_text = state.review or "(no structured review produced)"
    if len(review_text) > 2000:
        review_text = review_text[:2000] + "\n... [truncated]"
    console.print(Panel(
        Markdown(review_text),
        title="Full Review",
        border_style="green",
        box=box.ROUNDED,
    ))

    console.print(f"\n[dim]Completed in {elapsed:.1f}s — "
                  f"{state.iteration_count} iteration(s)"
                  f"{' (reflection triggered)' if state.reflection_triggered else ''}[/]")


def cmd_eval(args: argparse.Namespace) -> None:
    from pr_triage_agent.evaluation.run_eval import (
        EvaluationHarness,
        load_dataset,
    )

    console.print(Panel.fit(
        "[bold blue]PR Triage Agent[/] - Running evaluation",
        border_style="blue",
    ))

    dataset = load_dataset(args.dataset)
    harness = EvaluationHarness(
        dataset=dataset,
        results_dir=args.results_dir,
        skip_existing=args.skip_existing,
        limit=args.limit,
    )

    with console.status("[bold yellow]Evaluating..."):
        harness.run()

    for r in harness.results:
        err_flag = " [red]ERR[/]" if r.fetch_error or r.agent_error else ""
        risk = r.agent_risk_rating or "-"
        console.print(
            f"  {r.pr_id}{err_flag}: "
            f"P={r.precision:.2f} R={r.recall:.2f} F1={r.f1:.2f} "
            f"risk={risk}"
        )

    if harness.results:
        total_tp = sum(len(r.true_positives) for r in harness.results)
        total_fp = sum(len(r.false_positives) for r in harness.results)
        total_fn = sum(len(r.false_negatives) for r in harness.results)
        total_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0
        total_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0
        total_f1 = 2 * total_p * total_r / (total_p + total_r) if (total_p + total_r) else 0

        console.print(Panel(
            f"[bold]Overall across {len(harness.results)} PRs[/]\n"
            f"Precision: {total_p:.3f}\n"
            f"Recall:    {total_r:.3f}\n"
            f"F1 Score:  {total_f1:.3f}",
            border_style="green",
        ))

        summary_path = args.results_dir / "results_summary.md"
        console.print(f"[dim]Full results: {summary_path}[/]")


def cmd_init(args: argparse.Namespace) -> None:
    template_path = Path(__file__).parent.parent / ".env.example"
    target_path = Path.cwd() / ".env"

    if target_path.exists() and not args.force:
        console.print("[yellow].env already exists. Use --force to overwrite.[/]")
        sys.exit(1)

    if not template_path.exists():
        console.print("[red].env.example not found at %s[/]" % template_path)
        sys.exit(1)

    content = template_path.read_text()
    target_path.write_text(content)
    console.print(f"[green]Created {target_path}[/]")
    console.print("Edit it to add your GROQ_API_KEY (get one free at https://console.groq.com/keys)")


def _check_api_key() -> None:
    import os
    if not os.environ.get("GROQ_API_KEY"):
        console.print("[red]Error:[/] GROQ_API_KEY not set.")
        console.print("  Run [bold]pr-triage-agent init[/] to create a .env file, then add your key.")
        console.print("  Get a free key at: https://console.groq.com/keys")
        sys.exit(1)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "review":
        cmd_review(args)
    elif args.command == "eval":
        cmd_eval(args)
    elif args.command == "init":
        cmd_init(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
