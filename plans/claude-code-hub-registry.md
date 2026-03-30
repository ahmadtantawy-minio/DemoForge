# Claude Code — Private Docker Registry + Image Management

## Context

DemoForge has a hub MinIO instance at `http://34.18.90.197` (S3 on `:9000`, Console on `:9001`). The `scripts/hub-setup.sh` script already bootstraps the templates bucket, IAM, and seeding. This instruction:

1. **Investigates** how DemoForge handles Docker images today (Phase 0)
2. **Adds a private Docker registry** (`registry:2`) on the same VM, using MinIO as blob storage (Phases 1-8)

No images ever touch Docker Hub or any public registry. The registry runs on port 5000 of the same VM: `http://34.18.90.197:5000`.

---

## Phase 0: Investigate current image handling

**Do this first. Do NOT start Phase 1 until Phase 0 is complete.** Read the codebase and produce findings inline. These findings determine how you adapt Phases 1-8 to the existing code.

### 0.1 Image Manager page
- Does `frontend/src/pages/ImagesPage.tsx` exist? If yes, read the full source.
- Run: `find frontend/src -name "*image*" -o -name "*Image*" | head -20`
- Run: `find frontend/src -name "*registry*" -o -name "*Registry*" | head -10`
- Is there a route for /images in the app router? Note the routing config.
- What does the Image Manager page currently show? List all functional features.

### 0.2 Backend image endpoints
- Run: `grep -rn "image\|registry\|docker.*pull\|docker.*build" backend/app/api/ --include="*.py" | head -30`
- Is there an `/api/images` router? Read its full source if it exists.
- Any endpoints for checking image availability, pulling, or building?

### 0.3 Component manifests — image fields
- Show image-related fields in 3 component manifests: one vendor (e.g., minio), one custom-build (e.g., inference-sim or data-generator or rag-app), one with `image_size_mb`.
- Run: `grep -rn "image\|build_context\|image_size" components/*/manifest.yaml | head -30`

### 0.4 Compose generator — image handling
- In the compose generator, find how `image` and `build` fields are set per service.
- Is there logic distinguishing "pull from registry" vs "build from Dockerfile"?

### 0.5 Makefile / startup script — image-related targets
- Run: `grep -n "image\|pull\|build\|registry" Makefile demoforge.sh 2>/dev/null | head -30`
- Note any existing `make pull-all`, `make build`, `make check-images` targets.

### 0.6 check_images.py or equivalent
- Run: `find . -name "check_images*" -o -name "image_check*" -o -name "preflight*" | head -10`
- Does a pre-flight image checker exist? Read its source if yes.

### 0.7 Dev mode vs SE mode distinction
- Run: `grep -rn "dev.*mode\|DEV_MODE\|DEMOFORGE_MODE\|make dev\|make start" Makefile demoforge.sh backend/app/ --include="*.py" --include="*.sh" 2>/dev/null | head -20`

### 0.8 Docker socket access
- Run: `grep -rn "docker\|DockerClient\|from_env\|DOCKER_HOST" backend/app/ --include="*.py" | head -20`
- Can the backend execute `docker build` or `docker push`?

### 0.9 Custom Dockerfiles
- Run: `find components/ -name "Dockerfile" | head -15`
- For each, show first 5 lines (FROM line).

### 0.10 OrbStack-specific handling
- Run: `grep -rn "orbstack\|OrbStack\|ORBSTACK" . --include="*.py" --include="*.ts" --include="*.sh" --include="*.md" --include="*.yaml" 2>/dev/null | head -10`

### Phase 0 output

After completing all 10 sections, summarize findings before proceeding:

```
PHASE 0 FINDINGS:
- Image Manager page: [exists/missing] — [what it does]
- Backend image API: [exists/missing] — [endpoints found]
- Custom Dockerfiles: [list of components with Dockerfiles]
- Compose generator image logic: [how it resolves image vs build]
- Dev/SE mode flag: [how it's detected]
- Pre-flight checker: [exists/missing]
- Docker access: [socket/env/auto]
```

