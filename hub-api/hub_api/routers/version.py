"""Version tracking — exposes the latest released DemoForge version."""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from ..database import get_db

router = APIRouter()


@router.get("/latest")
async def get_latest_version(db: aiosqlite.Connection = Depends(get_db)):
    """Return the latest released DemoForge version stored in hub-api."""
    cursor = await db.execute(
        "SELECT value, updated_at FROM app_config WHERE key = 'latest_demoforge_version'"
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No version published yet")
    return {
        "demoforge": {
            "version": row["value"],
            "released_at": row["updated_at"],
        }
    }
