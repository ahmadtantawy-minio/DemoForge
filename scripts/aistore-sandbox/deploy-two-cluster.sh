#!/usr/bin/env bash
#
# deploy-two-cluster.sh — two deployment modes (pick with env).
#
# ── Mode 1 — AISTOR_TWO_MINIO_NAMESPACES=1 (same Kubernetes cluster, two tenants) ─────────────
#   Namespaces df-cursor-cluster-a and df-cursor-cluster-b; values-cluster-a.yaml / b.yaml.
#   • A: 4×4 drives, S3 LoadBalancer, Console ClusterIP — LICENSE_FILE_CLUSTER_A (default LICENSE_FILE / minio.license)
#   • B: 2×3 drives, S3 ClusterIP, Console LoadBalancer — LICENSE_FILE_CLUSTER_B (falls back to A if file missing)
#   Before install: AISTOR_CLEANUP_ALL_DF_CURSOR_NAMESPACES=1 (default in this mode) removes every namespace
#   matching ^df-cursor- and prunes CRDs per AISTOR_PRUNE_CRDS_AFTER_BULK (default 1) for a clean operator install.
#   AISTOR_DEPLOY_SECOND_OPERATOR=1 → second aistor-operator in B (usually wrong: CRDs are cluster-scoped).
#   Default 0 → only A runs the operator chart; B is objectstore-only (SKIP_OPERATOR=1). deploy.sh adds
#   helm --skip-crds automatically when aistor CRDs already exist (e.g. leftover df-cursor-aistor-operator).
#   Wrapper: scripts/aistore-sandbox/deploy-two-minio-clusters.sh (sets this flag and re-execs this file).
#
# ── Mode 2 — default: two kubectl contexts + optional remote Console (legacy) ─────────────────
#
# DATA plane (cluster A): ONLY the official AIStor Helm path — no custom MinIO StatefulSet.
#   • minio/aistor-operator (object-store operator, webhooks, CRDs)
#   • minio/aistor-objectstore → ObjectStore CR reconciled by that operator
#   This script shells to scripts/aistore-sandbox/deploy.sh for that path. If that is not
#   acceptable, stop here — there is no supported “pure custom” MinIO replacement in-repo.
#
# UI plane (default AISTOR_DEPLOY_REMOTE_CONSOLE=1): cluster B = only deploy-remote-console.sh —
#   Console Deployment + ClusterIP Service (no ObjectStore on B, no S3 pools/disks on B). The Console
#   uses CONSOLE_MINIO_SERVER from a ConfigMap fed by REMOTE_MINIO_URL (override with AISTOR_REMOTE_S3_URL_OVERRIDE
#   or same-API in-cluster DNS / LB / NodePort logic below). Operator Console on A stays ClusterIP in values.yaml.
# Set AISTOR_DEPLOY_REMOTE_CONSOLE=0 to use only operator Console on DATA (Service df-cursor-console-ui).
#
# REMOTE_MINIO_URL (remote Console path) is derived automatically in this order:
#   1) AISTOR_REMOTE_S3_URL_OVERRIDE if you set it (escape hatch)
#   2) If both kubectl contexts point at the SAME Kubernetes API server → in-cluster DNS:
#        http://<s3-svc>.<namespace>.svc.cluster.local:9000
#   3) Else if the operator-created S3 Service has LoadBalancer ingress → http(s) host:9000
#   4) Else create a NodePort sibling Service (df-cursor-s3-api-nodeport-expose) via
#        kubectl expose … and use http://<node-ip>:<nodePort> from the DATA cluster
#   5) Else fail with guidance (true multi-cloud needs mesh / Ingress / manual override)
#
# Kubectl contexts (resolution order for each of DATA / UI when env unset):
#   1) AISTOR_KUBE_CONTEXT_DATA / AISTOR_KUBE_CONTEXT_UI if set
#   2) Else named defaults demoforge-aistore-data / demoforge-aistore-console if those contexts exist
#   3) Else kubectl's current-context (typical local dev: one cluster, one context)
#   DATA and UI may be the same context (single-cluster dev); two physical clusters → set both env vars.
#
set -euo pipefail

