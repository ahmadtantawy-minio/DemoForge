# Claude Code — Field Architect Identity via Git Email

## Context

DemoForge has no concept of "who is this user." Templates are saved without attribution, all FAs share one API key, and there's no way to filter "my templates" from "team templates." This instruction adds FA identity using `git config user.email` — zero extra accounts, zero passwords, zero setup beyond what FAs already have.

**Current state (confirmed from codebase snapshot 2026-03-31):**
- No `FA_ID`, `FA_EMAIL`, or identity env vars exist anywhere
- `scripts/fa-setup.sh` exists — handles FA onboarding (hub-connector, .env.local, image pulls)
- `demoforge.sh` is the main task runner — sources `.env.hub` then `.env.local` before `docker compose up`
- Template save-from-demo, fork, override, publish all implemented but save without FA attribution
- `user-templates/` is flat (no per-FA subdirectories) — 0 user templates currently
- Backend runs in Docker container — cannot call `git config` directly
- The template override system writes SHA-256 backed manifests to `data/template-backups/`

## Pre-work: Read before writing

```
scripts/fa-setup.sh              # FA onboarding — WILL BE UPDATED
demoforge.sh                     # Main task runner — WILL BE UPDATED
docker-compose.yml               # Env vars to backend — WILL BE UPDATED
backend/app/api/templates.py     # Template CRUD — WILL BE UPDATED
backend/app/api/demos.py         # Demo CRUD — check for save points
backend/app/engine/template_sync.py  # Sync engine — minor update
backend/app/main.py              # App startup — WILL BE UPDATED
frontend/src/stores/demoStore.ts # Zustand store — WILL BE UPDATED
frontend/src/api/client.ts       # API client — WILL BE UPDATED
frontend/src/components/templates/TemplateGallery.tsx  # Gallery — WILL BE UPDATED
```

Read all files before making changes. Match existing patterns exactly.

---

## How it works

```
Host machine (fa-setup.sh)
  → reads: git config user.email
  → fallback: prompts FA to type email
  → FAILS if neither works (can't proceed without identity)
  → writes: DEMOFORGE_FA_ID=ahmad@minio.io to .env.local

demoforge.sh (start command)
  → sources .env.hub then .env.local
  → FA mode: REFUSES to start if DEMOFORGE_FA_ID is empty
  → Dev mode: no check (backend falls back to "dev@localhost")
  → passes DEMOFORGE_FA_ID through docker compose env

Backend container
  → reads DEMOFORGE_FA_ID from os.environ
  → Dev mode fallback: "dev@localhost" if empty
  → Attaches FA_ID to: save-from-demo, fork, override, publish
  → Exposes GET /api/identity for frontend
  → Supports ?mine=true filter on GET /api/templates
```

---

## Task 1: Update `scripts/fa-setup.sh` — read git email

### 1A. Add identity detection

Find the section where `.env.local` is generated. Insert FA identity detection BEFORE the `.env.local` write block:

```bash
# ─── Detect FA identity ──────────────────────────────────────────────
log "Detecting FA identity..."

FA_EMAIL=""

# Try git config (FAs have this configured for repo access)
if command -v git &>/dev/null; then
    FA_EMAIL=$(git config user.email 2>/dev/null || echo "")
fi

# Fallback: prompt
if [[ -z "$FA_EMAIL" ]]; then
    warn "Could not detect git email (git config user.email is empty)."
    echo ""
    echo -e "  ${CYAN}DemoForge identifies you by email to scope your templates and customizations.${NC}"
    echo -e "  ${CYAN}This is typically your work email — the same one used for git commits.${NC}"
    echo ""
    read -rp "  Your email: " FA_EMAIL
    echo ""
fi

# Hard fail if still empty
if [[ -z "$FA_EMAIL" ]]; then
    err "FA identity is required to use DemoForge."
    err "  Option 1: git config --global user.email \"you@company.com\""
    err "  Option 2: Re-run 'make fa-setup' and enter your email when prompted"
    exit 1
fi

# Basic email format validation
if [[ ! "$FA_EMAIL" =~ ^[^@]+@[^@]+\.[^@]+$ ]]; then
    err "Invalid email format: ${FA_EMAIL}"
    err "  Fix: git config --global user.email \"you@company.com\""
    exit 1
fi

log "  ✓ FA identity: ${FA_EMAIL}"
```

