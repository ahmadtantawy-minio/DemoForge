# Claude Code — Template Management: Save-as-Template, Centralized Sync, Local Fallback

## Context

DemoForge is an existing platform. Read the codebase before making changes. This instruction adds three capabilities:

1. **Save as Template** — take a running/modified demo and save it as a reusable template
2. **Centralized template sync** — pull templates from a shared MinIO instance (`http://34.18.90.197:9000`)
3. **Local fallback** — built-in templates always available offline; user-saved templates persist locally
4. **Hub setup automation** — scripts to bootstrap the remote MinIO bucket, IAM, and seed templates

## Pre-work: Read before writing

Before any code changes, read these files to understand existing patterns:

```
backend/app/api/templates.py        # Template loading, listing, PATCH endpoint
backend/app/api/demos.py            # Demo CRUD, save_diagram, export/import
backend/app/models/demo.py          # DemoDefinition, DemoNode, DemoEdge, etc.
backend/app/engine/docker_manager.py  # Deploy flow
frontend/src/api/client.ts          # API client functions
frontend/src/stores/diagramStore.ts # Zustand diagram state
frontend/src/stores/demoStore.ts    # Zustand demo state
frontend/src/components/templates/TemplateGallery.tsx  # Gallery UI
frontend/src/types/index.ts         # DemoTemplate, DemoTemplateDetail types
docker-compose.yml                  # Volume mounts
```

---

## Architecture: Three-Tier Template Sources

Templates come from three places, merged at query time with this priority (higher wins on ID collision):

```
Priority 1 (highest):  user-templates/      — SE-saved templates, read-write
Priority 2:            synced-templates/     — pulled from remote MinIO, read-only locally
Priority 3 (lowest):   demo-templates/       — built-in, ships with repo, read-only
```

When listing templates, the backend scans all three directories. If the same template ID exists in multiple, the highest-priority version wins. Each template carries a `source` field in the API response: `"builtin"`, `"synced"`, or `"user"`.

### Directory layout

```
DemoForge/
├── demo-templates/          # Built-in (existing, unchanged, :ro mount)
├── user-templates/          # NEW — SE-saved templates (:rw mount)
├── synced-templates/        # NEW — pulled from remote MinIO (:rw mount)
├── demos/                   # Existing — running/stopped demo instances
└── ...
```

---

## Task 0: Hub MinIO Setup — Automation Scripts

These scripts bootstrap the remote MinIO instance at `http://34.18.90.197`. They are idempotent — safe to run multiple times.

### 0A. Create `scripts/hub-setup.sh`

This is the main setup script. It creates the bucket, IAM policy, service account, and seeds templates. Requires `mc` (MinIO Client) installed locally.

```bash
#!/usr/bin/env bash
set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────
HUB_ENDPOINT="${DEMOFORGE_HUB_ENDPOINT:-http://34.18.90.197:9000}"
HUB_CONSOLE="${DEMOFORGE_HUB_CONSOLE:-http://34.18.90.197:9001}"
HUB_ALIAS="demoforge-hub"
HUB_BUCKET="demoforge-templates"
HUB_PREFIX="templates"

# Service account for DemoForge sync
SVC_USER="demoforge-sync"
SVC_POLICY="demoforge-sync-policy"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATES_DIR="$PROJECT_ROOT/demo-templates"
ENV_FILE="$PROJECT_ROOT/.env.hub"
POLICY_FILE="$SCRIPT_DIR/hub-sync-policy.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[hub-setup]${NC} $*"; }
warn() { echo -e "${YELLOW}[hub-setup]${NC} $*"; }
err()  { echo -e "${RED}[hub-setup]${NC} $*" >&2; }

# ─── Pre-flight checks ──────────────────────────────────────────────
if ! command -v mc &>/dev/null; then
    err "MinIO Client (mc) is not installed."
    err "Install: brew install minio/stable/mc  OR  https://min.io/docs/minio/linux/reference/minio-mc.html"
    exit 1
fi

# ─── Step 1: Configure mc alias ─────────────────────────────────────
log "Step 1/6: Configuring mc alias '${HUB_ALIAS}'"

if mc alias list "${HUB_ALIAS}" &>/dev/null 2>&1; then
    log "  Alias '${HUB_ALIAS}' already exists. Verifying connectivity..."
    if mc admin info "${HUB_ALIAS}" &>/dev/null 2>&1; then
        log "  ✓ Connected to ${HUB_ENDPOINT}"
    else
        warn "  Alias exists but connection failed. Re-configuring..."
        echo ""
        echo -e "${CYAN}Enter root credentials for ${HUB_ENDPOINT}:${NC}"
        read -rp "  Access Key (root user): " ROOT_USER
        read -rsp "  Secret Key (root pass): " ROOT_PASS
        echo ""
        mc alias set "${HUB_ALIAS}" "${HUB_ENDPOINT}" "${ROOT_USER}" "${ROOT_PASS}"
    fi
else
    echo ""
    echo -e "${CYAN}First-time setup. Enter root credentials for ${HUB_ENDPOINT}:${NC}"
    echo -e "${CYAN}(Console: ${HUB_CONSOLE})${NC}"
    read -rp "  Access Key (root user): " ROOT_USER
    read -rsp "  Secret Key (root pass): " ROOT_PASS
    echo ""
    mc alias set "${HUB_ALIAS}" "${HUB_ENDPOINT}" "${ROOT_USER}" "${ROOT_PASS}"
fi

# Verify connection
if ! mc admin info "${HUB_ALIAS}" &>/dev/null 2>&1; then
    err "Cannot connect to ${HUB_ENDPOINT}. Check credentials and network."
    exit 1
fi
log "  ✓ Connected to MinIO"

# ─── Step 2: Create bucket ──────────────────────────────────────────
log "Step 2/6: Creating bucket '${HUB_BUCKET}'"

if mc ls "${HUB_ALIAS}/${HUB_BUCKET}" &>/dev/null 2>&1; then
    log "  ✓ Bucket '${HUB_BUCKET}' already exists"
else
    mc mb "${HUB_ALIAS}/${HUB_BUCKET}"
    log "  ✓ Created bucket '${HUB_BUCKET}'"
fi

# Enable versioning for safety
mc version enable "${HUB_ALIAS}/${HUB_BUCKET}" 2>/dev/null || true
log "  ✓ Versioning enabled"

# ─── Step 3: Create IAM policy ──────────────────────────────────────
log "Step 3/6: Creating IAM policy '${SVC_POLICY}'"

cat > "${POLICY_FILE}" << POLICY_EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning"
      ],
      "Resource": [
        "arn:aws:s3:::${HUB_BUCKET}",
        "arn:aws:s3:::${HUB_BUCKET}/*"
      ]
    }
  ]
}
POLICY_EOF

# Create or update policy
mc admin policy create "${HUB_ALIAS}" "${SVC_POLICY}" "${POLICY_FILE}" 2>/dev/null \
  || mc admin policy create "${HUB_ALIAS}" "${SVC_POLICY}" "${POLICY_FILE}"
log "  ✓ Policy '${SVC_POLICY}' created/updated"

# ─── Step 4: Create service account ─────────────────────────────────
log "Step 4/6: Creating service account '${SVC_USER}'"

SVC_PASS=""
if mc admin user info "${HUB_ALIAS}" "${SVC_USER}" &>/dev/null 2>&1; then
    log "  User '${SVC_USER}' already exists"
    warn "  To reset password: mc admin user remove ${HUB_ALIAS} ${SVC_USER}"
    echo ""
    read -rsp "  Enter existing password for '${SVC_USER}' (Enter to regenerate): " SVC_PASS
    echo ""
    if [[ -z "$SVC_PASS" ]]; then
        mc admin user remove "${HUB_ALIAS}" "${SVC_USER}" 2>/dev/null || true
        mc admin policy detach "${HUB_ALIAS}" "${SVC_POLICY}" --user "${SVC_USER}" 2>/dev/null || true
        SVC_PASS="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
        mc admin user add "${HUB_ALIAS}" "${SVC_USER}" "${SVC_PASS}"
        log "  ✓ Recreated user with new password"
    fi
else
    SVC_PASS="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
    mc admin user add "${HUB_ALIAS}" "${SVC_USER}" "${SVC_PASS}"
    log "  ✓ Created user '${SVC_USER}'"
fi

mc admin policy attach "${HUB_ALIAS}" "${SVC_POLICY}" --user "${SVC_USER}" 2>/dev/null || true
log "  ✓ Policy attached to '${SVC_USER}'"

# ─── Step 5: Seed templates ─────────────────────────────────────────
log "Step 5/6: Seeding templates from ${TEMPLATES_DIR}"

if [[ ! -d "$TEMPLATES_DIR" ]]; then
    err "Templates directory not found: $TEMPLATES_DIR"
    exit 1
fi

TEMPLATE_COUNT=$(find "$TEMPLATES_DIR" -name "*.yaml" -type f | wc -l | tr -d ' ')
if [[ "$TEMPLATE_COUNT" -eq 0 ]]; then
    warn "  No .yaml files found in $TEMPLATES_DIR"
else
    mc mirror --overwrite --remove "$TEMPLATES_DIR/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" \
      --exclude ".*" 2>/dev/null || \
    mc cp --recursive "$TEMPLATES_DIR/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"
    log "  ✓ Seeded ${TEMPLATE_COUNT} templates"
fi

REMOTE_COUNT=$(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | grep -c "\.yaml" || echo "0")
log "  ✓ Remote has ${REMOTE_COUNT} templates"

# ─── Step 6: Generate .env.hub ───────────────────────────────────────
log "Step 6/6: Generating ${ENV_FILE}"

cat > "${ENV_FILE}" << ENV_EOF
# DemoForge Hub — Template Sync Configuration
# Generated by hub-setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Copy to .env.local:  cp .env.hub .env.local
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=${HUB_ENDPOINT}
DEMOFORGE_SYNC_BUCKET=${HUB_BUCKET}
DEMOFORGE_SYNC_PREFIX=${HUB_PREFIX}/
DEMOFORGE_SYNC_ACCESS_KEY=${SVC_USER}
DEMOFORGE_SYNC_SECRET_KEY=${SVC_PASS}
ENV_EOF

chmod 600 "${ENV_FILE}"

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Hub setup complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Endpoint:        ${CYAN}${HUB_ENDPOINT}${NC}"
echo -e "  Console:         ${CYAN}${HUB_CONSOLE}${NC}"
echo -e "  Bucket:          ${CYAN}${HUB_BUCKET}/${HUB_PREFIX}/${NC}"
echo -e "  Service account: ${CYAN}${SVC_USER}${NC}"
echo -e "  Templates:       ${CYAN}${REMOTE_COUNT} synced${NC}"
echo ""
echo -e "  Credentials saved to: ${CYAN}${ENV_FILE}${NC}"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "    1. cp .env.hub .env.local"
echo -e "    2. make start   (or docker compose up -d)"
echo -e "    3. Templates will sync on startup"
echo ""
```