readonly DEFAULT_AISTOR_KUBE_CONTEXT_DATA=demoforge-aistore-data
readonly DEFAULT_AISTOR_KUBE_CONTEXT_UI=demoforge-aistore-console
readonly NODEPORT_SVC_NAME=df-cursor-s3-api-nodeport-expose

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_DATA="${ROOT}/scripts/aistore-sandbox/deploy.sh"
DEPLOY_UI="${ROOT}/scripts/aistore-sandbox/deploy-remote-console.sh"
VALUES="${ROOT}/scripts/aistore-sandbox/values.yaml"
LICENSE_FILE="${LICENSE_FILE:-${ROOT}/scripts/minio.license}"

readonly TWO_MINIO_NS_A=df-cursor-cluster-a
readonly TWO_MINIO_NS_B=df-cursor-cluster-b
readonly TWO_MINIO_VAL_A="${ROOT}/scripts/aistore-sandbox/values-cluster-a.yaml"
readonly TWO_MINIO_VAL_B="${ROOT}/scripts/aistore-sandbox/values-cluster-b.yaml"

die() { echo "[df-cursor-2c] ERROR: $*" >&2; exit 1; }
log() { echo "[df-cursor-2c] $*"; }
log_step() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "► $*"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Mode 1: two full ObjectStore tenants (see header). Exits the script when done.
run_two_minio_namespaces_mode() {
  local DEPLOY CLEAN LICENSE_A LICENSE_B _second_op _skip

  DEPLOY="${ROOT}/scripts/aistore-sandbox/deploy.sh"
  CLEAN="${ROOT}/scripts/aistore-sandbox/cleanup-aistor.sh"
  LICENSE_A="${LICENSE_FILE_CLUSTER_A:-${LICENSE_FILE:-${ROOT}/scripts/minio.license}}"
  LICENSE_B="${LICENSE_FILE_CLUSTER_B:-${ROOT}/scripts/minio.license.cluster-b}"
  if [[ ! -f "$LICENSE_B" ]]; then
    LICENSE_B="$LICENSE_A"
    log "No separate B license at LICENSE_FILE_CLUSTER_B — using the same file as A for this test."
  fi

  [[ -f "$DEPLOY" && -f "$TWO_MINIO_VAL_A" && -f "$TWO_MINIO_VAL_B" ]] || die "missing deploy.sh or values-cluster-*.yaml"
  [[ -f "$LICENSE_A" ]] || die "missing license A: ${LICENSE_A}"
  [[ -f "$LICENSE_B" ]] || die "missing license file: ${LICENSE_A}"
  command -v kubectl >/dev/null || die "kubectl not in PATH"
  command -v helm >/dev/null || die "helm not in PATH"

  two_minio_deploy_ns() {
    local ns="$1" values="$2" license="$3" skip_op="${4:-0}"
    (
      export KUBECTL_CONTEXT="${KUBECTL_CONTEXT:-}"
      export AISTOR_NAMESPACE="$ns"
      export VALUES="$values"
      export LICENSE_FILE="$license"
      export OPERATOR_RELEASE="${ns}-operator"
      export OBJECTSTORE_RELEASE="${ns}-objectstore"
      export AISTOR_SKIP_CLEANUP="${AISTOR_SKIP_CLEANUP:-0}"
      export AISTOR_PRUNE_CRDS="${AISTOR_PRUNE_CRDS:-0}"
      if [[ "$skip_op" == "1" ]]; then
        export SKIP_OPERATOR=1
      else
        unset SKIP_OPERATOR || true
      fi
      bash "$DEPLOY"
    )
  }

  log_step "Two MinIO namespaces — ${TWO_MINIO_NS_A} (S3 LB + console ClusterIP), ${TWO_MINIO_NS_B} (S3 ClusterIP + console LB)"
  log "  License A: ${LICENSE_A}"
  log "  License B: ${LICENSE_B}"
  if [[ "${AISTOR_DEPLOY_SECOND_OPERATOR:-0}" != "1" ]]; then
    log "  Default single operator in ${TWO_MINIO_NS_A} — ${TWO_MINIO_NS_B} uses SKIP_OPERATOR=1 (set AISTOR_DEPLOY_SECOND_OPERATOR=1 only after removing other aistor-operator releases / CRD owners)."
  else
    log "  AISTOR_DEPLOY_SECOND_OPERATOR=1 — installing operator in ${TWO_MINIO_NS_B} as well (ensure no conflicting aistor-operator release owns CRDs)."
  fi
  log "  After bulk wipe: AISTOR_PRUNE_CRDS_AFTER_BULK=${AISTOR_PRUNE_CRDS_AFTER_BULK:-1} (set 0 to keep aistor CRDs if another non–df-cursor tenant needs them)"

  if [[ "${AISTOR_SKIP_CLEANUP:-0}" != "1" ]]; then
    log_step "Cleanup all namespaces matching ^df-cursor-* (Helm uninstall, ObjectStores, delete ns, optional CRD prune)"
    (
      export KUBECTL_CONTEXT="${KUBECTL_CONTEXT:-}"
      export AISTOR_CLEANUP_ALL_DF_CURSOR_NAMESPACES=1
      export AISTOR_PRUNE_CRDS="${AISTOR_PRUNE_CRDS_AFTER_BULK:-1}"
      bash "$CLEAN"
    )
  fi

  log_step "CLUSTER A — deploy operator + ObjectStore in ${TWO_MINIO_NS_A}"
  two_minio_deploy_ns "$TWO_MINIO_NS_A" "$TWO_MINIO_VAL_A" "$LICENSE_A" 0

  _second_op="${AISTOR_DEPLOY_SECOND_OPERATOR:-0}"
  _skip=1
  if [[ "$_second_op" == "1" ]]; then
    _skip=0
  fi

  log_step "CLUSTER B — deploy in ${TWO_MINIO_NS_B} (SKIP_OPERATOR=$([[ "$_skip" == 1 ]] && echo 1 || echo 0))"
  two_minio_deploy_ns "$TWO_MINIO_NS_B" "$TWO_MINIO_VAL_B" "$LICENSE_B" "$_skip"

  echo ""
  echo "╔══════════════════════════════════════════════════════════════════════════════╗"
  echo "║  Two MinIO AIStor namespaces — finished (AISTOR_TWO_MINIO_NAMESPACES=1)       ║"
  echo "╚══════════════════════════════════════════════════════════════════════════════╝"
  echo "  CLUSTER A:  kubectl get pods,svc -n ${TWO_MINIO_NS_A}   # S3: df-cursor-s3-api (LoadBalancer)"
  echo "  CLUSTER B:  kubectl get pods,svc -n ${TWO_MINIO_NS_B}   # Console: df-cursor-console-ui (LoadBalancer)"
  echo "  Root creds:  kubectl get secret df-cursor-cluster-a-root-creds -n ${TWO_MINIO_NS_A}"
  echo "              kubectl get secret df-cursor-cluster-b-root-creds -n ${TWO_MINIO_NS_B}"
  echo ""
}

