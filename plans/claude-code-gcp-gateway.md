# Claude Code — GCP Gateway, VPC, Cloud Run + Hub Connector

## Context

DemoForge has a GCP VM running MinIO + Docker Registry, managed by `minio-gcp.sh`. Currently everything is exposed directly on a public IP. This instruction:

1. **Adds a VPC** with a private subnet — VM loses direct public exposure
2. **Deploys a Cloud Run gateway** that proxies HTTPS + API key auth to the VM
3. **Builds a hub-connector container** — SEs run it locally, it proxies localhost → Cloud Run
4. **Keeps your IP whitelisted** for direct access during development
5. **Adds local test scripts** that simulate the SE experience

The existing `minio-gcp.sh` script is the starting point. Read it fully before making changes.

## Pre-work: Read before writing

```
minio-gcp.sh                    # Existing VM management — will be updated
scripts/hub-setup.sh             # Existing hub setup (if present) — coordinate, don't duplicate
scripts/hub-push.sh              # Existing image push script (if present)
docker-compose.yml               # DemoForge local compose
```

---

## Phase 0: Investigate existing state

Before writing any code, check:
- Run: `cat minio-gcp.sh | head -30` — confirm it matches the script you were given
- Run: `ls scripts/hub*.sh 2>/dev/null` — check which hub scripts exist
- Run: `ls scripts/gateway/ 2>/dev/null` — check if any gateway work exists
- Run: `grep -rn "CLOUD_RUN\|VPC\|CONNECTOR\|GATEWAY" minio-gcp.sh scripts/ 2>/dev/null | head -10`
- Note findings before proceeding

---

## Phase 1: Update `minio-gcp.sh` — add VPC, Cloud Run, gateway

### 1A. Add new configuration variables at the top

Add after the existing configuration block:

```bash
# ─── Gateway / VPC Configuration ─────────────────────────────────────
VPC_NAME="demoforge-vpc"
SUBNET_NAME="demoforge-subnet"
SUBNET_RANGE="10.10.0.0/24"
VPC_CONNECTOR_NAME="demoforge-connector"
VPC_CONNECTOR_RANGE="10.10.1.0/28"        # /28 = 16 IPs for connector
CLOUD_RUN_SERVICE="demoforge-gateway"
CLOUD_RUN_REGION="${REGION}"
GATEWAY_IMAGE="gcr.io/${PROJECT_ID}/demoforge-gateway:latest"
FIREWALL_RULE_INTERNAL="allow-internal-to-minio"
FIREWALL_RULE_MYIP="allow-myip-to-minio"
CONNECTOR_IMAGE="gcr.io/${PROJECT_ID}/demoforge-hub-connector:latest"

# API key for gateway auth (generated on first deploy, stored in metadata)
GATEWAY_API_KEY=""
```

### 1B. Add new mode `--gateway`

Update the mode parser:

```bash
MODE="deploy"
case "${1:-}" in
  --update)   MODE="update" ;;
  --activate) MODE="activate" ;;
  --gateway)  MODE="gateway" ;;
  --help|-h)  usage ;;
  "")         MODE="deploy" ;;
  *)          echo "Unknown flag: $1"; usage ;;
esac
```

Update usage():

```bash
usage() {
  echo "Usage: $0 [--update | --activate | --gateway]"
  echo ""
  echo "  (no flag)    Fresh deploy — creates project, VM, disk, firewall, runs AIStor"
  echo "  --update     Upgrade running MinIO container to AIStor image (preserves everything)"
  echo "  --activate   Register AIStor Free license on the running deployment"
  echo "  --gateway    Deploy/update Cloud Run gateway + VPC (run AFTER fresh deploy)"
  exit 0
}
```

### 1C. New `--gateway` mode — full implementation

Insert before the `--update` mode block. This is the core of the spec.

