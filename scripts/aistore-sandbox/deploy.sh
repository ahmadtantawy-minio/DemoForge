#!/usr/bin/env bash
#
# Verbose installer: MinIO AIStor operator + ObjectStore (df-cursor-* prefixed names).
# License: scripts/minio.license (SUBNET JWT).
#
# Optional env:
#   AISTOR_NAMESPACE       (default df-cursor-aistor)
#   OPERATOR_RELEASE       (default df-cursor-aistor-operator)
#   OBJECTSTORE_RELEASE    (default df-cursor-aistor-objectstore)
#   LICENSE_FILE           (default <repo>/scripts/minio.license)
#   SKIP_OPERATOR=1 | SKIP_OBJECTSTORE=1
#   HEALTH_WAIT_SEC        (default 600) max seconds to wait for pods after object store
#   AISTOR_SKIP_CLEANUP=1  skip uninstall + CRD prune (default: cleanup runs before operator install)
#   AISTOR_PRUNE_CRDS=0    do not delete conflicting sts.min.io / aistor.min.io CRDs (default: prune)
#   AISTOR_ORBSTACK_RESET=1  before anything else: interactive wipe for local OrbStack (see script body)
#   AISTOR_ORBSTACK_RESET_CONFIRM=YES  non-interactive confirmation for CI/automation (use with care)
#   AISTOR_RESET_PROTECTED_NS  space-separated namespaces to keep (default: kube-system kube-public kube-node-lease)
#
# Naming: namespace, Helm release names, ObjectStore CR, pool, Services, and root Secret
# use the df-cursor-* prefix (see values.yaml). Upstream operator charts may still create
# Deployments whose metadata.name matches embedded chart defaults; they remain isolated in ${NS}.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALUES="${ROOT}/scripts/aistore-sandbox/values.yaml"
LICENSE_FILE="${LICENSE_FILE:-${ROOT}/scripts/minio.license}"

NS="${AISTOR_NAMESPACE:-df-cursor-aistor}"
OPERATOR_REL="${OPERATOR_RELEASE:-df-cursor-aistor-operator}"
STORE_REL="${OBJECTSTORE_RELEASE:-df-cursor-aistor-objectstore}"
HEALTH_WAIT_SEC="${HEALTH_WAIT_SEC:-600}"

# Prior installs (other release names, kubectl apply, or helm uninstall leaving CRDs) leave CRDs without
# Helm labels — new helm install fails with "cannot be imported into the current release".
AISTOR_PRUNE_CRDS="${AISTOR_PRUNE_CRDS:-1}"

die() { echo "[df-cursor] ERROR: $*" >&2; exit 1; }

log() { echo "[df-cursor] $*"; }
log_step() { echo ""; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "► STEP $1"; echo "   $2"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }

# $1 = force (1 = delete CRDs even if AISTOR_PRUNE_CRDS=0 — used after full cluster reset)
prune_aistor_crds() {
  local force="${1:-0}"
  if [[ "$force" != "1" ]] && [[ "$AISTOR_PRUNE_CRDS" != "1" ]]; then
    log "  AISTOR_PRUNE_CRDS=0 — not deleting CRDs."
    return 0
  fi
  log "  Deleting CRDs (*.sts.min.io, *.aistor.min.io) so Helm can own them on next install..."
  local crd_count=0
  while IFS= read -r crd; do
    [[ -z "$crd" ]] && continue
    log "    kubectl delete $crd"
    kubectl delete "$crd" --wait=false 2>/dev/null && crd_count=$((crd_count + 1)) || true
  done < <(kubectl get crd -o name 2>/dev/null | grep -E '\.(sts|aistor)\.min\.io$' || true)
  if [[ "$crd_count" -eq 0 ]]; then
    log "  No sts.min.io / aistor.min.io CRDs found (or already clean)."
  else
    log "  Submitted deletion for ${crd_count} CRD(s); waiting for API to settle..."
    sleep 3
    local _i rem
    for _i in $(seq 1 30); do
      rem=$(kubectl get crd -o name 2>/dev/null | grep -E '\.(sts|aistor)\.min\.io$' | wc -l | tr -d ' ')
      rem=${rem:-0}
      [[ "$rem" == "0" ]] && break
      sleep 2
    done
  fi
}