### 0B. Create `scripts/hub-seed.sh`

Lightweight re-seed script — pushes current built-in templates to the hub without touching IAM. Run this after adding or modifying templates in `demo-templates/`.

```bash
#!/usr/bin/env bash
set -euo pipefail

HUB_ALIAS="demoforge-hub"
HUB_BUCKET="demoforge-templates"
HUB_PREFIX="templates"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$(dirname "$SCRIPT_DIR")/demo-templates"

GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[hub-seed]${NC} $*"; }

if ! mc admin info "${HUB_ALIAS}" &>/dev/null 2>&1; then
    echo "Hub alias '${HUB_ALIAS}' not configured. Run hub-setup.sh first."
    exit 1
fi

log "Syncing templates to ${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"

mc mirror --overwrite --remove "${TEMPLATES_DIR}/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" \
  --exclude ".*" 2>/dev/null || \
mc cp --recursive "${TEMPLATES_DIR}/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"

REMOTE_COUNT=$(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | grep -c "\.yaml" || echo "0")
log "✓ ${REMOTE_COUNT} templates on hub"
```

### 0C. Create `scripts/hub-status.sh`

Quick status check — local vs remote template counts, sync config state.

```bash
#!/usr/bin/env bash
set -euo pipefail

HUB_ALIAS="demoforge-hub"
HUB_BUCKET="demoforge-templates"
HUB_PREFIX="templates"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}═══ DemoForge Hub Status ═══${NC}"
echo ""

BUILTIN=$(find "$PROJECT_ROOT/demo-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')
USER=$(find "$PROJECT_ROOT/user-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')
SYNCED=$(find "$PROJECT_ROOT/synced-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')

echo -e "  Local templates:"
echo -e "    Built-in:  ${GREEN}${BUILTIN}${NC}"
echo -e "    User:      ${GREEN}${USER}${NC}"
echo -e "    Synced:    ${GREEN}${SYNCED}${NC}"
echo ""

if mc admin info "${HUB_ALIAS}" &>/dev/null 2>&1; then
    REMOTE=$(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | grep -c "\.yaml" || echo "0")
    echo -e "  Remote hub (${HUB_ALIAS}):"
    echo -e "    Templates: ${GREEN}${REMOTE}${NC}"
    echo ""

    echo -e "  ${YELLOW}Remote-only (not in built-in):${NC}"
    comm -23 \
        <(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | awk '{print $NF}' | grep "\.yaml$" | sort) \
        <(ls "$PROJECT_ROOT/demo-templates/"*.yaml 2>/dev/null | xargs -n1 basename | sort) \
      | sed 's/^/    /' || echo "    (none)"

    echo -e "  ${YELLOW}Local-only (not on hub):${NC}"
    comm -13 \
        <(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | awk '{print $NF}' | grep "\.yaml$" | sort) \
        <(ls "$PROJECT_ROOT/demo-templates/"*.yaml 2>/dev/null | xargs -n1 basename | sort) \
      | sed 's/^/    /' || echo "    (none)"
else
    echo -e "  Remote hub: ${YELLOW}not configured${NC} (run scripts/hub-setup.sh)"
fi

echo ""
if [[ -f "$PROJECT_ROOT/.env.hub" ]]; then
    echo -e "  .env.hub:    ${GREEN}exists${NC}"
else
    echo -e "  .env.hub:    ${YELLOW}missing${NC} (run scripts/hub-setup.sh)"
fi
if [[ -f "$PROJECT_ROOT/.env.local" ]]; then
    ENABLED=$(grep "DEMOFORGE_SYNC_ENABLED" "$PROJECT_ROOT/.env.local" 2>/dev/null | grep -c "true" || echo "0")
    if [[ "$ENABLED" -gt 0 ]]; then
        echo -e "  .env.local:  ${GREEN}sync enabled${NC}"
    else
        echo -e "  .env.local:  ${YELLOW}sync disabled${NC}"
    fi
else
    echo -e "  .env.local:  ${YELLOW}missing${NC} (cp .env.hub .env.local)"
fi
echo ""
```

