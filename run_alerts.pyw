"""Entry point for the optional scheduled search (Settings → Alerts). Runs without a console window."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from rivian_finder.cli import main  # noqa: E402

sys.exit(main(["run", "--notify", "--scheduled"]))
