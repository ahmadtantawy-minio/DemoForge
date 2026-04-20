#!/usr/bin/env bash
#
# Shared cleanup for MinIO AIStor sandbox (Helm releases in namespace + ObjectStore CRs + optional CRD prune).
# Used by deploy.sh and deploy-two-cluster.sh.
#
# Optional env (same defaults as deploy.sh):
#   KUBECTL_CONTEXT              pin kubectl/helm to this context
#   AISTOR_NAMESPACE             default df-cursor-aistor
#   OPERATOR_RELEASE             default df-cursor-aistor-operator
#   OBJECTSTORE_RELEASE          default df-cursor-aistor-objectstore
#   AISTOR_SKIP_CLEANUP=1        no-op (exit 0)
#   AISTOR_PRUNE_CRDS=0          skip CRD deletion (default is 1 when unset in caller)
#   AISTOR_CLEANUP_PRUNE_CRDS_FORCE=1  only run CRD prune with force=1, then exit (OrbStack reset path)
#   AISTOR_CLEANUP_NODEPORT_SVC  delete this Service in namespace first (default df-cursor-s3-api-nodeport-expose)
#   AISTOR_CLEANUP_ALL_DF_CURSOR_NAMESPACES=1  uninstall every Helm release in each namespace matching ^df-cursor-,
#        delete ObjectStores there, delete those namespaces, then run CRD prune per AISTOR_PRUNE_CRDS (then exit;
#        the per-namespace block below is skipped). Destructive — any workload under df-cursor-* is removed.
#
set -euo pipefail

NS="${AISTOR_NAMESPACE:-df-cursor-aistor}"
OPERATOR_REL="${OPERATOR_RELEASE:-df-cursor-aistor-operator}"
STORE_REL="${OBJECTSTORE_RELEASE:-df-cursor-aistor-objectstore}"
AISTOR_PRUNE_CRDS="${AISTOR_PRUNE_CRDS:-1}"
NODEPORT_SVC="${AISTOR_CLEANUP_NODEPORT_SVC:-df-cursor-s3-api-nodeport-expose}"

die() { echo "[df-cursor] ERROR: $*" >&2; exit 1; }
log() { echo "[df-cursor] $*"; }

if [[ -n "${KUBECTL_CONTEXT:-}" ]]; then
  kubectl() { command kubectl --context "${KUBECTL_CONTEXT}" "$@"; }
  helm() { command helm --kube-context "${KUBECTL_CONTEXT}" "$@"; }
fi

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
      rem="$(kubectl get crd -o name 2>/dev/null | awk '/\.(sts|aistor)\.min\.io$/ { n++ } END { print n + 0 }')"
      [[ "${rem:-0}" == "0" ]] && break
      sleep 2
    done
  fi
}

command -v kubectl >/dev/null || die "kubectl not found in PATH"
command -v helm >/dev/null || die "helm not found in PATH"

if [[ "${AISTOR_CLEANUP_PRUNE_CRDS_FORCE:-0}" == "1" ]]; then
  prune_aistor_crds 1
  exit 0
fi

if [[ "${AISTOR_SKIP_CLEANUP:-0}" == "1" ]]; then
  log "AISTOR_SKIP_CLEANUP=1 — skipping shared AIStor cleanup."
  exit 0
fi

# Wipe every namespace whose name starts with df-cursor- (Helm uninstall → ObjectStores → delete ns).
cleanup_all_df_cursor_namespaces() {
  local ns rel common_np
  common_np="${AISTOR_CLEANUP_NODEPORT_SVC:-df-cursor-s3-api-nodeport-expose}"
  log "  Enumerating namespaces matching ^df-cursor- ..."
  while IFS= read -r ns; do
    [[ -z "$ns" ]] && continue
    log "  ── namespace ${ns}"
    kubectl delete svc "${common_np}" -n "$ns" --ignore-not-found --wait=false 2>/dev/null || true
    while IFS= read -r rel; do
      [[ -z "${rel// }" ]] && continue
      log "    helm uninstall ${rel} -n ${ns}"
      helm uninstall "$rel" -n "$ns" --wait --timeout 5m 2>/dev/null || log "      ⚠ helm uninstall ${rel} failed (continuing)"
    done < <({ helm list -n "$ns" --no-headers -q 2>/dev/null || true; } | awk 'NF { print $1 }')
    log "    kubectl delete objectstore --all -n ${ns}"
    kubectl delete objectstore --all -n "$ns" --wait=false 2>/dev/null || true
    log "    kubectl delete namespace ${ns}"
    kubectl delete namespace "$ns" --wait=false 2>/dev/null || log "      ⚠ delete namespace ${ns} failed (continuing)"
  done < <(kubectl get ns -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -E '^df-cursor-' || true)
}

if [[ "${AISTOR_CLEANUP_ALL_DF_CURSOR_NAMESPACES:-0}" == "1" ]]; then
  log "AISTOR_CLEANUP_ALL_DF_CURSOR_NAMESPACES=1 — uninstalling all Helm releases in ^df-cursor- namespaces, then deleting those namespaces"
  cleanup_all_df_cursor_namespaces
  log "  Waiting for terminating namespaces (up to 120s)..."
  _bulk_wait_end=$((SECONDS + 120))
  while (( SECONDS < _bulk_wait_end )); do
    # grep exits 1 when there are no matches — must not trip set -e (pipefail).
    _bulk_ns_left="$(kubectl get ns -o name 2>/dev/null | awk '/^namespace\/df-cursor-/ { n++ } END { print n + 0 }')"
    [[ "${_bulk_ns_left:-0}" == "0" ]] && break
    sleep 2
  done
  log "Why: leftover CRDs after removing all df-cursor-* namespaces (optional prune)..."
  prune_aistor_crds 0
  log "  Bulk df-cursor-* cleanup finished."
  exit 0
fi

log "Why: leftover Helm releases or CRDs from an older release name / manual apply block the operator chart"
log "     (Helm cannot adopt CRDs that lack meta.helm.sh/release-name and app.kubernetes.io/managed-by=Helm)."

kubectl delete svc "$NODEPORT_SVC" -n "$NS" --ignore-not-found --wait=false 2>/dev/null || true

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