command -v kubectl >/dev/null || die "kubectl not found in PATH"
command -v helm >/dev/null || die "helm not found in PATH"
[[ -f "$VALUES" ]] || die "missing values file: ${VALUES}"
[[ -f "$LICENSE_FILE" ]] || die "missing license file: ${LICENSE_FILE} — place your SUBNET JWT there"

OBJ="$(awk '/^objectStore:/{f=1} f&&/^  name:/{print $2; exit}' "$VALUES")"
SVC_S3="$(awk '/^    minio:/{f=1} f&&/^      name:/{print $2; exit}' "$VALUES")"
SVC_UI="$(awk '/^    console:/{f=1} f&&/^      name:/{print $2; exit}' "$VALUES")"
POOL="$(awk '/^    - name:/{print $3; exit}' "$VALUES")"

log "DemoForge AIStor sandbox deploy"
log "  Repository root:     ${ROOT}"
log "  Values file:         ${VALUES}"
log "  License file:        ${LICENSE_FILE}"
log "  Kubernetes context:  $(kubectl config current-context 2>/dev/null || echo '(unknown)')"
log "  Target namespace:      ${NS} (Helm releases, CR, Services, pool: df-cursor-*; see header note for operator chart names)"
log "  Helm release (op):   ${OPERATOR_REL}"
log "  Helm release (store):${STORE_REL}"
log "  ObjectStore CR name: ${OBJ}"
log "  S3 Service:          ${SVC_S3}"
log "  Console Service:     ${SVC_UI}"
log "  Pool name:           ${POOL}"

# --- Optional: OrbStack / local cluster full wipe (destructive, user-confirmed) ---
if [[ "${AISTOR_ORBSTACK_RESET:-0}" == "1" ]]; then
  log_step 0 "OrbStack / cluster reset (AISTOR_ORBSTACK_RESET=1)"
  echo ""
  PROTECTED_NS="${AISTOR_RESET_PROTECTED_NS:-kube-system kube-public kube-node-lease}"
  log "DESTRUCTIVE: clears user workloads on the CURRENT kubectl context so a fresh AIStor install can succeed."
  log "  • Uninstall every Helm release in every namespace."
  log "  • Delete every namespace except protected: ${PROTECTED_NS}"
  log "  • Clear namespace default (the default ns cannot be removed; workloads inside it are deleted)."
  log "  • Delete *.sts.min.io / *.aistor.min.io CRDs cluster-wide."
  log "  • Does NOT stop OrbStack; protected namespaces keep core cluster components (no pod delete in kube-system)."
  echo ""
  if [[ -t 0 ]]; then
    read -r -p "[df-cursor] Type RESET to wipe this cluster context (anything else aborts): " _orb_confirm
    [[ "${_orb_confirm}" == "RESET" ]] || die "Aborted — no changes made."
  else
    [[ "${AISTOR_ORBSTACK_RESET_CONFIRM:-}" == "YES" ]] || die "Non-interactive shell: set AISTOR_ORBSTACK_RESET_CONFIRM=YES to confirm cluster wipe."
  fi

  log "Uninstalling all Helm releases (cluster-wide)..."
  rel_count=$(helm list -A -q 2>/dev/null | wc -l | tr -d ' ')
  rel_count=${rel_count:-0}
  if [[ "$rel_count" == "0" ]]; then
    log "  No Helm releases found."
  else
    while read -r rel_name rel_ns _rest; do
      [[ -z "${rel_name:-}" ]] && continue
      log "  helm uninstall ${rel_name} -n ${rel_ns}"
      helm uninstall "${rel_name}" -n "${rel_ns}" --wait --timeout 5m 2>/dev/null || log "    ⚠ uninstall failed or timed out (continuing)"
    done < <(helm list -A --no-headers 2>/dev/null || true)
  fi

  namespace_is_protected() {
    local cand="$1" p
    for p in ${PROTECTED_NS}; do
      [[ "$cand" == "$p" ]] && return 0
    done
    return 1
  }

  log "Deleting all namespaces except protected list..."
  while IFS= read -r n; do
    [[ -z "$n" ]] && continue
    if namespace_is_protected "$n"; then
      log "  keep namespace: ${n}"
      continue
    fi
    if [[ "$n" == "default" ]]; then
      log "  skip deleting namespace default (will clear its resources next)"
      continue
    fi
    log "  kubectl delete namespace ${n} --wait=true --timeout=300s"
    kubectl delete namespace "$n" --wait=true --timeout=300s 2>/dev/null || log "    ⚠ delete ${n} incomplete (Terminating? check: kubectl get ns ${n})"
  done < <(kubectl get ns -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)

  log "Clearing workloads in namespace default (namespace itself is retained)..."
  kubectl delete deploy,sts,ds --all -n default --grace-period=0 --timeout=180s 2>/dev/null || true
  kubectl delete svc,ing,pvc,job,cronjob --all -n default --grace-period=0 --timeout=120s 2>/dev/null || true
  kubectl delete pod --all -n default --grace-period=0 --force 2>/dev/null || true
  kubectl delete configmap --all -n default 2>/dev/null || true
  kubectl delete secrets -n default --field-selector type!=kubernetes.io/service-account-token 2>/dev/null || true

  prune_aistor_crds 1
  AISTOR_SKIP_CLEANUP=1
  log "  Full reset done. Subsequent steps will recreate namespace ${NS} and install charts."
  log "  kubectl get pods -A (protected namespaces may still show system pods):"
  kubectl get pods -A 2>/dev/null || true
  log "  helm list -A:"
  helm list -A 2>/dev/null || true
