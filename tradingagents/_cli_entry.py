"""
Console-script entry shim for `tradingagents`.

Lives in the tradingagents.* namespace (not cli.*) so a stray cli.py module
on PYTHONPATH (e.g., Hermes agent sandbox injects /data/hermes/hermes-agent)
cannot shadow it.
"""
import sys
_CONFLICTING_DIRS = (
    "/data/hermes/hermes-agent",  # has competing cli.py single-file module
)
for _d in _CONFLICTING_DIRS:
    while _d in sys.path:
        sys.path.remove(_d)

from cli.main import app  # noqa: E402

if __name__ == "__main__":
    sys.exit(app())