Adapt all subsequent phases to match existing patterns, file paths, and conventions. If an Image Manager page exists, integrate with it. If a pre-flight checker exists, update it rather than creating a new one.

---

## Phase 1: Registry infrastructure files

Create `scripts/hub/` directory with two files.

### 1A. Create `scripts/hub/registry-config.yml`

```yaml
version: 0.1
log:
  level: info
  formatter: text
storage:
  s3:
    accesskey: DEMOFORGE_REGISTRY_ACCESS_KEY_PLACEHOLDER
    secretkey: DEMOFORGE_REGISTRY_SECRET_KEY_PLACEHOLDER
    region: us-east-1
    regionendpoint: http://minio:9000
    bucket: demoforge-registry
    rootdirectory: /docker/registry
    encrypt: false
    secure: false
    v4auth: true
    chunksize: 5242880
  delete:
    enabled: true
  cache:
    blobdescriptor: inmemory
http:
  addr: 0.0.0.0:5000
  headers:
    X-Content-Type-Options: [nosniff]
health:
  storagedriver:
    enabled: true
    interval: 30s
    threshold: 3
```

`regionendpoint` uses `http://minio:9000` — resolved via `extra_hosts` in compose. Placeholders replaced by `hub-setup.sh`.

### 1B. Create `scripts/hub/docker-compose.hub.yml`

```yaml
services:
  registry:
    image: registry:2
    container_name: demoforge-registry
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./registry-config.yml:/etc/docker/registry/config.yml:ro
    environment:
      - REGISTRY_LOG_LEVEL=info
    networks:
      - hub
    extra_hosts:
      - "minio:host-gateway"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:5000/v2/"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    labels:
      com.demoforge.role: registry
      com.demoforge.hub: "true"

networks:
  hub:
    driver: bridge
```

---

## Phase 2: Update `scripts/hub-setup.sh`

### 2A. Add configuration variables at the top

```bash
REGISTRY_PORT="${DEMOFORGE_REGISTRY_PORT:-5000}"
REGISTRY_BUCKET="demoforge-registry"
REGISTRY_SVC_USER="demoforge-registry"
REGISTRY_SVC_POLICY="demoforge-registry-policy"
HUB_COMPOSE_DIR="$SCRIPT_DIR/hub"
```

### 2B. Renumber existing steps from `/6` to `/10`

### 2C. New Step 7: Create registry bucket

```bash
log "Step 7/10: Creating registry bucket '${REGISTRY_BUCKET}'"
if mc ls "${HUB_ALIAS}/${REGISTRY_BUCKET}" &>/dev/null 2>&1; then
    log "  ✓ Bucket '${REGISTRY_BUCKET}' already exists"
else
    mc mb "${HUB_ALIAS}/${REGISTRY_BUCKET}"
    log "  ✓ Created bucket '${REGISTRY_BUCKET}'"
fi
```

### 2D. New Step 8: Create registry IAM

