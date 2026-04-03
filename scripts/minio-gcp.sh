#!/usr/bin/env bash
#
# minio-gcp.sh
# MinIO AIStor Free — GCP Management Script
#
# Usage:
#   ./minio-gcp.sh                  # Fresh deployment (idempotent)
#   ./minio-gcp.sh --update         # Update running MinIO to AIStor image (preserves data, firewall, disk)
#   ./minio-gcp.sh --activate       # Register AIStor Free license on running deployment
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - A GCP billing account linked (deploy mode will prompt)
#
set -euo pipefail

# ─────────────────────────── Configuration ───────────────────────────
PROJECT_ID="minio-demoforge"
REGION="me-central1"            # Doha — closest to Dubai
ZONE="${REGION}-a"
VM_NAME="minio-node"
MACHINE_TYPE="e2-medium"        # 2 vCPU, 4 GB RAM
BOOT_DISK_SIZE="20GB"
DATA_DISK_NAME="minio-data"
DATA_DISK_SIZE="50GB"
DATA_DISK_TYPE="pd-balanced"
NETWORK_TAG="minio-server"
FIREWALL_RULE="allow-minio"
AISTOR_IMAGE="quay.io/minio/aistor/minio:latest"
AISTOR_MC_URL="https://dl.min.io/aistor/mc/release/linux-amd64/mc"
OS_IMAGE_FAMILY="ubuntu-2404-lts-amd64"
OS_IMAGE_PROJECT="ubuntu-os-cloud"

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

# ─────────────────────────── Helpers ─────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

step()    { echo -e "\n${CYAN}▶ STEP $1: $2${NC}"; }
ok()      { echo -e "  ${GREEN}✔ $1${NC}"; }
warn()    { echo -e "  ${YELLOW}⚠ $1${NC}"; }
fail()    { echo -e "  ${RED}✘ $1${NC}"; exit 1; }

verify() {
  if eval "$2" &>/dev/null; then
    ok "$1"
  else
    fail "$1 — aborting."
  fi
}

# Helper: run a command on the VM via SSH (uses IAP tunneling when no public IP)
run_on_vm() {
  gcloud compute ssh "${VM_NAME}" \
    --zone="${ZONE}" \
    --project="${PROJECT_ID}" \
    --tunnel-through-iap \
    --command="$1" \
    --quiet
}

# Helper: get external IP
get_external_ip() {
  gcloud compute instances describe "${VM_NAME}" \
    --zone="${ZONE}" --project="${PROJECT_ID}" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
}

# Helper: read credentials from VM metadata
get_vm_metadata() {
  gcloud compute instances describe "${VM_NAME}" \
    --zone="${ZONE}" --project="${PROJECT_ID}" \
    --format="value(metadata.items.filter(key='$1').extract(value).flatten())" 2>/dev/null || echo ""
}

usage() {
  echo "Usage: $0 [--update | --activate | --gateway]"
  echo ""
  echo "  (no flag)    Fresh deploy — creates project, VM, disk, firewall, runs AIStor"
  echo "  --update     Upgrade running MinIO container to AIStor image (preserves everything)"
  echo "  --activate   Register AIStor Free license on the running deployment"
  echo "  --gateway    Deploy/update Cloud Run gateway + VPC (run AFTER fresh deploy)"
  exit 0
}

# ─────────────────────────── Parse Mode ──────────────────────────────
MODE="deploy"
case "${1:-}" in
  --update)   MODE="update" ;;
  --activate) MODE="activate" ;;
  --gateway)  MODE="gateway" ;;
  --help|-h)  usage ;;
  "")         MODE="deploy" ;;
  *)          echo "Unknown flag: $1"; usage ;;
esac

