#!/usr/bin/env bash
#
# deploy-minio-gcp.sh
# Automated MinIO AIStor Free deployment on GCP
# Project: minio-demoforge
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - A GCP billing account linked (script will prompt)
#
set -euo pipefail

# ─────────────────────────── Configuration ───────────────────────────
PROJECT_ID="minio-demoforge"
REGION="me-central1"            # Doha — closest to Dubai
ZONE="${REGION}-a"
VM_NAME="minio-node"
MACHINE_TYPE="e2-medium"        # 2 vCPU, 4 GB RAM — plenty for minimal workload
BOOT_DISK_SIZE="20GB"
DATA_DISK_NAME="minio-data"
DATA_DISK_SIZE="50GB"
DATA_DISK_TYPE="pd-balanced"
NETWORK_TAG="minio-server"
FIREWALL_RULE="allow-minio"
# MinIO credentials — CHANGE THESE before running in production
MINIO_ROOT_USER="minioadmin"
MINIO_ROOT_PASSWORD="minioadmin-$(openssl rand -hex 6)"
OS_IMAGE_FAMILY="ubuntu-2404-lts-amd64"
OS_IMAGE_PROJECT="ubuntu-os-cloud"

# ─────────────────────────── Helpers ─────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

step()    { echo -e "\n${CYAN}▶ STEP $1: $2${NC}"; }
ok()      { echo -e "  ${GREEN}✔ $1${NC}"; }
warn()    { echo -e "  ${YELLOW}⚠ $1${NC}"; }
fail()    { echo -e "  ${RED}✘ $1${NC}"; exit 1; }

verify() {
  # $1 = description, $2 = command to eval (should return 0 on success)
  if eval "$2" &>/dev/null; then
    ok "$1"
  else
    fail "$1 — aborting."
  fi
}

# ─────────────────────────── Pre-flight ──────────────────────────────
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  MinIO AIStor Free — GCP Automated Deployment          ║${NC}"
echo -e "${CYAN}║  Project : ${PROJECT_ID}                              ║${NC}"
echo -e "${CYAN}║  Region  : ${REGION}                            ║${NC}"
echo -e "${CYAN}║  VM      : ${MACHINE_TYPE} · ${DATA_DISK_SIZE} data disk            ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check gcloud is available
command -v gcloud &>/dev/null || fail "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
ok "gcloud CLI found: $(gcloud version 2>/dev/null | head -1)"

# Check authentication
ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
[[ -n "$ACCOUNT" ]] || fail "No active gcloud account. Run: gcloud auth login"
ok "Authenticated as: ${ACCOUNT}"

# ─────────────────────────── Step 1: Create Project ──────────────────
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

# ─────────────────────────── Step 2: Link Billing ────────────────────
step 2 "Link billing account"

BILLING_ACCOUNT=$(gcloud billing accounts list --filter="open=true" --format="value(ACCOUNT_ID)" --limit=1 2>/dev/null || true)
if [[ -z "$BILLING_ACCOUNT" ]]; then
  fail "No active billing account found. Set one up at https://console.cloud.google.com/billing"
fi

CURRENT_BILLING=$(gcloud billing projects describe "${PROJECT_ID}" --format="value(billingAccountName)" 2>/dev/null || true)
if [[ -z "$CURRENT_BILLING" || "$CURRENT_BILLING" == "" ]]; then
  gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT}"
  ok "Linked billing account: ${BILLING_ACCOUNT}"
else
  ok "Billing already linked: ${CURRENT_BILLING}"
fi

verify "Billing is active" \
  "gcloud billing projects describe ${PROJECT_ID} --format='value(billingEnabled)' 2>/dev/null | grep -qi true"

# ─────────────────────────── Step 3: Enable APIs ─────────────────────
step 3 "Enable Compute Engine API"

gcloud services enable compute.googleapis.com --project="${PROJECT_ID}"
ok "compute.googleapis.com enabled."

# Wait for API propagation
echo "  Waiting for API propagation (up to 60s)..."
for i in $(seq 1 12); do
  if gcloud compute regions list --project="${PROJECT_ID}" &>/dev/null; then
    ok "Compute Engine API is ready."
    break
  fi
  sleep 5
done

verify "Compute Engine API responsive" \
  "gcloud compute regions list --project=${PROJECT_ID} --limit=1"

# ─────────────────────────── Step 4: Create Data Disk ────────────────
step 4 "Create persistent data disk [${DATA_DISK_NAME}] — ${DATA_DISK_SIZE}"

if gcloud compute disks describe "${DATA_DISK_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" &>/dev/null; then
  warn "Disk ${DATA_DISK_NAME} already exists — reusing."
else
  gcloud compute disks create "${DATA_DISK_NAME}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --size="${DATA_DISK_SIZE}" \
    --type="${DATA_DISK_TYPE}"
  ok "Disk created."
fi

verify "Disk exists and is ${DATA_DISK_SIZE}" \
  "gcloud compute disks describe ${DATA_DISK_NAME} --zone=${ZONE} --project=${PROJECT_ID} --format='value(sizeGb)' | grep -q 50"

# ─────────────────────────── Step 5: Firewall Rules ──────────────────
step 5 "Create firewall rules for MinIO (ports 9000, 9001)"

if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" &>/dev/null; then
  warn "Firewall rule ${FIREWALL_RULE} already exists — reusing."