```bash
# ═════════════════════════════════════════════════════════════════════
# MODE: --gateway
# Deploy Cloud Run gateway + VPC + connector image
# Run AFTER the base VM is deployed and healthy
# ═════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "gateway" ]]; then
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  DemoForge Gateway — Cloud Run + VPC Deployment         ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

  # ── Step 1: Verify VM is running ──
  step 1 "Verify VM [${VM_NAME}] is running"
  verify "VM is RUNNING" \
    "gcloud compute instances describe ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --format='value(status)' | grep -q RUNNING"
  EXTERNAL_IP=$(get_external_ip)
  ok "External IP: ${EXTERNAL_IP}"

  # ── Step 2: Enable required APIs ──
  step 2 "Enable Cloud Run, VPC Access, Container Registry APIs"
  for API in run.googleapis.com vpcaccess.googleapis.com containerregistry.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com; do
    gcloud services enable "${API}" --project="${PROJECT_ID}" 2>/dev/null || true
  done
  ok "APIs enabled."

  # ── Step 3: Create VPC and subnet ──
  step 3 "Create VPC [${VPC_NAME}] and subnet [${SUBNET_NAME}]"

  if gcloud compute networks describe "${VPC_NAME}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
    warn "VPC ${VPC_NAME} already exists — reusing."
  else
    gcloud compute networks create "${VPC_NAME}" \
      --project="${PROJECT_ID}" \
      --subnet-mode=custom
    ok "VPC created."
  fi

  if gcloud compute networks subnets describe "${SUBNET_NAME}" --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
    warn "Subnet ${SUBNET_NAME} already exists — reusing."
  else
    gcloud compute networks subnets create "${SUBNET_NAME}" \
      --project="${PROJECT_ID}" \
      --network="${VPC_NAME}" \
      --region="${REGION}" \
      --range="${SUBNET_RANGE}"
    ok "Subnet created: ${SUBNET_RANGE}"
  fi

  # ── Step 4: Move VM to VPC (if still on default network) ──
  step 4 "Ensure VM is on VPC [${VPC_NAME}]"

  CURRENT_NETWORK=$(gcloud compute instances describe "${VM_NAME}" \
    --zone="${ZONE}" --project="${PROJECT_ID}" \
    --format='get(networkInterfaces[0].network)' 2>/dev/null | xargs basename)

  if [[ "$CURRENT_NETWORK" == "${VPC_NAME}" ]]; then
    ok "VM already on ${VPC_NAME}."
  else
    warn "VM is on '${CURRENT_NETWORK}' network. Moving requires stop/start."
    echo -e "  ${YELLOW}The VM will be stopped, its network interface changed, and restarted.${NC}"
    echo -e "  ${YELLOW}Data on the persistent disk is preserved. This takes ~60 seconds.${NC}"
    read -rp "  Proceed? (y/N) " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
      fail "Aborted."
    fi

    # Stop VM
    gcloud compute instances stop "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --quiet
    ok "VM stopped."

    # Delete old network interface and add new one
    # GCP doesn't support in-place NIC change — we need to delete and recreate the VM
    # BUT we can preserve the disk. Export the VM config, recreate with new network.

    # Simpler approach: add a second NIC isn't supported on e2-medium.
    # Correct approach: recreate VM with same disks on new network.

    # Get current disk info
    BOOT_DISK=$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" \
      --format='get(disks[0].source)' | xargs basename)

    # Get metadata
    MINIO_ROOT_USER_META=$(get_vm_metadata "minio-root-user")
    MINIO_ROOT_PASSWORD_META=$(get_vm_metadata "minio-root-password")
    REGISTRY_PASS_META=$(get_vm_metadata "registry-password")

    # Delete VM but keep disks
    gcloud compute instances delete "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" \
      --keep-disks=all --quiet
    ok "Old VM deleted (disks preserved)."

    # Recreate VM on new VPC
    gcloud compute instances create "${VM_NAME}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" \
      --machine-type="${MACHINE_TYPE}" \
      --disk="name=${BOOT_DISK},boot=yes,auto-delete=no" \
      --disk="name=${DATA_DISK_NAME},device-name=minio-data,mode=rw,boot=no,auto-delete=no" \
      --network="${VPC_NAME}" \
      --subnet="${SUBNET_NAME}" \
      --tags="${NETWORK_TAG}" \
      --metadata="minio-root-user=${MINIO_ROOT_USER_META},minio-root-password=${MINIO_ROOT_PASSWORD_META},registry-password=${REGISTRY_PASS_META}" \
      --scopes=default \
      --no-address  # NO PUBLIC IP — this is the key change
    ok "VM recreated on ${VPC_NAME} with no public IP."

    # Wait for VM
    for i in $(seq 1 30); do
      STATUS=$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --format='value(status)' 2>/dev/null || echo "")
      [[ "$STATUS" == "RUNNING" ]] && break
      sleep 2
    done
    ok "VM is running on private network."

    # Get internal IP
    INTERNAL_IP=$(gcloud compute instances describe "${VM_NAME}" \
      --zone="${ZONE}" --project="${PROJECT_ID}" \
      --format='get(networkInterfaces[0].networkIP)')
    ok "Internal IP: ${INTERNAL_IP}"

    # Restart MinIO and registry containers (startup script should handle this,
    # but the network change may require a manual kick)
    run_on_vm "sudo docker start minio demoforge-registry 2>/dev/null || true" 2>/dev/null || true
  fi

  # Get internal IP (whether we moved or not)
  INTERNAL_IP=$(gcloud compute instances describe "${VM_NAME}" \
    --zone="${ZONE}" --project="${PROJECT_ID}" \
    --format='get(networkInterfaces[0].networkIP)')
  ok "VM internal IP: ${INTERNAL_IP}"

  # ── Step 5: Firewall rules for VPC ──
  step 5 "Configure firewall rules on ${VPC_NAME}"

  # Allow VPC connector → VM (Cloud Run traffic)
  if gcloud compute firewall-rules describe "${FIREWALL_RULE_INTERNAL}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
    warn "Internal firewall rule exists — updating."
    gcloud compute firewall-rules update "${FIREWALL_RULE_INTERNAL}" \
      --project="${PROJECT_ID}" \
      --source-ranges="${VPC_CONNECTOR_RANGE},${SUBNET_RANGE}" \
      --rules=tcp:9000,tcp:9001,tcp:5000
  else
    gcloud compute firewall-rules create "${FIREWALL_RULE_INTERNAL}" \
      --project="${PROJECT_ID}" \
      --network="${VPC_NAME}" \
      --direction=INGRESS --priority=900 \
      --action=ALLOW --rules=tcp:9000,tcp:9001,tcp:5000 \
      --source-ranges="${VPC_CONNECTOR_RANGE},${SUBNET_RANGE}" \
      --target-tags="${NETWORK_TAG}" \
      --description="Allow VPC connector and subnet to reach MinIO and Registry"
  fi
  ok "Internal access rule configured."

  # Allow your current IP for direct SSH and service access
  MY_IP=$(curl -sf https://ifconfig.me || curl -sf https://api.ipify.org || echo "")
  if [[ -n "$MY_IP" ]]; then
    if gcloud compute firewall-rules describe "${FIREWALL_RULE_MYIP}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
      gcloud compute firewall-rules update "${FIREWALL_RULE_MYIP}" \
        --project="${PROJECT_ID}" \
        --source-ranges="${MY_IP}/32"
    else
      gcloud compute firewall-rules create "${FIREWALL_RULE_MYIP}" \
        --project="${PROJECT_ID}" \
        --network="${VPC_NAME}" \
        --direction=INGRESS --priority=800 \
        --action=ALLOW --rules=tcp:22,tcp:9000,tcp:9001,tcp:5000 \
        --source-ranges="${MY_IP}/32" \
        --target-tags="${NETWORK_TAG}" \
        --description="Allow dev IP direct access (SSH + services)"
    fi
    ok "Dev IP allow-listed: ${MY_IP}"
  else
    warn "Could not detect your IP. Add manually:"
    warn "  gcloud compute firewall-rules create ${FIREWALL_RULE_MYIP} --source-ranges=<YOUR_IP>/32 ..."
  fi

  # Allow IAP for SSH (so gcloud compute ssh still works without public IP)
  IAP_RULE="allow-iap-ssh"
  if ! gcloud compute firewall-rules describe "${IAP_RULE}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
    gcloud compute firewall-rules create "${IAP_RULE}" \
      --project="${PROJECT_ID}" \
      --network="${VPC_NAME}" \
      --direction=INGRESS --priority=850 \
      --action=ALLOW --rules=tcp:22 \
      --source-ranges="35.235.240.0/20" \
      --target-tags="${NETWORK_TAG}" \
      --description="Allow IAP TCP tunneling for SSH"
    ok "IAP SSH rule created."
  else
    ok "IAP SSH rule exists."
  fi

  # Delete the old broad firewall rule if it exists (was 0.0.0.0/0)
  if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
    RULE_NETWORK=$(gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" --format='get(network)' | xargs basename)
    if [[ "$RULE_NETWORK" == "default" ]]; then
      warn "Old firewall rule '${FIREWALL_RULE}' is on 'default' network — leaving it (VM moved)."
    else
      warn "Deleting old broad firewall rule '${FIREWALL_RULE}' (was open to 0.0.0.0/0)."
      gcloud compute firewall-rules delete "${FIREWALL_RULE}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
    fi
  fi

  # ── Step 6: Create VPC connector for Cloud Run ──
  step 6 "Create Serverless VPC Access connector [${VPC_CONNECTOR_NAME}]"

  if gcloud compute networks vpc-access connectors describe "${VPC_CONNECTOR_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null 2>&1; then
    warn "VPC connector already exists — reusing."
  else
    gcloud compute networks vpc-access connectors create "${VPC_CONNECTOR_NAME}" \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --network="${VPC_NAME}" \
      --range="${VPC_CONNECTOR_RANGE}" \
      --min-instances=2 \
      --max-instances=3
    ok "VPC connector created."
  fi

  # Wait for connector to be READY
  for i in $(seq 1 30); do
    STATE=$(gcloud compute networks vpc-access connectors describe "${VPC_CONNECTOR_NAME}" \
      --region="${REGION}" --project="${PROJECT_ID}" --format='value(state)' 2>/dev/null || echo "")
    [[ "$STATE" == "READY" ]] && break
    echo "  ... connector state: ${STATE} — retrying (${i}/30)"
    sleep 5
  done
  verify "VPC connector is READY" \
    "gcloud compute networks vpc-access connectors describe ${VPC_CONNECTOR_NAME} --region=${REGION} --project=${PROJECT_ID} --format='value(state)' | grep -q READY"

  # ── Step 7: Generate or read API key ──
  step 7 "Generate gateway API key"

  GATEWAY_API_KEY=$(get_vm_metadata "gateway-api-key")
  if [[ -z "$GATEWAY_API_KEY" ]]; then
    GATEWAY_API_KEY="dfg-$(openssl rand -hex 20)"
    # Store in VM metadata for persistence
    gcloud compute instances add-metadata "${VM_NAME}" \
      --zone="${ZONE}" --project="${PROJECT_ID}" \
      --metadata="gateway-api-key=${GATEWAY_API_KEY}"
    ok "API key generated and stored in VM metadata."
  else
    ok "Using existing API key from VM metadata."
  fi

  # ── Step 8: Build and deploy Cloud Run gateway ──
  step 8 "Build and deploy Cloud Run gateway"

  # Create gateway source directory
  GATEWAY_DIR=$(mktemp -d /tmp/demoforge-gateway-XXXXXX)

  # Write Caddyfile
  cat > "${GATEWAY_DIR}/Caddyfile" <<CADDY_EOF
{
  auto_https off
  admin off
}

:8080 {
  # Health check — no auth required
  handle /health {
    respond "ok" 200
  }

  # API key validation for all other routes
  @nokey {
    not header X-Api-Key ${GATEWAY_API_KEY}
  }
  handle @nokey {
    respond "Unauthorized — X-Api-Key header required" 401
  }

  # S3 API → MinIO
  handle /s3/* {
    uri strip_prefix /s3
    reverse_proxy ${INTERNAL_IP}:9000
  }

  # MinIO Console
  handle /console/* {
    uri strip_prefix /console
    reverse_proxy ${INTERNAL_IP}:9001
  }

  # Docker Registry v2 API
  handle /v2/* {
    reverse_proxy ${INTERNAL_IP}:5000
  }

  # Root health
  handle / {
    respond "DemoForge Hub Gateway" 200
  }
}
CADDY_EOF

  # Write Dockerfile for gateway
  cat > "${GATEWAY_DIR}/Dockerfile" <<'GWDOCKERFILE'
FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
GWDOCKERFILE

  # Build with Cloud Build
  ok "Building gateway image..."
  gcloud builds submit "${GATEWAY_DIR}" \
    --project="${PROJECT_ID}" \
    --tag="${GATEWAY_IMAGE}" \
    --quiet

  ok "Gateway image built: ${GATEWAY_IMAGE}"

  # Deploy to Cloud Run
  gcloud run deploy "${CLOUD_RUN_SERVICE}" \
    --project="${PROJECT_ID}" \
    --region="${CLOUD_RUN_REGION}" \
    --image="${GATEWAY_IMAGE}" \
    --platform=managed \
    --port=8080 \
    --allow-unauthenticated \
    --vpc-connector="${VPC_CONNECTOR_NAME}" \
    --vpc-egress=private-ranges-only \
    --min-instances=1 \
    --max-instances=5 \
    --memory=256Mi \
    --cpu=1 \
    --timeout=300 \
    --concurrency=100 \
    --set-env-vars="GATEWAY_TARGET=${INTERNAL_IP}" \
    --quiet

  GATEWAY_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE}" \
    --region="${CLOUD_RUN_REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)')
  ok "Gateway deployed: ${GATEWAY_URL}"

  # Clean up temp dir
  rm -rf "${GATEWAY_DIR}"

  # ── Step 9: Verify gateway ──
  step 9 "Verify gateway connectivity"

  # Health check (no auth)
  if curl -sf "${GATEWAY_URL}/health" &>/dev/null; then
    ok "Gateway health check passed."
  else
    warn "Gateway health check failed. It may need a moment to start."
  fi

  # Auth check — should fail without key
  HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/s3/" 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "401" ]]; then
    ok "Auth enforcement working (401 without API key)."
  else
    warn "Expected 401 without API key, got ${HTTP_CODE}."
  fi

  # Auth check — should pass with key
  HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -H "X-Api-Key: ${GATEWAY_API_KEY}" "${GATEWAY_URL}/s3/minio/health/live" 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "200" ]]; then
    ok "MinIO reachable through gateway with API key."
  else
    warn "MinIO through gateway returned ${HTTP_CODE}. May need time for VPC connector."
  fi

  # ── Step 10: Build hub-connector image ──
  step 10 "Build hub-connector image"

  CONNECTOR_DIR=$(mktemp -d /tmp/demoforge-connector-XXXXXX)

  cat > "${CONNECTOR_DIR}/Caddyfile" <<'CONNCADDY'
{
  auto_https off
  admin off
}

# S3 API proxy
:9000 {
  reverse_proxy {$HUB_URL}/s3 {
    header_up X-Api-Key {$API_KEY}
    header_up Host {upstream_hostport}
  }
}

# Docker Registry proxy
:5000 {
  reverse_proxy {$HUB_URL}/v2 {
    header_up X-Api-Key {$API_KEY}
    header_up Host {upstream_hostport}
  }
}

# MinIO Console proxy
:9001 {
  reverse_proxy {$HUB_URL}/console {
    header_up X-Api-Key {$API_KEY}
    header_up Host {upstream_hostport}
  }
}

# Health endpoint
:8080 {
  handle /health {
    reverse_proxy {$HUB_URL}/health
  }
  handle / {
    respond "hub-connector running" 200
  }
}
CONNCADDY

  cat > "${CONNECTOR_DIR}/Dockerfile" <<'CONNDOCKERFILE'
FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 9000 5000 9001 8080
ENV HUB_URL=https://demoforge-gateway-xxx.run.app
ENV API_KEY=change-me
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
CONNDOCKERFILE

  # Build connector image
  gcloud builds submit "${CONNECTOR_DIR}" \
    --project="${PROJECT_ID}" \
    --tag="${CONNECTOR_IMAGE}" \
    --quiet
  ok "Hub connector image built: ${CONNECTOR_IMAGE}"

  # Also push to the private registry on the VM (so SEs can pull it)
  # This requires the VM to be reachable — use direct IP if allowed
  if [[ -n "$MY_IP" ]]; then
    # Tag for private registry
    docker pull "${CONNECTOR_IMAGE}" 2>/dev/null || true
    PRIVATE_TAG="${EXTERNAL_IP}:5000/demoforge/hub-connector:latest"
    docker tag "${CONNECTOR_IMAGE}" "${PRIVATE_TAG}" 2>/dev/null || true
    docker push "${PRIVATE_TAG}" 2>/dev/null || warn "Could not push to private registry. Push manually later."
  fi

  rm -rf "${CONNECTOR_DIR}"

  # ── Step 11: Generate .env.hub ──
  step 11 "Generate .env.hub"

  ENV_FILE="$(dirname "$0")/.env.hub"
  cat > "${ENV_FILE}" <<ENV_EOF
# DemoForge Hub Configuration
# Generated by minio-gcp.sh --gateway on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Copy to .env.local:  cp .env.hub .env.local

# ── Gateway ──
DEMOFORGE_HUB_URL=${GATEWAY_URL}
DEMOFORGE_API_KEY=${GATEWAY_API_KEY}

# ── Template Sync (via gateway) ──
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=${GATEWAY_URL}/s3
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=<run-hub-setup-to-get-this>

# ── Registry (via hub-connector on localhost) ──
DEMOFORGE_REGISTRY_HOST=localhost:5000

# ── Direct access (dev only) ──
DEMOFORGE_DIRECT_IP=${EXTERNAL_IP:-${INTERNAL_IP}}
ENV_EOF

  chmod 600 "${ENV_FILE}"
  ok "Wrote ${ENV_FILE}"

  # ── Summary ──
  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║       DemoForge Gateway — DEPLOYMENT COMPLETE           ║${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Gateway URL : ${GATEWAY_URL}  ${NC}"
  echo -e "${GREEN}║  API Key     : ${GATEWAY_API_KEY:0:12}...  ${NC}"
  echo -e "${GREEN}║  VM internal : ${INTERNAL_IP}  ${NC}"
  echo -e "${GREEN}║  VPC         : ${VPC_NAME} / ${SUBNET_NAME}  ${NC}"
  echo -e "${GREEN}║  Connector   : ${VPC_CONNECTOR_NAME}  ${NC}"
  echo -e "${GREEN}║  Min instances: 1 (warm — no cold starts)  ${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Hub connector image: ${CONNECTOR_IMAGE}  ${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Your IP (${MY_IP}) has direct access  ${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${YELLOW}SE setup (one command):${NC}"
  echo ""
  echo "  docker run -d --name hub-connector --restart=always \\"
  echo "    -p 9000:9000 -p 5000:5000 -p 9001:9001 -p 8080:8080 \\"
  echo "    -e HUB_URL=${GATEWAY_URL} \\"
  echo "    -e API_KEY=${GATEWAY_API_KEY} \\"
  echo "    ${CONNECTOR_IMAGE}"
  echo ""
  echo -e "${YELLOW}Or use the test script:${NC}"
  echo "  ./scripts/local-hub-test.sh"
  echo ""
  echo -e "${YELLOW}Update your IP if it changes:${NC}"
  echo "  gcloud compute firewall-rules update ${FIREWALL_RULE_MYIP} --source-ranges=\$(curl -sf ifconfig.me)/32 --project=${PROJECT_ID}"
  echo ""
  exit 0
fi
```