fi

# --- Helm repo -----------------------------------------------------------------
log_step 1 "Add MinIO Helm repo and refresh index"
log "The chart installs CRDs (aistor.min.io/v1 ObjectStore) and operators from minio/aistor-operator."
if helm repo add minio https://helm.min.io 2>/dev/null; then
  log "  Added repo: minio -> https://helm.min.io"
else
  log "  Repo minio already present (or add skipped)"
fi
helm repo update minio
log "  Chart index updated."

# --- Namespace -----------------------------------------------------------------
log_step 2 "Ensure namespace ${NS} exists (df-cursor-* prefix)"
if kubectl get ns "$NS" >/dev/null 2>&1; then
  log "  Namespace ${NS} already exists."
else
  kubectl create ns "$NS"
  log "  Created namespace ${NS}."
fi

# --- Cleanup prior installs (Helm + orphan CRDs) ---------------------------------
if [[ "${AISTOR_SKIP_CLEANUP:-0}" != "1" ]]; then
  log_step 3 "Clean up prior MinIO AIStor deployments (before fresh install)"
  log "Why: leftover Helm releases or CRDs from an older release name / manual apply block the operator chart"
  log "      (Helm cannot adopt CRDs that lack meta.helm.sh/release-name and app.kubernetes.io/managed-by=Helm)."
  if helm status "$STORE_REL" -n "$NS" &>/dev/null; then
    log "  Uninstalling prior Helm release: ${STORE_REL} (aistor-objectstore first)..."
    helm uninstall "$STORE_REL" -n "$NS" --wait --timeout 5m || log "  ⚠ uninstall ${STORE_REL} returned non-zero (continuing)"
  else
    log "  No existing Helm release ${STORE_REL} in ${NS}."
  fi
  log "  Removing any remaining ObjectStore CRs in ${NS} (safe if none / CRD missing)..."
  kubectl delete objectstore --all -n "$NS" --wait=true --timeout=120s 2>/dev/null || log "  (no ObjectStore CRs, or CRD not installed — ok)"
  if helm status "$OPERATOR_REL" -n "$NS" &>/dev/null; then
    log "  Uninstalling prior Helm release: ${OPERATOR_REL} (aistor-operator)..."
    helm uninstall "$OPERATOR_REL" -n "$NS" --wait --timeout 5m || log "  ⚠ uninstall ${OPERATOR_REL} returned non-zero (continuing)"
  else
    log "  No existing Helm release ${OPERATOR_REL} in ${NS}."
  fi
  log "  Note: helm uninstall often leaves cluster-scoped CRDs; those must match this release or install fails."
  if [[ "$AISTOR_PRUNE_CRDS" == "1" ]]; then
    log "  (Set AISTOR_PRUNE_CRDS=0 to skip — required if another namespace on this cluster still uses these APIs.)"
  fi
  prune_aistor_crds 0
  log "  Cleanup step finished."
