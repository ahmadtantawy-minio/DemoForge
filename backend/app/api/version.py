"""Expose local DemoForge version (from git tags)."""

from __future__ import annotations

import os
import subprocess
import logging
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger("demoforge.version")

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # backend/app/api/version.py → project root


def get_local_version() -> str:
    """Read version from git describe. Falls back to DEMOFORGE_VERSION env var or 'dev'."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, timeout=3,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"git describe failed: {e}")
    return os.getenv("DEMOFORGE_VERSION", "dev")


@router.get("/api/version")
def get_version():
    return {"version": get_local_version()}