### 1B. Include FA_ID in .env.local

Add `DEMOFORGE_FA_ID` as the FIRST line in the `.env.local` generation block. Find the existing `cat > "$PROJECT_ROOT/.env.local"` and ensure it includes:

```bash
DEMOFORGE_FA_ID=${FA_EMAIL}
```

If the `.env.local` block already exists, add this line at the top — do NOT duplicate the other existing variables.

### 1C. Show identity in setup summary

In the final summary output block, add a line:

```bash
echo -e "  FA identity: ${CYAN}${FA_EMAIL}${NC}"
```

---

## Task 2: Update `demoforge.sh` — startup identity check

### 2A. Add check to start command

Find the `start)` case handler (or wherever `docker compose up` is called for FA mode). Add AFTER the `.env.hub` / `.env.local` sourcing and BEFORE `docker compose up`:

```bash
# ── FA identity check (FA mode only) ──
if [[ "${DEMOFORGE_MODE:-fa}" != "dev" ]]; then
    if [[ -z "${DEMOFORGE_FA_ID:-}" ]]; then
        echo -e "${RED}✗ FA identity not configured.${NC}"
        echo -e "  Run: ${CYAN}make fa-setup${NC}"
        echo -e "  Or add manually: ${CYAN}echo 'DEMOFORGE_FA_ID=you@company.com' >> .env.local${NC}"
        exit 1
    fi
    echo -e "  FA: ${CYAN}${DEMOFORGE_FA_ID}${NC}"
fi
```

### 2B. Do NOT add this check to dev:be or dev:fe commands

Dev mode must work without FA identity. The backend's own fallback handles this.

---

## Task 3: Update `docker-compose.yml`

Add to the backend service `environment` list, alongside the other `DEMOFORGE_*` variables:

```yaml
- DEMOFORGE_FA_ID=${DEMOFORGE_FA_ID:-}
- DEMOFORGE_MODE=${DEMOFORGE_MODE:-fa}
```

If `DEMOFORGE_MODE` is already passed, only add the `DEMOFORGE_FA_ID` line.

---

## Task 4: Backend — FA identity module

### 4A. Create `backend/app/fa_identity.py`

```python
"""
Field Architect identity — reads FA_ID from environment.

FA mode: DEMOFORGE_FA_ID must be set (enforced by demoforge.sh on host).
Dev mode: falls back to "dev@localhost".
"""

import os
import logging

logger = logging.getLogger("demoforge.fa_identity")

_fa_id: str = ""


def init_fa_identity():
    """Initialize FA identity from environment. Called once at startup."""
    global _fa_id
    _fa_id = os.environ.get("DEMOFORGE_FA_ID", "").strip()
    mode = os.environ.get("DEMOFORGE_MODE", "fa")

    if _fa_id:
        logger.info(f"FA identity: {_fa_id}")
    elif mode == "dev":
        _fa_id = "dev@localhost"
        logger.info(f"Dev mode — fallback identity: {_fa_id}")
    else:
        logger.warning("DEMOFORGE_FA_ID not set. Template attribution disabled.")
        _fa_id = ""


def get_fa_id() -> str:
    """Get the current FA identity. Empty string if not configured."""
    return _fa_id
```

### 4B. Initialize at startup

In `backend/app/main.py`, inside the lifespan function, add BEFORE template sync:

```python
from app.fa_identity import init_fa_identity
init_fa_identity()
```

### 4C. Add identity endpoint

Add to `backend/app/api/templates.py` (or create `backend/app/api/identity.py` and register it):

```python
from app.fa_identity import get_fa_id

@router.get("/api/identity")
async def get_identity():
    fa_id = get_fa_id()
    return {
        "fa_id": fa_id,
        "identified": bool(fa_id),
        "mode": os.environ.get("DEMOFORGE_MODE", "fa"),
    }
```

---

## Task 5: Backend — attach FA_ID to template write operations

### 5A. save-from-demo

Find `POST /api/templates/save-from-demo` in `templates.py`. In the `_template` metadata dict construction, add:

```python
from app.fa_identity import get_fa_id

# Add these fields to template_meta:
"saved_by": get_fa_id(),
```

The `saved_at` field likely already exists. If not, add it too.

### 5B. fork

Find `POST /api/templates/{id}/fork`. Where metadata is updated before writing, add:

```python
meta["forked_by"] = get_fa_id()
```

