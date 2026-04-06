import json
from datetime import datetime

import aiosqlite
from fastapi import Depends, HTTPException, Request

from .config import settings
from .database import get_db


async def get_current_fa(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> dict:
    api_key = request.headers.get("X-Api-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-Api-Key header")

    cursor = await db.execute(
        "SELECT * FROM field_architects WHERE api_key = ?", (api_key,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    now = datetime.utcnow().isoformat() + "Z"
    await db.execute(
        "UPDATE field_architects SET last_seen_at = ? WHERE fa_id = ?",
        (now, row["fa_id"]),
    )
    await db.commit()

    return {
        "fa_id": row["fa_id"],
        "fa_name": row["fa_name"],
        "api_key": row["api_key"],
        "permissions": json.loads(row["permissions"]),
        "registered_at": row["registered_at"],
        "last_seen_at": now,
        "is_active": bool(row["is_active"]),
        "metadata": json.loads(row["metadata"]),
    }


async def require_admin(request: Request) -> None:
    # Accept X-Hub-Admin-Key (passes through gateway/connector untouched)
    # or fall back to X-Api-Key for direct local access
    api_key = request.headers.get("X-Hub-Admin-Key") or request.headers.get("X-Api-Key")
    if not api_key or api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Admin access required")
