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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
HUB_API_IMAGE="gcr.io/${PROJECT_ID}/demoforge-hub-api:latest"
HUB_API_SERVICE="demoforge-hub-api"
HUB_API_SA_NAME="demoforge-hub-api"
LITESTREAM_BUCKET="${PROJECT_ID}-demoforge-hub-litestream"

# API key for gateway auth (generated on first deploy, stored in metadata)
GATEWAY_API_KEY=""

ENV_FILE="${SCRIPT_DIR}/../.env.hub"

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

# Helper: provision GCS bucket + service account + IAM for Litestream (idempotent)
setup_hub_api_litestream_infra() {
  local bucket="gs://${LITESTREAM_BUCKET}"
  local sa="${HUB_API_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  # GCS bucket (versioning on, uniform ACL, regional)
  if ! gcloud storage buckets describe "${bucket}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud storage buckets create "${bucket}" \
      --project="${PROJECT_ID}" \
      --location="${CLOUD_RUN_REGION}" \
      --uniform-bucket-level-access \
      --quiet
    gcloud storage buckets update "${bucket}" --versioning --quiet
    ok "Created Litestream bucket: ${bucket}"
  else
    ok "Litestream bucket already exists: ${bucket}"
  fi

  # Service account
  if ! gcloud iam service-accounts describe "${sa}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud iam service-accounts create "${HUB_API_SA_NAME}" \
      --project="${PROJECT_ID}" \
      --display-name="DemoForge Hub API (Litestream)" \
      --quiet
    ok "Created service account: ${sa}"
  else
    ok "Service account already exists: ${sa}"
  fi

  # objectAdmin on the bucket only (not project-wide)
  gcloud storage buckets add-iam-policy-binding "${bucket}" \
    --member="serviceAccount:${sa}" \
    --role="roles/storage.objectAdmin" \
    --project="${PROJECT_ID}" \
    --quiet 2>/dev/null || true
  ok "IAM binding set: ${sa} → objectAdmin on ${bucket}"
}