### 0D. Create `scripts/hub-sync-policy.json`

Committed as reference (also generated by `hub-setup.sh`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning"
      ],
      "Resource": [
        "arn:aws:s3:::demoforge-templates",
        "arn:aws:s3:::demoforge-templates/*"
      ]
    }
  ]
}
```

### 0E. Make scripts executable and add Makefile targets

```bash
chmod +x scripts/hub-setup.sh scripts/hub-seed.sh scripts/hub-status.sh
```

Add to `Makefile` (or `demoforge.sh` if that's the project task runner):

```makefile
hub-setup:    ## First-time hub setup: bucket + IAM + seed templates
	@scripts/hub-setup.sh

hub-seed:     ## Re-seed templates to hub after local changes
	@scripts/hub-seed.sh

hub-status:   ## Show local vs remote template counts and sync config
	@scripts/hub-status.sh
```

### 0F. Verification

After running `scripts/hub-setup.sh`:

```bash
# 1. Templates exist on hub
mc ls demoforge-hub/demoforge-templates/templates/ | head -5

# 2. Service account can access the bucket
mc alias set demoforge-verify http://34.18.90.197:9000 demoforge-sync <PASSWORD_FROM_ENV_HUB>
mc ls demoforge-verify/demoforge-templates/templates/ | wc -l

# 3. Service account CANNOT list other buckets or perform admin ops
mc admin info demoforge-verify 2>&1 | grep -i "denied"   # Should show access denied

# 4. .env.hub generated with correct values
cat .env.hub

# 5. Cleanup
mc alias remove demoforge-verify
```

---

## Task 1: Backend — Multi-source template loader

### 1A. Update `backend/app/api/templates.py`

**Replace the single-directory loader with a multi-source loader.**

Add these environment variables (with defaults):

```python
BUILTIN_TEMPLATES_DIR = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
USER_TEMPLATES_DIR = os.environ.get("DEMOFORGE_USER_TEMPLATES_DIR", "./user-templates")
SYNCED_TEMPLATES_DIR = os.environ.get("DEMOFORGE_SYNCED_TEMPLATES_DIR", "./synced-templates")
```

Add a helper that scans all three directories and merges:

```python
# Template source priority: user > synced > builtin
TEMPLATE_SOURCES = [
    ("user", USER_TEMPLATES_DIR),
    ("synced", SYNCED_TEMPLATES_DIR),
    ("builtin", BUILTIN_TEMPLATES_DIR),
]

def _discover_all_templates() -> list[tuple[str, str, dict]]:
    """
    Scan all template directories. Returns list of (template_id, source, raw_dict).
    Higher-priority sources shadow lower-priority ones on ID collision.
    """
    seen_ids: set[str] = set()
    results: list[tuple[str, str, dict]] = []

    for source_name, source_dir in TEMPLATE_SOURCES:
        if not os.path.isdir(source_dir):
            continue
        for fname in sorted(os.listdir(source_dir)):
            if not fname.endswith(".yaml"):
                continue
            template_id = fname.replace(".yaml", "")
            if template_id in seen_ids:
                continue  # Higher-priority source already has this ID
            try:
                path = os.path.join(source_dir, fname)
                with open(path) as f:
                    raw = yaml.safe_load(f)
                if raw:
                    seen_ids.add(template_id)
                    results.append((template_id, source_name, raw))
            except Exception as e:
                logger.warning(f"Failed to load template {fname} from {source_name}: {e}")
    return results
```

**Update `list_templates` endpoint** to use `_discover_all_templates()` and include `source` in each summary:

```python
@router.get("/api/templates")
async def list_templates():
    templates = []
    for template_id, source, raw in _discover_all_templates():
        summary = _template_summary(f"{template_id}.yaml", raw)
        summary["source"] = source  # "builtin" | "synced" | "user"
        templates.append(summary)
    return {"templates": templates}
```

**Update `_load_template_raw`** to search all three directories in priority order:

```python
def _load_template_raw(template_id: str) -> tuple[dict | None, str | None, str | None]:
    """
    Load a template by ID from the highest-priority source.
    Returns (raw_dict, source_name, file_path) or (None, None, None).
    """
    for source_name, source_dir in TEMPLATE_SOURCES:
        path = os.path.join(source_dir, f"{template_id}.yaml")
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(source_dir)):
            continue
        if os.path.exists(path):
            with open(path) as f:
                raw = yaml.safe_load(f)
            return raw, source_name, path
    return None, None, None
```

Update all callers of the old `_load_template_raw` (which returned just `dict | None`) to destructure the new tuple. The template detail endpoint, create-from-template endpoint, and PATCH endpoint all need this.

**Fix the PATCH endpoint** — only allow writes to user-templates, not builtin or synced:

```python
@router.patch("/api/templates/{template_id}")
async def update_template(template_id: str, req: dict):
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    if source != "user":
        raise HTTPException(403, "Only user-saved templates can be edited. Use 'Save as Template' to create an editable copy.")
    # ... existing update logic, but write to USER_TEMPLATES_DIR ...
    out_path = os.path.join(USER_TEMPLATES_DIR, f"{template_id}.yaml")
    with open(out_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)
    return _template_summary(f"{template_id}.yaml", raw)
```

### 1B. Add `source` to the template summary dict

Update `_template_summary` to accept an optional `source` parameter:

```python
def _template_summary(fname: str, raw: dict, source: str = "builtin") -> dict:
    # ... existing logic ...
    summary = {
        # ... existing fields ...
        "source": source,
        "editable": source == "user",
    }
    return summary
```

### 1C. Add `source` to the template detail endpoint

```python
@router.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    detail = _build_template_detail(template_id, raw)
    detail["source"] = source
    detail["editable"] = source == "user"
    return detail