if [[ "${AISTOR_TWO_MINIO_NAMESPACES:-0}" == "1" ]]; then
  run_two_minio_namespaces_mode
  exit 0
fi

pick_kube_context() {
  # $1 = env value (may be empty), $2 = preferred default context name from kubeconfig
  local from_env="${1:-}" def_name="${2:-}"
  if [[ -n "$from_env" ]]; then
    printf '%s' "$from_env"
    return 0
  fi
  if kubectl config get-contexts -o name 2>/dev/null | grep -qx "$def_name"; then
    printf '%s' "$def_name"
    return 0
  fi
  local cur
  cur="$(kubectl config current-context 2>/dev/null || true)"
  if [[ -n "$cur" ]] && kubectl config get-contexts -o name 2>/dev/null | grep -qx "$cur"; then
    printf '%s' "$cur"
    return 0
  fi
  return 1
}

apiserver_url_for_context() {
  local ctx="$1" cluster_name url
  cluster_name="$(kubectl config view -o "jsonpath={.contexts[?(@.name=='${ctx}')].context.cluster}" 2>/dev/null || true)"
  [[ -n "$cluster_name" ]] || return 1
  url="$(kubectl config view -o "jsonpath={.clusters[?(@.name=='${cluster_name}')].cluster.server}" 2>/dev/null || true)"
  printf '%s' "${url%/}"
}