```bash
log "Step 8/10: Creating registry service account '${REGISTRY_SVC_USER}'"

cat > "${SCRIPT_DIR}/hub-registry-policy.json" << RPOLICY_EOF
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
        "s3:ListMultipartUploadParts",
        "s3:AbortMultipartUpload",
        "s3:ListBucketMultipartUploads"
      ],
      "Resource": [
        "arn:aws:s3:::${REGISTRY_BUCKET}",
        "arn:aws:s3:::${REGISTRY_BUCKET}/*"
      ]
    }
  ]
}
RPOLICY_EOF

mc admin policy create "${HUB_ALIAS}" "${REGISTRY_SVC_POLICY}" "${SCRIPT_DIR}/hub-registry-policy.json" 2>/dev/null \
  || mc admin policy create "${HUB_ALIAS}" "${REGISTRY_SVC_POLICY}" "${SCRIPT_DIR}/hub-registry-policy.json"
log "  ✓ Policy '${REGISTRY_SVC_POLICY}' created/updated"

REGISTRY_SVC_PASS=""
if mc admin user info "${HUB_ALIAS}" "${REGISTRY_SVC_USER}" &>/dev/null 2>&1; then
    log "  User '${REGISTRY_SVC_USER}' already exists"
    if [[ -f "${HUB_COMPOSE_DIR}/registry-config.yml" ]]; then
        EXISTING_KEY=$(grep "accesskey:" "${HUB_COMPOSE_DIR}/registry-config.yml" 2>/dev/null | awk '{print $2}' || true)
        if [[ "$EXISTING_KEY" == "$REGISTRY_SVC_USER" ]]; then
            REGISTRY_SVC_PASS=$(grep "secretkey:" "${HUB_COMPOSE_DIR}/registry-config.yml" 2>/dev/null | awk '{print $2}' || true)
            log "  ✓ Using existing credentials from registry config"
        fi
    fi
    if [[ -z "$REGISTRY_SVC_PASS" ]]; then
        read -rsp "  Enter existing password for '${REGISTRY_SVC_USER}' (Enter to regenerate): " REGISTRY_SVC_PASS
        echo ""
        if [[ -z "$REGISTRY_SVC_PASS" ]]; then
            mc admin user remove "${HUB_ALIAS}" "${REGISTRY_SVC_USER}" 2>/dev/null || true
            REGISTRY_SVC_PASS="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
            mc admin user add "${HUB_ALIAS}" "${REGISTRY_SVC_USER}" "${REGISTRY_SVC_PASS}"
            log "  ✓ Recreated user with new password"
        fi
    fi
else
    REGISTRY_SVC_PASS="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
    mc admin user add "${HUB_ALIAS}" "${REGISTRY_SVC_USER}" "${REGISTRY_SVC_PASS}"
    log "  ✓ Created user '${REGISTRY_SVC_USER}'"
fi

mc admin policy attach "${HUB_ALIAS}" "${REGISTRY_SVC_POLICY}" --user "${REGISTRY_SVC_USER}" 2>/dev/null || true
log "  ✓ Policy attached to '${REGISTRY_SVC_USER}'"
```

### 2E. New Step 9: Deploy registry container

```bash
log "Step 9/10: Deploying registry container"

cat > "${HUB_COMPOSE_DIR}/registry-config.yml" << REGCFG_EOF
version: 0.1
log:
  level: info
  formatter: text
storage:
  s3:
    accesskey: ${REGISTRY_SVC_USER}
    secretkey: ${REGISTRY_SVC_PASS}
    region: us-east-1
    regionendpoint: http://minio:9000
    bucket: ${REGISTRY_BUCKET}
    rootdirectory: /docker/registry
    encrypt: false
    secure: false
    v4auth: true
    chunksize: 5242880
  delete:
    enabled: true
  cache:
    blobdescriptor: inmemory
http:
  addr: 0.0.0.0:5000
  headers:
    X-Content-Type-Options: [nosniff]
health:
  storagedriver:
    enabled: true
    interval: 30s
    threshold: 3
REGCFG_EOF

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "demoforge-registry"; then
    log "  Registry already running. Restarting..."
    (cd "${HUB_COMPOSE_DIR}" && docker compose -f docker-compose.hub.yml down registry 2>/dev/null || true)
fi

(cd "${HUB_COMPOSE_DIR}" && docker compose -f docker-compose.hub.yml up -d registry)

log "  Waiting for registry to be healthy..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${REGISTRY_PORT}/v2/" &>/dev/null; then
        log "  ✓ Registry is healthy at http://localhost:${REGISTRY_PORT}"
        break
    fi
    [[ $i -eq 30 ]] && { err "  Registry failed to start. Check: docker logs demoforge-registry"; exit 1; }
    sleep 1
done

CATALOG=$(curl -sf "http://localhost:${REGISTRY_PORT}/v2/_catalog" 2>/dev/null || echo '{"error":"failed"}')
log "  ✓ Registry catalog: ${CATALOG}"
```

