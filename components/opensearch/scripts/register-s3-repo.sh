#!/bin/bash
# Register MinIO/AIStor as an OpenSearch S3 snapshot repository.
set -euo pipefail

ENDPOINT="${S3_ENDPOINT:-}"
BUCKET="${OPENSEARCH_SNAPSHOT_BUCKET:-opensearch-snapshots}"
REPO="${OPENSEARCH_SNAPSHOT_REPO:-demoforge-s3}"
AK="${S3_ACCESS_KEY:-minioadmin}"
SK="${S3_SECRET_KEY:-minioadmin}"

if [ -z "$ENDPOINT" ]; then
  echo "OPENSEARCH: S3_ENDPOINT empty — skip snapshot repo registration"
  exit 0
fi

# Path-style S3 on MinIO; strip scheme for client settings
HOSTPORT="${ENDPOINT#http://}"
HOSTPORT="${HOSTPORT#https://}"

echo "Waiting for OpenSearch..."
for i in $(seq 1 60); do
  if curl -sf "http://localhost:9200/_cluster/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# Install repository-s3 if missing (official image usually includes it)
if ! curl -sf "http://localhost:9200/_cat/plugins" 2>/dev/null | grep -q repository-s3; then
  echo "repository-s3 plugin not listed; attempting install (may require restart — demo images usually ship it)"
  bin/opensearch-plugin install -b repository-s3 2>/dev/null || true
fi

# Keystore credentials for the S3 client (idempotent-ish)
echo "$AK" | bin/opensearch-keystore add -xf s3.client.default.access_key 2>/dev/null || true
echo "$SK" | bin/opensearch-keystore add -xf s3.client.default.secret_key 2>/dev/null || true

# Reload secure settings when possible
curl -sf -X POST "http://localhost:9200/_nodes/reload_secure_settings" \
  -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1 || true

BODY=$(cat <<EOF
{
  "type": "s3",
  "settings": {
    "bucket": "${BUCKET}",
    "endpoint": "${HOSTPORT}",
    "protocol": "http",
    "path_style_access": "true",
    "compress": "true"
  }
}
EOF
)

echo "Registering snapshot repo ${REPO} → s3://${BUCKET} @ ${HOSTPORT}"
HTTP=$(curl -s -o /tmp/os-repo.json -w "%{http_code}" -X PUT "http://localhost:9200/_snapshot/${REPO}" \
  -H 'Content-Type: application/json' -d "$BODY" || true)
echo "HTTP ${HTTP}: $(cat /tmp/os-repo.json 2>/dev/null || true)"
# 200 OK or already exists is fine
case "$HTTP" in
  200|201) exit 0 ;;
  *)
    # Retry once after short sleep (keystore reload lag)
    sleep 3
    curl -sf -X PUT "http://localhost:9200/_snapshot/${REPO}" \
      -H 'Content-Type: application/json' -d "$BODY" && exit 0
    echo "WARN: snapshot repo registration may need a node restart after keystore change"
    exit 0
    ;;
esac