contexts_share_same_kubernetes_api() {
  local a b
  a="$(apiserver_url_for_context "$CTX_DATA" || true)"
  b="$(apiserver_url_for_context "$CTX_UI" || true)"
  [[ -n "$a" && -n "$b" && "$a" == "$b" ]]
}

# Prints resolved API server URLs so operators can see one vs two physical clusters.
log_kubernetes_two_cluster_map() {
  local url_data url_ui
  url_data="$(apiserver_url_for_context "$CTX_DATA" 2>/dev/null || true)"
  url_ui="$(apiserver_url_for_context "$CTX_UI" 2>/dev/null || true)"
  [[ -z "${url_data// }" ]] && url_data="(could not resolve from kubeconfig)"
  [[ -z "${url_ui// }" ]] && url_ui="(could not resolve from kubeconfig)"
  log_step "Kubernetes targets — CLUSTER A (DATA) vs CLUSTER B (UI)"
  log "CLUSTER A (DATA):  kubectl --context ${CTX_DATA}"
  log "                     API server: ${url_data}"
  log "                     Workloads:  Helm aistor-operator + aistor-objectstore → namespace ${DATA_NS}"
  log "CLUSTER B (UI):    kubectl --context ${CTX_UI}"
  log "                     API server: ${url_ui}"
  if [[ "${AISTOR_DEPLOY_REMOTE_CONSOLE:-1}" == "1" ]]; then
    log "                     Workloads:  remote Console only → namespace ${REMOTE_UI_NS} (no ObjectStore / no S3 disks)"
  else
    log "                     Workloads:  (skipped — AISTOR_DEPLOY_REMOTE_CONSOLE=0; Console stays on CLUSTER A)"
  fi
  if [[ "$CTX_DATA" == "$CTX_UI" ]]; then
    log "Evidence: SAME kubectl context name → one kubeconfig entry; DATA + UI steps both run against that cluster."
  elif contexts_share_same_kubernetes_api; then
    log "Evidence: different context NAMES but SAME API server URL → one Kubernetes control plane (two aliases)."
  else
    log "Evidence: different API server URLs → two separate Kubernetes clusters."
  fi
}

CTX_DATA="$(pick_kube_context "${AISTOR_KUBE_CONTEXT_DATA:-}" "$DEFAULT_AISTOR_KUBE_CONTEXT_DATA")" \
  || die "Could not pick DATA context. Set AISTOR_KUBE_CONTEXT_DATA or create/rename a context (defaults: ${DEFAULT_AISTOR_KUBE_CONTEXT_DATA}, or use your current-context). Available: $(kubectl config get-contexts -o name 2>/dev/null | tr '\n' ' ')"
CTX_UI="$(pick_kube_context "${AISTOR_KUBE_CONTEXT_UI:-}" "$DEFAULT_AISTOR_KUBE_CONTEXT_UI")" \
  || die "Could not pick UI context. Set AISTOR_KUBE_CONTEXT_UI or create/rename a context (defaults: ${DEFAULT_AISTOR_KUBE_CONTEXT_UI}, or use your current-context). Available: $(kubectl config get-contexts -o name 2>/dev/null | tr '\n' ' ')"

LABEL_DATA="${AISTOR_CLUSTER_DATA_NAME:-$CTX_DATA}"
LABEL_UI="${AISTOR_CLUSTER_UI_NAME:-$CTX_UI}"
READY_TIMEOUT="${AISTOR_CLUSTER_READY_TIMEOUT:-300}"
DATA_NS="${AISTOR_NAMESPACE:-df-cursor-aistor}"
REMOTE_UI_NS="${CONSOLE_REMOTE_NS:-df-cursor-console-remote}"
# Default 1 = two-cluster test: Console workload on UI context, ObjectStore on DATA.
AISTOR_DEPLOY_REMOTE_CONSOLE="${AISTOR_DEPLOY_REMOTE_CONSOLE:-1}"

kcd() { kubectl --context "$CTX_DATA" "$@"; }
kcu() { kubectl --context "$CTX_UI" "$@"; }

command -v kubectl >/dev/null || die "kubectl not in PATH"
[[ -f "$DEPLOY_DATA" && -f "$VALUES" && -f "$DEPLOY_UI" ]] || die "missing deploy.sh, values.yaml, or deploy-remote-console.sh"
[[ -f "$LICENSE_FILE" ]] || die "missing license at ${LICENSE_FILE}"