### 2F. Replace Step 6 `.env.hub` generation with combined version

```bash
log "Step 10/10: Generating ${ENV_FILE}"

cat > "${ENV_FILE}" << ENV_EOF
# DemoForge Hub — Template Sync + Registry
# Generated by hub-setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Copy to .env.local:  cp .env.hub .env.local

# ── Template Sync ──
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=${HUB_ENDPOINT}
DEMOFORGE_SYNC_BUCKET=${HUB_BUCKET}
DEMOFORGE_SYNC_PREFIX=${HUB_PREFIX}/
DEMOFORGE_SYNC_ACCESS_KEY=${SVC_USER}
DEMOFORGE_SYNC_SECRET_KEY=${SVC_PASS}

# ── Private Registry ──
DEMOFORGE_REGISTRY_URL=${HUB_ENDPOINT%%:*}:${REGISTRY_PORT}
DEMOFORGE_REGISTRY_HOST=$(echo "${HUB_ENDPOINT}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):${REGISTRY_PORT}
ENV_EOF

chmod 600 "${ENV_FILE}"
```

### 2G. Replace final summary

```bash
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Hub setup complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}MinIO${NC}"
echo -e "    Endpoint:        ${CYAN}${HUB_ENDPOINT}${NC}"
echo -e "    Console:         ${CYAN}${HUB_CONSOLE}${NC}"
echo -e "    Templates:       ${CYAN}${HUB_BUCKET}/${HUB_PREFIX}/ (${REMOTE_COUNT} templates)${NC}"
echo -e "    Sync account:    ${CYAN}${SVC_USER}${NC}"
echo ""
echo -e "  ${CYAN}Registry${NC}"
echo -e "    URL:             ${CYAN}http://$(echo "${HUB_ENDPOINT}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):${REGISTRY_PORT}${NC}"
echo -e "    Storage:         ${CYAN}${REGISTRY_BUCKET} (MinIO-backed)${NC}"
echo -e "    Registry account:${CYAN} ${REGISTRY_SVC_USER}${NC}"
echo ""
echo -e "  Credentials saved to: ${CYAN}${ENV_FILE}${NC}"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "    1. cp .env.hub .env.local"
echo -e "    2. Configure Docker to trust the registry (see below)"
echo -e "    3. make start"
echo ""
echo -e "  ${YELLOW}Docker insecure registry (run once per machine):${NC}"
echo ""
echo -e "    ${CYAN}OrbStack:${NC}"
echo -e "      orb config set docker.insecure-registries '[\"$(echo "${HUB_ENDPOINT}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):${REGISTRY_PORT}\"]'"
echo -e "      orb restart docker"
echo ""
echo -e "    ${CYAN}Docker Desktop:${NC}"
echo -e "      Settings → Docker Engine → add:"
echo -e "      {\"insecure-registries\": [\"$(echo "${HUB_ENDPOINT}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):${REGISTRY_PORT}\"]}"
echo ""
echo -e "    ${CYAN}Linux:${NC}"
echo -e "      echo '{\"insecure-registries\": [\"$(echo "${HUB_ENDPOINT}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):${REGISTRY_PORT}\"]}' | sudo tee /etc/docker/daemon.json"
echo -e "      sudo systemctl restart docker"
echo ""
```

---

## Phase 3: Update `scripts/hub-status.sh`

Add after existing remote template section:

