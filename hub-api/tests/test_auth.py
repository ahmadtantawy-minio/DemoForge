import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_missing_api_key(client: AsyncClient):
    resp = await client.get("/api/hub/fa/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_api_key(client: AsyncClient):
    resp = await client.get(
        "/api/hub/fa/me", headers={"X-Api-Key": "invalid-key"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_fa_key(client: AsyncClient, registered_fa: dict):
    resp = await client.get(
        "/api/hub/fa/me", headers={"X-Api-Key": "df-test-key"}
    )
    assert resp.status_code == 200
    assert resp.json()["fa_id"] == "test-fa@minio.io"


@pytest.mark.asyncio
async def test_fa_key_on_admin_endpoint(client: AsyncClient, registered_fa: dict):
    resp = await client.get(
        "/api/hub/admin/fas", headers={"X-Api-Key": "df-test-key"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_key_on_admin_endpoint(client: AsyncClient):
    resp = await client.get(
        "/api/hub/admin/fas", headers={"X-Api-Key": "test-admin-key"}
    )
    assert resp.status_code == 200
