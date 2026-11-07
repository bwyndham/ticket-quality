"""Loads the ticket-quality plug-ins for this suite.

Adds the repo's src/ to the path so this works both from a checkout with
ticket-quality installed and inside the llm-evals GitHub Action (which only
installs llm-evals).
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import ticket_quality.evals_plugin  # noqa: E402,F401  registers the schema and checks
from ticket_quality.eval_mock import respond  # noqa: E402,F401  the --provider mock stand-in