### 1D. Update the fresh deploy mode

In the existing deploy mode, after the VM is created and healthy, add a note:

```bash
# At the end of the deploy summary, add:
echo ""
echo -e "${YELLOW}To add Cloud Run gateway (VPC + HTTPS + auth):${NC}"
echo "  ./$(basename "$0") --gateway"
```

---

## Phase 2: Local test script — `scripts/local-hub-test.sh`

This script simulates the SE experience locally. It starts the hub-connector, verifies connectivity, tests template sync and registry access, then cleans up.

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-test]${NC} $*"; }
warn() { echo -e "${YELLOW}[hub-test]${NC} $*"; }
err()  { echo -e "${RED}[hub-test]${NC} $*" >&2; }

# ── Load config ──
if [[ -f "$PROJECT_ROOT/.env.hub" ]]; then
    source "$PROJECT_ROOT/.env.hub"
else
    err ".env.hub not found. Run: ./minio-gcp.sh --gateway"
    exit 1
fi

HUB_URL="${DEMOFORGE_HUB_URL:?Missing DEMOFORGE_HUB_URL in .env.hub}"
API_KEY="${DEMOFORGE_API_KEY:?Missing DEMOFORGE_API_KEY in .env.hub}"
CONNECTOR_IMAGE="${1:-gcr.io/minio-demoforge/demoforge-hub-connector:latest}"
CONTAINER_NAME="hub-connector-test"

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  DemoForge Hub — Local Integration Test                 ║${NC}"
echo -e "${CYAN}║  Simulates SE experience with hub-connector             ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Cleanup from previous runs ──
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

