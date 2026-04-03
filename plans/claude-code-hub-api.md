# DemoForge Hub API — FA Tracking, Telemetry & Permissions

## Goal

Add a Hub API service to the DemoForge hub infrastructure that provides:
1. **FA Registry** — central record of all Field Architects, their API keys, and per-FA permissions
2. **Event Telemetry** — track demo deployments, template usage, and FA activity
3. **Permission Enforcement** — enable/disable features (e.g., manual demo creation) per FA
4. **Admin Endpoints** — query activity, manage FAs, view aggregate stats

The Hub API runs as a FastAPI service on the existing GCP VM alongside MinIO and the Docker registry. It uses SQLite for storage (no additional infrastructure). FAs have zero awareness of it — their local DemoForge backend communicates with it transparently through the existing hub connector → Cloud Run gateway path.

---

## Phase 0 — Investigation (DO THIS FIRST)

Before writing ANY code, investigate the current state of the codebase.

### 0.1 Understand the existing backend

```bash
# Find the main FastAPI app
find . -name "main.py" -o -name "app.py" | head -20
find . -path "*/api/*" -name "*.py" | head -30

# Find existing routers
grep -r "APIRouter" --include="*.py" -l
grep -r "app.include_router" --include="*.py" -l

# Find existing models/schemas
find . -name "models.py" -o -name "schemas.py" | head -20

# Check if there's already any telemetry or event tracking
grep -r "telemetry\|event\|tracking\|analytics" --include="*.py" -l
```

### 0.2 Understand the hub connector and gateway

```bash
# Find the Caddyfile for the Cloud Run gateway
find . -name "Caddyfile*" | head -10
cat <gateway-caddyfile>

# Find the hub connector Caddyfile
grep -r "X-Service" --include="Caddyfile*" -l
grep -r "X-Service" --include="*.py" -l

# Check the gateway deployment script
cat scripts/minio-gcp.sh | head -100

# Find existing hub scripts
ls scripts/hub-*.sh scripts/fa-*.sh 2>/dev/null
```

### 0.3 Understand the template sync and FA identity status

```bash
# Check how templates are synced (this is where events will be emitted)
grep -r "sync" --include="*.py" -l | head -10

# Check if FA identity is implemented
grep -r "DEMOFORGE_FA_ID\|DEMOFORGE_FA_NAME\|DEMOFORGE_MODE" --include="*.py" -l
grep -r "DEMOFORGE_FA_ID\|DEMOFORGE_FA_NAME\|DEMOFORGE_MODE" --include="*.env*" -l
grep -r "fa.setup\|fa-setup\|FA_ID" --include="Makefile" -l

# Check the .env files
cat .env 2>/dev/null
cat .env.local 2>/dev/null
cat .env.example 2>/dev/null
```

### 0.4 Understand the deploy/demo lifecycle

```bash
# Find where demos are deployed/started/stopped
grep -r "deploy\|compose.*up\|docker.*run" --include="*.py" -l | head -20
grep -r "def deploy\|def start_demo\|def stop_demo\|def destroy" --include="*.py" -l

# Find the demo state management
grep -r "demo_id\|demo_name\|DemoState\|demo_status" --include="*.py" -l | head -20
```

### 0.5 Check existing Makefile targets

```bash
grep -E "^[a-zA-Z_-]+:" Makefile | head -30
```

**IMPORTANT**: After investigation, update your understanding of file paths and patterns before proceeding. The paths used in later phases are illustrative — adapt them to match what you find.

---

## Phase 1 — Hub API Service (on GCP VM)

This is a NEW FastAPI service that runs on the GCP VM. It is NOT part of the local DemoForge backend that runs on the FA's laptop. It lives in a new directory at the project root.

### 1.1 Project structure

Create the Hub API as a standalone service:

```
hub-api/
├── main.py              # FastAPI app entry point
├── config.py            # Settings (from env vars)
├── database.py          # SQLite connection + table creation
├── auth.py              # API key validation middleware
├── models.py            # SQLAlchemy/Pydantic models
├── routers/
│   ├── __init__.py
│   ├── fa.py            # FA self-service endpoints
│   ├── events.py        # Telemetry event ingestion
│   └── admin.py         # Admin query/management endpoints
├── requirements.txt     # FastAPI, uvicorn, pydantic, aiosqlite
├── Dockerfile           # For deployment on the VM
├── tests/
│   ├── __init__.py
│   ├── conftest.py      # Shared fixtures (test client, test DB)
│   ├── test_fa.py       # FA endpoint tests
│   ├── test_events.py   # Event ingestion tests
│   ├── test_admin.py    # Admin endpoint tests
│   └── test_auth.py     # Auth middleware tests
└── README.md
```

### 1.2 Database schema (SQLite)

Create these tables in `database.py`:

