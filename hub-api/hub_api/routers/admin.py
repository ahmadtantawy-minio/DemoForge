from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import require_admin
from ..database import get_db
from ..models import (
    ActivityStats,
    FAKeyResponse,
    FAKeyUpdateRequest,
    FAListItem,
    FAPermissions,
    FAProfile,
    FAProfileWithKey,
    FARegistrationRequest,
    StatusUpdate,
)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/fas", response_model=List[FAListItem])
async def list_fas(db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        """SELECT f.*, COUNT(e.id) as event_count
           FROM field_architects f
           LEFT JOIN events e ON f.fa_id = e.fa_id
           GROUP BY f.fa_id"""
    )
    rows = await cursor.fetchall()
    return [
        FAListItem(
            fa_id=row["fa_id"],
            fa_name=row["fa_name"],
            is_active=bool(row["is_active"]),
            last_seen_at=row["last_seen_at"],
            registered_at=row["registered_at"],
            event_count=row["event_count"],
        )
        for row in rows
    ]


@router.get("/fas/{fa_id}", response_model=FAProfile)
async def get_fa(fa_id: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT * FROM field_architects WHERE fa_id = ?", (fa_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="FA not found")
    return FAProfile(
        fa_id=row["fa_id"],
        fa_name=row["fa_name"],
        permissions=json.loads(row["permissions"]),
        registered_at=row["registered_at"],
        last_seen_at=row["last_seen_at"],
        is_active=bool(row["is_active"]),
    )


@router.get("/fas/{fa_id}/activity")
async def get_fa_activity(
    fa_id: str,
    event_type: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    query = "SELECT * FROM events WHERE fa_id = ?"
    params: list = [fa_id]

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if since:
        query += " AND timestamp >= ?"
        params.append(since)
    if until:
        query += " AND timestamp <= ?"
        params.append(until)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "fa_id": row["fa_id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload"]),
            "timestamp": row["timestamp"],
            "received_at": row["received_at"],
        }
        for row in rows
    ]