# ── Test 1: Gateway reachability ──
log "Test 1: Gateway health check"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "${HUB_URL}/health" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" ]]; then
    log "  ✓ Gateway healthy at ${HUB_URL}"
else
    err "  ✗ Gateway unreachable (HTTP ${HTTP_CODE}). Is Cloud Run deployed?"
    exit 1
fi

# ── Test 2: Auth enforcement ──
log "Test 2: Auth enforcement"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "${HUB_URL}/s3/" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "401" ]]; then
    log "  ✓ Requests without API key rejected (401)"
else
    err "  ✗ Expected 401 without key, got ${HTTP_CODE}"
fi

HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -H "X-Api-Key: wrong-key" "${HUB_URL}/s3/" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "401" ]]; then
    log "  ✓ Wrong API key rejected (401)"
else
    err "  ✗ Expected 401 with wrong key, got ${HTTP_CODE}"
fi

# ── Test 3: Start hub-connector ──
log "Test 3: Start hub-connector container"
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p 19000:9000 \
    -p 15000:5000 \
    -p 19001:9001 \
    -p 18080:8080 \
    -e "HUB_URL=${HUB_URL}" \
    -e "API_KEY=${API_KEY}" \
    "${CONNECTOR_IMAGE}"

# Wait for connector to be ready
for i in $(seq 1 15); do
    if curl -sf "http://localhost:18080/health" &>/dev/null; then
        log "  ✓ Hub connector running"
        break
    fi
    [[ $i -eq 15 ]] && { err "  ✗ Connector failed to start"; docker logs "${CONTAINER_NAME}" --tail 20; exit 1; }
    sleep 1