```sql
-- FA Registry
CREATE TABLE IF NOT EXISTS field_architects (
    fa_id TEXT PRIMARY KEY,           -- email from git config (e.g. ahmad@minio.io)
    fa_name TEXT NOT NULL,            -- display name from git config
    api_key TEXT UNIQUE NOT NULL,     -- the FA's API key (df-xxxx)
    permissions TEXT NOT NULL DEFAULT '{}',  -- JSON blob of permissions
    registered_at TEXT NOT NULL,      -- ISO 8601 timestamp
    last_seen_at TEXT,                -- updated on every authenticated request
    is_active INTEGER NOT NULL DEFAULT 1,  -- soft disable
    metadata TEXT DEFAULT '{}'        -- JSON blob for future extensibility
);

-- Event Log
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fa_id TEXT NOT NULL,
    event_type TEXT NOT NULL,         -- demo_deployed, demo_stopped, etc.
    payload TEXT NOT NULL DEFAULT '{}', -- JSON blob with event-specific data
    timestamp TEXT NOT NULL,          -- ISO 8601 from client
    received_at TEXT NOT NULL,        -- server-side timestamp
    FOREIGN KEY (fa_id) REFERENCES field_architects(fa_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_events_fa_id ON events(fa_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_fa_api_key ON field_architects(api_key);
```

### 1.3 Configuration (`config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_path: str = "/data/hub-api/demoforge-hub.db"
    admin_api_key: str  # required — set in env
    log_level: str = "INFO"
    
    # Default permissions for new FAs
    default_permissions: dict = {
        "manual_demo_creation": True,
        "template_publish": True,
        "template_fork": True,
        "max_concurrent_demos": 5,
    }
    
    class Config:
        env_prefix = "HUB_API_"