# Helper: build hub-api image and deploy/update the Cloud Run service
deploy_hub_api_cloudrun() {
  local admin_key="${1:-}"
  local connector_key="${2:-}"

  # Fall back to .env.hub when called from --deploy-api
  [[ -z "$admin_key" ]]      && admin_key=$(grep "^DEMOFORGE_HUB_API_ADMIN_KEY=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "")
  [[ -z "$connector_key" ]]  && connector_key=$(grep "^DEMOFORGE_API_KEY=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "")

  [[ -z "$admin_key" ]] && fail "hub-api-admin-key not available. Run 'make hub-update-gateway' first."

  local hub_api_dir
  hub_api_dir="$(dirname "$SCRIPT_DIR")/hub-api"
  [[ -f "${hub_api_dir}/Dockerfile" ]] || fail "hub-api/Dockerfile not found at ${hub_api_dir}"

  setup_hub_api_litestream_infra

  local sa="${HUB_API_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  ok "Building hub-api image via Cloud Build..."
  gcloud builds submit "${hub_api_dir}" \
    --project="${PROJECT_ID}" \
    --tag="${HUB_API_IMAGE}" \
    --quiet

  ok "Deploying hub-api to Cloud Run..."
  gcloud run deploy "${HUB_API_SERVICE}" \
    --project="${PROJECT_ID}" \
    --region="${CLOUD_RUN_REGION}" \
    --image="${HUB_API_IMAGE}" \
    --platform=managed \
    --port=8000 \
    --allow-unauthenticated \
    --service-account="${sa}" \
    --min-instances=1 \
    --max-instances=1 \
    --cpu=1 --memory=512Mi \
    --cpu-boost \
    --no-cpu-throttling \
    --timeout=300 \
    --concurrency=80 \
    --set-env-vars="LITESTREAM_BUCKET=${LITESTREAM_BUCKET},HUB_API_ADMIN_API_KEY=${admin_key},HUB_API_CONNECTOR_KEY=${connector_key},HUB_API_DATABASE_PATH=/data/hub-api/demoforge-hub.db,HUB_API_TEMPLATES_BUCKET=demoforge-hub-templates,HUB_API_LICENSES_BUCKET=demoforge-hub-licenses" \
    --quiet

  HUB_API_URL=$(gcloud run services describe "${HUB_API_SERVICE}" \
    --region="${CLOUD_RUN_REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)')
  HUB_API_HOST="${HUB_API_URL#https://}"

  # URL is written to .env.hub at end of deploy

  ok "Hub API deployed: ${HUB_API_URL}"

  # Health check
  sleep 3
  if curl -sf "${HUB_API_URL}/health" &>/dev/null; then
    ok "Hub API health check passed."
  else
    warn "Hub API may still be starting — check: curl ${HUB_API_URL}/health"
  fi
}

# Helper: build gateway image and deploy/update the Cloud Run gateway service
deploy_gateway_cloudrun() {
  local gateway_api_key="${1:-}"
  local hub_api_host="${2:-}"

  # Fall back to .env.hub, then gcloud, when called from --deploy-gateway
  [[ -z "$gateway_api_key" ]] && gateway_api_key=$(grep "^DEMOFORGE_API_KEY=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "")
  [[ -z "$hub_api_host" ]]    && hub_api_host=$(grep "^DEMOFORGE_HUB_API_URL=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | sed 's|^https://||' || echo "")
  [[ -z "$hub_api_host" ]]    && hub_api_host=$(gcloud run services describe "${HUB_API_SERVICE}" \
    --project="${PROJECT_ID}" --region="${CLOUD_RUN_REGION}" \
    --format='value(status.url)' 2>/dev/null | sed 's|^https://||' || echo "")

  [[ -z "$gateway_api_key" ]] && fail "gateway-api-key not found. Run 'make hub-deploy' first."
  [[ -z "$hub_api_host" ]]    && fail "hub-api-url not found. Run 'make hub-deploy-api' first."

  local GATEWAY_DIR
  GATEWAY_DIR=$(mktemp -d /tmp/demoforge-gateway-XXXXXX)

  # Gateway is now a pure auth-gating proxy to hub-api Cloud Run.
  # MinIO S3/console, registry, and license/template bucket routes removed
  # (storage migrated to GCS; templates/licenses served by hub-api directly).
  cat > "${GATEWAY_DIR}/Caddyfile" <<'CADDY_EOF'
{
  auto_https off
  admin off
}

:8080 {
  # Health check — no auth required
  handle /health {
    respond "ok" 200
  }

  # FA bootstrap — no gateway key required; hub-api validates FA key directly
  # Called by fa-setup.sh before the connector exists
  handle /api/hub/fa/bootstrap {
    reverse_proxy {env.HUB_API_HOST}:443 {
      header_up Host {env.HUB_API_HOST}
      transport http {
        tls
        tls_server_name {env.HUB_API_HOST}
      }
    }
  }

  # API key validation — uses runtime env var (not baked into image)
  @nokey {
    not header X-Api-Key {env.GATEWAY_API_KEY}
  }
  handle @nokey {
    respond "Unauthorized — X-Api-Key header required" 401
  }

  # All authenticated traffic → hub-api Cloud Run
  handle {
    request_header -X-Service
    reverse_proxy {env.HUB_API_HOST}:443 {
      header_up Host {env.HUB_API_HOST}
      transport http {
        tls
        tls_server_name {env.HUB_API_HOST}
      }
    }
  }
}
CADDY_EOF

  cat > "${GATEWAY_DIR}/Dockerfile" <<'GWDOCKERFILE'
FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
GWDOCKERFILE

  ok "Building gateway image..."
  gcloud builds submit "${GATEWAY_DIR}" \
    --project="${PROJECT_ID}" \
    --tag="${GATEWAY_IMAGE}" \
    --quiet

  ok "Gateway image built: ${GATEWAY_IMAGE}"

  gcloud run deploy "${CLOUD_RUN_SERVICE}" \
    --project="${PROJECT_ID}" \
    --region="${CLOUD_RUN_REGION}" \
    --image="${GATEWAY_IMAGE}" \
    --platform=managed \
    --port=8080 \
    --allow-unauthenticated \
    --min-instances=1 \
    --max-instances=5 \
    --memory=256Mi \
    --cpu=1 \
    --timeout=300 \
    --concurrency=100 \
    --clear-vpc-connector \
    --set-env-vars="GATEWAY_API_KEY=${gateway_api_key},HUB_API_HOST=${hub_api_host}" \
    --quiet

  GATEWAY_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE}" \
    --region="${CLOUD_RUN_REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)')
  ok "Gateway deployed: ${GATEWAY_URL}"

  rm -rf "${GATEWAY_DIR}"
}

usage() {
  echo "Usage: $0 [--update | --activate | --deploy]"
  echo ""
  echo "  (no flag)    Fresh deploy — creates project, VM, disk, firewall, runs AIStor"
  echo "  --update     Upgrade running MinIO container to AIStor image (preserves everything)"
  echo "  --activate   Register AIStor Free license on the running deployment"
  echo "  --deploy         Full deploy: VPC + gateway Cloud Run + hub-api Cloud Run + Litestream infra"
  echo "  --deploy-gateway Rebuild and redeploy Cloud Run gateway only (fast path, no hub-api rebuild)"
  echo "  --deploy-api     Rebuild and redeploy hub-api Cloud Run only (SSH-free, ~2 min)"
  exit 0
}

# ─────────────────────────── Parse Mode ──────────────────────────────
MODE="deploy"
case "${1:-}" in
  --update)        MODE="update" ;;
  --activate)      MODE="activate" ;;
  --deploy)          MODE="deploy" ;;
  --deploy-gateway)  MODE="deploy-gateway" ;;
  --deploy-api)      MODE="deploy-api" ;;
  --gateway)         MODE="deploy" ;;      # backward compat
  --hub-api-only)    MODE="deploy-api" ;;  # backward compat
  --help|-h)       usage ;;
  "")              MODE="deploy" ;;
  *)               echo "Unknown flag: $1"; usage ;;
