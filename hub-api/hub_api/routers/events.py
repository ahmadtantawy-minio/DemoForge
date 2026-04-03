import json
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_fa
from ..database import get_db
from ..models import BatchEventCreate, EventCreate, EventResponse

router = APIRouter()


@router.post("/events", response_model=EventResponse, status_code=201)
async def create_event(
    event: EventCreate,
    fa: dict = Depends(get_current_fa),
    db: aiosqlite.Connection = Depends(get_db),
):
    if event.event_type == "manual_demo_created":
        if not fa["permissions"].get("manual_demo_creation", True):
            raise HTTPException(
                status_code=403, detail="manual_demo_creation permission denied"
            )

    received_at = datetime.utcnow().isoformat() + "Z"
    cursor = await db.execute(
        """INSERT INTO events (fa_id, event_type, payload, timestamp, received_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            fa["fa_id"],
            event.event_type,
            json.dumps(event.payload),
            event.timestamp,
            received_at,
        ),
    )
    await db.commit()

    return EventResponse(
        id=cursor.lastrowid,
        fa_id=fa["fa_id"],
        event_type=event.event_type,
        payload=event.payload,
        timestamp=event.timestamp,
        received_at=received_at,
    )


@router.post("/events/batch", status_code=201)
async def create_events_batch(
    batch: BatchEventCreate,
    fa: dict = Depends(get_current_fa),
    db: aiosqlite.Connection = Depends(get_db),
):
    received_at = datetime.utcnow().isoformat() + "Z"
    results = []

    for event in batch.events:
        if event.event_type == "manual_demo_created":
            if not fa["permissions"].get("manual_demo_creation", True):
                raise HTTPException(
                    status_code=403, detail="manual_demo_creation permission denied"
                )

        cursor = await db.execute(
            """INSERT INTO events (fa_id, event_type, payload, timestamp, received_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                fa["fa_id"],
                event.event_type,
                json.dumps(event.payload),
                event.timestamp,
                received_at,
            ),
        )
        results.append(
            EventResponse(
                id=cursor.lastrowid,
                fa_id=fa["fa_id"],
                event_type=event.event_type,
                payload=event.payload,
                timestamp=event.timestamp,
                received_at=received_at,
            )
        )

    await db.commit()
    return results