else
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
    --project="${PROJECT_ID}" \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:9000,tcp:9001 \
    --source-ranges=0.0.0.0/0 \
    --target-tags="${NETWORK_TAG}" \
    --description="Allow MinIO API (9000) and Console (9001)"
  ok "Firewall rule created."
fi

verify "Firewall rule exists" \
  "gcloud compute firewall-rules describe ${FIREWALL_RULE} --project=${PROJECT_ID}"

# ─────────────────────────── Step 6: Create VM ───────────────────────
step 6 "Create VM instance [${VM_NAME}]"

# Startup script that formats the data disk and runs MinIO via Docker
STARTUP_SCRIPT=$(cat <<'STARTUP'
#!/bin/bash
set -euo pipefail
exec > /var/log/minio-setup.log 2>&1
echo "=== MinIO Setup Started at $(date) ==="

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
  # Persist in fstab
  echo "UUID=$(blkid -s UUID -o value ${DATA_DEV})  ${MOUNT_POINT}  ext4  discard,defaults,nofail  0 2" >> /etc/fstab
fi

mkdir -p "${MOUNT_POINT}/data"
echo "Data disk mounted at ${MOUNT_POINT}"

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

systemctl enable docker
systemctl start docker
echo "Docker installed: $(docker --version)"

# ── Read MinIO credentials from instance metadata ──
MINIO_USER=$(curl -sf "http://metadata.google.internal/computeMetadata/v1/instance/attributes/minio-root-user" -H "Metadata-Flavor: Google" || echo "minioadmin")
MINIO_PASS=$(curl -sf "http://metadata.google.internal/computeMetadata/v1/instance/attributes/minio-root-password" -H "Metadata-Flavor: Google" || echo "minioadmin")

# ── Run MinIO container ──
docker rm -f minio 2>/dev/null || true

docker run -d \
  --name minio \
  --restart always \
  -p 9000:9000 \
  -p 9001:9001 \
  -e "MINIO_ROOT_USER=${MINIO_USER}" \
  -e "MINIO_ROOT_PASSWORD=${MINIO_PASS}" \
  -v /mnt/minio-data/data:/data \
  quay.io/minio/minio:latest \
  server /data --console-address ":9001"

echo "=== MinIO Setup Completed at $(date) ==="
echo "Console: http://$(hostname -I | awk '{print $1}'):9001"
STARTUP
)

# Write startup script to a temp file (process substitution doesn't work with gcloud)
STARTUP_FILE=$(mktemp /tmp/minio-startup-XXXXXX.sh)
echo "${STARTUP_SCRIPT}" > "${STARTUP_FILE}"
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
    --metadata="minio-root-user=${MINIO_ROOT_USER},minio-root-password=${MINIO_ROOT_PASSWORD}" \
    --metadata-from-file="startup-script=${STARTUP_FILE}" \
    --scopes=default
  ok "VM created."
fi

# Clean up temp file
rm -f "${STARTUP_FILE}"

verify "VM is RUNNING" \
  "gcloud compute instances describe ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --format='value(status)' | grep -q RUNNING"

# ─────────────────────────── Step 7: Wait for MinIO ──────────────────
step 7 "Wait for MinIO to come online"

EXTERNAL_IP=$(gcloud compute instances describe "${VM_NAME}" \
  --zone="${ZONE}" --project="${PROJECT_ID}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo "  External IP: ${EXTERNAL_IP}"
echo "  Waiting for MinIO health endpoint (up to 3 minutes)..."

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
  ok "MinIO is healthy!"
else
  warn "MinIO not yet responding — startup script may still be running."
  echo "  Check logs: gcloud compute ssh ${VM_NAME} --zone=${ZONE} -- 'sudo cat /var/log/minio-setup.log'"
fi

# ─────────────────────────── Summary ─────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              DEPLOYMENT COMPLETE                        ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Project     : ${PROJECT_ID}                           ║${NC}"
echo -e "${GREEN}║  VM          : ${VM_NAME} (${MACHINE_TYPE})            ║${NC}"
echo -e "${GREEN}║  Zone        : ${ZONE}                          ║${NC}"
echo -e "${GREEN}║  Data Disk   : ${DATA_DISK_SIZE} ${DATA_DISK_TYPE}                  ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  MinIO API   : http://${EXTERNAL_IP}:9000              ${NC}"
echo -e "${GREEN}║  Console     : http://${EXTERNAL_IP}:9001              ${NC}"
echo -e "${GREEN}║  User        : ${MINIO_ROOT_USER}                     ${NC}"
echo -e "${GREEN}║  Password    : ${MINIO_ROOT_PASSWORD}   ${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Est. Cost   : ~\$30–35/month (on-demand)              ║${NC}"
echo -e "${GREEN}║  Savings Tip : 1-yr CUD → ~\$20–22/month              ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Security Notes:${NC}"
echo "  1. Password saved above — store it securely."
echo "  2. Firewall rule 0.0.0.0/0 is open to all. Restrict to your IP:"
echo "     gcloud compute firewall-rules update ${FIREWALL_RULE} --source-ranges=<YOUR_IP>/32 --project=${PROJECT_ID}"
echo "  3. For TLS, set up a reverse proxy (Caddy/nginx) or Cloudflare Tunnel."
echo ""
echo "Useful commands:"
echo "  SSH into VM    : gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID}"
echo "  View logs      : gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} -- 'sudo docker logs minio --tail 50'"
echo "  Stop VM        : gcloud compute instances stop ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID}"
echo "  Delete all     : gcloud projects delete ${PROJECT_ID}"