esac

# ─────────────────────────── Pre-flight (all modes) ──────────────────
command -v gcloud &>/dev/null || fail "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
[[ -n "$ACCOUNT" ]] || fail "No active gcloud account. Run: gcloud auth login"
gcloud config set project "${PROJECT_ID}" --quiet 2>/dev/null
ok "Authenticated as: ${ACCOUNT} | Project: ${PROJECT_ID}"


# ═════════════════════════════════════════════════════════════════════
# MODE: --deploy
# Full deploy: VPC + gateway Cloud Run + hub-api Cloud Run + Litestream infra
# Run AFTER the base VM is deployed and healthy
# ═════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "deploy" ]]; then
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  DemoForge Hub — Full GCP Deploy                        ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

  # ── Step 1: Setup GCS + IAM infra ──
  step 1 "Setup Litestream GCS bucket + hub-api service account"
  setup_hub_api_litestream_infra
  echo ""

  # ── Step 2: Generate or read hub-api admin key ──
  step 2 "Hub API admin key"
  HUB_API_ADMIN_KEY=$(grep "^DEMOFORGE_HUB_API_ADMIN_KEY=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "")
  if [[ -z "$HUB_API_ADMIN_KEY" ]]; then
    HUB_API_ADMIN_KEY="hubadm-$(openssl rand -hex 20)"
    ok "Generated new hub-api admin key"
  else
    ok "Reusing existing hub-api admin key from .env.hub"
  fi

  # ── Step 3: Generate or read gateway API key ──
  step 3 "Gateway API key"
  GATEWAY_API_KEY=$(grep "^DEMOFORGE_API_KEY=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "")
  if [[ -z "$GATEWAY_API_KEY" ]]; then
    GATEWAY_API_KEY="dfg-$(openssl rand -hex 20)"
    ok "Generated new gateway API key"
  else
    ok "Reusing existing gateway API key from .env.hub"
  fi

  # ── Step 4: Deploy hub-api ──
  step 4 "Deploy hub-api Cloud Run"
  deploy_hub_api_cloudrun "${HUB_API_ADMIN_KEY}" "${GATEWAY_API_KEY}"

  # ── Step 5: Deploy gateway ──
  step 5 "Deploy gateway Cloud Run"
  deploy_gateway_cloudrun "${GATEWAY_API_KEY}" "${HUB_API_HOST}"

  # ── Step 6: Verify gateway ──
  step 6 "Verify gateway"
  GATEWAY_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE}" \
    --project="${PROJECT_ID}" --region="${CLOUD_RUN_REGION}" \
    --format='value(status.url)' 2>/dev/null || echo "")

  HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/health" 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "200" ]]; then
    ok "Gateway healthy at ${GATEWAY_URL}"
  else
    warn "Gateway returned HTTP ${HTTP_CODE} — may still be warming up"
  fi

  # ── Step 7: Write .env.hub ──
  step 7 "Write .env.hub"
  cat > "${ENV_FILE}" <<ENV_EOF
# DemoForge Hub Configuration
# Generated by minio-gcp.sh --deploy on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Copy to .env.local:  cp .env.hub .env.local

# ── Gateway ──
DEMOFORGE_HUB_URL=${GATEWAY_URL}
DEMOFORGE_API_KEY=${GATEWAY_API_KEY}

# ── Hub API ──
DEMOFORGE_HUB_API_ADMIN_KEY=${HUB_API_ADMIN_KEY}
DEMOFORGE_HUB_API_URL=${HUB_API_URL}

# ── Template Sync (via gateway) ──
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=${GATEWAY_URL}/s3
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=

# ── Registry (via hub-connector on localhost) ──
DEMOFORGE_REGISTRY_HOST=localhost:5000
ENV_EOF
  chmod 600 "${ENV_FILE}"
  ok "Written to ${ENV_FILE}"

  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║  Hub deploy complete!                                   ║${NC}"
  echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║  Gateway:  ${GATEWAY_URL}  ${NC}"
  echo -e "${GREEN}║  Hub API:  ${HUB_API_URL}  ${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  Next steps:"
  echo -e "    cp .env.hub .env.local   # copy to local config"
  echo -e "    make hub-seed            # seed templates to GCS"
  echo -e "    make seed-licenses       # seed licenses to GCS"
  echo ""

  exit 0
fi

# ═════════════════════════════════════════════════════════════════════
# MODE: --deploy-gateway
# Rebuild gateway image and redeploy Cloud Run gateway only (fast path)
# ═════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "deploy-gateway" ]]; then
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  DemoForge — Rebuild & Redeploy Gateway (Cloud Run)     ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

  deploy_gateway_cloudrun

  GATEWAY_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE}" \
    --region="${CLOUD_RUN_REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)')

  # Verify
  sleep 3
  if curl -sf "${GATEWAY_URL}/health" &>/dev/null; then
    ok "Gateway health check passed."
  else
    warn "Gateway health check failed — check: curl ${GATEWAY_URL}/health"
  fi

  echo ""
  ok "Gateway redeployed to Cloud Run."
  exit 0