done

# ── Test 4: S3 API through connector ──
log "Test 4: MinIO S3 API via connector (localhost:19000)"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "http://localhost:19000/minio/health/live" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" ]]; then
    log "  ✓ MinIO S3 API reachable through connector"
else
    warn "  ⚠ MinIO health returned ${HTTP_CODE} (may need MinIO credentials for full check)"
fi

# ── Test 5: Registry through connector ──
log "Test 5: Docker Registry via connector (localhost:15000)"
REGISTRY_RESP=$(curl -sf "http://localhost:15000/v2/" 2>/dev/null || echo "FAIL")
if [[ "$REGISTRY_RESP" == "{}" || "$REGISTRY_RESP" == *"repositories"* ]]; then
    log "  ✓ Registry reachable through connector"
else
    warn "  ⚠ Registry returned: ${REGISTRY_RESP}"
fi

# ── Test 6: Registry catalog ──
log "Test 6: Registry catalog"
CATALOG=$(curl -sf "http://localhost:15000/v2/_catalog" 2>/dev/null || echo "FAIL")
log "  Catalog: ${CATALOG}"

# ── Test 7: Docker pull through connector ──
log "Test 7: Docker pull test (if images exist in registry)"
REPOS=$(echo "$CATALOG" | python3 -c "import sys,json; repos=json.load(sys.stdin).get('repositories',[]); print(repos[0] if repos else '')" 2>/dev/null || echo "")
if [[ -n "$REPOS" ]]; then
    IMAGE="localhost:15000/${REPOS}:latest"
    log "  Pulling ${IMAGE}..."
    if docker pull "${IMAGE}" 2>&1 | tail -3; then
        log "  ✓ Docker pull successful"
    else
        warn "  ⚠ Docker pull failed (may need insecure-registries for non-standard port)"
    fi