else
  log_step 3 "AISTOR_SKIP_CLEANUP=1 — skipping prior uninstall / CRD prune"
fi

# --- Operator ------------------------------------------------------------------
if [[ "${SKIP_OPERATOR:-0}" != "1" ]]; then
  log_step 4 "Install/upgrade aistor-operator (release: ${OPERATOR_REL})"
  log "This deploys the object-store operator + webhooks + CRDs so ObjectStore resources can be reconciled."
  log "License is passed with --set-file (content of ${LICENSE_FILE})."
  helm upgrade --install "$OPERATOR_REL" minio/aistor-operator \
    --namespace "$NS" \
    --set-file license="$LICENSE_FILE" \
    --wait --timeout 12m
  log "  Helm reports success; verifying operator workloads in namespace..."
  kubectl get deploy,po -n "$NS" -l "app.kubernetes.io/instance=${OPERATOR_REL}" 2>/dev/null || kubectl get deploy,po -n "$NS"
  log "  Health: waiting for every Deployment in ${NS} to become available (max 300s each)..."
  while IFS= read -r d; do
    [[ -z "$d" ]] && continue
    if kubectl rollout status deployment/"$d" -n "$NS" --timeout=300s 2>/dev/null; then
      log "  ✓ Deployment/${d} is available."
    else
      log "  ⚠ rollout status for ${d} timed out or failed — check: kubectl describe deploy -n ${NS} ${d}"
    fi
  done < <(kubectl get deploy -n "$NS" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
else
  log_step 4 "SKIP_OPERATOR=1 — not installing aistor-operator"
fi

# --- Object store ---------------------------------------------------------------
if [[ "${SKIP_OBJECTSTORE:-0}" != "1" ]]; then
  log_step 5 "Install/upgrade aistor-objectstore (release: ${STORE_REL})"
  log "This renders an ObjectStore CR: kind ObjectStore, apiVersion aistor.min.io/v1, name ${OBJ}."
  log "  • spec.pools → ${POOL} with 4 servers (S3 API / data plane)"
  log "  • spec.services.minio → Service ${SVC_S3} (S3 endpoint)"
  log "  • spec.services.console → Service ${SVC_UI} (Console UI)"
  helm upgrade --install "$STORE_REL" minio/aistor-objectstore \
    --namespace "$NS" \
    -f "$VALUES" \
    --wait --timeout 25m
  log "  Helm reports success."
else
  log_step 5 "SKIP_OBJECTSTORE=1 — not installing aistor-objectstore"
fi

# --- Post-install health --------------------------------------------------------
log_step 6 "Post-install health checks (namespace ${NS})"
log "Listing ObjectStore CR and workloads:"
if kubectl get "objectstore/${OBJ}" -n "$NS" >/dev/null 2>&1; then
  log "  ObjectStore ${OBJ}:"
  kubectl get "objectstore/${OBJ}" -n "$NS" -o wide 2>/dev/null || true
else
  log "  (ObjectStore ${OBJ} not found yet — CRD or reconcile delay)"
  kubectl get objectstore -n "$NS" 2>/dev/null || log "  (no ObjectStore CR or CRD not visible)"
fi
kubectl get sts,deploy,svc,pvc -n "$NS" 2>/dev/null || true
kubectl get pods -n "$NS" -o wide 2>/dev/null || true

if [[ "${SKIP_OBJECTSTORE:-0}" != "1" ]]; then
  log "Waiting up to ${HEALTH_WAIT_SEC}s for all pods to be Running or Completed..."
  end=$((SECONDS + HEALTH_WAIT_SEC))
  not_ready=""
  while (( SECONDS < end )); do
    pod_count=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [[ "${pod_count}" == "0" ]]; then
      log "  No pods yet..."
      sleep 5
      continue
    fi
    not_ready=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null | awk '$3!~/^(Running|Completed|Succeeded)/ {print $1" "$3}' || true)
    if [[ -z "${not_ready// }" ]]; then
      log "  ✓ All reported pods are Running/Completed."
      break
    fi
    log "  Still waiting — non-ready: $(echo "$not_ready" | tr '\n' '; ')"
    sleep 8
  done
  not_ready=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null | awk '$3!~/^(Running|Completed|Succeeded)/ {print $1" "$3}' || true)
  if [[ -n "${not_ready// }" ]]; then
    log "  ⚠ Some pods not Ready after wait — inspect: kubectl describe pod -n ${NS}"
  fi

  while IFS= read -r sts; do
    [[ -z "$sts" ]] && continue
    log "  StatefulSet rollout: ${sts}"
    kubectl rollout status "statefulset/${sts}" -n "$NS" --timeout=300s 2>/dev/null && log "    ✓ ${sts} rolled out" || log "    ⚠ ${sts} rollout incomplete"
  done < <(kubectl get sts -n "$NS" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)

  # Optional in-cluster S3 health via Service (ClusterIP — port-forward may be needed on restricted clusters)
  log "ClusterIP services are not reachable from your laptop without port-forward or Ingress."