[[ "${SKIP_OPERATOR:-0}" != "1" ]] || die "SKIP_OPERATOR=1 is incompatible with deploy-two-cluster.sh (AIStor operator is required on DATA)."
[[ "${SKIP_OBJECTSTORE:-0}" != "1" ]] || die "SKIP_OBJECTSTORE=1 is incompatible with deploy-two-cluster.sh (ObjectStore via operator is required on DATA)."

for c in "$CTX_DATA" "$CTX_UI"; do
  kubectl config get-contexts -o name | grep -qx "$c" || die "Unknown kubectl context: ${c}. Available: $(kubectl config get-contexts -o name 2>/dev/null | tr '\n' ' ')"
done

log_kubernetes_two_cluster_map

if [[ "$CTX_DATA" == "$CTX_UI" ]]; then
  log "NOTE: DATA and UI share context ${CTX_DATA} — for two physical clusters set AISTOR_KUBE_CONTEXT_DATA and AISTOR_KUBE_CONTEXT_UI to different entries whose apiServer URLs differ."
fi

OBJ="$(awk '/^objectStore:/{f=1} f&&/^  name:/{print $2; exit}' "$VALUES")"
SVC_S3="$(awk '/^    minio:/{f=1} f&&/^      name:/{print $2; exit}' "$VALUES")"
SVC_UI="$(awk '/^    console:/{f=1} f&&/^      name:/{print $2; exit}' "$VALUES")"
[[ -n "${OBJ:-}" && -n "${SVC_S3:-}" && -n "${SVC_UI:-}" ]] || die "could not parse ObjectStore / S3 / Console Service names from values.yaml"

log_step "Operator-only DATA path (mandatory)"
log "DATA (${LABEL_DATA}) uses ONLY ${DEPLOY_DATA} → Helm minio/aistor-operator + minio/aistor-objectstore."
log "No in-repo substitute replaces the AIStor operator for the data plane."
if [[ "$AISTOR_DEPLOY_REMOTE_CONSOLE" == "1" ]]; then
  log "UI (${LABEL_UI}): remote Console via ${DEPLOY_UI} (CONSOLE_IMAGE detected from operator on DATA when possible)."
else
  log "AISTOR_DEPLOY_REMOTE_CONSOLE=0 — Console UI only on DATA Service ${SVC_UI} (operator-managed)."
fi

log_step "Wait up to ${READY_TIMEOUT}s until BOTH kubectl contexts respond"
deadline=$((SECONDS + READY_TIMEOUT))
while (( SECONDS < deadline )); do
  ok_d=false
  ok_u=false
  kcd get ns >/dev/null 2>&1 && ok_d=true
  kcu get ns >/dev/null 2>&1 && ok_u=true
  if $ok_d && $ok_u; then
    log "Both contexts reachable (DATA=${CTX_DATA}, UI=${CTX_UI})."
    break
  fi
  log "  waiting… DATA=${ok_d} UI=${ok_u}"
  sleep 3
done
kcd get ns >/dev/null 2>&1 || die "DATA cluster API not ready within ${READY_TIMEOUT}s (context ${CTX_DATA})."
kcu get ns >/dev/null 2>&1 || die "UI cluster API not ready within ${READY_TIMEOUT}s (context ${CTX_UI})."

log_step "CLUSTER A — Cleanup DATA plane (${LABEL_DATA}) — Helm uninstall / ObjectStore / CRD prune"
(
  export KUBECTL_CONTEXT="$CTX_DATA"
  export AISTOR_NAMESPACE="${DATA_NS}"
  export AISTOR_PRUNE_CRDS="${AISTOR_PRUNE_CRDS:-1}"
  export OPERATOR_RELEASE="${OPERATOR_RELEASE:-df-cursor-aistor-operator}"
  export OBJECTSTORE_RELEASE="${OBJECTSTORE_RELEASE:-df-cursor-aistor-objectstore}"
  bash "${ROOT}/scripts/aistore-sandbox/cleanup-aistor.sh"
)

