#!/bin/bash
# Wrap apache/hive entrypoint so warehouse.dir can point at DemoForge HDFS.
set -euo pipefail
if [ -n "${HDFS_NAMENODE:-}" ]; then
  WH="hdfs://${HDFS_NAMENODE}:8020${HIVE_WAREHOUSE_PATH:-/user/hive/warehouse}"
  export SERVICE_OPTS="${SERVICE_OPTS:--Xmx512m} -Dhive.metastore.warehouse.dir=${WH}"
  echo "Hive warehouse → ${WH}"
fi
exec /entrypoint.sh "$@"
