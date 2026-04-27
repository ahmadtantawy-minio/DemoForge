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

# Set by nginx for the DemoForge API; must not be forwarded to component UIs.
# Jetty/Airlift (e.g. Trino) reject X-Forwarded-* with 406 unless explicitly trusted.
_STRIP_PROXY_HEADERS_TO_UPSTREAM = frozenset({
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-forwarded-prefix",
    "x-real-ip",
    "forwarded",
})

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
    # Remove Accept-Encoding so upstream sends uncompressed content.
    # The proxy does HTML injection on the raw bytes; compressed bytes would
    # be stripped of their Content-Encoding header and rendered as garbage.
    headers.pop("accept-encoding", None)
    headers.pop("Accept-Encoding", None)
    for hk in list(headers.keys()):
        if hk.lower() in _STRIP_PROXY_HEADERS_TO_UPSTREAM:
            del headers[hk]

    # Read request body
    body = await request.body()

    client = get_http_client()
    upstream_resp = await client.request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body if body else None,
    )

    content_type = upstream_resp.headers.get("content-type", "")
    _rewrite_content = "text/html" in content_type or "javascript" in content_type

    # Build response headers, rewriting as needed
    resp_headers = {}
    # Headers to strip — they break iframe embedding or cause issues
    strip_headers = {"transfer-encoding", "content-encoding", "content-length",
                     "x-frame-options", "content-security-policy"}
    # For rewritten content (HTML/JS), also strip cache headers so the browser
    # always fetches fresh rewritten content (our rewrites embed the demo/node path).
    if _rewrite_content:
        strip_headers |= {"cache-control", "expires", "etag", "last-modified",
                          "pragma", "vary"}
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

    # Prevent browser from caching rewritten HTML/JS (rewrites are demo/node-specific)
    if _rewrite_content:
        resp_headers["Cache-Control"] = "no-store"

    content = upstream_resp.content

    # For HTML responses, inject a <base> tag so relative asset paths resolve through proxy
    if "text/html" in content_type:
        # Use the directory of the actual request path so relative assets resolve correctly
        # e.g. for /ui/login.html → base should be /proxy/.../trino-ui/ui/
        if subpath:
            subdir = "/".join(subpath.split("/")[:-1])  # directory part
            base_path = f"{proxy_prefix}/{subdir}/" if subdir else f"{proxy_prefix}/"
        else:
            base_path = f"{proxy_prefix}/"
        content = _inject_base_tag(content, base_path, proxy_prefix)

    elif "javascript" in content_type and proxy_prefix:
        # Rewrite hardcoded root paths inside JS bundles (Superset publicPath, MinIO Console
        # lazy chunks: /api/v1/, /ws/, /static/...). fetch/WebSocket interceptors only see calls
        # from the main bundle; chunk code often uses string literals directly.
        try:
            js = content.decode("utf-8", errors="ignore")
            pb = proxy_prefix.rstrip("/")
            js = js.replace('"/static/assets/"', f'"{proxy_prefix}/static/assets/"')
            js = js.replace("'/static/assets/'", f"'{proxy_prefix}/static/assets/'")
            for q in ('"', "'", "`"):
                js = js.replace(f"{q}/static/", f"{q}{pb}/static/")
                js = js.replace(f"{q}/api/v1/", f"{q}{pb}/api/v1/")
                js = js.replace(f"{q}/ws/", f"{q}{pb}/ws/")
            content = js.encode("utf-8")
        except Exception:
            pass

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