fi

# ═════════════════════════════════════════════════════════════════════
# MODE: --deploy-api
# Rebuild hub-api image via Cloud Build and redeploy to Cloud Run
# ═════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "deploy-api" ]]; then
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  DemoForge — Rebuild & Redeploy Hub API (Cloud Run)     ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

  # All keys come from .env.hub (set during hub-deploy)
  deploy_hub_api_cloudrun

  # Update the gateway's HUB_API_HOST env var so it routes to the new revision
  step 2 "Update gateway env → new hub-api URL"
  HUB_API_URL=$(gcloud run services describe "${HUB_API_SERVICE}" \
    --region="${CLOUD_RUN_REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)')
  HUB_API_HOST="${HUB_API_URL#https://}"
  gcloud run services update "${CLOUD_RUN_SERVICE}" \
    --project="${PROJECT_ID}" \
    --region="${CLOUD_RUN_REGION}" \
    --update-env-vars="HUB_API_HOST=${HUB_API_HOST}" \
    --quiet
  ok "Gateway updated → HUB_API_HOST=${HUB_API_HOST}"

  echo ""
  ok "Hub API redeployed to Cloud Run. No SSH required."
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
echo -e "${YELLOW}To deploy Cloud Run gateway + hub-api (VPC + HTTPS + auth):${NC}"
echo "  ./$(basename "$0") --deploy"
