import sys
import warnings

if not sys.warnoptions:
    warnings.simplefilter("ignore", category=FutureWarning)

from pr_triage_agent.cli import main

main()