```

### 1.4 Auth middleware (`auth.py`)

Two auth levels:
- **FA auth**: `X-Api-Key` header matched against `field_architects.api_key`. Updates `last_seen_at` on every request.
- **Admin auth**: `X-Api-Key` header matched against `HUB_API_ADMIN_API_KEY` env var.

```python
# Dependency injection pattern
async def get_current_fa(request: Request, db: AsyncSession = Depends(get_db)) -> FieldArchitect:
    """Validate API key and return FA record. Updates last_seen_at."""
    api_key = request.headers.get("X-Api-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    
    fa = await db.execute(select(FieldArchitect).where(FieldArchitect.api_key == api_key))
    fa = fa.scalar_one_or_none()
    if not fa:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not fa.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    
    # Update last_seen_at
    fa.last_seen_at = datetime.utcnow().isoformat()
    await db.commit()
    return fa

async def require_admin(request: Request):
    """Validate admin API key."""
    api_key = request.headers.get("X-Api-Key")
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Admin access required")
```

### 1.5 Models (`models.py`)

Define both SQLAlchemy models (for DB) and Pydantic schemas (for request/response).

**Pydantic schemas — request/response contracts:**

```python
# --- FA schemas ---
class FARegistrationRequest(BaseModel):
    fa_id: str          # email
    fa_name: str        # display name
    api_key: str        # pre-provisioned API key

class FAProfile(BaseModel):
    fa_id: str
    fa_name: str
    permissions: dict
    registered_at: str
    last_seen_at: str | None
    is_active: bool

class FAPermissions(BaseModel):
    """Used for both GET response and PUT request"""
    manual_demo_creation: bool = True
    template_publish: bool = True
    template_fork: bool = True
    max_concurrent_demos: int = 5

# --- Event schemas ---
class EventCreate(BaseModel):
    event_type: str     # constrained to known types below
    payload: dict = {}
    timestamp: str      # ISO 8601 from client

    @validator("event_type")
    def validate_event_type(cls, v):
        allowed = {
            "demo_deployed", "demo_stopped", "demo_destroyed",
            "template_synced", "template_forked", "template_published",
            "manual_demo_created", "app_started", "app_stopped",
        }
        if v not in allowed:
            raise ValueError(f"Unknown event type: {v}. Allowed: {allowed}")
        return v

class EventResponse(BaseModel):
    id: int
    fa_id: str
    event_type: str
    payload: dict
    timestamp: str
    received_at: str

# --- Admin schemas ---
class FAListItem(BaseModel):
    fa_id: str
    fa_name: str
    is_active: bool
    last_seen_at: str | None
    registered_at: str
    event_count: int        # total events from this FA

class ActivityStats(BaseModel):
    total_fas: int
    active_fas: int          # seen in last 30 days
    total_events: int
    events_last_7_days: int
    events_last_30_days: int
    top_templates: list[dict]  # [{template_id, count}]
    events_by_type: dict       # {event_type: count}
```

**Allowed event types and their expected payload shapes:**

| Event Type | Payload Fields |
|---|---|
| `app_started` | `{mode: "fa"\|"dev", version: "x.y.z"}` |
| `app_stopped` | `{uptime_seconds: int}` |
| `demo_deployed` | `{template_id, demo_id, components: [...], component_count: int}` |
| `demo_stopped` | `{demo_id, uptime_seconds: int}` |
| `demo_destroyed` | `{demo_id}` |
| `manual_demo_created` | `{demo_id, components: [...], component_count: int}` |
| `template_synced` | `{template_id, source: "hub"\|"builtin"}` |
| `template_forked` | `{source_template_id, new_template_id}` |
| `template_published` | `{template_id}` |

### 1.6 Routers

#### `routers/fa.py` — FA self-service

```
POST /api/hub/fa/register     — Register a new FA (called by fa-setup.sh)
GET  /api/hub/fa/me            — Get own profile + permissions (called on startup)
```

**Registration logic:**
- Accepts `FARegistrationRequest`
- Checks if `fa_id` already exists → if yes, return existing profile (idempotent)
- Creates new record with default permissions
- Returns `FAProfile`

**Profile logic:**
- Uses `get_current_fa` dependency
- Returns full profile including permissions
- This is called on every DemoForge startup in FA mode

#### `routers/events.py` — Telemetry ingestion

```
POST /api/hub/events           — Record a telemetry event
POST /api/hub/events/batch     — Record multiple events at once
```

**Event ingestion logic:**
- Uses `get_current_fa` dependency (events are tied to the authenticated FA)
- Validates `event_type` against allowed list
- For `manual_demo_created`: check if FA has `manual_demo_creation` permission → reject with 403 if not
- Stores event with server-side `received_at` timestamp
- Returns 201 with event ID(s)

**Batch endpoint:**
- Accepts `list[EventCreate]` (max 100 per batch)
- Useful for offline/queued events
- Returns list of event IDs

#### `routers/admin.py` — Admin management

All endpoints require `require_admin` dependency.

```
GET    /api/hub/admin/fas                          — List all FAs with summary stats
GET    /api/hub/admin/fas/{fa_id}                  — Get detailed FA profile
GET    /api/hub/admin/fas/{fa_id}/activity         — Get FA activity log
PUT    /api/hub/admin/fas/{fa_id}/permissions      — Update FA permissions
PUT    /api/hub/admin/fas/{fa_id}/status           — Activate/deactivate FA
POST   /api/hub/admin/fas                          — Pre-register an FA (provision before they run fa-setup)
DELETE /api/hub/admin/fas/{fa_id}                  — Soft-delete an FA (sets is_active=false)

GET    /api/hub/admin/events                       — Query events with filters
GET    /api/hub/admin/stats                        — Aggregate statistics
```

**Event query parameters:**
- `fa_id` (optional) — filter by FA
- `event_type` (optional) — filter by type
- `since` (optional) — ISO 8601 start date
- `until` (optional) — ISO 8601 end date
- `limit` (optional, default=100, max=1000) — pagination
- `offset` (optional, default=0) — pagination

**Stats endpoint returns** `ActivityStats` schema.

**Permissions update:**
- Accepts `FAPermissions` model
- Merges with existing permissions (partial update)
- Returns updated permissions
- Changes take effect on the FA's next startup (or next permission check)

### 1.7 Main app (`main.py`)

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    await init_db()
    yield
    # Shutdown: close DB connections

app = FastAPI(
    title="DemoForge Hub API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(fa_router, prefix="/api/hub/fa", tags=["fa"])
app.include_router(events_router, prefix="/api/hub", tags=["events"])
app.include_router(admin_router, prefix="/api/hub/admin", tags=["admin"])

# Health check (no auth required)
@app.get("/api/hub/health")
async def health():
    return {"status": "ok", "service": "demoforge-hub-api"}
```

### 1.8 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite data directory
RUN mkdir -p /data/hub-api

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
```

### 1.9 Validation — Phase 1

Run these checks before moving to Phase 2:

```bash
# 1. Install dependencies and run the service locally
cd hub-api
pip install -r requirements.txt
HUB_API_ADMIN_API_KEY=test-admin-key uvicorn main:app --port 8000 &

# 2. Health check
curl -s http://localhost:8000/api/hub/health | python -m json.tool
# Expected: {"status": "ok", "service": "demoforge-hub-api"}

# 3. Register an FA
curl -s -X POST http://localhost:8000/api/hub/fa/register \
  -H "Content-Type: application/json" \
  -d '{"fa_id": "test@minio.io", "fa_name": "Test FA", "api_key": "df-test-key-123"}' \
  | python -m json.tool
# Expected: FAProfile response with default permissions

# 4. Get FA profile
curl -s http://localhost:8000/api/hub/fa/me \
  -H "X-Api-Key: df-test-key-123" \
  | python -m json.tool
# Expected: same profile, last_seen_at updated

# 5. Post an event
curl -s -X POST http://localhost:8000/api/hub/events \
  -H "X-Api-Key: df-test-key-123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "demo_deployed", "payload": {"template_id": "minio-iceberg", "demo_id": "demo-001", "components": ["minio", "trino"], "component_count": 2}, "timestamp": "2026-04-03T10:00:00Z"}' \
  | python -m json.tool
# Expected: 201 with event ID

# 6. Admin: list FAs
curl -s http://localhost:8000/api/hub/admin/fas \
  -H "X-Api-Key: test-admin-key" \
  | python -m json.tool
# Expected: list with test FA and event_count=1

# 7. Admin: query events
curl -s "http://localhost:8000/api/hub/admin/events?fa_id=test@minio.io" \
  -H "X-Api-Key: test-admin-key" \
  | python -m json.tool
# Expected: list with the demo_deployed event

# 8. Admin: update permissions (disable manual demo creation)
curl -s -X PUT http://localhost:8000/api/hub/admin/fas/test@minio.io/permissions \
  -H "X-Api-Key: test-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"manual_demo_creation": false}' \
  | python -m json.tool
# Expected: updated permissions with manual_demo_creation=false

# 9. Verify permission enforcement — try posting manual_demo_created event
curl -s -X POST http://localhost:8000/api/hub/events \
  -H "X-Api-Key: df-test-key-123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "manual_demo_created", "payload": {"demo_id": "demo-002", "components": ["minio"], "component_count": 1}, "timestamp": "2026-04-03T10:05:00Z"}' \
  -w "\nHTTP %{http_code}\n"
# Expected: 403 Forbidden

# 10. Auth failure tests
curl -s http://localhost:8000/api/hub/fa/me -w "\nHTTP %{http_code}\n"
# Expected: 401 (no key)

curl -s http://localhost:8000/api/hub/fa/me -H "X-Api-Key: wrong-key" -w "\nHTTP %{http_code}\n"
# Expected: 401 (bad key)

curl -s http://localhost:8000/api/hub/admin/fas -H "X-Api-Key: df-test-key-123" -w "\nHTTP %{http_code}\n"
# Expected: 403 (FA key used on admin endpoint)

# 11. Idempotent registration
curl -s -X POST http://localhost:8000/api/hub/fa/register \
  -H "Content-Type: application/json" \
  -d '{"fa_id": "test@minio.io", "fa_name": "Test FA", "api_key": "df-test-key-123"}' \
  | python -m json.tool
# Expected: returns existing profile, no duplicate created

# 12. Stats endpoint
curl -s http://localhost:8000/api/hub/admin/stats \
  -H "X-Api-Key: test-admin-key" \
  | python -m json.tool
# Expected: total_fas=1, total_events>=1, top_templates, events_by_type

# Cleanup
kill %1
```

### 1.10 Automated tests (`tests/`)

Write pytest tests using `httpx.AsyncClient` with FastAPI's `TestClient`.

**`tests/conftest.py`:**
- Create an in-memory SQLite DB for each test session
- Override the `get_db` dependency to use the test DB
- Create fixtures: `test_client`, `registered_fa`, `admin_headers`, `fa_headers`

**`tests/test_auth.py`:**
- `test_missing_api_key_returns_401`
- `test_invalid_api_key_returns_401`
- `test_disabled_fa_returns_403`
- `test_fa_key_on_admin_endpoint_returns_403`
- `test_admin_key_works_on_admin_endpoints`
- `test_last_seen_updated_on_request`

**`tests/test_fa.py`:**
- `test_register_new_fa`
- `test_register_existing_fa_is_idempotent`
- `test_register_duplicate_email_different_key_returns_conflict`
- `test_get_profile_returns_permissions`
- `test_get_profile_updates_last_seen`

**`tests/test_events.py`:**
- `test_post_valid_event`
- `test_post_event_unknown_type_returns_422`
- `test_post_event_missing_fields_returns_422`
- `test_post_batch_events`
- `test_batch_max_100_limit`
- `test_manual_demo_created_blocked_when_permission_disabled`
- `test_manual_demo_created_allowed_when_permission_enabled`
- `test_event_timestamps_stored_correctly`

**`tests/test_admin.py`:**
- `test_list_fas_returns_all`
- `test_list_fas_includes_event_count`
- `test_get_fa_detail`
- `test_get_fa_activity`
- `test_update_permissions_partial_merge`
- `test_deactivate_fa`
- `test_reactivate_fa`
- `test_query_events_filter_by_fa`
- `test_query_events_filter_by_type`
- `test_query_events_filter_by_date_range`
- `test_query_events_pagination`
- `test_stats_endpoint`
- `test_stats_top_templates`
- `test_pre_register_fa`

Run with:
```bash
cd hub-api
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

**All tests must pass before moving to Phase 2.**

---

## Phase 2 — Gateway Routing

Add routing for the Hub API service through the existing Cloud Run Caddy gateway.

### 2.1 Investigate current gateway config

```bash
# Find the Caddyfile used by the Cloud Run gateway
# It should already have routes for:
#   X-Service: s3       → MinIO :9000
#   X-Service: console  → MinIO Console :9001
#   /v2/*               → Registry :5000
# We need to add:
#   X-Service: hub-api  → Hub API :8000
```

### 2.2 Add hub-api route

Add a new route block to the gateway Caddyfile:

```caddyfile
# Hub API service
@hub_api header X-Service hub-api
handle @hub_api {
    reverse_proxy localhost:8000
}
```

This goes BEFORE the default/catch-all route, alongside the existing S3 and console routes.

### 2.3 Update hub connector (local Caddy)

The FA's local hub connector also needs to know about the hub-api service. Add routing so requests to a local port or path get `X-Service: hub-api` header added and forwarded to the gateway.

**Option A (recommended):** Route through port 8080 (already allocated for the connector's admin/API use):

```caddyfile
# In the hub connector Caddyfile
:8080 {
    # Forward to gateway with hub-api service header
    reverse_proxy {$GATEWAY_URL} {
        header_up X-Api-Key {$API_KEY}
        header_up X-Service hub-api
    }
}
```

**Option B:** Add a path-based route on an existing port. Investigate which approach is cleaner given the current connector config.

### 2.4 Validation — Phase 2

```bash
# 1. Deploy the updated gateway
# (use existing minio-gcp.sh --gateway or equivalent)

# 2. Test from local machine through the gateway
curl -s https://<cloud-run-url>/api/hub/health \
  -H "X-Api-Key: <your-gateway-api-key>" \
  -H "X-Service: hub-api" \
  | python -m json.tool
# Expected: {"status": "ok", "service": "demoforge-hub-api"}

# 3. Test through the local hub connector
curl -s http://localhost:8080/api/hub/health \
  | python -m json.tool
# Expected: same response (connector adds X-Api-Key and X-Service headers)

# 4. Verify existing routes still work
curl -s http://localhost:9000/minio/health/live
# Expected: MinIO health response (unchanged)
```

---

## Phase 3 — FA Registration in Setup

Extend `fa-setup.sh` to register the FA with the Hub API during onboarding.

### 3.1 Investigate current fa-setup.sh

```bash
cat scripts/fa-setup.sh
# Understand what it currently does:
# - Pulls hub connector image
# - Starts hub connector container
# - Writes .env.local with DEMOFORGE_FA_ID, DEMOFORGE_FA_NAME
# - Pulls custom images from registry
```

### 3.2 Add registration step

After the connector is running and before images are pulled, add:

```bash
# --- Register with Hub API ---
echo "Registering with DemoForge Hub..."

FA_ID=$(git config user.email)
FA_NAME=$(git config user.name)
API_KEY="${DEMOFORGE_API_KEY}"  # already set in the script

REGISTER_RESPONSE=$(curl -s -X POST http://localhost:8080/api/hub/fa/register \
  -H "Content-Type: application/json" \
  -d "{\"fa_id\": \"${FA_ID}\", \"fa_name\": \"${FA_NAME}\", \"api_key\": \"${API_KEY}\"}")

# Validate response
if echo "$REGISTER_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); assert data.get('fa_id')" 2>/dev/null; then
    echo "✅ Registered as: ${FA_ID}"
else
    echo "⚠️  Hub registration failed (non-blocking). You can still use DemoForge locally."
    echo "    Response: ${REGISTER_RESPONSE}"
fi
```

**IMPORTANT:** Registration failure must NOT block FA setup. It's fire-and-forget. The FA can still use DemoForge locally without hub registration.

### 3.3 Validation — Phase 3

```bash
# 1. Run fa-setup.sh on a test machine (or simulate locally)
# 2. Check that the FA appears in the admin API:
curl -s http://localhost:8080/api/hub/admin/fas \
  -H "X-Api-Key: <admin-key>" \
  | python -m json.tool
# Expected: the newly registered FA appears in the list

# 3. Run fa-setup.sh again (idempotency test)
# Expected: no error, no duplicate FA created
```

---

## Phase 4 — Telemetry Emitter (Local Backend)

Add a telemetry module to the local DemoForge FastAPI backend that sends events to the Hub API.

### 4.1 Investigate current backend structure

```bash
# Find the backend entry point
find . -path "*/backend/*" -name "main.py" -o -path "*/backend/*" -name "app.py"

# Find where demos are deployed/managed
grep -r "def deploy\|def start\|def stop\|def destroy" --include="*.py" backend/
```

### 4.2 Create telemetry module

Create `backend/telemetry.py` (or wherever the backend lives):

```python
"""
Fire-and-forget telemetry emitter.
Sends events to the Hub API through the local hub connector.
Never blocks or fails the main operation.
"""
import asyncio
import logging
import httpx
from datetime import datetime, timezone
from collections import deque

logger = logging.getLogger("demoforge.telemetry")

class TelemetryEmitter:
    def __init__(self, hub_url: str, api_key: str, fa_id: str, enabled: bool = True):
        self.hub_url = hub_url          # e.g. http://localhost:8080
        self.api_key = api_key
        self.fa_id = fa_id
        self.enabled = enabled
        self._queue: deque = deque(maxlen=1000)  # buffer for offline/retry
        self._client: httpx.AsyncClient | None = None
    
    async def start(self):
        """Initialize the HTTP client."""
        if self.enabled:
            self._client = httpx.AsyncClient(
                base_url=self.hub_url,
                headers={"X-Api-Key": self.api_key},
                timeout=5.0,
            )
    
    async def stop(self):
        """Flush queue and close client."""
        if self._client:
            await self._flush_queue()
            await self._client.aclose()
    
    async def emit(self, event_type: str, payload: dict | None = None):
        """
        Send a telemetry event. Never raises — failures are logged and queued.
        """
        if not self.enabled:
            return
        
        event = {
            "event_type": event_type,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            if self._client:
                response = await self._client.post(
                    "/api/hub/events",
                    json=event,
                )
                if response.status_code == 201:
                    logger.debug(f"Telemetry sent: {event_type}")
                elif response.status_code == 403:
                    logger.warning(f"Telemetry rejected (permission denied): {event_type}")
                else:
                    logger.warning(f"Telemetry failed ({response.status_code}): {event_type}")
                    self._queue.append(event)
            else:
                self._queue.append(event)
        except Exception as e:
            logger.debug(f"Telemetry send failed: {e}")
            self._queue.append(event)
    
    async def _flush_queue(self):
        """Try to send queued events as a batch."""
        if not self._queue or not self._client:
            return
        
        events = list(self._queue)
        self._queue.clear()
        
        try:
            response = await self._client.post(
                "/api/hub/events/batch",
                json=events,
            )
            if response.status_code != 201:
                logger.warning(f"Batch flush failed ({response.status_code}), {len(events)} events lost")
        except Exception as e:
            logger.debug(f"Batch flush failed: {e}, {len(events)} events lost")


# Global singleton — initialized on app startup
_emitter: TelemetryEmitter | None = None

async def init_telemetry(hub_url: str, api_key: str, fa_id: str, enabled: bool):
    global _emitter
    _emitter = TelemetryEmitter(hub_url, api_key, fa_id, enabled)
    await _emitter.start()

async def shutdown_telemetry():
    global _emitter
    if _emitter:
        await _emitter.stop()

async def emit_event(event_type: str, payload: dict | None = None):
    if _emitter:
        await _emitter.emit(event_type, payload)
```

### 4.3 Integrate into app lifecycle

In the backend's main app file:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    
    # Initialize telemetry (FA mode only)
    mode = os.getenv("DEMOFORGE_MODE", "dev")
    await init_telemetry(
        hub_url=os.getenv("HUB_API_URL", "http://localhost:8080"),
        api_key=os.getenv("DEMOFORGE_API_KEY", ""),
        fa_id=os.getenv("DEMOFORGE_FA_ID", "dev@localhost"),
        enabled=(mode == "fa"),
    )
    
    # Emit app_started event
    await emit_event("app_started", {"mode": mode, "version": os.getenv("DEMOFORGE_VERSION", "unknown")})
    
    yield
    
    # Emit app_stopped event
    await emit_event("app_stopped", {"uptime_seconds": int(time.time() - app.state.start_time)})
    await shutdown_telemetry()
```

### 4.4 Add emit calls to existing operations

Find the functions that deploy, stop, and destroy demos, and add `await emit_event(...)` calls. For example:

```python
# In the deploy function (after successful deployment)
await emit_event("demo_deployed", {
    "template_id": template.id,
    "demo_id": demo.id,
    "components": [c.name for c in demo.components],
    "component_count": len(demo.components),
})

# In the stop function
await emit_event("demo_stopped", {
    "demo_id": demo.id,
    "uptime_seconds": int(time.time() - demo.started_at),
})

# In the destroy function
await emit_event("demo_destroyed", {"demo_id": demo.id})

# When creating a manual demo (from canvas, not a template)
await emit_event("manual_demo_created", {
    "demo_id": demo.id,
    "components": [c.name for c in demo.components],
    "component_count": len(demo.components),
})

# Template operations
await emit_event("template_synced", {"template_id": template.id, "source": "hub"})
await emit_event("template_forked", {"source_template_id": source.id, "new_template_id": new.id})
await emit_event("template_published", {"template_id": template.id})
```

### 4.5 Validation — Phase 4

```bash
# 1. Start DemoForge in dev mode
make dev
# Expected: telemetry disabled, no events sent (check logs)

# 2. Start DemoForge in FA mode (with hub connector running)
make start
# Expected: app_started event sent to hub

# 3. Deploy a demo from a template
# Expected: demo_deployed event sent

# 4. Check events via admin API
curl -s "http://localhost:8080/api/hub/admin/events?fa_id=$(git config user.email)" \
  -H "X-Api-Key: <admin-key>" \
  | python -m json.tool
# Expected: app_started and demo_deployed events visible

# 5. Kill the hub connector, then deploy another demo
docker stop demoforge-hub-connector
# Deploy a demo...
# Expected: deploy succeeds, telemetry fails silently (check backend logs for debug message)

# 6. Restart connector
docker start demoforge-hub-connector
# Start another demo action...
# Expected: queued events flushed on next successful send (or on shutdown)
```

---

## Phase 5 — Permission Enforcement

### 5.1 Frontend: Fetch permissions on startup

In the React app's initialization (likely in a context provider or Zustand store):

```typescript
// types/hub.ts
interface FAPermissions {
  manual_demo_creation: boolean;
  template_publish: boolean;
  template_fork: boolean;
  max_concurrent_demos: number;
}

interface FAProfile {
  fa_id: string;
  fa_name: string;
  permissions: FAPermissions;
  is_active: boolean;
}

// store/hubStore.ts (Zustand)
interface HubState {
  faProfile: FAProfile | null;
  permissionsLoaded: boolean;
  fetchPermissions: () => Promise<void>;
  hasPermission: (key: keyof FAPermissions) => boolean;
}

export const useHubStore = create<HubState>((set, get) => ({
  faProfile: null,
  permissionsLoaded: false,
  
  fetchPermissions: async () => {
    const mode = import.meta.env.VITE_DEMOFORGE_MODE;
    if (mode !== 'fa') {
      // Dev mode: all permissions enabled, skip fetch
      set({
        faProfile: {
          fa_id: 'dev@localhost',
          fa_name: 'Developer',
          permissions: {
            manual_demo_creation: true,
            template_publish: true,
            template_fork: true,
            max_concurrent_demos: 99,
          },
          is_active: true,
        },
        permissionsLoaded: true,
      });
      return;
    }
    
    try {
      const response = await fetch('/api/hub/fa/me');
      if (response.ok) {
        const profile = await response.json();
        set({ faProfile: profile, permissionsLoaded: true });
      } else {
        console.warn('Failed to fetch permissions, using defaults');
        set({ permissionsLoaded: true }); // Allow app to continue
      }
    } catch (err) {
      console.warn('Hub unreachable, using defaults');
      set({ permissionsLoaded: true }); // Allow app to continue
    }
  },
  
  hasPermission: (key) => {
    const { faProfile } = get();
    if (!faProfile) return true; // Default: allow (graceful degradation)
    return faProfile.permissions[key] ?? true;
  },
}));
```

### 5.2 Frontend: Conditionally show/hide features

```tsx
// In the canvas toolbar or "New Demo" UI
const canCreateManual = useHubStore(s => s.hasPermission('manual_demo_creation'));

{canCreateManual && (
  <Button onClick={handleNewManualDemo}>
    New Demo from Scratch
  </Button>
)}

// In the template gallery actions
const canPublish = useHubStore(s => s.hasPermission('template_publish'));
const canFork = useHubStore(s => s.hasPermission('template_fork'));

{canPublish && <Button onClick={handlePublish}>Publish to Hub</Button>}
{canFork && <Button onClick={handleFork}>Fork Template</Button>}
```

### 5.3 Backend: Second layer of enforcement

In the local DemoForge backend, cache permissions and enforce them on API calls:

```python
# backend/permissions.py
_cached_permissions: dict | None = None

async def get_permissions() -> dict:
    """Fetch and cache FA permissions from hub."""
    global _cached_permissions
    if _cached_permissions is not None:
        return _cached_permissions
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{HUB_API_URL}/api/hub/fa/me",
                headers={"X-Api-Key": API_KEY},
                timeout=5.0,
            )
            if response.status_code == 200:
                profile = response.json()
                _cached_permissions = profile.get("permissions", {})
                return _cached_permissions
    except Exception:
        pass
    
    # Default: allow everything if hub is unreachable
    return {"manual_demo_creation": True, "template_publish": True, "template_fork": True, "max_concurrent_demos": 5}

async def check_permission(permission: str) -> bool:
    perms = await get_permissions()
    return perms.get(permission, True)

def refresh_permissions():
    """Called periodically or on specific triggers."""
    global _cached_permissions
    _cached_permissions = None
```

Use in deploy endpoint:

```python
@router.post("/api/demos/deploy")
async def deploy_demo(request: DeployRequest):
    # Check if this is a manual (non-template) deploy
    if not request.template_id:
        if not await check_permission("manual_demo_creation"):
            raise HTTPException(
                status_code=403,
                detail="Manual demo creation is disabled for your account. Contact your admin."
            )
    # ... proceed with deploy
```

### 5.4 Validation — Phase 5

```bash
# 1. Admin: disable manual demo creation for test FA
curl -s -X PUT http://localhost:8080/api/hub/admin/fas/test@minio.io/permissions \
  -H "X-Api-Key: <admin-key>" \
  -H "Content-Type: application/json" \
  -d '{"manual_demo_creation": false}'

# 2. Restart DemoForge (to fetch fresh permissions)
# 3. Check the UI:
#    - "New Demo from Scratch" button should NOT appear
#    - Template-based deploys should still work
#    - Fork and Publish should still work (those were not disabled)

# 4. Try to bypass the UI by calling the API directly
curl -s -X POST http://localhost:3000/api/demos/deploy \
  -H "Content-Type: application/json" \
  -d '{"components": ["minio"]}'
# Expected: 403 with "Manual demo creation is disabled" message

# 5. Re-enable manual demo creation
curl -s -X PUT http://localhost:8080/api/hub/admin/fas/test@minio.io/permissions \
  -H "X-Api-Key: <admin-key>" \
  -H "Content-Type: application/json" \
  -d '{"manual_demo_creation": true}'

# 6. Restart DemoForge, verify button reappears

# 7. Offline resilience test:
#    - Stop the hub connector
#    - Start DemoForge
#    - Verify all features are available (graceful degradation — default allow)
#    - Deploy a demo (should work even without hub)
```

---

## Phase 6 — Deploy Hub API to GCP VM

### 6.1 Add Hub API to VM setup

Extend `minio-gcp.sh` (or create a new `hub-api-deploy.sh`) to:

1. Copy the `hub-api/` directory to the VM
2. Build the Docker image on the VM
3. Run the container with:
   - Port 8000 mapped (internal only — not exposed to internet)
   - Volume mount for SQLite: `-v /data/hub-api:/data/hub-api`
   - Environment variables: `HUB_API_ADMIN_API_KEY`, `HUB_API_DATABASE_PATH`
4. Add to the VM's Docker Compose or systemd so it auto-restarts

```bash
# Example deployment commands (adapt to existing patterns)
gcloud compute scp --recurse hub-api/ demoforge-vm:~/hub-api/ --zone=me-central1-a
gcloud compute ssh demoforge-vm --zone=me-central1-a --command="
    cd ~/hub-api
    docker build -t hub-api:latest .
    docker stop hub-api 2>/dev/null || true
    docker rm hub-api 2>/dev/null || true
    docker run -d \
        --name hub-api \
        --restart unless-stopped \
        -p 127.0.0.1:8000:8000 \
        -v /data/hub-api:/data/hub-api \
        -e HUB_API_ADMIN_API_KEY=${ADMIN_API_KEY} \
        hub-api:latest
"
```

### 6.2 Update gateway Caddyfile

Deploy the updated Caddyfile that includes the `hub-api` route (from Phase 2).

### 6.3 Validation — Phase 6

```bash
# 1. Verify Hub API is running on the VM
gcloud compute ssh demoforge-vm --zone=me-central1-a --command="
    docker ps | grep hub-api
    curl -s http://localhost:8000/api/hub/health
"
# Expected: container running, health check passes

# 2. Verify routing through Cloud Run gateway
curl -s https://<cloud-run-url>/api/hub/health \
  -H "X-Api-Key: <gateway-api-key>" \
  -H "X-Service: hub-api"
# Expected: health response

# 3. Verify through local hub connector
curl -s http://localhost:8080/api/hub/health
# Expected: health response (full chain: connector → gateway → VM → hub-api)

# 4. End-to-end: register FA, send event, query via admin
# Run the full manual test sequence from Phase 1.9 but through the connector

# 5. SQLite persistence test
gcloud compute ssh demoforge-vm --zone=me-central1-a --command="
    docker restart hub-api
    sleep 2
    curl -s http://localhost:8000/api/hub/admin/fas -H 'X-Api-Key: ${ADMIN_API_KEY}'
"
# Expected: FA data persists across restarts

# 6. Check VM resource impact
gcloud compute ssh demoforge-vm --zone=me-central1-a --command="
    docker stats --no-stream hub-api
"
# Expected: minimal CPU and memory usage (<50MB)
```

---

## Phase 7 — Hub Status Integration

Extend the existing `hub-status.sh` script to include Hub API status.

### 7.1 Add Hub API checks

```bash
# In hub-status.sh, add after existing checks:

echo ""
echo "=== Hub API ==="
HUB_API_HEALTH=$(curl -s --max-time 5 http://localhost:8080/api/hub/health 2>/dev/null)
if [ $? -eq 0 ] && echo "$HUB_API_HEALTH" | grep -q "ok"; then
    echo "✅ Hub API: healthy"
    
    # Show FA count and recent activity (admin key required)
    if [ -n "$ADMIN_API_KEY" ]; then
        STATS=$(curl -s --max-time 5 http://localhost:8080/api/hub/admin/stats \
            -H "X-Api-Key: ${ADMIN_API_KEY}" 2>/dev/null)
        if [ $? -eq 0 ]; then
            TOTAL_FAS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_fas', '?'))" 2>/dev/null)
            ACTIVE_FAS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('active_fas', '?'))" 2>/dev/null)
            TOTAL_EVENTS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_events', '?'))" 2>/dev/null)
            echo "   Field Architects: ${TOTAL_FAS} total, ${ACTIVE_FAS} active (last 30d)"
            echo "   Events tracked:   ${TOTAL_EVENTS}"
        fi
    fi
else
    echo "❌ Hub API: unreachable"
fi
```

### 7.2 Validation — Phase 7

```bash
# Run hub-status.sh
ADMIN_API_KEY=<admin-key> bash scripts/hub-status.sh
# Expected: Hub API section shows healthy + FA/event counts
```

---

## Security & Design Principles

### Non-negotiables

1. **FA setup never blocks on hub failures** — registration, telemetry, and permission fetching all fail gracefully
2. **Telemetry is fire-and-forget** — never blocks or slows demo operations
3. **Default-allow on permission failures** — if the hub is unreachable, all features are available
4. **Admin API key is separate from FA API keys** — never shared with FAs
5. **SQLite is the right tool** — no Postgres, no Redis, no external DB. Dozens of FAs, not millions of users
6. **No PII beyond git email and name** — already public in git commits

### What NOT to build

- **No SSO/OAuth** — API keys are sufficient for this scale
- **No real-time websockets** — admin can poll or refresh
- **No complex dashboards yet** — curl against admin endpoints is sufficient for v1
- **No event streaming/webhooks** — simple REST is fine
- **No data retention policies** — SQLite file is small, can be managed manually

### Rate limiting

Add basic rate limiting on the event ingestion endpoint to prevent accidental loops:
- Max 100 events per minute per FA
- Max 100 events per batch request

Implement with an in-memory counter (no Redis needed):

```python
from collections import defaultdict
import time

_rate_limits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 100  # events per minute

def check_rate_limit(fa_id: str) -> bool:
    now = time.time()
    window = [t for t in _rate_limits[fa_id] if now - t < 60]
    _rate_limits[fa_id] = window
    if len(window) >= RATE_LIMIT:
        return False
    _rate_limits[fa_id].append(now)
    return True
```

---

## Summary of Changes by File/Area

| Area | What Changes | New Files |
|---|---|---|
| `hub-api/` | New standalone FastAPI service | All files in Phase 1 |
| Gateway Caddyfile | Add `X-Service: hub-api` route | — |
| Hub connector Caddyfile | Add `:8080` → hub-api routing | — |
| `scripts/fa-setup.sh` | Add registration API call | — |
| Backend `telemetry.py` | New telemetry emitter module | `backend/telemetry.py` |
| Backend `permissions.py` | New permissions cache module | `backend/permissions.py` |
| Backend `main.py` | Initialize telemetry + permissions on startup | — |
| Backend deploy/demo handlers | Add `emit_event()` calls | — |
| Frontend Zustand store | New `hubStore.ts` for permissions | `store/hubStore.ts` |
| Frontend UI components | Conditional rendering based on permissions | — |
| `scripts/hub-status.sh` | Add Hub API health/stats section | — |
| `minio-gcp.sh` (or new script) | Deploy Hub API container to VM | — |

---

## Implementation Order

**Do phases sequentially. Each phase must pass its validation before the next begins.**

1. **Phase 0** — Investigate (understand current state)
2. **Phase 1** — Hub API service (standalone, testable locally)
3. **Phase 2** — Gateway routing (connect it to the infrastructure)
4. **Phase 3** — FA registration (fa-setup.sh integration)
5. **Phase 4** — Telemetry emitter (local backend sends events)
6. **Phase 5** — Permission enforcement (frontend + backend)
7. **Phase 6** — Deploy to GCP VM (production)
8. **Phase 7** — Hub status integration (operational visibility)