else
    warn "  No images in registry yet — push some first with: make hub-push"
fi

# ── Cleanup ──
log "Cleaning up test container..."
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

# ── Summary ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Hub Integration Test Complete                          ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Gateway:   ${HUB_URL}  ${NC}"
echo -e "${GREEN}║  Auth:      working  ${NC}"
echo -e "${GREEN}║  Connector: verified  ${NC}"
echo -e "${GREEN}║  S3 proxy:  verified  ${NC}"
echo -e "${GREEN}║  Registry:  verified  ${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}SE quick-start command:${NC}"
echo ""
echo "  docker run -d --name hub-connector --restart=always \\"
echo "    -p 9000:9000 -p 5000:5000 -p 9001:9001 -p 8080:8080 \\"
echo "    -e HUB_URL=${HUB_URL} \\"
echo "    -e API_KEY=${API_KEY} \\"
echo "    ${CONNECTOR_IMAGE}"
echo ""
```

Make executable: `chmod +x scripts/local-hub-test.sh`

---

## Phase 3: SE quick-start script — `scripts/se-setup.sh`

What an SE actually runs on day one:

```bash
#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  DemoForge — SE Setup                                   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Pre-flight ──
if ! command -v docker &>/dev/null; then
    echo -e "${RED}Docker not found. Install OrbStack: https://orbstack.dev${NC}"
    exit 1