log_step "CLUSTER B — Cleanup UI namespace (${LABEL_UI}) — ${REMOTE_UI_NS}"
kcu delete namespace "$REMOTE_UI_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
if kcu get ns "$REMOTE_UI_NS" >/dev/null 2>&1; then
  log "  Namespace ${REMOTE_UI_NS} still terminating; waiting up to 120s…"
  end=$((SECONDS + 120))
  while (( SECONDS < end )); do
    kcu get ns "$REMOTE_UI_NS" >/dev/null 2>&1 || break
    sleep 2
  done
fi

log_step "CLUSTER A — Deploy DATA plane (${LABEL_DATA}) — AIStor operator + ObjectStore (Helm only)"
(
  export KUBECTL_CONTEXT="$CTX_DATA"
  export LICENSE_FILE
  export AISTOR_NAMESPACE="${DATA_NS}"
  export AISTOR_SKIP_CLEANUP=1
  bash "$DEPLOY_DATA"
)

log_step "Wait for operator-created S3 Service (${SVC_S3})"
end=$((SECONDS + 180))
while (( SECONDS < end )); do
  if kcd get svc "$SVC_S3" -n "$DATA_NS" >/dev/null 2>&1; then
    log "  Service ${SVC_S3} present in ${DATA_NS}."
    break
  fi
  sleep 3
done
kcd get svc "$SVC_S3" -n "$DATA_NS" >/dev/null 2>&1 || die "S3 Service ${SVC_S3} not found in ${DATA_NS} after wait."

REMOTE_STRATEGY=""
REMOTE_MINIO_URL=""

# Pick a container image from a "###"-delimited line: name###img1 img2 …
# Match if the workload name or any image path suggests Console (AIStor / MinIO).
_pick_console_image_from_record() {
  local rec="$1" name imgs img
  name="${rec%%###*}"
  imgs="${rec#*###}"
  [[ -n "$name" && -n "${imgs// }" ]] || return 1
  if ! echo "$name $imgs" | grep -qi console; then
    return 1
  fi
  for img in $imgs; do
    [[ -z "$img" ]] && continue
    if echo "$img" | grep -qi console; then
      printf '%s' "$img"
      return 0
    fi
  done
  set -- $imgs
  [[ -n "${1:-}" ]] || return 1
  printf '%s' "$1"
}

# Line: deployOrStsName###cname^img,cname^img,…  (^ and , chosen so image refs stay intact.)
_pick_image_from_console_named_container() {
  local rec="$1" name rest pair cname cimg cname_lc
  name="${rec%%###*}"
  rest="${rec#*###}"
  [[ -n "$name" && -n "${rest//,}" ]] || return 1
  while [[ -n "$rest" ]]; do
    if [[ "$rest" == *","* ]]; then
      pair="${rest%%,*}"
      rest="${rest#*,}"
    else
      pair="$rest"
      rest=""
    fi
    [[ -z "$pair" ]] && continue
    cname="${pair%%^*}"
    cimg="${pair#*^}"
    [[ -z "$cimg" ]] && continue
    cname_lc="$(echo "$cname" | tr '[:upper:]' '[:lower:]')"
    if [[ "$cname_lc" == console || "$cname_lc" == *-console ]]; then
      printf '%s' "$cimg"
      return 0
    fi
  done
  return 1
}

# Same objectStore.image block Helm uses on DATA (AIStor Console train matches spec.image on typical installs).
_console_image_from_values_yaml() {
  [[ -f "${VALUES:-}" ]] || return 1
  awk '
    /^objectStore:/ { o=1; next }
    o && /^  image:/ { im=1; next }
    im && /^    repository:/ { r=$2; next }
    im && /^    tag:/ { if (length(r)) { print r ":" $2; exit 0 } }
    im && /^  [a-z]/ { im=0 }
  ' "$VALUES" 2>/dev/null || true
}