### 5C. override

Find `POST /api/templates/{id}/override`. In the override metadata (likely in the manifest or in the template meta), add:

```python
"overridden_by": get_fa_id()
```

Look at how the override manifest (`data/template-backups/.override-manifest.json`) is structured and add the FA identity to the override record entry — not the template YAML itself.

### 5D. publish

Find `POST /api/templates/{id}/publish`. If metadata is updated before uploading to the hub, add:

```python
meta["published_by"] = get_fa_id()
```

### 5E. Update template summary

In `_template_summary()`, add `saved_by` to the returned dict so the frontend can filter and display it:

```python
summary = {
    # ... existing fields ...
    "saved_by": meta.get("saved_by", ""),
}
```

---

## Task 6: Backend — template list filtering

Update `GET /api/templates` to accept a filter parameter:

```python
@router.get("/api/templates")
async def list_templates(mine: bool = False):
    from app.fa_identity import get_fa_id

    templates = []
    for template_id, source, raw in _discover_all_templates():
        summary = _template_summary(f"{template_id}.yaml", raw, source=source)

        if mine:
            current_fa = get_fa_id()
            if not current_fa or summary.get("saved_by") != current_fa:
                continue

        templates.append(summary)
    return {"templates": templates}
```

This adds `?mine=true` filtering. Builtin and synced templates have no `saved_by` so they're excluded from `?mine=true` results. All templates still appear in the default unfiltered list.

---

## Task 7: Frontend — identity in UI

### 7A. API client

In `frontend/src/api/client.ts`, add:

```typescript
export const fetchIdentity = () =>
  apiFetch<{ fa_id: string; identified: boolean; mode: string }>("/api/identity");
```

### 7B. Zustand store

In `frontend/src/stores/demoStore.ts`, add to the state interface:

```typescript
faId: string;
faIdentified: boolean;
setFaIdentity: (id: string, identified: boolean) => void;
```

And in the store creation:

```typescript
faId: "",
faIdentified: false,
setFaIdentity: (id, identified) => set({ faId: id, faIdentified: identified }),
```

### 7C. Fetch on startup

In `App.tsx` (or wherever initial API calls happen), add to the mount effect:

```typescript
fetchIdentity().then(({ fa_id, identified }) => {
  useDemoStore.getState().setFaIdentity(fa_id, identified);
}).catch(() => {});
```

### 7D. TemplateGallery — "My templates" filter

Find the tab logic. When "My Templates" tab is active, either:

**Option A** — filter client-side (simpler, if templates are already loaded):
```typescript
const filtered = activeTier === "my-templates"
  ? templates.filter(t => t.saved_by === faId)
  : templates.filter(t => /* existing tier filter */);
```

**Option B** — fetch with server-side filter:
```typescript
const url = activeTier === "my-templates"
  ? "/api/templates?mine=true"
  : "/api/templates";
```

Match whichever pattern the existing tab filtering uses.

### 7E. Show FA identity in the header

Add a small identity indicator somewhere in the existing toolbar or sidebar:

```tsx
{faIdentified && (
  <span className="text-[11px] text-muted-foreground/60 truncate max-w-[200px]">
    {faId}
  </span>
)}
```

Keep it minimal — one line of text, low contrast, doesn't compete with the main UI.

### 7F. Template card attribution

On user-template cards where `saved_by` exists and differs from the current FA:

```tsx
{template.source === "user" && template.saved_by && template.saved_by !== faId && (
  <span className="text-[10px] text-muted-foreground/50">
    by {template.saved_by.split("@")[0]}
  </span>
)}
```

### 7G. Update TypeScript types

In `frontend/src/types/index.ts`, add to `DemoTemplate`:

```typescript
saved_by?: string;
```

---

## Task 8: Update SaveAsTemplateDialog

Find the save-as-template dialog. The backend attaches `saved_by` server-side (via `get_fa_id()`), so the frontend doesn't need to send it. But show it as confirmation in the dialog:

```tsx
{faIdentified && (
  <p className="text-xs text-muted-foreground mt-3">
    Template will be saved as {faId}
  </p>
)}
```

---

## Task 9: Validation

### Unit tests (pytest)