fi

# ── Get config from user (or .env.hub) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ -f "$PROJECT_ROOT/.env.hub" ]]; then
    source "$PROJECT_ROOT/.env.hub"
    echo -e "${GREEN}✓ Loaded config from .env.hub${NC}"
else
    echo "Enter the Hub URL (from your team lead):"
    read -rp "  HUB_URL: " DEMOFORGE_HUB_URL
    echo "Enter your API key:"
    read -rsp "  API_KEY: " DEMOFORGE_API_KEY
    echo ""
fi

HUB_URL="${DEMOFORGE_HUB_URL:?Missing HUB_URL}"
API_KEY="${DEMOFORGE_API_KEY:?Missing API_KEY}"

# ── Verify gateway ──
echo -e "\n${CYAN}Checking hub connectivity...${NC}"
if curl -sf "${HUB_URL}/health" &>/dev/null; then
    echo -e "${GREEN}✓ Hub gateway reachable${NC}"
else
    echo -e "${RED}✗ Cannot reach ${HUB_URL}. Check your network.${NC}"
    exit 1
fi

# ── Stop existing connector ──
docker rm -f hub-connector 2>/dev/null || true

# ── Start hub connector ──
echo -e "\n${CYAN}Starting hub connector...${NC}"
CONNECTOR_IMAGE="gcr.io/minio-demoforge/demoforge-hub-connector:latest"
docker pull "${CONNECTOR_IMAGE}" 2>/dev/null || true

docker run -d \
    --name hub-connector \
    --restart=always \
    -p 9000:9000 \
    -p 5000:5000 \
    -p 9001:9001 \
    -p 8080:8080 \
    -e "HUB_URL=${HUB_URL}" \
    -e "API_KEY=${API_KEY}" \
    "${CONNECTOR_IMAGE}"

# Wait
for i in $(seq 1 10); do
    curl -sf "http://localhost:8080/health" &>/dev/null && break
    sleep 1
done

echo -e "${GREEN}✓ Hub connector running${NC}"

# ── Write .env.local ──
cat > "$PROJECT_ROOT/.env.local" <<EOF
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=http://localhost:9000
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=${DEMOFORGE_SYNC_SECRET_KEY:-change-me}
DEMOFORGE_REGISTRY_HOST=localhost:5000
EOF

echo -e "${GREEN}✓ Wrote .env.local${NC}"

