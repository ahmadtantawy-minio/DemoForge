#!/bin/bash
# Apply DemoForge S3 named collection / S3Queue DDL once ClickHouse is up.
set -euo pipefail
SQL_FILE="${CLICKHOUSE_INIT_SQL:-/docker-entrypoint-initdb.d/init-s3.sql}"
if [ ! -f "$SQL_FILE" ]; then
  echo "No $SQL_FILE; skipping ClickHouse S3 init"
  exit 0
fi
# Skip noop placeholder
if grep -q 'named collection skipped' "$SQL_FILE" 2>/dev/null; then
  echo "ClickHouse S3 init: no MinIO edge"
  exit 0
fi
for i in $(seq 1 30); do
  if clickhouse-client --port 9001 --query "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
clickhouse-client --port 9001 --multiquery < "$SQL_FILE"
echo "ClickHouse S3 init applied"