```bash
REGISTRY_HOST="$(echo "${HUB_ENDPOINT:-http://34.18.90.197:9000}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):5000"

echo -e "  ${CYAN}Registry:${NC}"
if curl -sf "http://${REGISTRY_HOST}/v2/" &>/dev/null 2>&1; then
    CATALOG=$(curl -sf "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null)
    REPO_COUNT=$(echo "$CATALOG" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('repositories',[])))" 2>/dev/null || echo "?")
    echo -e "    Status:      ${GREEN}healthy${NC}"
    echo -e "    URL:         ${CYAN}http://${REGISTRY_HOST}${NC}"
    echo -e "    Repositories:${GREEN} ${REPO_COUNT}${NC}"
    if [[ "$REPO_COUNT" != "0" && "$REPO_COUNT" != "?" ]]; then
        echo -e "    ${YELLOW}Images:${NC}"
        for repo in $(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null); do
            TAGS=$(curl -sf "http://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null \
              | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('tags',[])))" 2>/dev/null || echo "?")
            echo -e "      ${repo}: ${CYAN}${TAGS}${NC}"
        done
    fi
else
    echo -e "    Status:      ${YELLOW}unreachable${NC} (http://${REGISTRY_HOST})"
    echo -e "    ${YELLOW}Run scripts/hub-setup.sh to deploy the registry${NC}"
fi
echo ""
```

---

## Phase 4: Create `scripts/hub-push.sh`

Dev-only. Scans for Dockerfiles, builds, tags as `34.18.90.197:5000/demoforge/<component>:latest`, pushes.

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPONENTS_DIR="$PROJECT_ROOT/components"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

REGISTRY_HOST="${DEMOFORGE_REGISTRY_HOST:-34.18.90.197:5000}"
REGISTRY_PREFIX="demoforge"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-push]${NC} $*"; }
err()  { echo -e "${RED}[hub-push]${NC} $*" >&2; }

curl -sf "http://${REGISTRY_HOST}/v2/" &>/dev/null || { err "Registry unreachable at http://${REGISTRY_HOST}"; exit 1; }
log "Registry reachable at ${REGISTRY_HOST}"

COMPONENTS=(); DOCKERFILES=()
while IFS= read -r df; do
    COMPONENTS+=("$(basename "$(dirname "$df")")")
    DOCKERFILES+=("$df")
done < <(find "$COMPONENTS_DIR" -name "Dockerfile" -type f | sort)

[[ -f "$PROJECT_ROOT/backend/Dockerfile" ]] && { COMPONENTS+=("demoforge-backend"); DOCKERFILES+=("$PROJECT_ROOT/backend/Dockerfile"); }
[[ -f "$PROJECT_ROOT/frontend/Dockerfile" ]] && { COMPONENTS+=("demoforge-frontend"); DOCKERFILES+=("$PROJECT_ROOT/frontend/Dockerfile"); }