def _inject_base_tag(content: bytes, base_href: str, proxy_prefix: str = "") -> bytes:
    """Inject a <base href> tag and fetch interceptor into HTML.

    The base tag fixes relative CSS/JS paths. The fetch interceptor rewrites
    absolute API paths (like /ui/api/...) through the proxy prefix so that
    SPAs with hardcoded fetch() calls work correctly.
    Also rewrites absolute paths in href/src/action HTML attributes so that
    <link>, <script>, and <img> tags with hardcoded /static/... paths are
    proxied correctly.
    """
    import re
    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    # Use the proxy prefix (without subdir) for fetch rewriting
    proxy_base = proxy_prefix.rstrip("/") if proxy_prefix else base_href.rstrip("/")

    # Detect if the original HTML already has a <base> tag.
    # Apps with their own <base> tag (e.g. MinIO console) read it as their React Router
    # basename and expect the URL to retain the proxy prefix — replaceState would break them.
    # Apps without a <base> tag (e.g. Superset) use window.location.pathname directly for
    # routing and need replaceState to strip the proxy prefix before their router initializes.
    has_own_base = bool(re.search(r'<base\s', html, re.IGNORECASE))

    # Remove any existing <base> tag so our injected one is the only one
    html = re.sub(r'<base\s[^>]*/?>',  '', html, flags=re.IGNORECASE)

    base_tag = f'<base href="{base_href}">'
    # Comprehensive proxy interceptor (runs synchronously before SPA bundle scripts):
    # 1. history.replaceState: strips the proxy prefix from the URL immediately so that
    #    SPAs with client-side routing see the correct route path on init.
    #    SKIPPED for apps that already have a <base> tag (they use it as router basename
    #    and expect window.location to keep the full proxy-prefixed URL).
    # 2. fetch() / XHR: rewrites "/path" and "http://origin/path" API calls through
    #    the proxy prefix so REST API calls reach the right container.
    # 3. Node.prototype.appendChild/insertBefore: rewrites src/href on dynamically
    #    injected script/link elements (webpack lazy chunk loading).
    replace_state_block = (
        # Strip proxy prefix from URL before SPA initializes.
        # SKIP on login/logout pages so form actions stay on the proxy URL.
        f'try{{var p=window.location.pathname;'
        f'var stripped=p.slice(pb.length)||"/";'
        f'var isAuth=stripped==="/login/"||stripped==="/login"||stripped==="/logout/"||stripped==="/logout";'
        f'if(!isAuth&&(p===pb||p.startsWith(pb+"/")))'
        f'window.history.replaceState(window.history.state,"",stripped'
        f'+window.location.search+window.location.hash);}}catch(e){{}}'
    ) if not has_own_base else ""

    fetch_interceptor = (
        f'<script>'
        f'(function(){{'
        # proxy prefix
        f'var pb="{proxy_base}";'
        # Persist proxy prefix in sessionStorage so refresh-recovery redirects work
        f'try{{sessionStorage.setItem("_dfproxy",pb);}}catch(e){{}}'
        + replace_state_block +
        # rewrite helper: "/path" and "http://origin/path" → proxy-prefixed URL
        f'function rw(u){{'
        f'if(typeof u!=="string")return u;'
        f'if(u.startsWith("/")&&!u.startsWith(pb))return pb+u;'
        f'try{{var og=window.location.origin;'
        f'if(u.startsWith(og+"/")&&!u.startsWith(og+pb))return og+pb+u.slice(og.length);}}catch(e){{}}'
        f'return u;}}'
        # patch script/link before DOM insertion (webpack lazy chunk loading)
        f'function ps(c){{'
        f'if(!c||!c.tagName)return c;'
        f'var t=c.tagName;'
        f'if(t==="SCRIPT"&&c.src){{var ns=rw(c.src);if(ns!==c.src)c.setAttribute("src",ns);}}'
        f'if(t==="LINK"&&c.href){{var nh=rw(c.href);if(nh!==c.href)c.setAttribute("href",nh);}}'
        f'return c;}}'
        f'var _ac=Node.prototype.appendChild;'
        f'Node.prototype.appendChild=function(c){{return _ac.call(this,ps(c));}};'
        f'var _ib=Node.prototype.insertBefore;'
        f'Node.prototype.insertBefore=function(c,r){{return _ib.call(this,ps(c),r);}};'
        # fetch — must rewrite Request/URL inputs, not only strings. MinIO AIStor / Console
        # often uses fetch(new Request("/api/v1/...")) which would otherwise hit the SPA
        # origin and return wrong JSON/HTML → "Parsing Error" on the login screen.
        f'var _f=window.fetch;window.fetch=function(u,o){{'
        f'if(typeof u==="string")return _f.call(this,rw(u),o);'
        f'try{{if(typeof URL!=="undefined"&&u instanceof URL){{var hu=rw(u.href);'
        f'if(hu!==u.href)return _f.call(this,new URL(hu),o);}}}}catch(e){{}}'
        f'try{{if(typeof Request!=="undefined"&&u instanceof Request){{var ru=rw(u.url);'
        f'if(ru!==u.url)return _f.call(this,new Request(ru,u),o);}}}}catch(e){{}}'
        f'return _f.call(this,u,o);'
        f'}};'
        # XHR
        f'var _x=XMLHttpRequest.prototype.open;'
        f'XMLHttpRequest.prototype.open=function(m,u){{return _x.apply(this,[m,rw(u)].concat([].slice.call(arguments,2)));}};'
        # MinIO Console (and similar SPAs) open root-absolute ws URLs (e.g. /ws/...). Without
        # this they hit the app origin path instead of /proxy/{demo}/{node}/{ui}/... .
        f'var _WS=window.WebSocket;'
        f'function _dfWs(u,protocols){{var nu=(typeof u==="string")?rw(u):u;'
        f'return protocols===undefined?new _WS(nu):new _WS(nu,protocols);}}'
        f'_dfWs.prototype=_WS.prototype;'
        f'window.WebSocket=_dfWs;'
        f'window.WebSocket.CONNECTING=_WS.CONNECTING;'
        f'window.WebSocket.OPEN=_WS.OPEN;'
        f'window.WebSocket.CLOSING=_WS.CLOSING;'
        f'window.WebSocket.CLOSED=_WS.CLOSED;'
        f'window.WebSocket.prototype=_WS.prototype;'
        f'}})();'
        f'</script>'
    )

    inject = base_tag + fetch_interceptor

    # Insert after <head> if present
    if "<head>" in html:
        html = html.replace("<head>", f"<head>{inject}", 1)
    elif "<HEAD>" in html:
        html = html.replace("<HEAD>", f"<HEAD>{inject}", 1)
    elif "<html" in html.lower():
        # Fallback: insert at the start of body or after first tag
        html = base_tag + html
    else:
        return content

    # Rewrite absolute paths in HTML attributes (href, src, action) so that
    # <link>, <script>, <img> etc. with hardcoded /static/... paths are proxied.
    # Skip protocol-relative URLs (//) and paths already going through the proxy.
    if proxy_base:
        def _rewrite_attr(m: re.Match) -> str:
            attr, quote, path = m.group(1), m.group(2), m.group(3)
            if path.startswith("//") or path.startswith(proxy_base):
                return m.group(0)
            return f'{attr}={quote}{proxy_base}{path}{quote}'

        html = re.sub(r'(href|src|action)=(["\'])(/[^"\']*)\2', _rewrite_attr, html)

    return html.encode("utf-8")
