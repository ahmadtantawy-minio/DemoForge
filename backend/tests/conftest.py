"""Pytest path: run from ``backend/`` with ``PYTHONPATH=.`` or ``python -m pytest``."""
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    raise RuntimeError(
        f"Backend tests require Python 3.10+ (this interpreter is {sys.version_info.major}.{sys.version_info.minor})"
    )

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