```python
def test_fa_identity_from_env(monkeypatch):
    monkeypatch.setenv("DEMOFORGE_FA_ID", "test@minio.io")
    monkeypatch.setenv("DEMOFORGE_MODE", "fa")
    from app.fa_identity import init_fa_identity, get_fa_id
    init_fa_identity()
    assert get_fa_id() == "test@minio.io"


def test_fa_identity_dev_fallback(monkeypatch):
    monkeypatch.delenv("DEMOFORGE_FA_ID", raising=False)
    monkeypatch.setenv("DEMOFORGE_MODE", "dev")
    from app.fa_identity import init_fa_identity, get_fa_id
    init_fa_identity()
    assert get_fa_id() == "dev@localhost"


def test_fa_identity_missing_fa_mode(monkeypatch):
    monkeypatch.delenv("DEMOFORGE_FA_ID", raising=False)
    monkeypatch.setenv("DEMOFORGE_MODE", "fa")
    from app.fa_identity import init_fa_identity, get_fa_id
    init_fa_identity()
    assert get_fa_id() == ""


def test_save_template_attribution(client, monkeypatch):
    """Saved templates include the FA identity."""
    monkeypatch.setenv("DEMOFORGE_FA_ID", "ahmad@minio.io")
    from app.fa_identity import init_fa_identity
    init_fa_identity()
    # ... create demo, then save-from-demo ...
    # Verify _template.saved_by == "ahmad@minio.io" in the written YAML


def test_list_templates_mine_filter(client, monkeypatch):
    """?mine=true returns only current FA's templates."""
    monkeypatch.setenv("DEMOFORGE_FA_ID", "ahmad@minio.io")
    from app.fa_identity import init_fa_identity
    init_fa_identity()
    resp = client.get("/api/templates?mine=true")
    for t in resp.json()["templates"]:
        if t["source"] == "user":
            assert t["saved_by"] == "ahmad@minio.io"


def test_identity_endpoint(client, monkeypatch):
    monkeypatch.setenv("DEMOFORGE_FA_ID", "test@minio.io")
    monkeypatch.setenv("DEMOFORGE_MODE", "fa")
    from app.fa_identity import init_fa_identity
    init_fa_identity()
    resp = client.get("/api/identity")
    assert resp.json()["fa_id"] == "test@minio.io"
    assert resp.json()["identified"] is True
```

### Playwright E2E

**Test: Start fails without FA identity**
```
1. Ensure DEMOFORGE_FA_ID is NOT in .env.local
2. Run make start
3. Verify exit code is non-zero
4. Verify stderr contains "FA identity not configured"
```

**Test: FA identity shown in UI**
```
1. Set DEMOFORGE_FA_ID=playwright@test.io in .env.local
2. Start DemoForge
3. Verify the email appears in the header/sidebar
```

**Test: Saved template has attribution**
```
1. Set DEMOFORGE_FA_ID=playwright@test.io
2. Create demo from template, save as "E2E test template"
3. GET /api/templates → find the saved template
4. Verify saved_by === "playwright@test.io"
5. Navigate to My Templates tab → verify it appears there
```

---

## What NOT to do

- Do NOT create a user database, auth system, or login page
- Do NOT create per-FA subdirectories under `user-templates/` — keep it flat, scope via `saved_by` metadata
- Do NOT block dev mode (`make dev`, `dev:be`, `dev:fe`) on missing FA identity
- Do NOT send FA_ID from frontend to backend on template save — backend reads its own env
- Do NOT add `saved_by` to builtin or synced templates
- Do NOT modify the sync engine to filter by FA — synced templates are shared across all FAs
- Do NOT change the hub API key to be per-FA in this task (that's a future enhancement)

---

## Build order

1. **Task 4** — `fa_identity.py` + init in `main.py` + `/api/identity` endpoint
2. **Task 3** — `docker-compose.yml` env var
3. **Task 5** — Attach FA_ID to all template write operations + summary
4. **Task 6** — `?mine=true` list filter
5. **Task 2** — `demoforge.sh` startup check
6. **Task 1** — `fa-setup.sh` git email detection
7. **Task 7** — Frontend: store, API, gallery, identity display
8. **Task 8** — Save dialog attribution display
9. **Task 9** — Tests

After Task 4, verify: `curl http://localhost:9210/api/identity`
After Task 6, verify: `curl "http://localhost:9210/api/templates?mine=true"`
After Task 1, verify: `make fa-setup` detects your git email
After Task 5, verify: save a template, check the YAML for `saved_by` field