```

---

## Task 2: Backend — Save-as-Template endpoint

### 2A. New endpoint `POST /api/templates/save-from-demo`

Add to `backend/app/api/templates.py`:

```python
class SaveAsTemplateRequest(BaseModel):
    demo_id: str
    template_name: str
    description: str = ""
    tier: str = "advanced"             # "essentials" | "advanced"
    category: str = "general"
    tags: list[str] = []
    objective: str = ""
    minio_value: str = ""
    overwrite: bool = False            # If true, overwrite existing user template with same ID

def _slugify(name: str) -> str:
    """Convert template name to a safe filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug or "custom-template"

@router.post("/api/templates/save-from-demo")
async def save_as_template(req: SaveAsTemplateRequest):
    # 1. Load the demo
    demo_path = os.path.join(DEMOS_DIR, f"{req.demo_id}.yaml")
    if not os.path.exists(demo_path):
        raise HTTPException(404, "Demo not found")
    with open(demo_path) as f:
        demo_raw = yaml.safe_load(f)

    # 2. Generate template ID from name
    template_id = _slugify(req.template_name)

    # 3. Check for collision
    existing_path = os.path.join(USER_TEMPLATES_DIR, f"{template_id}.yaml")
    if os.path.exists(existing_path) and not req.overwrite:
        raise HTTPException(
            409,
            f"A user template with ID '{template_id}' already exists. "
            "Set overwrite=true to replace it, or choose a different name."
        )

    # 4. Build the _template metadata block
    template_meta = {
        "name": req.template_name,
        "tier": req.tier,
        "category": req.category,
        "tags": req.tags,
        "description": req.description,
        "objective": req.objective,
        "minio_value": req.minio_value,
        "estimated_resources": _estimate_resources(demo_raw),
        "external_dependencies": [],
        "walkthrough": [],
        "saved_from_demo": req.demo_id,
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }

    # 5. Build template YAML: _template metadata + demo definition
    template_raw = {"_template": template_meta}

    # Copy all DemoDefinition fields (nodes, edges, clusters, groups, etc.)
    # but reset the ID to a template seed ID
    for key in ["name", "description", "mode", "networks", "nodes", "edges",
                 "groups", "sticky_notes", "annotations", "schematics",
                 "clusters", "resources"]:
        if key in demo_raw:
            template_raw[key] = demo_raw[key]

    template_raw["id"] = f"template-{template_id}"
    template_raw["name"] = req.template_name
    template_raw["description"] = req.description or demo_raw.get("description", "")

    # 6. Ensure user-templates directory exists
    os.makedirs(USER_TEMPLATES_DIR, exist_ok=True)

    # 7. Write
    out_path = os.path.join(USER_TEMPLATES_DIR, f"{template_id}.yaml")
    with open(out_path, "w") as f:
        yaml.dump(template_raw, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Saved template '{template_id}' from demo '{req.demo_id}'")

    return {
        "template_id": template_id,
        "source": "user",
        "message": f"Template '{req.template_name}' saved successfully.",
    }


def _estimate_resources(demo_raw: dict) -> dict:
    """Estimate resource requirements from demo topology."""
    node_count = len(demo_raw.get("nodes", []))
    cluster_containers = sum(
        c.get("node_count", 0) for c in demo_raw.get("clusters", [])
    )
    total_containers = node_count + cluster_containers
    # Rough estimate: 512MB per container average
    est_memory_gb = max(1, round(total_containers * 0.5))
    return {
        "memory": f"{est_memory_gb}GB",
        "cpu": max(1, total_containers // 2),
        "containers": total_containers,
    }
```

### 2B. Delete user template endpoint

```python
@router.delete("/api/templates/{template_id}")
async def delete_template(template_id: str):
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    if source != "user":
        raise HTTPException(403, "Only user-saved templates can be deleted.")
    os.remove(path)
    logger.info(f"Deleted user template '{template_id}'")
    return {"deleted": template_id}
```

### 2C. Duplicate (fork) a builtin/synced template into user-templates

```python
@router.post("/api/templates/{template_id}/fork")
async def fork_template(template_id: str, req: dict = Body(default={})):
    """Copy a builtin or synced template into user-templates for editing."""
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")

    new_name = req.get("name", raw.get("_template", {}).get("name", template_id) + " (custom)")
    new_id = _slugify(new_name)

    existing = os.path.join(USER_TEMPLATES_DIR, f"{new_id}.yaml")
    if os.path.exists(existing):
        raise HTTPException(409, f"User template '{new_id}' already exists.")

    # Update metadata
    meta = raw.get("_template", {})
    meta["name"] = new_name
    meta["forked_from"] = template_id
    meta["forked_at"] = datetime.utcnow().isoformat() + "Z"
    raw["_template"] = meta
    raw["name"] = new_name
    raw["id"] = f"template-{new_id}"

    os.makedirs(USER_TEMPLATES_DIR, exist_ok=True)
    out_path = os.path.join(USER_TEMPLATES_DIR, f"{new_id}.yaml")
    with open(out_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)

    return {
        "template_id": new_id,
        "source": "user",
        "forked_from": template_id,
    }
```

---

## Task 3: Backend — Remote sync from MinIO/GCS

### 3A. New file `backend/app/engine/template_sync.py`

This module syncs templates from a remote S3-compatible bucket to `synced-templates/`. It runs on startup and can be triggered manually via API.

```python
"""
Template sync — pulls templates from a remote MinIO bucket.

Environment variables:
  DEMOFORGE_SYNC_ENABLED=true|false       (default: false)
  DEMOFORGE_SYNC_ENDPOINT=http://34.18.90.197:9000
  DEMOFORGE_SYNC_BUCKET=demoforge-templates
  DEMOFORGE_SYNC_PREFIX=templates/        (prefix within bucket)
  DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
  DEMOFORGE_SYNC_SECRET_KEY=<from .env.hub>
  DEMOFORGE_SYNC_REGION=us-east-1
  DEMOFORGE_SYNCED_TEMPLATES_DIR=./synced-templates
