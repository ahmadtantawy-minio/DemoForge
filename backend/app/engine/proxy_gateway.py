"""
Reverse proxy: forwards /proxy/{demo}/{node}/{ui_name}/* to the container's
internal port over the Docker network.

The backend must be connected to the demo's Docker network for this to work.
Container is reached by its Docker Compose service hostname (node_id).
"""
import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from ..registry.loader import get_component
from ..state.store import state

# Persistent async HTTP client — connection pooling across requests
_http_client: httpx.AsyncClient | None = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            follow_redirects=False,          # We handle redirects ourselves
            limits=httpx.Limits(max_connections=100),
        )
    return _http_client

def resolve_target(demo_id: str, node_id: str, ui_name: str) -> tuple[str, str]:
    """
    Given demo/node/ui_name, return (base_url, ui_path).
    e.g. ("http://demoforge-lakehouse-minio-1:9001", "/")

    The hostname is the Docker Compose container name.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise ValueError(f"Demo {demo_id} is not running")

    container_info = running.containers.get(node_id)
    if not container_info:
        raise ValueError(f"Node {node_id} not found in demo {demo_id}")

    manifest = get_component(container_info.component_id)
    if not manifest:
        raise ValueError(f"Component {container_info.component_id} not in registry")

    # Find the matching web_ui entry
    ui_def = None
    for ui in manifest.web_ui:
        if ui.name == ui_name:
            ui_def = ui
            break

    if not ui_def:
        # Fallback: if ui_name matches a port name, proxy to that port
        for port in manifest.ports:
            if port.name == ui_name:
                return f"http://{container_info.container_name}:{port.container}", "/"
        raise ValueError(f"UI '{ui_name}' not found for component {manifest.id}")

    base_url = f"http://{container_info.container_name}:{ui_def.port}"
    return base_url, ui_def.path

async def forward_request(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
    subpath: str = "",
) -> Response:
    """
    Forward an HTTP request to the target container.
    Handles: method, headers, body, query params, streaming response.
    Rewrites Location headers and Set-Cookie paths.
    """
    base_url, ui_base_path = resolve_target(demo_id, node_id, ui_name)

    # Build target URL
    target_path = f"{ui_base_path.rstrip('/')}/{subpath}" if subpath else ui_base_path
    target_url = f"{base_url}{target_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Proxy prefix for rewriting
    proxy_prefix = f"/proxy/{demo_id}/{node_id}/{ui_name}"

    # Forward headers (remove host, adjust origin)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("Host", None)

    # Read request body
    body = await request.body()

    client = get_http_client()
    upstream_resp = await client.request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body if body else None,
    )

    # Build response headers, rewriting as needed
    resp_headers = {}
    # Headers to strip — they break iframe embedding or cause issues
    strip_headers = {"transfer-encoding", "content-encoding", "content-length",
                     "x-frame-options", "content-security-policy"}
    for key, value in upstream_resp.headers.multi_items():
        lower = key.lower()
        if lower in strip_headers:
            continue
        if lower == "location":
            # Rewrite redirects to go through proxy
            value = _rewrite_location(value, base_url, proxy_prefix)
        if lower == "set-cookie":
            # Scope cookies to proxy path
            value = _rewrite_cookie_path(value, proxy_prefix)
        resp_headers[key] = value

    content = upstream_resp.content
    content_type = upstream_resp.headers.get("content-type", "")

    # For HTML responses, inject a <base> tag so absolute asset paths resolve through proxy
    if "text/html" in content_type:
        content = _inject_base_tag(content, proxy_prefix)

    return Response(
        content=content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=content_type,
    )

def _rewrite_location(location: str, base_url: str, proxy_prefix: str) -> str:
    """Rewrite an absolute Location header to route through the proxy."""
    if location.startswith(base_url):
        return proxy_prefix + location[len(base_url):]
    if location.startswith("/"):
        return proxy_prefix + location
    return location

def _rewrite_cookie_path(cookie: str, proxy_prefix: str) -> str:
    """Rewrite Path= in Set-Cookie to scope to the proxy prefix."""
    if "Path=" in cookie:
        import re
        return re.sub(r'Path=/[^;]*', f'Path={proxy_prefix}/', cookie)
    return cookie + f"; Path={proxy_prefix}/"

def _inject_base_tag(content: bytes, proxy_prefix: str) -> bytes:
    """Inject a <base href> tag into HTML so absolute paths resolve through the proxy."""
    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    base_tag = f'<base href="{proxy_prefix}/">'

    # Insert after <head> if present
    if "<head>" in html:
        html = html.replace("<head>", f"<head>{base_tag}", 1)
    elif "<HEAD>" in html:
        html = html.replace("<HEAD>", f"<HEAD>{base_tag}", 1)
    elif "<html" in html.lower():
        # Fallback: insert at the start of body or after first tag
        html = base_tag + html
    else:
        return content

    return html.encode("utf-8")
