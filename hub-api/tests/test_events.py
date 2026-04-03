import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_event(client: AsyncClient, registered_fa: dict):
    resp = await client.post(
        "/api/hub/events",
        headers={"X-Api-Key": "df-test-key"},
        json={
            "event_type": "demo_deployed",
            "payload": {"template": "test-template"},
            "timestamp": "2024-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["fa_id"] == "test-fa@minio.io"
    assert data["event_type"] == "demo_deployed"
    assert data["payload"]["template"] == "test-template"


@pytest.mark.asyncio
async def test_create_event_invalid_type(client: AsyncClient, registered_fa: dict):
    resp = await client.post(
        "/api/hub/events",
        headers={"X-Api-Key": "df-test-key"},
        json={
            "event_type": "invalid_type",
            "payload": {},
            "timestamp": "2024-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_events(client: AsyncClient, registered_fa: dict):
    events = [
        {
            "event_type": "demo_deployed",
            "payload": {"i": i},
            "timestamp": "2024-01-01T00:00:00Z",
        }
        for i in range(3)
    ]
    resp = await client.post(
        "/api/hub/events/batch",
        headers={"X-Api-Key": "df-test-key"},
        json={"events": events},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 3


@pytest.mark.asyncio
async def test_batch_events_max_exceeded(client: AsyncClient, registered_fa: dict):
    events = [
        {
            "event_type": "demo_deployed",
            "payload": {},
            "timestamp": "2024-01-01T00:00:00Z",
        }
        for _ in range(101)
    ]
    resp = await client.post(
        "/api/hub/events/batch",
        headers={"X-Api-Key": "df-test-key"},
        json={"events": events},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_manual_demo_created_permission_denied(
    client: AsyncClient, registered_fa: dict
):
    # Update permissions to deny manual_demo_creation
    from tests.conftest import _test_db

    perms = dict(registered_fa["permissions"])
    perms["manual_demo_creation"] = False
    await _test_db.execute(
        "UPDATE field_architects SET permissions = ? WHERE fa_id = ?",
        (json.dumps(perms), registered_fa["fa_id"]),
    )
    await _test_db.commit()

    resp = await client.post(
        "/api/hub/events",
        headers={"X-Api-Key": "df-test-key"},
        json={
            "event_type": "manual_demo_created",
            "payload": {},
            "timestamp": "2024-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 403