# Console may be a Deployment or StatefulSet; some builds use a non-console
# image as containers[0]. Prefer a container named "console", then name/image heuristics.
# If no workload matches, use ObjectStore CR spec.image (same train as DATA) then values.yaml.
detect_operator_console_image() {
  local line kind fb r t
  for kind in deploy sts; do
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      if _pick_image_from_console_named_container "$line"; then
        return 0
      fi
    done < <(
      kcd get "$kind" -n "$DATA_NS" -o jsonpath='{range .items[*]}{.metadata.name}{"###"}{range .spec.template.spec.containers[*]}{.name}{"^"}{.image}{","}{end}{"\n"}{end}' 2>/dev/null \
        || true
    )
  done
  for kind in deploy sts; do
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      if _pick_console_image_from_record "$line"; then
        return 0
      fi
    done < <(
      kcd get "$kind" -n "$DATA_NS" -o jsonpath='{range .items[*]}{.metadata.name}{"###"}{range .spec.template.spec.containers[*]}{.image}{" "}{end}{"\n"}{end}' 2>/dev/null \
        || true
    )
  done
  fb="$(kcd get objectstore "${OBJ}" -n "${DATA_NS}" -o jsonpath='{.spec.image}' 2>/dev/null || true)"
  if [[ -n "${fb// }" && "$fb" != "null" ]]; then
    printf '%s' "$fb"
    return 0
  fi
  r="$(kcd get objectstore "${OBJ}" -n "${DATA_NS}" -o jsonpath='{.spec.image.repository}' 2>/dev/null || true)"
  t="$(kcd get objectstore "${OBJ}" -n "${DATA_NS}" -o jsonpath='{.spec.image.tag}' 2>/dev/null || true)"
  if [[ -n "${r// }" && -n "${t// }" && "$r" != "null" && "$t" != "null" ]]; then
    printf '%s:%s' "$r" "$t"
    return 0
  fi
  fb="$(_console_image_from_values_yaml || true)"
  if [[ -n "${fb// }" ]]; then
    printf '%s' "$fb"
    return 0
  fi
  return 1
}

