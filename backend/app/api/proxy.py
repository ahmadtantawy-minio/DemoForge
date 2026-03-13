"""Reverse proxy route: /proxy/{demo_id}/{node_id}/{ui_name}/{path:path}"""
from fastapi import APIRouter, Request
from ..engine.proxy_gateway import forward_request

router = APIRouter()

@router.api_route(
    "/proxy/{demo_id}/{node_id}/{ui_name}/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_handler(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
    subpath: str = "",
):
    return await forward_request(request, demo_id, node_id, ui_name, subpath)

# Also handle the root path (no subpath)
@router.api_route(
    "/proxy/{demo_id}/{node_id}/{ui_name}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_handler_root(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
):
    return await forward_request(request, demo_id, node_id, ui_name, "")