[[ ${#COMPONENTS[@]} -eq 0 ]] && { echo "No Dockerfiles found."; exit 0; }

echo -e "\n${CYAN}Found ${#COMPONENTS[@]} images to build:${NC}"
for i in "${!COMPONENTS[@]}"; do echo "  ${COMPONENTS[$i]} ← ${DOCKERFILES[$i]#$PROJECT_ROOT/}"; done
echo ""

FILTER="${1:-}"
BUILT=0; FAILED=0

for i in "${!COMPONENTS[@]}"; do
    comp="${COMPONENTS[$i]}"; dockerfile="${DOCKERFILES[$i]}"; context=$(dirname "$dockerfile")
    [[ -n "$FILTER" && "$comp" != "$FILTER" ]] && continue

    IMAGE_TAG="${REGISTRY_HOST}/${REGISTRY_PREFIX}/${comp}:latest"
    log "Building ${comp}..."

    if docker build -t "$IMAGE_TAG" -f "$dockerfile" "$context" 2>&1 | tail -5; then
        log "  ✓ Built: $IMAGE_TAG"
    else
        err "  ✗ Build failed: $comp"; ((FAILED++)); continue
    fi

    log "  Pushing..."
    if docker push "$IMAGE_TAG" 2>&1 | tail -3; then
        log "  ✓ Pushed: $IMAGE_TAG"; ((BUILT++))
    else
        err "  ✗ Push failed: $comp"; ((FAILED++))
    fi

    # Git hash tag
    if command -v git &>/dev/null && git rev-parse --short HEAD &>/dev/null 2>&1; then
        GIT_TAG="${REGISTRY_HOST}/${REGISTRY_PREFIX}/${comp}:$(git rev-parse --short HEAD)"
        docker tag "$IMAGE_TAG" "$GIT_TAG"; docker push "$GIT_TAG" 2>/dev/null || true
    fi
    echo ""
done

echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo -e "  Built & pushed: ${GREEN}${BUILT}${NC}"
[[ $FAILED -gt 0 ]] && echo -e "  Failed:         ${RED}${FAILED}${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"

log "Registry contents:"
CATALOG=$(curl -sf "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
for repo in $(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null); do
    TAGS=$(curl -sf "http://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null \
      | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('tags',[])))" 2>/dev/null || echo "?")
    echo -e "  ${repo}: ${CYAN}${TAGS}${NC}"
done
exit $FAILED
```

---

## Phase 5: Create `scripts/hub-pull.sh`

SE use — pulls all custom images from the private registry. No building.

**If Phase 0 found an existing pre-flight checker or Image Manager API, integrate with those instead of creating a standalone script.**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

REGISTRY_HOST="${DEMOFORGE_REGISTRY_HOST:-34.18.90.197:5000}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-pull]${NC} $*"; }
err()  { echo -e "${RED}[hub-pull]${NC} $*" >&2; }

curl -sf "http://${REGISTRY_HOST}/v2/" &>/dev/null || { err "Registry unreachable at http://${REGISTRY_HOST}"; exit 1; }

CATALOG=$(curl -sf "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
REPOS=$(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null)

[[ -z "$REPOS" ]] && { echo -e "${YELLOW}No images in registry. Dev needs to run: make hub-push${NC}"; exit 0; }

echo -e "${CYAN}Pulling custom images from ${REGISTRY_HOST}:${NC}\n"
PULLED=0; FAILED=0

while IFS= read -r repo; do
    [[ -z "$repo" ]] && continue
    IMAGE="${REGISTRY_HOST}/${repo}:latest"
    log "Pulling ${IMAGE}..."
    if docker pull "$IMAGE" 2>&1 | tail -2; then
        log "  ✓ ${repo}"; ((PULLED++))
    else
        err "  ✗ ${repo}"; ((FAILED++))
    fi
done <<< "$REPOS"

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
```

---

## Phase 6: Create `scripts/hub-trust-registry.sh`

One-time per machine — configures Docker to trust the HTTP registry.

```bash
#!/usr/bin/env bash
set -euo pipefail

REGISTRY_HOST="${1:-34.18.90.197:5000}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}Configure Docker to trust insecure registry: ${REGISTRY_HOST}${NC}\n"

if command -v orb &>/dev/null; then
    echo -e "${GREEN}Detected: OrbStack${NC}\n"
    echo -e "  ${CYAN}orb config set docker.insecure-registries '[\"${REGISTRY_HOST}\"]'${NC}"
    echo -e "  ${CYAN}orb restart docker${NC}\n"
    read -rp "Run automatically? (y/N) " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
        orb config set docker.insecure-registries "[\"${REGISTRY_HOST}\"]"
        orb restart docker; sleep 3
        echo -e "${GREEN}✓ Done${NC}"
        curl -sf "http://${REGISTRY_HOST}/v2/" &>/dev/null && echo -e "${GREEN}✓ Registry accessible${NC}"
    fi
elif [[ "$(uname)" == "Darwin" ]]; then
    echo -e "${GREEN}Detected: Docker Desktop (macOS)${NC}\n"
    echo "Open Docker Desktop → Settings → Docker Engine → add:"
    echo -e "  ${CYAN}\"insecure-registries\": [\"${REGISTRY_HOST}\"]${NC}"
    echo "Then click 'Apply & Restart'."
elif [[ -f "/etc/docker/daemon.json" ]] || command -v dockerd &>/dev/null; then
    echo -e "${GREEN}Detected: Docker Engine (Linux)${NC}"
    DAEMON_JSON="/etc/docker/daemon.json"
    echo -e "Add to ${DAEMON_JSON}:"
    echo -e "  ${CYAN}{\"insecure-registries\": [\"${REGISTRY_HOST}\"]}${NC}\n"
    read -rp "Run automatically? (y/N) " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
        if [[ -f "$DAEMON_JSON" ]]; then
            python3 -c "
import json
with open('$DAEMON_JSON') as f: cfg = json.load(f)
regs = cfg.get('insecure-registries', [])
if '$REGISTRY_HOST' not in regs:
    regs.append('$REGISTRY_HOST'); cfg['insecure-registries'] = regs
    with open('$DAEMON_JSON', 'w') as f: json.dump(cfg, f, indent=2)
    print('Updated')
else: print('Already configured')
"
        else
            echo "{\"insecure-registries\": [\"${REGISTRY_HOST}\"]}" | sudo tee "$DAEMON_JSON"
        fi
        sudo systemctl restart docker
        echo -e "${GREEN}✓ Docker restarted${NC}"
    fi
else
    echo -e "${YELLOW}Could not detect Docker runtime.${NC}"
    echo "Manually add: ${CYAN}\"insecure-registries\": [\"${REGISTRY_HOST}\"]${NC}"
fi
```

---

## Phase 7: Makefile targets and permissions

```bash
chmod +x scripts/hub-push.sh scripts/hub-pull.sh scripts/hub-trust-registry.sh
```

Add to Makefile:

```makefile
hub-push:         ## [Dev] Build all custom images and push to private registry
	@scripts/hub-push.sh

hub-push-%:       ## [Dev] Build and push one image, e.g.: make hub-push-inference-sim
	@scripts/hub-push.sh $*

hub-pull:         ## [SE] Pull all custom images from private registry
	@scripts/hub-pull.sh

hub-trust:        ## [One-time] Configure Docker to trust the private registry
	@scripts/hub-trust-registry.sh
```

---

## Phase 8: Verification

### After `hub-setup.sh`:

```bash
curl -s http://34.18.90.197:5000/v2/                    # → {}
mc ls demoforge-hub/demoforge-registry/                  # → docker/ dir
grep REGISTRY .env.hub                                   # → URL + HOST
scripts/hub-status.sh                                    # → Registry: healthy
```

### After `make hub-push`:

```bash
curl -s http://34.18.90.197:5000/v2/_catalog             # → repositories list
curl -s http://34.18.90.197:5000/v2/demoforge/inference-sim/tags/list  # → tags
mc ls demoforge-hub/demoforge-registry/docker/ --recursive | head -10  # → blobs in MinIO
```

### After `make hub-trust` + `make hub-pull` on SE laptop:

```bash
docker images | grep "34.18.90.197:5000/demoforge"       # → all custom images
```

---

## What NOT to do

- Do NOT use Docker Hub, GHCR, or any public registry — all images stay private
- Do NOT set up HTTPS/TLS in this phase — HTTP + insecure-registries is fine for internal team
- Do NOT store root MinIO credentials anywhere — only scoped service accounts
- Do NOT skip Phase 0 — findings determine integration with existing Image Manager / pre-flight checker
- Do NOT modify the compose generator to use registry images yet — follow-up task after registry works end-to-end

---

## Build order

1. **Phase 0** — Investigate codebase, produce findings
2. **Phase 1** — Create `scripts/hub/` with config + compose
3. **Phase 2** — Update `hub-setup.sh` (add steps 7-10, renumber to /10)
4. **Phase 3** — Update `hub-status.sh` with registry health
5. **Phase 4** — Create `hub-push.sh`
6. **Phase 5** — Create `hub-pull.sh` (integrate with existing pre-flight if found)
7. **Phase 6** — Create `hub-trust-registry.sh`
8. **Phase 7** — Makefile + chmod
9. **Phase 8** — Verify end-to-end
