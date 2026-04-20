#!/usr/bin/env bash
#
# Cluster B — standalone MinIO Console only (Option A). No ObjectStore / operator here.
#
# Defaults (override with env when your kubeconfig uses other context names):
#   KUBECTL_CONTEXT=demoforge-aistore-console
#   REMOTE_CONSOLE_DATA_KUBE_CONTEXT=demoforge-aistore-data  (labels only: DATA cluster kubectl context)
#
# Requires:
#   • kubectl context (default demoforge-aistore-console unless KUBECTL_CONTEXT is set)
#   • REMOTE_MINIO_URL — MinIO S3 API base URL reachable FROM pods on cluster B (written to ConfigMap as
#       CONSOLE_MINIO_SERVER, which the Console container reads). Alias: set CONSOLE_MINIO_SERVER_URL if you
#       prefer not to use the name REMOTE_MINIO_URL.
#       Cluster-internal DNS for a Service on cluster A is not enough unless B shares that network.
#
# Optional env:
#   KUBECTL_CONTEXT     pin all kubectl calls to this kubeconfig context
#   CONSOLE_REMOTE_NS   (default df-cursor-console-remote)
#   CONSOLE_MINIO_SERVER_URL  same as REMOTE_MINIO_URL if REMOTE_MINIO_URL is unset
#   CONSOLE_IMAGE       required — use the same image as the AIStor operator Console workload on DATA
#                        (see deploy-two-cluster.sh detection or kubectl get deploy,sts … -o wide).
#                        Do not use quay.io/minio/console community tags; they lag AIStor.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="${ROOT}/scripts/aistore-sandbox/remote-console/console-remote.yaml"

: "${KUBECTL_CONTEXT:=demoforge-aistore-console}"
: "${REMOTE_CONSOLE_DATA_KUBE_CONTEXT:=demoforge-aistore-data}"
export KUBECTL_CONTEXT REMOTE_CONSOLE_DATA_KUBE_CONTEXT

kc() {
  if [[ -n "${KUBECTL_CONTEXT:-}" ]]; then
    command kubectl --context "${KUBECTL_CONTEXT}" "$@"
  else
    command kubectl "$@"
  fi
}

command -v kubectl >/dev/null || { echo "[df-cursor] ERROR: kubectl not in PATH" >&2; exit 1; }
[[ -f "$TEMPLATE" ]] || { echo "[df-cursor] ERROR: missing ${TEMPLATE}" >&2; exit 1; }

REMOTE_MINIO_URL="${REMOTE_MINIO_URL:-${CONSOLE_MINIO_SERVER_URL:-}}"
[[ -n "$REMOTE_MINIO_URL" ]] || {
  echo "[df-cursor] ERROR: set REMOTE_MINIO_URL or CONSOLE_MINIO_SERVER_URL to the MinIO API URL reachable from cluster B pods." >&2
  exit 1
}

NS="${CONSOLE_REMOTE_NS:-df-cursor-console-remote}"
IMG="${CONSOLE_IMAGE:-}"
[[ -n "$IMG" ]] || {
  echo "[df-cursor] ERROR: set CONSOLE_IMAGE to the AIStor operator Console container image (see kubectl get deploy on the DATA namespace)." >&2
  exit 1
}

JWT_P=$(openssl rand -hex 32)
JWT_S=$(openssl rand -hex 32)

log() { echo "[df-cursor] $*"; }

log "Remote Console deploy (CLUSTER B — no ObjectStore on this kube target)"
if [[ -n "${KUBECTL_CONTEXT:-}" ]]; then
  log "  kubectl context: ${KUBECTL_CONTEXT} (pinned: KUBECTL_CONTEXT)"
  _b_api="$(kubectl config view --minify --context="${KUBECTL_CONTEXT}" -o 'jsonpath={.clusters[0].cluster.server}' 2>/dev/null || true)"
  [[ -n "${_b_api:-}" ]] && log "  CLUSTER B API server: ${_b_api}"
else
  log "  kubectl context: $(kubectl config current-context 2>/dev/null || echo '(unknown)')"
fi
log "  namespace:       ${NS}"
log "  console image:   ${IMG}"
log "  MinIO API URL:   ${REMOTE_MINIO_URL}"

TMP="$(mktemp)"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

kc create namespace "$NS" --dry-run=client -o yaml | kc apply -f -
kc label namespace "$NS" \
  df-cursor.min.io/kube-context="${KUBECTL_CONTEXT}" \
  df-cursor.min.io/data-kube-context="${REMOTE_CONSOLE_DATA_KUBE_CONTEXT}" \
  df-cursor.min.io/cluster-role=console-remote \
  --overwrite >/dev/null

kc -n "$NS" create configmap df-cursor-console-remote-endpoint \
  --from-literal=CONSOLE_MINIO_SERVER="$REMOTE_MINIO_URL" \
  --dry-run=client -o yaml | kc apply -f -
kc -n "$NS" label configmap df-cursor-console-remote-endpoint \
  df-cursor.min.io/kube-context="${KUBECTL_CONTEXT}" \
  df-cursor.min.io/data-kube-context="${REMOTE_CONSOLE_DATA_KUBE_CONTEXT}" \
  df-cursor.min.io/cluster-role=console-remote \
  --overwrite >/dev/null 2>&1 || true

sed -e "s/__CONSOLE_NS__/${NS}/g" \
    -e "s|__CONSOLE_IMAGE__|${IMG}|g" \
    -e "s/__JWT_PASSPHRASE__/${JWT_P}/g" \
    -e "s/__JWT_SALT__/${JWT_S}/g" \
    -e "s|__KUBE_CONTEXT_UI__|${KUBECTL_CONTEXT}|g" \
    -e "s|__KUBE_CONTEXT_DATA__|${REMOTE_CONSOLE_DATA_KUBE_CONTEXT}|g" \
    "$TEMPLATE" >"$TMP"

kc apply -f "$TMP"

kc -n "$NS" rollout restart deployment/df-cursor-console-remote 2>/dev/null || true
kc -n "$NS" rollout status deployment/df-cursor-console-remote --timeout=180s || {
  log "⚠ rollout not ready — check: kubectl describe deploy -n ${NS} df-cursor-console-remote"
}

echo ""
echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║  Remote Console (cluster B) — next steps                                     ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  kubectl get svc,po -n ${NS}"
echo "  kubectl port-forward -n ${NS} svc/df-cursor-console-remote 9090:9090"
echo "  # Browser: http://127.0.0.1:9090"
echo "  # Log in with cluster A root credentials (same as ObjectStore on A)."
echo ""
echo "Tip: match CONSOLE_IMAGE to the Console image on cluster A:"
echo "  kubectl get deploy -A -o jsonpath='{range .items[*]}{.metadata.namespace}{\" \"}{.metadata.name}{\" \"}{.spec.template.spec.containers[0].image}{\"\\n\"}{end}' | grep -i console"
echo ""
log "Done."
