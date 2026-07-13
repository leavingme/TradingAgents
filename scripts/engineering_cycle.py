#!/usr/bin/env python3
"""Repository wrapper for :mod:`tradingagents.engineering_cycle`."""

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "TRADINGAGENTS_DB",
    str(ROOT / ".tradingagents" / "engineering-cycle-runs.db"),
)

from tradingagents.engineering_cycle import main


if __name__ == "__main__":
    raise SystemExit(main())