"""

import os
import json
import logging
import hashlib
from datetime import datetime

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger("demoforge.template_sync")

SYNC_ENABLED = os.environ.get("DEMOFORGE_SYNC_ENABLED", "false").lower() == "true"
SYNC_ENDPOINT = os.environ.get("DEMOFORGE_SYNC_ENDPOINT", "http://34.18.90.197:9000")
SYNC_BUCKET = os.environ.get("DEMOFORGE_SYNC_BUCKET", "demoforge-templates")
SYNC_PREFIX = os.environ.get("DEMOFORGE_SYNC_PREFIX", "templates/")
SYNC_ACCESS_KEY = os.environ.get("DEMOFORGE_SYNC_ACCESS_KEY", "")
SYNC_SECRET_KEY = os.environ.get("DEMOFORGE_SYNC_SECRET_KEY", "")
SYNC_REGION = os.environ.get("DEMOFORGE_SYNC_REGION", "us-east-1")
SYNCED_DIR = os.environ.get("DEMOFORGE_SYNCED_TEMPLATES_DIR", "./synced-templates")

# Local manifest tracking what we've synced (etags for change detection)
SYNC_MANIFEST_PATH = os.path.join(SYNCED_DIR, ".sync-manifest.json")


def _get_s3_client():
    """Create an S3 client for the remote MinIO endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=SYNC_ENDPOINT,
        aws_access_key_id=SYNC_ACCESS_KEY,
        aws_secret_access_key=SYNC_SECRET_KEY,
        region_name=SYNC_REGION,
        config=BotoConfig(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


def _load_manifest() -> dict:
    """Load the local sync manifest (etag per template file)."""
    if os.path.exists(SYNC_MANIFEST_PATH):
        with open(SYNC_MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def _save_manifest(manifest: dict):
    """Save the local sync manifest."""
    with open(SYNC_MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def sync_templates() -> dict:
    """
    Pull templates from remote bucket. Returns summary of changes.
    Only downloads files whose ETag has changed since last sync.
    """
    if not SYNC_ENABLED:
        return {"status": "disabled", "message": "Template sync is not enabled."}

    if not SYNC_ACCESS_KEY or not SYNC_SECRET_KEY:
        return {"status": "error", "message": "Sync credentials not configured. Run scripts/hub-setup.sh and copy .env.hub to .env.local."}

    os.makedirs(SYNCED_DIR, exist_ok=True)
    manifest = _load_manifest()
    s3 = _get_s3_client()

    stats = {"downloaded": 0, "unchanged": 0, "deleted": 0, "errors": 0}
    remote_keys: set[str] = set()

    try:
        # List all .yaml files in the bucket prefix
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=SYNC_BUCKET, Prefix=SYNC_PREFIX):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".yaml"):
                    continue

                # Extract template filename from key
                fname = key.removeprefix(SYNC_PREFIX).lstrip("/")
                if "/" in fname:
                    continue  # Skip nested directories
                if not fname:
                    continue

                remote_keys.add(fname)
                remote_etag = obj.get("ETag", "").strip('"')

                # Check if we already have this version
                if manifest.get(fname, {}).get("etag") == remote_etag:
                    stats["unchanged"] += 1
                    continue

                # Download
                try:
                    local_path = os.path.join(SYNCED_DIR, fname)
                    s3.download_file(SYNC_BUCKET, key, local_path)
                    manifest[fname] = {
                        "etag": remote_etag,
                        "synced_at": datetime.utcnow().isoformat() + "Z",
                        "size": obj.get("Size", 0),
                    }
                    stats["downloaded"] += 1
                    logger.info(f"Synced template: {fname}")
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Failed to download {fname}: {e}")

        # Remove locally synced templates that no longer exist on remote
        for fname in list(manifest.keys()):
            if fname == ".sync-manifest.json":
                continue
            if fname not in remote_keys:
                local_path = os.path.join(SYNCED_DIR, fname)
                if os.path.exists(local_path):
                    os.remove(local_path)
                del manifest[fname]
                stats["deleted"] += 1
                logger.info(f"Removed template no longer on remote: {fname}")

        _save_manifest(manifest)

    except Exception as e:
        logger.error(f"Template sync failed: {e}")
        return {"status": "error", "message": str(e), **stats}

    return {"status": "ok", **stats}


def get_sync_status() -> dict:
    """Return current sync configuration and last sync state."""
    manifest = _load_manifest() if os.path.exists(SYNC_MANIFEST_PATH) else {}
    synced_count = len([k for k in manifest if k != ".sync-manifest.json"])

    return {
        "enabled": SYNC_ENABLED,
        "endpoint": SYNC_ENDPOINT,
        "bucket": SYNC_BUCKET,
        "prefix": SYNC_PREFIX,
        "synced_count": synced_count,
        "last_sync": max(
            (v.get("synced_at", "") for v in manifest.values() if isinstance(v, dict)),
            default=None,
        ),
    }
```

### 3B. Publish user template to remote

Add a publish function that uploads a user-saved template to the remote bucket:

```python
def publish_template(template_id: str) -> dict:
    """Upload a user template to the remote bucket for team sharing."""
    if not SYNC_ENABLED:
        return {"status": "error", "message": "Sync not enabled."}

    local_path = os.path.join(
        os.environ.get("DEMOFORGE_USER_TEMPLATES_DIR", "./user-templates"),
        f"{template_id}.yaml",
    )
    if not os.path.exists(local_path):
        return {"status": "error", "message": f"User template '{template_id}' not found."}

    s3 = _get_s3_client()
    remote_key = f"{SYNC_PREFIX}{template_id}.yaml"

    try:
        s3.upload_file(local_path, SYNC_BUCKET, remote_key)
        logger.info(f"Published template '{template_id}' to {SYNC_BUCKET}/{remote_key}")
        return {"status": "ok", "template_id": template_id, "remote_key": remote_key}
    except Exception as e:
        logger.error(f"Failed to publish template: {e}")
        return {"status": "error", "message": str(e)}
```

### 3C. Sync API endpoints

Add to `backend/app/api/templates.py`:

```python
from app.engine.template_sync import sync_templates, get_sync_status, publish_template

@router.post("/api/templates/sync")
async def trigger_sync():
    """Manually trigger template sync from remote."""
    result = sync_templates()
    return result

@router.get("/api/templates/sync/status")
async def sync_status():
    """Get sync configuration and state."""
    return get_sync_status()

@router.post("/api/templates/{template_id}/publish")
async def publish_template_endpoint(template_id: str):
    """Publish a user template to the remote bucket for team sharing."""
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    if source != "user":
        raise HTTPException(403, "Only user-saved templates can be published.")
    result = publish_template(template_id)
    if result["status"] == "error":
        raise HTTPException(500, result["message"])
    return result
```

### 3D. Run sync on startup

In `backend/app/main.py`, add sync to the lifespan:

```python
from app.engine.template_sync import sync_templates, SYNC_ENABLED

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup logic ...

    # Sync templates from remote (non-blocking, best-effort)
    if SYNC_ENABLED:
        try:
            result = sync_templates()
            logger.info(f"Template sync on startup: {result}")
        except Exception as e:
            logger.warning(f"Template sync failed on startup (continuing with local): {e}")

    yield

    # ... existing shutdown logic ...
```

### 3E. Add `boto3` to requirements

Add to `backend/requirements.txt`:

```
boto3>=1.34.0
```

---

## Task 4: Docker Compose — mount new directories

Update `docker-compose.yml`:

```yaml
services:
  backend:
    volumes:
      - ./components:/app/components:ro
      - ./demos:/app/demos
      - ./data:/app/data
      - ./demo-templates:/app/demo-templates:ro       # Built-in (existing, unchanged)
      - ./user-templates:/app/user-templates           # NEW — SE-saved templates, rw
      - ./synced-templates:/app/synced-templates        # NEW — remote sync target, rw
    environment:
      - DEMOFORGE_TEMPLATES_DIR=/app/demo-templates
      - DEMOFORGE_USER_TEMPLATES_DIR=/app/user-templates        # NEW
      - DEMOFORGE_SYNCED_TEMPLATES_DIR=/app/synced-templates    # NEW
      # Sync config — enabled via .env.local (generated by scripts/hub-setup.sh)
      - DEMOFORGE_SYNC_ENABLED=${DEMOFORGE_SYNC_ENABLED:-false}
      - DEMOFORGE_SYNC_ENDPOINT=${DEMOFORGE_SYNC_ENDPOINT:-http://34.18.90.197:9000}
      - DEMOFORGE_SYNC_BUCKET=${DEMOFORGE_SYNC_BUCKET:-demoforge-templates}
      - DEMOFORGE_SYNC_PREFIX=${DEMOFORGE_SYNC_PREFIX:-templates/}
      - DEMOFORGE_SYNC_ACCESS_KEY=${DEMOFORGE_SYNC_ACCESS_KEY:-}
      - DEMOFORGE_SYNC_SECRET_KEY=${DEMOFORGE_SYNC_SECRET_KEY:-}
```

Create `.env.local.example` showing what `hub-setup.sh` generates:

```env
# DemoForge Hub — Template Sync Configuration
# Generated by: scripts/hub-setup.sh
# Or copy from .env.hub after running hub-setup.sh:  cp .env.hub .env.local
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=http://34.18.90.197:9000
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=<generated-by-hub-setup>
```

Create empty directories with `.gitkeep`:

```bash
mkdir -p user-templates synced-templates
touch user-templates/.gitkeep synced-templates/.gitkeep
```

Add to `.gitignore`:

```
user-templates/*.yaml
synced-templates/*.yaml
synced-templates/.sync-manifest.json
.env.local
.env.hub
```

---

## Task 5: Frontend — API client additions

Add to `frontend/src/api/client.ts`:

```typescript
// --- Template management ---

export const saveAsTemplate = (payload: {
  demo_id: string;
  template_name: string;
  description?: string;
  tier?: string;
  category?: string;
  tags?: string[];
  objective?: string;
  minio_value?: string;
  overwrite?: boolean;
}) =>
  apiFetch<{ template_id: string; source: string; message: string }>(
    "/api/templates/save-from-demo",
    { method: "POST", body: JSON.stringify(payload) }
  );

export const deleteTemplate = (templateId: string) =>
  apiFetch<{ deleted: string }>(`/api/templates/${templateId}`, {
    method: "DELETE",
  });

export const forkTemplate = (templateId: string, name?: string) =>
  apiFetch<{ template_id: string; source: string; forked_from: string }>(
    `/api/templates/${templateId}/fork`,
    { method: "POST", body: JSON.stringify(name ? { name } : {}) }
  );

export const publishTemplate = (templateId: string) =>
  apiFetch<{ status: string; template_id: string; remote_key: string }>(
    `/api/templates/${templateId}/publish`,
    { method: "POST" }
  );

export const triggerTemplateSync = () =>
  apiFetch<{ status: string; downloaded: number; unchanged: number; deleted: number; errors: number }>(
    "/api/templates/sync",
    { method: "POST" }
  );

export const getTemplateSyncStatus = () =>
  apiFetch<{
    enabled: boolean;
    endpoint: string;
    bucket: string;
    prefix: string;
    synced_count: number;
    last_sync: string | null;
  }>("/api/templates/sync/status");
```

### Update TypeScript types

In `frontend/src/types/index.ts`, update `DemoTemplate`:

```typescript
export interface DemoTemplate {
  // ... existing fields ...
  source: "builtin" | "synced" | "user";
  editable: boolean;
}
```

---

## Task 6: Frontend — "Save as Template" dialog

### 6A. New component `frontend/src/components/templates/SaveAsTemplateDialog.tsx`

A dialog that opens when the user clicks "Save as Template" from the demo toolbar or diagram context menu. It collects the template metadata and calls the API.

```
┌─────────────────────────────────────────────┐
│  Save Demo as Template                   ✕  │
│                                             │
│  Template name *                            │
│  ┌─────────────────────────────────────┐    │
│  │ My Custom Lakehouse                 │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Description                                │
│  ┌─────────────────────────────────────┐    │
│  │ Dual-cluster lakehouse with ...     │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌──────────────┐  ┌──────────────────┐     │
│  │ Tier         │  │ Category         │     │
│  │ [Essentials▾]│  │ [Lakehouse    ▾] │     │
│  └──────────────┘  └──────────────────┘     │
│                                             │
│  Tags                                       │
│  ┌─────────────────────────────────────┐    │
│  │ iceberg, trino, dremio              │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Objective                                  │
│  ┌─────────────────────────────────────┐    │
│  │ Show how MinIO enables...           │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  MinIO value proposition                    │
│  ┌─────────────────────────────────────┐    │
│  │ MinIO provides the unified...       │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌─ Source demo ──────────────────────┐     │
│  │ Demo: lakehouse-ab12 (8 nodes)     │     │
│  │ Modified: 2 hours ago              │     │
│  └────────────────────────────────────┘     │
│                                             │
│             [Cancel]   [Save Template]       │
└─────────────────────────────────────────────┘
```

Implementation notes:
- Use the same shadcn/ui components as existing dialogs (Dialog, Input, Textarea, Select, Button)
- Pre-populate name/description from the demo's current name/description
- Tier dropdown: `essentials` / `advanced` (experience is not selectable — those are hand-authored)
- Category dropdown: same categories used in the gallery filter pills (read from existing templates or hardcode: `infrastructure`, `replication`, `analytics`, `lakehouse`, `ai`, `simulation`, `general`)
- Tags: free-text, comma-separated
- On submit: call `saveAsTemplate()`, show success toast with link to gallery, close dialog
- On 409 conflict: show inline warning "A template with this name already exists" with checkbox "Overwrite existing"
- Disable submit button while saving, show spinner

### 6B. Add "Save as Template" button to the Toolbar

In `frontend/src/components/toolbar/Toolbar.tsx`, add a button next to the existing Deploy/Stop controls. Only show it when a demo is loaded (not in template gallery view):

```typescript
// Inside the toolbar, next to export/import buttons
{activeDemoId && (
  <Button
    variant="outline"
    size="sm"
    onClick={() => setSaveTemplateOpen(true)}
    className="gap-1.5"
  >
    <BookmarkPlus className="h-4 w-4" />
    Save as Template
  </Button>
)}
```

Import the dialog and render it:

```typescript
<SaveAsTemplateDialog
  open={saveTemplateOpen}
  onOpenChange={setSaveTemplateOpen}
  demoId={activeDemoId}
  demoName={activeDemo?.name}
  demoDescription={activeDemo?.description}
  onSaved={(templateId) => {
    toast({ title: "Template saved", description: `Saved as "${templateId}"` });
    setSaveTemplateOpen(false);
  }}
/>
```

---

## Task 7: Frontend — Template gallery enhancements

### 7A. Source badges on template cards

In the TemplateGallery card rendering, add a small badge showing the source:

```typescript
// Inside each template card
<div className="flex items-center gap-1.5">
  {template.source === "user" && (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-medium">
      My Template
    </span>
  )}
  {template.source === "synced" && (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 font-medium">
      Team
    </span>
  )}
  {/* builtin gets no badge — it's the default */}
</div>
```

### 7B. Actions menu per template card

Add a "..." menu (DropdownMenu) on each template card with context-appropriate actions:

| Source   | Available actions                          |
|----------|--------------------------------------------|
| builtin  | Create Demo, Fork as My Template           |
| synced   | Create Demo, Fork as My Template           |
| user     | Create Demo, Edit, Publish to Team, Delete |

"Fork as My Template" calls `forkTemplate()` — creates an editable copy in user-templates.
"Publish to Team" calls `publishTemplate()` — uploads to remote bucket.
"Delete" calls `deleteTemplate()` with a confirmation dialog.
"Edit" opens the existing detail dialog with editable fields.

### 7C. Sync indicator in the gallery header

Add a small sync status indicator in the gallery toolbar area:

```
[Essentials] [Advanced] [Experiences]        🔄 Synced 12 templates · 2 min ago  [Sync Now]
```

- Show only when sync is enabled (`getTemplateSyncStatus()` returns `enabled: true`)
- "Sync Now" button calls `triggerTemplateSync()`, shows spinner while running, refreshes template list on completion
- If sync is disabled, show nothing (not even a disabled indicator — the SE doesn't need to know about sync if it's not configured)

### 7D. "My Templates" filter

Add a fourth tab or toggle to filter templates by source:

```
[Essentials] [Advanced] [Experiences] [My Templates]
```

"My Templates" tab shows only `source === "user"` templates. No tier/category sub-filtering needed — these are the SE's personal collection. Show a prominent "Save as Template" CTA if the list is empty.

---

## Task 8: Validation

### Unit tests (pytest)

**Test multi-source discovery:**

```python
def test_discover_templates_priority(tmp_path):
    """User templates shadow synced, synced shadows builtin."""
    builtin = tmp_path / "builtin"
    synced = tmp_path / "synced"
    user = tmp_path / "user"
    for d in [builtin, synced, user]:
        d.mkdir()

    # Same ID in all three
    for d, tier in [(builtin, "essentials"), (synced, "advanced"), (user, "advanced")]:
        (d / "lakehouse.yaml").write_text(yaml.dump({
            "_template": {"name": f"Lakehouse ({d.name})", "tier": tier, "category": "analytics"},
            "id": "template-lakehouse",
            "name": f"Lakehouse ({d.name})",
            "nodes": [], "edges": [], "clusters": [], "networks": [],
        }))

    # Patch TEMPLATE_SOURCES
    with patch("app.api.templates.TEMPLATE_SOURCES", [
        ("user", str(user)), ("synced", str(synced)), ("builtin", str(builtin))
    ]):
        results = _discover_all_templates()

    assert len(results) == 1
    assert results[0][1] == "user"  # User wins


def test_discover_templates_unique_ids(tmp_path):
    """Templates with different IDs all appear."""
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()

    (builtin / "rag.yaml").write_text(yaml.dump({
        "_template": {"name": "RAG", "tier": "advanced", "category": "ai"},
        "id": "t-rag", "name": "RAG", "nodes": [], "edges": [], "clusters": [], "networks": [],
    }))
    (user / "custom.yaml").write_text(yaml.dump({
        "_template": {"name": "Custom", "tier": "advanced", "category": "general"},
        "id": "t-custom", "name": "Custom", "nodes": [], "edges": [], "clusters": [], "networks": [],
    }))

    with patch("app.api.templates.TEMPLATE_SOURCES", [
        ("user", str(user)), ("synced", "/nonexistent"), ("builtin", str(builtin))
    ]):
        results = _discover_all_templates()

    assert len(results) == 2
    ids = {r[0] for r in results}
    assert ids == {"rag", "custom"}


def test_save_as_template(client, tmp_path):
    """Save a demo as a user template."""
    # Create a demo first
    demos_dir = tmp_path / "demos"
    demos_dir.mkdir()
    (demos_dir / "test-demo.yaml").write_text(yaml.dump({
        "id": "test-demo", "name": "Test Demo", "description": "A test",
        "nodes": [{"id": "minio-1", "component": "minio", "variant": "single", "position": {"x": 0, "y": 0}}],
        "edges": [], "clusters": [], "networks": [{"name": "default"}],
    }))

    user_dir = tmp_path / "user-templates"
    with patch("app.api.templates.DEMOS_DIR", str(demos_dir)), \
         patch("app.api.templates.USER_TEMPLATES_DIR", str(user_dir)):
        resp = client.post("/api/templates/save-from-demo", json={
            "demo_id": "test-demo",
            "template_name": "My Lakehouse Demo",
            "tier": "essentials",
            "category": "lakehouse",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["template_id"] == "my-lakehouse-demo"
    assert data["source"] == "user"

    # Verify file was written
    saved = user_dir / "my-lakehouse-demo.yaml"
    assert saved.exists()
    content = yaml.safe_load(saved.read_text())
    assert content["_template"]["name"] == "My Lakehouse Demo"
    assert content["_template"]["saved_from_demo"] == "test-demo"
    assert content["nodes"][0]["component"] == "minio"


def test_save_as_template_conflict(client, tmp_path):
    """409 on name collision without overwrite flag."""
    demos_dir = tmp_path / "demos"
    user_dir = tmp_path / "user-templates"
    demos_dir.mkdir()
    user_dir.mkdir()
    (demos_dir / "d1.yaml").write_text(yaml.dump({"id": "d1", "name": "D1", "nodes": [], "edges": [], "clusters": [], "networks": []}))
    (user_dir / "my-demo.yaml").write_text("existing: true")

    with patch("app.api.templates.DEMOS_DIR", str(demos_dir)), \
         patch("app.api.templates.USER_TEMPLATES_DIR", str(user_dir)):
        resp = client.post("/api/templates/save-from-demo", json={
            "demo_id": "d1", "template_name": "My Demo",
        })
    assert resp.status_code == 409


def test_delete_user_template(client, tmp_path):
    """Can delete user templates, not builtin."""
    user_dir = tmp_path / "user-templates"
    builtin_dir = tmp_path / "builtin"
    user_dir.mkdir()
    builtin_dir.mkdir()
    (user_dir / "custom.yaml").write_text(yaml.dump({
        "_template": {"name": "Custom"}, "id": "t", "name": "Custom",
        "nodes": [], "edges": [], "clusters": [], "networks": [],
    }))
    (builtin_dir / "builtin-one.yaml").write_text(yaml.dump({
        "_template": {"name": "Builtin"}, "id": "t", "name": "Builtin",
        "nodes": [], "edges": [], "clusters": [], "networks": [],
    }))

    with patch("app.api.templates.TEMPLATE_SOURCES", [
        ("user", str(user_dir)), ("synced", "/nonexistent"), ("builtin", str(builtin_dir))
    ]):
        # Delete user template — should succeed
        resp = client.delete("/api/templates/custom")
        assert resp.status_code == 200

        # Delete builtin — should fail
        resp = client.delete("/api/templates/builtin-one")
        assert resp.status_code == 403


def test_fork_template(client, tmp_path):
    """Fork a builtin template into user-templates."""
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "user-templates"
    builtin_dir.mkdir()
    (builtin_dir / "rag-pipeline.yaml").write_text(yaml.dump({
        "_template": {"name": "RAG Pipeline", "tier": "advanced", "category": "ai"},
        "id": "t-rag", "name": "RAG Pipeline",
        "nodes": [{"id": "n1", "component": "minio"}],
        "edges": [], "clusters": [], "networks": [],
    }))

    with patch("app.api.templates.TEMPLATE_SOURCES", [
        ("user", str(user_dir)), ("synced", "/nonexistent"), ("builtin", str(builtin_dir))
    ]), patch("app.api.templates.USER_TEMPLATES_DIR", str(user_dir)):
        resp = client.post("/api/templates/rag-pipeline/fork", json={"name": "My RAG"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["forked_from"] == "rag-pipeline"
    assert (user_dir / "my-rag.yaml").exists()
```

**Test template sync:**

```python
def test_sync_downloads_new_templates(tmp_path, mock_s3):
    """Sync pulls new templates from remote."""
    synced_dir = tmp_path / "synced"
    synced_dir.mkdir()

    mock_s3.put_object(
        Bucket="hub", Key="templates/new-demo.yaml",
        Body=yaml.dump({"_template": {"name": "New"}, "id": "t", "name": "New", "nodes": []})
    )

    with patch.multiple("app.engine.template_sync",
        SYNC_ENABLED=True, SYNC_ENDPOINT="http://mock",
        SYNC_BUCKET="hub", SYNC_PREFIX="templates/",
        SYNCED_DIR=str(synced_dir), SYNC_MANIFEST_PATH=str(synced_dir / ".manifest.json"),
        _get_s3_client=lambda: mock_s3,
    ):
        result = sync_templates()

    assert result["status"] == "ok"
    assert result["downloaded"] == 1
    assert (synced_dir / "new-demo.yaml").exists()


def test_sync_skips_unchanged(tmp_path, mock_s3):
    """Sync doesn't re-download unchanged templates."""
    # ... pre-populate manifest with matching etag ...
    # ... assert result["unchanged"] == 1, result["downloaded"] == 0 ...


def test_sync_disabled_returns_status():
    """Sync returns disabled status when not configured."""
    with patch("app.engine.template_sync.SYNC_ENABLED", False):
        result = sync_templates()
    assert result["status"] == "disabled"
```

### Playwright E2E tests

**Test: Save as Template flow**

```
1. Navigate to /templates
2. Create a demo from the "bi-dashboard-lakehouse" template
3. Wait for demo to load in the diagram editor
4. Drag a node to verify the demo is modifiable
5. Click "Save as Template" button in the toolbar
6. Verify the SaveAsTemplateDialog opens
7. Fill in: name="My Custom Lakehouse", tier="Advanced", category="lakehouse"
8. Click "Save Template"
9. Verify success toast appears
10. Navigate to /templates
11. Click "My Templates" tab
12. Verify "My Custom Lakehouse" appears with "My Template" badge
13. Verify source badge says "My Template" (blue)
```

**Test: Fork a builtin template**

```
1. Navigate to /templates, Essentials tab
2. Find a builtin template card
3. Click the "..." menu → "Fork as My Template"
4. Verify fork dialog/confirmation appears
5. Confirm fork
6. Navigate to "My Templates" tab
7. Verify forked template appears with "(custom)" suffix
8. Click the forked template → verify it shows "editable: true"
```

**Test: Delete a user template**

```
1. (Pre-condition: a user template exists from previous test or fixture)
2. Navigate to /templates → "My Templates" tab
3. Click "..." menu on the user template → "Delete"
4. Verify confirmation dialog appears
5. Confirm deletion
6. Verify template disappears from list
```

**Test: Source priority — user shadows builtin**

```
1. (Pre-condition: create a user template with same ID as a builtin)
2. Navigate to /templates
3. Verify only ONE template with that ID appears
4. Verify it shows "My Template" badge (user source wins)
```

**Test: Gallery shows sync indicator when enabled**

```
1. (Pre-condition: run scripts/hub-setup.sh, then cp .env.hub .env.local, restart DemoForge)
2. Navigate to /templates
3. Verify sync status indicator appears in gallery header
4. Verify it shows synced count and last sync time
5. Click "Sync Now" button
6. Verify spinner appears during sync
7. Verify template list refreshes after sync
```

**Test: Builtin templates can't be edited or deleted**

```
1. Navigate to /templates, Essentials tab
2. Click a builtin template card → open detail
3. Verify description/objective fields are NOT editable (read-only text, no input fields)
4. Verify "..." menu does NOT show "Delete" or "Edit" options
5. Verify "..." menu DOES show "Fork as My Template"
```

---

## What NOT to do

- Do NOT modify any existing template YAML files in `demo-templates/`
- Do NOT change the existing `create_from_template` endpoint signature or behavior
- Do NOT add a database (SQLite, Postgres, etc.) — file-based storage is intentional
- Do NOT implement user authentication in this task — that's a separate feature
- Do NOT implement the full Hub API — this task covers only the S3 bucket sync
- Do NOT add caching to the template loader — the filesystem scan is fast enough for 30-50 templates, and caching adds staleness risk when files change externally via sync
- Do NOT hardcode MinIO root credentials anywhere — only the scoped `demoforge-sync` service account credentials go into `.env.hub` / `.env.local`
- Do NOT commit `.env.hub` or `.env.local` to git — they contain secrets

---

## Build order

Execute tasks in this order:

1. **Task 0** — Hub MinIO setup scripts (create `scripts/`, run `hub-setup.sh` to bootstrap bucket + IAM + seed)
2. **Task 4** — Docker Compose and directory setup (creates local directories and mounts)
3. **Task 1** — Multi-source backend loader (the foundation everything else builds on)
4. **Task 2** — Save-as-template endpoint + delete + fork
5. **Task 3** — Remote sync module
6. **Task 5** — Frontend API client additions
7. **Task 6** — Save-as-template dialog
8. **Task 7** — Gallery enhancements (source badges, actions menu, sync indicator, My Templates tab)
9. **Task 8** — Run validation tests

After Task 0, verify the hub is live: `make hub-status`. After Task 2, test save-as-template via curl. After Task 5, start DemoForge with `cp .env.hub .env.local && make start` and verify templates sync on startup. After Task 7, the full UI flow works end-to-end.
