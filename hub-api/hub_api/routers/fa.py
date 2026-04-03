import json
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends

from ..auth import get_current_fa
from ..config import settings
from ..database import get_db
from ..models import FAProfile, FARegistrationRequest

router = APIRouter()


@router.post("/register", response_model=FAProfile)
async def register_fa(
    req: FARegistrationRequest, db: aiosqlite.Connection = Depends(get_db)
):
    cursor = await db.execute(
        "SELECT * FROM field_architects WHERE fa_id = ?", (req.fa_id,)
    )
    existing = await cursor.fetchone()
    if existing:
        return FAProfile(
            fa_id=existing["fa_id"],
            fa_name=existing["fa_name"],
            permissions=json.loads(existing["permissions"]),
            registered_at=existing["registered_at"],
            last_seen_at=existing["last_seen_at"],
            is_active=bool(existing["is_active"]),
        )

    now = datetime.utcnow().isoformat() + "Z"
    permissions = json.dumps(settings.default_permissions)
    await db.execute(
        """INSERT INTO field_architects (fa_id, fa_name, api_key, permissions, registered_at)
           VALUES (?, ?, ?, ?, ?)""",
        (req.fa_id, req.fa_name, req.api_key, permissions, now),
    )
    await db.commit()

    return FAProfile(
        fa_id=req.fa_id,
        fa_name=req.fa_name,
        permissions=settings.default_permissions,
        registered_at=now,
        last_seen_at=None,
        is_active=True,
    )


@router.get("/me", response_model=FAProfile)
async def get_my_profile(fa: dict = Depends(get_current_fa)):
    return FAProfile(
        fa_id=fa["fa_id"],
        fa_name=fa["fa_name"],
        permissions=fa["permissions"],
        registered_at=fa["registered_at"],
        last_seen_at=fa["last_seen_at"],
        is_active=fa["is_active"],
    )