# ─────────────────────────── Pre-flight (all modes) ──────────────────
command -v gcloud &>/dev/null || fail "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
[[ -n "$ACCOUNT" ]] || fail "No active gcloud account. Run: gcloud auth login"
gcloud config set project "${PROJECT_ID}" --quiet 2>/dev/null
ok "Authenticated as: ${ACCOUNT} | Project: ${PROJECT_ID}"


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

    # Restart MinIO and registry containers
    run_on_vm "sudo docker start minio demoforge-registry 2>/dev/null || true" 2>/dev/null || true
  fi

  # Re-query IPs after potential migration
  INTERNAL_IP=$(gcloud compute instances describe "${VM_NAME}" \
    --zone="${ZONE}" --project="${PROJECT_ID}" \
    --format='get(networkInterfaces[0].networkIP)')
  ok "VM internal IP: ${INTERNAL_IP}"

  EXTERNAL_IP=$(get_external_ip 2>/dev/null || echo "")
  if [[ -z "$EXTERNAL_IP" || "$EXTERNAL_IP" == "None" ]]; then
    EXTERNAL_IP=""
    ok "VM has no public IP (private VPC mode — as intended)."
  else
    ok "VM external IP: ${EXTERNAL_IP}"
  fi

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

  # Hub API admin key (separate from gateway key)
  HUB_API_ADMIN_KEY=$(get_vm_metadata "hub-api-admin-key")
  if [[ -z "$HUB_API_ADMIN_KEY" ]]; then
    HUB_API_ADMIN_KEY="hubadm-$(openssl rand -hex 20)"
    gcloud compute instances add-metadata "${VM_NAME}" \
      --zone="${ZONE}" --project="${PROJECT_ID}" \
      --metadata="hub-api-admin-key=${HUB_API_ADMIN_KEY}"
    ok "Hub API admin key generated and stored in VM metadata."
  else
    ok "Using existing Hub API admin key from VM metadata."
  fi

  # ── Step 7b: Start Hub API service on VM ──
  step "7b" "Start Hub API service on VM"

  run_on_vm "
    # Pull latest hub-api image
    docker pull demoforge/hub-api:latest 2>/dev/null || true

    # Stop existing hub-api container if running
    docker rm -f demoforge-hub-api 2>/dev/null || true

    # Start Hub API service
    docker run -d \
      --name demoforge-hub-api \
      --restart unless-stopped \
      -e HUB_API_ADMIN_API_KEY='${HUB_API_ADMIN_KEY}' \
      -v /data/hub-api:/data/hub-api \
      -p 8000:8000 \
      demoforge/hub-api:latest
  "

  # Verify hub-api is running
  sleep 2
  if run_on_vm "curl -sf http://localhost:8000/health" &>/dev/null; then
    ok "Hub API service is healthy."
  else
    warn "Hub API service may need a moment to start. Continuing..."
  fi

  # ── Step 8: Build and deploy Cloud Run gateway ──
  step 8 "Build and deploy Cloud Run gateway"

  # Create gateway source directory
  GATEWAY_DIR=$(mktemp -d /tmp/demoforge-gateway-XXXXXX)

  # Write Caddyfile — uses Caddy env vars for secrets, shell vars for infrastructure
  # Routing uses X-Service header (not path rewriting) to preserve S3 signature integrity
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

  # API key validation — uses runtime env var (not baked into image)
  @nokey {
    not header X-Api-Key {env.GATEWAY_API_KEY}
  }
  handle @nokey {
    respond "Unauthorized — X-Api-Key header required" 401
  }

  # S3 API → MinIO (routed by X-Service header to preserve S3 signatures)
  @s3 {
    header X-Service s3
  }
  handle @s3 {
    request_header -X-Service
    reverse_proxy ${INTERNAL_IP}:9000
  }

  # MinIO Console (routed by X-Service header)
  @console {
    header X-Service console
  }
  handle @console {
    request_header -X-Service
    reverse_proxy ${INTERNAL_IP}:9001
  }

  # Licenses bucket (anonymous read — path rewrite to MinIO bucket)
  handle_path /licenses/* {
    rewrite * /demoforge-licenses{uri}
    reverse_proxy ${INTERNAL_IP}:9000
  }

  # Templates bucket (anonymous read — path rewrite to MinIO bucket)
  handle_path /templates/* {
    rewrite * /demoforge-templates{uri}
    reverse_proxy ${INTERNAL_IP}:9000
  }

  # Hub API (routed by X-Service header)
  @hub_api {
    header X-Service hub-api
  }
  handle @hub_api {
    request_header -X-Service
    reverse_proxy ${INTERNAL_IP}:8000
  }

  # Docker Registry v2 API (path-based — Docker client doesn't sign requests)
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
    --set-env-vars="GATEWAY_TARGET=${INTERNAL_IP},GATEWAY_API_KEY=${GATEWAY_API_KEY}" \
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
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/s3/" 2>/dev/null)
  if [[ "$HTTP_CODE" == "401" ]]; then
    ok "Auth enforcement working (401 without API key)."
  else
    warn "Expected 401 without API key, got ${HTTP_CODE}."
  fi

  # Auth check — should pass with key
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Api-Key: ${GATEWAY_API_KEY}" "${GATEWAY_URL}/s3/minio/health/live" 2>/dev/null)
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

# S3 API proxy — route via X-Service header (preserves S3 signatures)
:9000 {
  reverse_proxy {$HUB_URL} {
    header_up X-Api-Key {$API_KEY}
    header_up X-Service s3
  }
}

# Docker Registry proxy — /v2 path-based routing on gateway
:5000 {
  reverse_proxy {$HUB_URL} {
    header_up X-Api-Key {$API_KEY}
  }
}

# MinIO Console proxy — route via X-Service header
:9001 {
  reverse_proxy {$HUB_URL} {
    header_up X-Api-Key {$API_KEY}
    header_up X-Service console
  }
}

# Health + Licenses + Hub API endpoint
:8080 {
  handle /health {
    rewrite * /health
    reverse_proxy {$HUB_URL}
  }
  handle /api/hub/* {
    reverse_proxy {$HUB_URL} {
      header_up X-Api-Key {$API_KEY}
      header_up X-Service hub-api
    }
  }
  handle /licenses/* {
    reverse_proxy {$HUB_URL} {
      header_up X-Api-Key {$API_KEY}
    }
  }
  handle /templates/* {
    reverse_proxy {$HUB_URL} {
      header_up X-Api-Key {$API_KEY}
    }
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

  # Also push to the private registry on the VM (so Field Architects can pull it)
  # Only works if VM still has a public IP (pre-VPC migration or dev IP whitelisted)
  if [[ -n "$EXTERNAL_IP" && -n "$MY_IP" ]]; then
    docker pull "${CONNECTOR_IMAGE}" 2>/dev/null || true
    PRIVATE_TAG="${EXTERNAL_IP}:5000/demoforge/hub-connector:latest"
    docker tag "${CONNECTOR_IMAGE}" "${PRIVATE_TAG}" 2>/dev/null || true
    docker push "${PRIVATE_TAG}" 2>/dev/null || warn "Could not push to private registry. Push manually later."
  elif [[ -z "$EXTERNAL_IP" ]]; then
    warn "VM has no public IP — skipping private registry push."
    warn "Push manually via hub-connector: make hub-push"
  fi

  rm -rf "${CONNECTOR_DIR}"

  # ── Step 11: Generate .env.hub ──
  step 11 "Generate .env.hub"

  ENV_FILE="$(dirname "$0")/../.env.hub"
  cat > "${ENV_FILE}" <<ENV_EOF
# DemoForge Hub Configuration
# Generated by minio-gcp.sh --gateway on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Copy to .env.local:  cp .env.hub .env.local

# ── Gateway ──
DEMOFORGE_HUB_URL=${GATEWAY_URL}
DEMOFORGE_API_KEY=${GATEWAY_API_KEY}

# ── Hub API ──
DEMOFORGE_HUB_API_ADMIN_KEY=${HUB_API_ADMIN_KEY}

# ── Template Sync (via gateway) ──
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=${GATEWAY_URL}/s3
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=

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
  echo -e "${GREEN}║  Hub API Key : ${HUB_API_ADMIN_KEY:0:12}...  ${NC}"
  echo -e "${GREEN}║  VM internal : ${INTERNAL_IP}  ${NC}"
  echo -e "${GREEN}║  VPC         : ${VPC_NAME} / ${SUBNET_NAME}  ${NC}"
  echo -e "${GREEN}║  Connector   : ${VPC_CONNECTOR_NAME}  ${NC}"
  echo -e "${GREEN}║  Min instances: 1 (warm — no cold starts)  ${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Hub connector image: ${CONNECTOR_IMAGE}  ${NC}"
  if [[ -n "$EXTERNAL_IP" ]]; then
    echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║  Your IP (${MY_IP}) has direct access  ${NC}"
  else
    echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║  VM has no public IP — access via gateway or IAP only   ║${NC}"
    echo -e "${GREEN}║  SSH: gcloud compute ssh ${VM_NAME} --tunnel-through-iap  ${NC}"
  fi
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${YELLOW}Field Architect setup (one command):${NC}"
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

# ═════════════════════════════════════════════════════════════════════
# MODE: --activate
# ═════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "activate" ]]; then
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  MinIO AIStor Free — License Activation                ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

  # ── Step 1: Verify VM is running ──
  step 1 "Verify VM [${VM_NAME}] is running"
  verify "VM is RUNNING" \
    "gcloud compute instances describe ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --format='value(status)' | grep -q RUNNING"

  EXTERNAL_IP=$(get_external_ip)
  ok "External IP: ${EXTERNAL_IP}"

  # ── Step 2: Read credentials from VM metadata ──
  step 2 "Read MinIO credentials from VM metadata"
  MINIO_ROOT_USER=$(get_vm_metadata "minio-root-user")
  MINIO_ROOT_PASSWORD=$(get_vm_metadata "minio-root-password")

  if [[ -z "$MINIO_ROOT_USER" || -z "$MINIO_ROOT_PASSWORD" ]]; then
    warn "Could not read credentials from metadata. You'll be prompted on the VM."
    MINIO_ROOT_USER=""
    MINIO_ROOT_PASSWORD=""
  else
    ok "Credentials retrieved from instance metadata."
  fi

  # ── Step 3: Ensure mc is installed on VM ──
  step 3 "Ensure AIStor mc client is installed on VM"
  run_on_vm "
    if ! command -v mc &>/dev/null && [ ! -f /usr/local/bin/mc ]; then
      echo 'Installing mc...'
      sudo curl --progress-bar -L ${AISTOR_MC_URL} -o /usr/local/bin/mc
      sudo chmod +x /usr/local/bin/mc
    fi
    mc --version
  "
  ok "mc client ready."

  # ── Step 4: Set mc alias ──
  step 4 "Configure mc alias for local MinIO"
  if [[ -n "$MINIO_ROOT_USER" ]]; then
    run_on_vm "sudo mc alias set local http://localhost:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}'"
    ok "mc alias 'local' configured."
  else
    echo "  Run this on the VM manually:"
    echo "    sudo mc alias set local http://localhost:9000 <USER> <PASSWORD>"
    fail "Cannot proceed without credentials."
  fi

  # ── Step 5: Register license ──
  step 5 "Register AIStor Free license"
  echo ""
  echo -e "  ${YELLOW}This will output a SUBNET registration URL.${NC}"
  echo -e "  ${YELLOW}Open it in your browser, sign up / log in, and select the Free plan.${NC}"
  echo -e "  ${YELLOW}The license will be applied automatically once registration completes.${NC}"
  echo ""
  read -p "  Press Enter to proceed..."
  echo ""

  # Run interactively so the user can see the URL
  gcloud compute ssh "${VM_NAME}" \
    --zone="${ZONE}" \
    --project="${PROJECT_ID}" \
    -- "sudo mc license register local"

  # ── Step 6: Verify license ──
  step 6 "Verify license status"
  echo ""
  run_on_vm "sudo mc license info local" || warn "Could not verify license. Check manually: sudo mc license info local"

  # ── Done ──
  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║  LICENSE ACTIVATION COMPLETE                            ║${NC}"
  echo -e "${GREEN}║                                                        ║${NC}"
  echo -e "${GREEN}║  Console : http://${EXTERNAL_IP}:9001                   ${NC}"
  echo -e "${GREEN}║  API     : http://${EXTERNAL_IP}:9000                   ${NC}"
  echo -e "${GREEN}║                                                        ║${NC}"
  echo -e "${GREEN}║  S3 operations should now be fully enabled.            ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
  exit 0
fi


# ═════════════════════════════════════════════════════════════════════
# MODE: --update
# ═════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "update" ]]; then
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  MinIO AIStor — In-Place Update                        ║${NC}"
  echo -e "${CYAN}║  Image: ${AISTOR_IMAGE}            ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

  # ── Step 1: Verify VM is running ──
  step 1 "Verify VM [${VM_NAME}] is running"
  verify "VM is RUNNING" \
    "gcloud compute instances describe ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --format='value(status)' | grep -q RUNNING"

  EXTERNAL_IP=$(get_external_ip)
  ok "External IP: ${EXTERNAL_IP}"

  # ── Step 2: Read current credentials from VM metadata ──
  step 2 "Read MinIO credentials from VM metadata"
  MINIO_ROOT_USER=$(get_vm_metadata "minio-root-user")
  MINIO_ROOT_PASSWORD=$(get_vm_metadata "minio-root-password")

  if [[ -z "$MINIO_ROOT_USER" ]]; then
    fail "Could not read minio-root-user from instance metadata."
  fi
  ok "User: ${MINIO_ROOT_USER}"

  # ── Step 3: Snapshot current container info ──
  step 3 "Check current MinIO container"
  CURRENT_IMAGE=$(run_on_vm "sudo docker inspect minio --format='{{.Config.Image}}' 2>/dev/null" || echo "unknown")
  echo "  Current image: ${CURRENT_IMAGE}"
  echo "  Target image : ${AISTOR_IMAGE}"

  if [[ "$CURRENT_IMAGE" == "$AISTOR_IMAGE" ]]; then
    warn "Already running the target image. Pulling latest tag anyway..."
  fi

  # ── Step 4: Pull new image ──
  step 4 "Pull AIStor image on VM"
  run_on_vm "sudo docker pull ${AISTOR_IMAGE}"
  ok "Image pulled."

  # ── Step 5: Stop old container, start new one ──
  step 5 "Swap MinIO container (data is preserved on /mnt/minio-data)"
  run_on_vm "
    set -e
    echo 'Stopping old container...'
    sudo docker stop minio 2>/dev/null || true
    sudo docker rm minio 2>/dev/null || true

    echo 'Starting AIStor container...'
    sudo docker run -d \
      --name minio \
      --restart always \
      -p 9000:9000 \
      -p 9001:9001 \
      -e \"MINIO_ROOT_USER=${MINIO_ROOT_USER}\" \
      -e \"MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}\" \
      -v /mnt/minio-data/data:/data \
      ${AISTOR_IMAGE} \
      server /data --console-address ':9001'

    echo 'Container started.'
  "
  ok "Container swapped to AIStor image."

  # ── Step 6: Install mc on VM ──
  step 6 "Install AIStor mc client"
  run_on_vm "
    sudo curl --progress-bar -L ${AISTOR_MC_URL} -o /usr/local/bin/mc
    sudo chmod +x /usr/local/bin/mc
    mc --version
  "
  ok "mc client installed."

  # ── Step 7: Health check ──
  step 7 "Wait for AIStor to respond"
  HEALTHY=false
  for i in $(seq 1 24); do
    if curl -sf --connect-timeout 3 "http://${EXTERNAL_IP}:9000/minio/health/live" &>/dev/null; then
      HEALTHY=true
      break
    fi
    echo "  ... attempt ${i}/24 — retrying in 5s"
    sleep 5
  done

  if [[ "$HEALTHY" == "true" ]]; then
    ok "MinIO AIStor is running (offline mode until license is registered)."
  else
    warn "Not responding yet. Check: gcloud compute ssh ${VM_NAME} --zone=${ZONE} -- 'sudo docker logs minio --tail 30'"
  fi

  # ── Step 8: Ensure registry container is running ──
  step 8 "Ensure Docker Registry container is running"
  REGISTRY_RUNNING=$(run_on_vm "sudo docker ps --format '{{.Names}}' | grep -c demoforge-registry || true")
  if [[ "$REGISTRY_RUNNING" == "0" ]]; then
    warn "Registry not running. Checking if config exists..."
    run_on_vm "
      if [ -f /opt/demoforge-registry/config.yml ]; then
        sudo docker rm -f demoforge-registry 2>/dev/null || true
        sudo docker run -d \
          --name demoforge-registry \
          --restart always \
          --network host \
          -v /opt/demoforge-registry/config.yml:/etc/docker/registry/config.yml:ro \
          registry:2
        echo 'Registry started.'
      else
        echo 'No registry config found. Run fresh deploy to set up registry.'
      fi
    "
  else
    ok "Registry container already running."
  fi

  # ── Step 9: Verify data integrity ──
  step 9 "Verify data disk is mounted and accessible"
  DATA_CHECK=$(run_on_vm "ls /mnt/minio-data/data/ 2>/dev/null && echo 'OK'" || echo "FAIL")
  if [[ "$DATA_CHECK" == *"OK"* ]]; then
    ok "Data disk mounted — existing data preserved."
  else
    warn "Data directory check inconclusive. SSH in and verify /mnt/minio-data/data/"
  fi

  # ── Summary ──
  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║         MinIO AIStor — UPDATE COMPLETE                  ║${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Previous : ${CURRENT_IMAGE}  ${NC}"
  echo -e "${GREEN}║  Current  : ${AISTOR_IMAGE}   ${NC}"
  echo -e "${GREEN}║  Console  : http://${EXTERNAL_IP}:9001                  ${NC}"
  echo -e "${GREEN}║  API      : http://${EXTERNAL_IP}:9000                  ${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Data     : preserved (/mnt/minio-data/data)           ║${NC}"
  echo -e "${GREEN}║  Firewall : unchanged                                  ║${NC}"
  echo -e "${GREEN}║  Disk     : unchanged                                  ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${YELLOW}Next step — activate the AIStor Free license:${NC}"
  echo "  ./$(basename "$0") --activate"
  exit 0
fi


# ═════════════════════════════════════════════════════════════════════
# MODE: deploy (default — fresh deployment, idempotent)
# ═════════════════════════════════════════════════════════════════════
MINIO_ROOT_PASSWORD="minioadmin-$(openssl rand -hex 6)"

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  MinIO AIStor Free — Fresh GCP Deployment               ║${NC}"
echo -e "${CYAN}║  Project : ${PROJECT_ID}                              ║${NC}"
echo -e "${CYAN}║  Region  : ${REGION}                            ║${NC}"
echo -e "${CYAN}║  VM      : ${MACHINE_TYPE} · ${DATA_DISK_SIZE} data disk            ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Create Project ──
step 1 "Create GCP project [${PROJECT_ID}]"
if gcloud projects describe "${PROJECT_ID}" &>/dev/null; then
  warn "Project ${PROJECT_ID} already exists — reusing."
else
  gcloud projects create "${PROJECT_ID}" --name="MinIO DemoForge" --set-as-default
  ok "Project created."
fi
gcloud config set project "${PROJECT_ID}"
verify "Active project is ${PROJECT_ID}" \
  "[[ \$(gcloud config get-value project 2>/dev/null) == '${PROJECT_ID}' ]]"

# ── Step 2: Link Billing ──
step 2 "Link billing account"
BILLING_ACCOUNT=$(gcloud billing accounts list --filter="open=true" --format="value(ACCOUNT_ID)" --limit=1 2>/dev/null || true)
[[ -n "$BILLING_ACCOUNT" ]] || fail "No active billing account found. https://console.cloud.google.com/billing"
CURRENT_BILLING=$(gcloud billing projects describe "${PROJECT_ID}" --format="value(billingAccountName)" 2>/dev/null || true)
if [[ -z "$CURRENT_BILLING" || "$CURRENT_BILLING" == "" ]]; then
  gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT}"
  ok "Linked billing account: ${BILLING_ACCOUNT}"
else
  ok "Billing already linked."
fi
verify "Billing is active" \
  "gcloud billing projects describe ${PROJECT_ID} --format='value(billingEnabled)' 2>/dev/null | grep -qi true"

# ── Step 3: Enable APIs ──
step 3 "Enable Compute Engine API"
gcloud services enable compute.googleapis.com --project="${PROJECT_ID}"
echo "  Waiting for API propagation..."
for i in $(seq 1 12); do
  if gcloud compute regions list --project="${PROJECT_ID}" &>/dev/null; then
    ok "Compute Engine API is ready."
    break
  fi
  sleep 5
done
verify "Compute Engine API responsive" \
  "gcloud compute regions list --project=${PROJECT_ID} --limit=1"

# ── Step 4: Create Data Disk ──
step 4 "Create persistent data disk [${DATA_DISK_NAME}] — ${DATA_DISK_SIZE}"
if gcloud compute disks describe "${DATA_DISK_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" &>/dev/null; then
  warn "Disk ${DATA_DISK_NAME} already exists — reusing."
else
  gcloud compute disks create "${DATA_DISK_NAME}" \
    --project="${PROJECT_ID}" --zone="${ZONE}" \
    --size="${DATA_DISK_SIZE}" --type="${DATA_DISK_TYPE}"
  ok "Disk created."
fi
verify "Disk exists" \
  "gcloud compute disks describe ${DATA_DISK_NAME} --zone=${ZONE} --project=${PROJECT_ID}"

# ── Step 5: Firewall Rules ──
step 5 "Create firewall rules for MinIO (ports 9000, 9001) and Registry (5000)"
if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" &>/dev/null; then
  # Update existing rule to include port 5000
  CURRENT_PORTS=$(gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" --format="value(allowed[].map().firewall_rule().list())" 2>/dev/null || true)
  if [[ "$CURRENT_PORTS" != *"5000"* ]]; then
    gcloud compute firewall-rules update "${FIREWALL_RULE}" \
      --project="${PROJECT_ID}" \
      --rules=tcp:9000,tcp:9001,tcp:5000
    ok "Firewall rule updated to include port 5000 (registry)."
  else
    warn "Firewall rule ${FIREWALL_RULE} already exists with port 5000 — reusing."
  fi
else
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
    --project="${PROJECT_ID}" --direction=INGRESS --priority=1000 \
    --network=default --action=ALLOW --rules=tcp:9000,tcp:9001,tcp:5000 \
    --source-ranges=0.0.0.0/0 --target-tags="${NETWORK_TAG}" \
    --description="Allow MinIO API (9000), Console (9001), Registry (5000)"
  ok "Firewall rule created."
fi
verify "Firewall rule exists" \
  "gcloud compute firewall-rules describe ${FIREWALL_RULE} --project=${PROJECT_ID}"

# ── Step 6: Create VM ──
step 6 "Create VM instance [${VM_NAME}]"

# Write startup script to temp file
STARTUP_FILE=$(mktemp /tmp/minio-startup-XXXXXX.sh)
cat > "${STARTUP_FILE}" <<'STARTUP'
#!/bin/bash
set -euo pipefail
exec > /var/log/minio-setup.log 2>&1
echo "=== MinIO AIStor Setup Started at $(date) ==="

# ── Format & mount the data disk ──
DATA_DEV="/dev/disk/by-id/google-minio-data"
MOUNT_POINT="/mnt/minio-data"

if ! blkid "${DATA_DEV}" &>/dev/null; then
  echo "Formatting data disk..."
  mkfs.ext4 -m 0 -F -E lazy_itable_init=0,lazy_journal_init=0 "${DATA_DEV}"
fi

mkdir -p "${MOUNT_POINT}"
if ! mountpoint -q "${MOUNT_POINT}"; then
  mount -o discard,defaults "${DATA_DEV}" "${MOUNT_POINT}"
  grep -q "${MOUNT_POINT}" /etc/fstab || \
    echo "UUID=$(blkid -s UUID -o value ${DATA_DEV})  ${MOUNT_POINT}  ext4  discard,defaults,nofail  0 2" >> /etc/fstab
fi
mkdir -p "${MOUNT_POINT}/data"

# ── Install Docker ──
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable docker && systemctl start docker

# ── Read credentials from instance metadata ──
META="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
MINIO_USER=$(curl -sf "${META}/minio-root-user" -H "Metadata-Flavor: Google" || echo "minioadmin")
MINIO_PASS=$(curl -sf "${META}/minio-root-password" -H "Metadata-Flavor: Google" || echo "minioadmin")

# ── Run MinIO AIStor container ──
docker rm -f minio 2>/dev/null || true
docker run -d \
  --name minio \
  --restart always \
  -p 9000:9000 \
  -p 9001:9001 \
  -e "MINIO_ROOT_USER=${MINIO_USER}" \
  -e "MINIO_ROOT_PASSWORD=${MINIO_PASS}" \
  -v /mnt/minio-data/data:/data \
  quay.io/minio/aistor/minio:latest \
  server /data --console-address ":9001"

# ── Install mc (AIStor client) ──
curl --progress-bar -L https://dl.min.io/aistor/mc/release/linux-amd64/mc -o /usr/local/bin/mc
chmod +x /usr/local/bin/mc

# ── Wait for MinIO to be ready before setting up registry ──
echo "Waiting for MinIO to be ready..."
for i in $(seq 1 30); do
  curl -sf http://localhost:9000/minio/health/live &>/dev/null && break
  sleep 2
done

# ── Create registry bucket and service account ──
mc alias set local http://localhost:9000 "${MINIO_USER}" "${MINIO_PASS}" 2>/dev/null || true

# Create registry bucket (idempotent)
mc mb local/demoforge-registry 2>/dev/null || true

# Create registry IAM policy
cat > /tmp/registry-policy.json <<'REGPOL'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket","s3:GetBucketLocation","s3:ListMultipartUploadParts","s3:AbortMultipartUpload","s3:ListBucketMultipartUploads"],
    "Resource": ["arn:aws:s3:::demoforge-registry","arn:aws:s3:::demoforge-registry/*"]
  }]
}
REGPOL
mc admin policy create local demoforge-registry-policy /tmp/registry-policy.json 2>/dev/null || true

# Create registry service account (idempotent)
REGISTRY_PASS="registry-$(openssl rand -hex 12)"
if ! mc admin user info local demoforge-registry &>/dev/null; then
  mc admin user add local demoforge-registry "${REGISTRY_PASS}"
  mc admin policy attach local demoforge-registry-policy --user demoforge-registry
fi
# Read back password if user already exists (use metadata fallback)
REG_PASS_META=$(curl -sf "${META}/registry-password" -H "Metadata-Flavor: Google" || echo "")
if [ -n "${REG_PASS_META}" ]; then
  REGISTRY_PASS="${REG_PASS_META}"
fi

# ── Write registry config ──
mkdir -p /opt/demoforge-registry
cat > /opt/demoforge-registry/config.yml <<REGCFG
version: 0.1
log:
  level: info
  formatter: text
storage:
  s3:
    accesskey: demoforge-registry
    secretkey: ${REGISTRY_PASS}
    region: us-east-1
    regionendpoint: http://localhost:9000
    bucket: demoforge-registry
    rootdirectory: /docker/registry
    encrypt: false
    secure: false
    v4auth: true
    chunksize: 5242880
  delete:
    enabled: true
  redirect:
    disable: true
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
REGCFG

# ── Run Docker Registry container ──
docker rm -f demoforge-registry 2>/dev/null || true
docker run -d \
  --name demoforge-registry \
  --restart always \
  --network host \
  -v /opt/demoforge-registry/config.yml:/etc/docker/registry/config.yml:ro \
  registry:2

echo "=== MinIO AIStor + Registry Setup Completed at $(date) ==="
STARTUP

ok "Startup script written to ${STARTUP_FILE}"

if gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" &>/dev/null; then
  warn "VM ${VM_NAME} already exists — reusing."
else
  gcloud compute instances create "${VM_NAME}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --machine-type="${MACHINE_TYPE}" \
    --image-family="${OS_IMAGE_FAMILY}" \
    --image-project="${OS_IMAGE_PROJECT}" \
    --boot-disk-size="${BOOT_DISK_SIZE}" \
    --boot-disk-type=pd-balanced \
    --disk="name=${DATA_DISK_NAME},device-name=minio-data,mode=rw,boot=no,auto-delete=no" \
    --tags="${NETWORK_TAG}" \
    --metadata="minio-root-user=minioadmin,minio-root-password=${MINIO_ROOT_PASSWORD}" \
    --metadata-from-file="startup-script=${STARTUP_FILE}" \
    --scopes=default
  ok "VM created."
fi
rm -f "${STARTUP_FILE}"

verify "VM is RUNNING" \
  "gcloud compute instances describe ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --format='value(status)' | grep -q RUNNING"

# ── Step 7: Wait for MinIO ──
step 7 "Wait for AIStor to come online"
EXTERNAL_IP=$(get_external_ip)
echo "  External IP: ${EXTERNAL_IP}"

HEALTHY=false
for i in $(seq 1 36); do
  if curl -sf --connect-timeout 3 "http://${EXTERNAL_IP}:9000/minio/health/live" &>/dev/null; then
    HEALTHY=true
    break
  fi
  echo "  ... attempt ${i}/36 — retrying in 5s"
  sleep 5
done

if [[ "$HEALTHY" == "true" ]]; then
  ok "MinIO AIStor is running (offline mode — license needed)."
else
  warn "Not responding yet. Check: gcloud compute ssh ${VM_NAME} --zone=${ZONE} -- 'sudo cat /var/log/minio-setup.log'"
fi

# ── Step 8: Wait for Registry ──
step 8 "Wait for Docker Registry to come online"
REG_HEALTHY=false
for i in $(seq 1 24); do
  if curl -sf --connect-timeout 3 "http://${EXTERNAL_IP}:5000/v2/" &>/dev/null; then
    REG_HEALTHY=true
    break
  fi
  echo "  ... attempt ${i}/24 — retrying in 5s"
  sleep 5
done

if [[ "$REG_HEALTHY" == "true" ]]; then
  ok "Docker Registry is running at http://${EXTERNAL_IP}:5000"
else
  warn "Registry not responding yet. It may need more time for MinIO to be ready first."
fi

# ── Summary ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       MinIO AIStor Free — DEPLOYMENT COMPLETE          ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Project  : ${PROJECT_ID}                              ║${NC}"
echo -e "${GREEN}║  VM       : ${VM_NAME} (${MACHINE_TYPE})               ║${NC}"
echo -e "${GREEN}║  Zone     : ${ZONE}                             ║${NC}"
echo -e "${GREEN}║  Disk     : ${DATA_DISK_SIZE} ${DATA_DISK_TYPE}                     ║${NC}"
echo -e "${GREEN}║  Image    : ${AISTOR_IMAGE}   ${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Console  : http://${EXTERNAL_IP}:9001                  ${NC}"
echo -e "${GREEN}║  API      : http://${EXTERNAL_IP}:9000                  ${NC}"
echo -e "${GREEN}║  Registry : http://${EXTERNAL_IP}:5000                  ${NC}"
echo -e "${GREEN}║  User     : minioadmin                                 ║${NC}"
echo -e "${GREEN}║  Password : ${MINIO_ROOT_PASSWORD}              ${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Cost     : ~\$30–35/month (CUD: ~\$20–22/month)        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Next step — activate the AIStor Free license:${NC}"
echo "  ./$(basename "$0") --activate"
echo ""
echo -e "${YELLOW}Security:${NC}"
echo "  Restrict firewall: gcloud compute firewall-rules update ${FIREWALL_RULE} --source-ranges=<YOUR_IP>/32 --project=${PROJECT_ID}"
echo ""
echo "Useful commands:"
echo "  SSH        : gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID}"
echo "  Logs       : gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} -- 'sudo docker logs minio --tail 50'"
echo "  Stop       : gcloud compute instances stop ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID}"
echo "  Delete all : gcloud projects delete ${PROJECT_ID}"
echo ""
echo -e "${YELLOW}To add Cloud Run gateway (VPC + HTTPS + auth):${NC}"
echo "  ./$(basename "$0") --gateway"
