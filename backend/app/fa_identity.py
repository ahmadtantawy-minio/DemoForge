"""
Field Architect identity — reads FA_ID from environment.

FA mode (any non-dev mode): DEMOFORGE_FA_ID should be set (email or username).
Dev mode: tries DEMOFORGE_FA_ID first, then git config user.email, then falls back to "dev".
"""

from __future__ import annotations


import os
import subprocess
import logging

logger = logging.getLogger("demoforge.fa_identity")

_fa_id: str = ""


def _detect_git_identity() -> str:
    """Try to detect identity from git config (email or username)."""
    try:
        # Try email first
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        # Fall back to git username
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def init_fa_identity():
    """Initialize FA identity from environment. Called once at startup."""
    global _fa_id
    _fa_id = os.environ.get("DEMOFORGE_FA_ID", "").strip()
    mode = os.environ.get("DEMOFORGE_MODE", "standard")

    if _fa_id:
        logger.info(f"FA identity: {_fa_id}")
    elif mode == "dev":
        # Dev mode: try git identity, then fallback
        _fa_id = _detect_git_identity() or "dev"
        logger.info(f"Dev mode — identity: {_fa_id}")
    else:
        logger.warning("DEMOFORGE_FA_ID not set. Template attribution disabled.")
        _fa_id = ""


def get_fa_id() -> str:
    """Get the current FA identity. Empty string if not configured."""
    return _fa_id