fi

# --- Access guide ---------------------------------------------------------------
SECRET_NAME="${OBJ}-root-creds"

echo ""
echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║  df-cursor AIStor sandbox — how to access each layer                         ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Layer 0 — Namespace & Helm (df-cursor-* release names)"
echo "  Namespace:     ${NS}"
echo "  helm list -n ${NS}"
echo "    • ${OPERATOR_REL}   → installs CRDs + AIStor operators"
echo "    • ${STORE_REL}  → renders ObjectStore CR / ${OBJ}"
echo "  Resources we named with df-cursor-*: CR ${OBJ}, Services ${SVC_S3} & ${SVC_UI}, pool ${POOL}, Secret ${SECRET_NAME}"
echo ""
echo "Layer 1 — Custom resource (desired state)"
echo "  kubectl get objectstore ${OBJ} -n ${NS} -o yaml"
echo "  kubectl describe objectstore ${OBJ} -n ${NS}"
echo ""
echo "Layer 2 — Kubernetes workloads (actual pods)"
echo "  kubectl get sts,deploy,pods -n ${NS}"
echo "  # MinIO server pods are usually: ${OBJ}-${POOL}-<ordinal>"
echo "  # Console Deployment name often ends with -console (operator-managed)."
echo ""
echo "Layer 3 — S3 API (inside cluster: Service ${SVC_S3}, port 9000 typically)"
echo "  kubectl get svc ${SVC_S3} -n ${NS}"
echo "  # From your machine (separate terminals):"
echo "  kubectl port-forward -n ${NS} svc/${SVC_S3} 9000:9000"
echo "  # Then (insecure TLS off / http):"
echo "  mc alias set df-cursor http://127.0.0.1:9000 minioadmin minioadmin"
echo "  mc mb df-cursor/test-bucket --ignore-existing"
echo "  mc ls df-cursor/"
echo "  # Health check against forwarded API:"
echo "  curl -sS http://127.0.0.1:9000/minio/health/live"
echo ""
echo "Layer 4 — Web Console UI (Service ${SVC_UI}, HTTPS port 9443 typically)"
echo "  kubectl get svc ${SVC_UI} -n ${NS}"
echo "  kubectl port-forward -n ${NS} svc/${SVC_UI} 9443:9443"
echo "  # Open: https://127.0.0.1:9443  (accept self-signed / insecure if disableAutoCert)"
echo "  # Login: minioadmin / minioadmin"
echo ""
echo "Credentials secret (created by Helm chart)"
echo "  kubectl get secret ${SECRET_NAME} -n ${NS} -o yaml"
echo "  Root user/password are minioadmin/minioadmin (from values.yaml secrets)."
echo ""
echo "Troubleshooting"
echo "  kubectl logs -n ${NS} -l app.kubernetes.io/instance=${STORE_REL} --tail=50 2>/dev/null || true"
echo "  kubectl get events -n ${NS} --sort-by=.lastTimestamp | tail -30"
echo ""
log "Done."