@router.put("/fas/{fa_id}/permissions", response_model=FAProfile)
async def update_permissions(
    fa_id: str,
    perms: FAPermissions,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT * FROM field_architects WHERE fa_id = ?", (fa_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="FA not found")

    existing = json.loads(row["permissions"])
    updated = {**existing, **perms.model_dump()}
    await db.execute(
        "UPDATE field_architects SET permissions = ? WHERE fa_id = ?",
        (json.dumps(updated), fa_id),
    )
    await db.commit()

    return FAProfile(
        fa_id=row["fa_id"],
        fa_name=row["fa_name"],
        permissions=updated,
        registered_at=row["registered_at"],
        last_seen_at=row["last_seen_at"],
        is_active=bool(row["is_active"]),
    )


@router.put("/fas/{fa_id}/status", response_model=FAProfile)
async def update_status(
    fa_id: str,
    status: StatusUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT * FROM field_architects WHERE fa_id = ?", (fa_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="FA not found")

    await db.execute(
        "UPDATE field_architects SET is_active = ? WHERE fa_id = ?",
        (int(status.is_active), fa_id),
    )
    await db.commit()

    return FAProfile(
        fa_id=row["fa_id"],
        fa_name=row["fa_name"],
        permissions=json.loads(row["permissions"]),
        registered_at=row["registered_at"],
        last_seen_at=row["last_seen_at"],
        is_active=status.is_active,
    )


@router.post("/fas", response_model=FAProfileWithKey, status_code=201)
async def pre_register_fa(
    req: FARegistrationRequest, db: aiosqlite.Connection = Depends(get_db)
):
    from ..config import settings

    now = datetime.utcnow().isoformat() + "Z"
    permissions = json.dumps(settings.default_permissions)
    api_key = req.api_key or secrets.token_urlsafe(32)
    try:
        await db.execute(
            """INSERT INTO field_architects (fa_id, fa_name, api_key, permissions, registered_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req.fa_id, req.fa_name, api_key, permissions, now),
        )
        await db.commit()
    except Exception:
        raise HTTPException(status_code=409, detail="FA already exists")

    return FAProfileWithKey(
        fa_id=req.fa_id,
        fa_name=req.fa_name,
        permissions=settings.default_permissions,
        registered_at=now,
        last_seen_at=None,
        is_active=True,
        api_key=api_key,
    )


@router.get("/fas/{fa_id}/key", response_model=FAKeyResponse)
async def get_fa_key(fa_id: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT fa_id, api_key FROM field_architects WHERE fa_id = ?", (fa_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="FA not found")
    return FAKeyResponse(fa_id=row["fa_id"], api_key=row["api_key"])


@router.put("/fas/{fa_id}/key", response_model=FAKeyResponse)
async def update_fa_key(
    fa_id: str,
    body: FAKeyUpdateRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT fa_id FROM field_architects WHERE fa_id = ?", (fa_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="FA not found")

    new_key = body.api_key or secrets.token_urlsafe(32)
    try:
        await db.execute(
            "UPDATE field_architects SET api_key = ? WHERE fa_id = ?", (new_key, fa_id)
        )
        await db.commit()
    except Exception:
        raise HTTPException(status_code=409, detail="Key already in use by another FA")
    return FAKeyResponse(fa_id=fa_id, api_key=new_key)


class VersionSetRequest(BaseModel):
    demoforge: str
    released_at: str | None = None


@router.post("/set-latest-version")
async def set_latest_version(
    req: VersionSetRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Set the latest released DemoForge version. Called by hub-release.sh after tagging."""
    now = req.released_at or (datetime.utcnow().isoformat() + "Z")
    await db.execute(
        """INSERT INTO app_config (key, value, updated_at)
           VALUES ('latest_demoforge_version', ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (req.demoforge, now),
    )
    await db.commit()
    return {"ok": True, "version": req.demoforge, "released_at": now}


@router.delete("/fas/{fa_id}")
async def delete_fa(fa_id: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT fa_id FROM field_architects WHERE fa_id = ?", (fa_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="FA not found")

    await db.execute("DELETE FROM events WHERE fa_id = ?", (fa_id,))
    await db.execute("DELETE FROM field_architects WHERE fa_id = ?", (fa_id,))
    await db.commit()
    return {"detail": "FA purged"}


@router.get("/events")
async def query_events(
    fa_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    query = "SELECT * FROM events WHERE 1=1"
    params: list = []

    if fa_id:
        query += " AND fa_id = ?"
        params.append(fa_id)
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if since:
        query += " AND timestamp >= ?"
        params.append(since)
    if until:
        query += " AND timestamp <= ?"
        params.append(until)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "fa_id": row["fa_id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload"]),
            "timestamp": row["timestamp"],
            "received_at": row["received_at"],
        }
        for row in rows
    ]


@router.get("/stats", response_model=ActivityStats)
async def get_stats(db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM field_architects")
    total_fas = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM field_architects WHERE is_active = 1"
    )
    active_fas = (await cursor.fetchone())["cnt"]

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM events")
    total_events = (await cursor.fetchone())["cnt"]

    now = datetime.utcnow()
    seven_days_ago = (now - timedelta(days=7)).isoformat() + "Z"
    thirty_days_ago = (now - timedelta(days=30)).isoformat() + "Z"

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM events WHERE timestamp >= ?", (seven_days_ago,)
    )
    events_7d = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM events WHERE timestamp >= ?", (thirty_days_ago,)
    )
    events_30d = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        """SELECT payload, COUNT(*) as cnt FROM events
           WHERE event_type IN ('template_synced', 'template_forked', 'template_published')
           GROUP BY payload ORDER BY cnt DESC LIMIT 10"""
    )
    top_templates_rows = await cursor.fetchall()
    top_templates = [
        {"payload": json.loads(row["payload"]), "count": row["cnt"]}
        for row in top_templates_rows
    ]

    cursor = await db.execute(
        "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
    )
    type_rows = await cursor.fetchall()
    events_by_type = {row["event_type"]: row["cnt"] for row in type_rows}

    return ActivityStats(
        total_fas=total_fas,
        active_fas=active_fas,
        total_events=total_events,
        events_last_7_days=events_7d,
        events_last_30_days=events_30d,
        top_templates=top_templates,
        events_by_type=events_by_type,
    )