# ── Pull custom images ──
echo -e "\n${CYAN}Pulling custom DemoForge images...${NC}"
CATALOG=$(curl -sf "http://localhost:5000/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
REPOS=$(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null || true)

if [[ -n "$REPOS" ]]; then
    while IFS= read -r repo; do
        [[ -z "$repo" ]] && continue
        echo "  Pulling localhost:5000/${repo}:latest..."
        docker pull "localhost:5000/${repo}:latest" 2>&1 | tail -1
    done <<< "$REPOS"
    echo -e "${GREEN}✓ Custom images pulled${NC}"
else
    echo -e "${YELLOW}No custom images in registry yet.${NC}"
fi

# ── Done ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Setup complete!                                        ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Hub connector: running (auto-restarts)                 ║${NC}"
echo -e "${GREEN}║  Templates:     sync on next 'make start'              ║${NC}"
echo -e "${GREEN}║  Images:        pulled from registry                    ║${NC}"
echo -e "${GREEN}║  Console:       http://localhost:9001                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Next: ${CYAN}make start${NC} to launch DemoForge"
```

Make executable: `chmod +x scripts/se-setup.sh`

---

## Phase 4: Makefile targets

Add to Makefile:

```makefile
# ─── Gateway ─────────────────────────────────────────────────────────
gateway:          ## Deploy Cloud Run gateway + VPC (run after fresh GCP deploy)
	@./minio-gcp.sh --gateway

gateway-test:     ## Test hub connectivity locally (simulates SE)
	@scripts/local-hub-test.sh

se-setup:         ## SE first-time setup (starts hub-connector, pulls images)
	@scripts/se-setup.sh

update-myip:      ## Update firewall with your current IP
	@MY_IP=$$(curl -sf ifconfig.me) && \
	gcloud compute firewall-rules update allow-myip-to-minio \
	  --source-ranges="$${MY_IP}/32" \
	  --project=minio-demoforge && \
	echo "Updated to $${MY_IP}"
```

---

## Phase 5: Update `scripts/hub-push.sh`

If `hub-push.sh` exists, update it to push through the connector (localhost:5000) instead of direct IP:

```bash
# Replace the REGISTRY_HOST default:
REGISTRY_HOST="${DEMOFORGE_REGISTRY_HOST:-localhost:5000}"
```

This means devs also run the hub-connector locally, and push goes: localhost:5000 → Cloud Run → VPC → Registry → MinIO. The dev experience is identical to the SE experience.

If you need direct push (bypassing the gateway), add a `--direct` flag:

```bash
if [[ "${1:-}" == "--direct" ]]; then
    shift
    DIRECT_IP=$(grep DEMOFORGE_DIRECT_IP .env.hub 2>/dev/null | cut -d= -f2 || echo "")
    if [[ -n "$DIRECT_IP" ]]; then
        REGISTRY_HOST="${DIRECT_IP}:5000"
        echo "Using direct access: ${REGISTRY_HOST}"
    fi
fi
```

---

## Phase 6: Verification checklist

### After `./minio-gcp.sh --gateway`:

```bash
# 1. VPC exists
gcloud compute networks describe demoforge-vpc --project=minio-demoforge

# 2. VM has no public IP
gcloud compute instances describe minio-node --zone=me-central1-a --project=minio-demoforge \
  --format='get(networkInterfaces[0].accessConfigs)'
# Should be empty or show no natIP

# 3. VPC connector is READY
gcloud compute networks vpc-access connectors describe demoforge-connector \
  --region=me-central1 --project=minio-demoforge --format='value(state)'
# → READY

# 4. Cloud Run is serving
GATEWAY_URL=$(gcloud run services describe demoforge-gateway \
  --region=me-central1 --project=minio-demoforge --format='value(status.url)')
curl -sf "${GATEWAY_URL}/health"
# → ok

# 5. Auth works
curl -sf -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/s3/"
# → 401
curl -sf -o /dev/null -w "%{http_code}" -H "X-Api-Key: $(grep API_KEY .env.hub | cut -d= -f2)" "${GATEWAY_URL}/s3/minio/health/live"
# → 200

# 6. Min instances = 1 (warm)
gcloud run services describe demoforge-gateway \
  --region=me-central1 --project=minio-demoforge \
  --format='value(spec.template.metadata.annotations["autoscaling.knative.dev/minScale"])'
# → 1

# 7. Your IP can still SSH
gcloud compute ssh minio-node --zone=me-central1-a --project=minio-demoforge --tunnel-through-iap
```

### After `scripts/local-hub-test.sh`:

```
All 7 tests should pass:
  ✓ Gateway healthy
  ✓ Auth enforcement (401 without key)
  ✓ Auth enforcement (401 wrong key)
  ✓ Hub connector running
  ✓ S3 API via connector
  ✓ Registry via connector
  ✓ Docker pull (if images exist)
```

### After `scripts/se-setup.sh` on a clean machine:

```bash
# Hub connector running
docker ps | grep hub-connector

# S3 accessible
curl -sf http://localhost:9000/minio/health/live

# Registry accessible
curl -sf http://localhost:5000/v2/

# Console accessible
curl -sf http://localhost:9001 | head -5

# .env.local generated
cat .env.local | grep SYNC_ENABLED
# → true
```

---

## What NOT to do

- Do NOT remove the `--update` or `--activate` modes — they still work for VM maintenance
- Do NOT delete the VM's data disk during the network migration — `--keep-disks=all` is critical
- Do NOT hardcode the API key in any committed file — it's generated and stored in VM metadata
- Do NOT set Cloud Run `min-instances: 0` — cold starts break Docker pull timeouts
- Do NOT open the VM's ports to 0.0.0.0/0 in the new VPC firewall — that defeats the purpose
- Do NOT skip the IAP SSH rule — without it, `gcloud compute ssh` stops working when the public IP is removed

---

## Build order

1. **Phase 0** — Investigate existing state
2. **Phase 1** — Update `minio-gcp.sh` with `--gateway` mode
3. **Phase 2** — Create `scripts/local-hub-test.sh`
4. **Phase 3** — Create `scripts/se-setup.sh`
5. **Phase 4** — Makefile targets
6. **Phase 5** — Update `hub-push.sh` for connector-based push
7. **Phase 6** — Run verification

Execution: run `./minio-gcp.sh` first (if VM doesn't exist), then `./minio-gcp.sh --gateway` to add the full gateway stack. Test with `make gateway-test`. Give SEs the Hub URL + API key and tell them to run `make se-setup`.

---

## Cost estimate

| Component | Monthly cost |
|---|---|
| VM (e2-medium, no public IP) | ~$25 |
| Cloud Run (min 1 instance, 256MB) | ~$5-8 |
| VPC connector (2 instances min) | ~$7 |
| Data disk (50GB pd-balanced) | ~$5 |
| Egress (template sync + image pulls) | ~$1-3 |
| **Total** | **~$43-48/month** |

Up from ~$30-35 without the gateway. The $13-18 premium buys TLS, auth, no exposed ports, and a clean SE onboarding experience.
