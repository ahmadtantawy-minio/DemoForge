import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_creates_fa(client: AsyncClient):
    resp = await client.post(
        "/api/hub/fa/register",
        json={
            "fa_id": "new-fa@minio.io",
            "fa_name": "New FA",
            "api_key": "df-new-key",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fa_id"] == "new-fa@minio.io"
    assert data["fa_name"] == "New FA"
    assert data["permissions"]["manual_demo_creation"] is True
    assert data["permissions"]["max_concurrent_demos"] == 5
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_register_idempotent(client: AsyncClient):
    payload = {
        "fa_id": "idem-fa@minio.io",
        "fa_name": "Idem FA",
        "api_key": "df-idem-key",
    }
    resp1 = await client.post("/api/hub/fa/register", json=payload)
    resp2 = await client.post("/api/hub/fa/register", json=payload)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["fa_id"] == resp2.json()["fa_id"]
    assert resp1.json()["registered_at"] == resp2.json()["registered_at"]


@pytest.mark.asyncio
async def test_get_me_valid_key(client: AsyncClient, registered_fa: dict):
    resp = await client.get(
        "/api/hub/fa/me", headers={"X-Api-Key": "df-test-key"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fa_id"] == "test-fa@minio.io"
    assert data["last_seen_at"] is not None


@pytest.mark.asyncio
async def test_get_me_no_key(client: AsyncClient):
    resp = await client.get("/api/hub/fa/me")
    assert resp.status_code == 401
