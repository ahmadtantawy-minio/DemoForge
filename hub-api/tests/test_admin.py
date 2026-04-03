import pytest
from httpx import AsyncClient

ADMIN_HEADERS = {"X-Api-Key": "test-admin-key"}


@pytest.mark.asyncio
async def test_list_fas(client: AsyncClient, registered_fa: dict):
    resp = await client.get("/api/hub/admin/fas", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["fa_id"] == "test-fa@minio.io"
    assert "event_count" in data[0]


@pytest.mark.asyncio
async def test_get_fa_detail(client: AsyncClient, registered_fa: dict):
    resp = await client.get(
        "/api/hub/admin/fas/test-fa@minio.io", headers=ADMIN_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fa_id"] == "test-fa@minio.io"
    assert "permissions" in data


@pytest.mark.asyncio
async def test_update_permissions(client: AsyncClient, registered_fa: dict):
    resp = await client.put(
        "/api/hub/admin/fas/test-fa@minio.io/permissions",
        headers=ADMIN_HEADERS,
        json={"manual_demo_creation": False, "max_concurrent_demos": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["permissions"]["manual_demo_creation"] is False
    assert data["permissions"]["max_concurrent_demos"] == 10


@pytest.mark.asyncio
async def test_update_status_deactivate(client: AsyncClient, registered_fa: dict):
    resp = await client.put(
        "/api/hub/admin/fas/test-fa@minio.io/status",
        headers=ADMIN_HEADERS,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_query_events_with_filter(client: AsyncClient, registered_fa: dict):
    # Create an event first
    await client.post(
        "/api/hub/events",
        headers={"X-Api-Key": "df-test-key"},
        json={
            "event_type": "demo_deployed",
            "payload": {},
            "timestamp": "2024-01-01T00:00:00Z",
        },
    )
    resp = await client.get(
        "/api/hub/admin/events",
        headers=ADMIN_HEADERS,
        params={"fa_id": "test-fa@minio.io"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["fa_id"] == "test-fa@minio.io"


@pytest.mark.asyncio
async def test_get_stats(client: AsyncClient, registered_fa: dict):
    resp = await client.get("/api/hub/admin/stats", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_fas" in data
    assert "active_fas" in data
    assert "total_events" in data
    assert "events_last_7_days" in data
    assert "events_last_30_days" in data
    assert "top_templates" in data
    assert "events_by_type" in data