resolve_remote_minio_url() {
  REMOTE_MINIO_URL=""
  REMOTE_STRATEGY=""
  if [[ -n "${AISTOR_REMOTE_S3_URL_OVERRIDE:-}" ]]; then
    REMOTE_STRATEGY="AISTOR_REMOTE_S3_URL_OVERRIDE"
    REMOTE_MINIO_URL="${AISTOR_REMOTE_S3_URL_OVERRIDE}"
    return
  fi
  if contexts_share_same_kubernetes_api; then
    REMOTE_STRATEGY="same Kubernetes API server → in-cluster DNS"
    REMOTE_MINIO_URL="$(printf 'http://%s.%s.svc.cluster.local:9000' "$SVC_S3" "$DATA_NS")"
    return
  fi
  local ip host
  ip="$(kcd get svc "$SVC_S3" -n "$DATA_NS" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  host="$(kcd get svc "$SVC_S3" -n "$DATA_NS" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  if [[ -n "$ip" ]]; then
    REMOTE_STRATEGY="LoadBalancer IP on ${SVC_S3}"
    REMOTE_MINIO_URL="$(printf 'http://%s:9000' "$ip")"
    return
  fi
  if [[ -n "$host" ]]; then
    REMOTE_STRATEGY="LoadBalancer hostname on ${SVC_S3}"
    REMOTE_MINIO_URL="$(printf 'http://%s:9000' "$host")"
    return
  fi

  log "  No LoadBalancer on ${SVC_S3}; creating NodePort sibling ${NODEPORT_SVC_NAME} (kubectl expose)…"
  kcd expose service "$SVC_S3" -n "$DATA_NS" --name="$NODEPORT_SVC_NAME" --type=NodePort --port=9000 --target-port=9000 >/dev/null

  local np="" nip=""
  end=$((SECONDS + 120))
  while (( SECONDS < end )); do
    np="$(kcd get svc "$NODEPORT_SVC_NAME" -n "$DATA_NS" -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || true)"
    [[ -n "$np" && "$np" != "null" ]] && break
    sleep 2
  done
  [[ -n "$np" && "$np" != "null" ]] || die "NodePort was not assigned on ${NODEPORT_SVC_NAME}."

  nip="$(kcd get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null || true)"
  [[ -z "${nip// }" ]] && nip="$(kcd get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)"
  [[ -n "${nip// }" ]] || die "Could not read a node IP on the DATA cluster for NodePort URL."

  REMOTE_STRATEGY="NodePort ${NODEPORT_SVC_NAME} (${nip}:${np})"
  REMOTE_MINIO_URL="$(printf 'http://%s:%s' "$nip" "$np")"
}

if [[ "$AISTOR_DEPLOY_REMOTE_CONSOLE" == "1" ]]; then
  resolve_remote_minio_url
  [[ -n "$REMOTE_MINIO_URL" ]] || die "REMOTE_MINIO_URL is empty after resolution."
  log "REMOTE_MINIO_URL (${REMOTE_STRATEGY}): ${REMOTE_MINIO_URL}"

  if [[ -z "${CONSOLE_IMAGE:-}" ]]; then
    _ci=""
    end=$((SECONDS + 180))
    log "  Resolving CONSOLE_IMAGE (workloads on DATA, else ObjectStore.spec.image / values.yaml same as DATA Helm)…"
    while (( SECONDS < end )); do
      _ci="$(detect_operator_console_image 2>/dev/null || true)"
      [[ -n "$_ci" ]] && break
      sleep 4
    done
    if [[ -n "$_ci" ]]; then
      export CONSOLE_IMAGE="$_ci"
      log "Resolved CONSOLE_IMAGE (same train as DATA cluster / ObjectStore): ${CONSOLE_IMAGE}"
    else
      die "Could not resolve CONSOLE_IMAGE. Set CONSOLE_IMAGE explicitly, or inspect: kubectl --context ${CTX_DATA} get objectstore,deploy,sts -n ${DATA_NS}"
    fi
  else
    export CONSOLE_IMAGE
    log "Using CONSOLE_IMAGE from environment: ${CONSOLE_IMAGE}"
  fi

  log_step "CLUSTER B — Deploy remote Console (${LABEL_UI}) — kubectl --context ${CTX_UI}"
  (
    export KUBECTL_CONTEXT="$CTX_UI"
    export REMOTE_CONSOLE_DATA_KUBE_CONTEXT="$CTX_DATA"
    export REMOTE_MINIO_URL
    export CONSOLE_REMOTE_NS="${REMOTE_UI_NS}"
    bash "$DEPLOY_UI"
  )
else
  log_step "Console UI — operator-managed on DATA (no standalone Console chart on UI cluster)"
  log "  Open the Console Service (${SVC_UI}) — default values use ClusterIP (port-forward); S3 API stays on ${SVC_S3} (ClusterIP)."
  end=$((SECONDS + 180))
  while (( SECONDS < end )); do
    _lip="$(kcd get svc "$SVC_UI" -n "$DATA_NS" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
    _lhost="$(kcd get svc "$SVC_UI" -n "$DATA_NS" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
    if [[ -n "${_lip// }" ]]; then
      log "  Console LoadBalancer: https://${_lip}:9443 (accept self-signed if disableAutoCert)"
      break
    fi
    if [[ -n "${_lhost// }" ]]; then
      log "  Console LoadBalancer: https://${_lhost}:9443 (accept self-signed if disableAutoCert)"
      break
    fi
    sleep 4
  done
  REMOTE_STRATEGY="operator Console on DATA (${SVC_UI})"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║  Finished — verify CLUSTER A vs CLUSTER B (contexts + API servers above)     ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo "  CLUSTER A:  kubectl --context ${CTX_DATA} get pods,svc -n ${DATA_NS}"
if [[ "$AISTOR_DEPLOY_REMOTE_CONSOLE" == "1" ]]; then
  echo "  CLUSTER B:  kubectl --context ${CTX_UI} get pods,svc -n ${REMOTE_UI_NS}"
  echo "  S3 URL (Console on B → API on A): ${REMOTE_STRATEGY} → ${REMOTE_MINIO_URL}"
  echo "  Port-forward UI on B:  kubectl --context ${CTX_UI} port-forward -n ${REMOTE_UI_NS} svc/df-cursor-console-remote 9090:9090"
  echo "  Browser: http://127.0.0.1:9090 — log in with CLUSTER A root credentials."
else
  echo "  CLUSTER B:  (remote Console not deployed)"
  echo "  Console on A:  kubectl --context ${CTX_DATA} get svc ${SVC_UI} -n ${DATA_NS}"
  echo "  Or port-forward: kubectl --context ${CTX_DATA} port-forward -n ${DATA_NS} svc/${SVC_UI} 9443:9443  # https://127.0.0.1:9443"
fi
echo ""
