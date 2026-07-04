"""
Demo script: simulates the PR Triage Agent reviewing a real PR.

Run: python pr_triage_agent/assets/demo_review.py
This generates the same output the agent would produce, using pre-recorded data.
No API keys required.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import box

console = Console(emoji=False)


def simulate_review() -> None:
    console.clear()

    # Header
    console.print(Panel.fit(
        "[bold blue]PR Triage Agent[/] - Demo Review",
        border_style="blue",
    ))
    console.print()

    # Step 1: Fetch PR
    with console.status("[bold yellow]Step 1/4: Fetching PR diff...") as status:
        time.sleep(1.2)
    console.print("  [green]OK[/] Fetched https://github.com/psf/requests/pull/6963")
    console.print("  [green]OK[/] 2 files changed (+20/-8)")
    console.print()

    # Step 2: Analyze
    with console.status("[bold yellow]Step 2/4: Running linter (ruff)...") as status:
        time.sleep(0.8)
    console.print("  [green]OK[/] ruff: no new issues")
    with console.status("[bold yellow]Step 2/4: Running tests (pytest)...") as status:
        time.sleep(1.0)
    console.print("  [green]OK[/] pytest: all tests passed")
    with console.status("[bold yellow]Step 2/4: Running static analysis (bandit)...") as status:
        time.sleep(1.2)
    console.print("  [yellow]!![/] bandit: potential issue in auth.py (line 178)")
    console.print()

    # Step 3: LLM Reasoning
    with console.status("[bold yellow]Step 3/4: Gemini LLM reasoning...") as status:
        time.sleep(2.5)
    console.print("  [green]OK[/] Analysis complete (confidence: 0.88)")
    console.print()

    # Step 4: Reflection check
    with console.status("[bold yellow]Step 4/4: Reflection check...") as status:
        time.sleep(0.5)
    console.print("  [green]OK[/] Confidence >= 0.6, no re-query needed")
    console.print()

    # Results
    color = "red"
    console.print(Panel(
        "[bold red]Risk Rating: high[/]\n"
        "[bold]Confidence:[/] 0.88\n"
        "[bold]Summary:[/] This PR fixes CVE-2024-47081, a netloc credential "
        "leak vulnerability where usernames and passwords embedded in URLs "
        "could leak via manual netloc parsing instead of using the hostname attribute.",
        title="Review Result",
        border_style=color,
        box=box.ROUNDED,
    ))
    console.print()

    table = Table(
        title="Per-File Comments",
        box=box.SIMPLE,
        header_style="bold cyan",
    )
    table.add_column("File", style="cyan")
    table.add_column("Line", justify="right")
    table.add_column("Severity")
    table.add_column("Comment")

    table.add_row(
        "requests/auth.py",
        "178",
        "[red]high[/]",
        "Manual netloc parsing instead of using hostname attribute -- "
        "URL credentials leak when netrc is used",
    )
    table.add_row(
        "requests/auth.py",
        "185",
        "[yellow]medium[/]",
        "Missing validation of parsed host component before comparison",
    )
    console.print(table)
    console.print()

    # Full review JSON
    console.print(Panel(
        Markdown(
            '```json\n'
            '{\n'
            '  "risk_rating": "high",\n'
            '  "confidence": 0.88,\n'
            '  "summary": "Fixes netloc credential leak (CVE-2024-47081).",\n'
            '  "per_file_comments": [\n'
            '    {\n'
            '      "file": "requests/auth.py",\n'
            '      "line": 178,\n'
            '      "comment": "Manual netloc parsing instead of hostname",\n'
            '      "severity": "high"\n'
            '    },\n'
            '    {\n'
            '      "file": "requests/auth.py",\n'
            '      "line": 185,\n'
            '      "comment": "Missing host component validation",\n'
            '      "severity": "medium"\n'
            '    }\n'
            '  ]\n'
            '}\n'
            '```'
        ),
        title="Full Review Output",
        border_style="green",
        box=box.ROUNDED,
    ))

    console.print(f"\n[dim]Completed in 6.8s -- 4 iterations[/]")


if __name__ == "__main__":
    simulate_review()
